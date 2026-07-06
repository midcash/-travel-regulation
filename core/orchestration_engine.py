"""编排引擎 — 任务分解、路由、结果整合与重试管理。

包含:
- Task 数据类 (原子任务)
- TaskDAG 类 (任务依赖图 + 拓扑排序)
- AgentRouter 类 (任务类型 → Agent 映射)
- RetryManager 类 (指数退避重试)
- ResultAssembler 类 (最终方案整合)

来源: spec/orchestrator_spec.md, playbooks/orchestrator_playbook.md
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Callable, Coroutine, Dict, List, Optional, Set
from uuid import uuid4

from .message import (
    MAX_RETRIES,
    RETRY_BACKOFF,
    AgentIdentity,
    AgentRegistry,
    TaskType,
)

logger = logging.getLogger(__name__)


# ============================================================
# Task 数据类 — orchestrator_spec.md §2.2
# ============================================================

class TaskStatus(Enum):
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    SKIPPED = "skipped"
    TIMED_OUT = "timed_out"


@dataclass
class Task:
    """原子任务 — 任务 DAG 中的单个节点。

    来源: spec/orchestrator_spec.md §2.2
    """

    task_id: str
    """任务唯一标识。"""

    title: str
    """任务标题。"""

    task_type: TaskType
    """对应的消息类型 (路由依据)。"""

    payload: Dict[str, Any] = field(default_factory=dict)
    """任务载荷。"""

    dependencies: List[str] = field(default_factory=list)
    """依赖的 task_id 列表。"""

    status: TaskStatus = TaskStatus.PENDING
    """当前状态。"""

    result: Optional[Dict[str, Any]] = None
    """执行结果 (完成后填充)。"""

    error: Optional[str] = None
    """错误信息 (失败时填充)。"""

    assigned_agent: Optional[str] = None
    """分配的目标 Agent 名称。"""

    retry_count: int = 0
    """已重试次数。"""

    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    """创建时间。"""

    completed_at: Optional[datetime] = None
    """完成时间。"""


# ============================================================
# TaskDAG — orchestrator_spec.md §2.2
# ============================================================

class TaskDAG:
    """任务依赖图 — 管理任务及其依赖关系。

    支持拓扑排序、就绪任务查询、依赖解析。
    """

    def __init__(self):
        self._tasks: Dict[str, Task] = {}
        self._adjacency: Dict[str, Set[str]] = {}       # task_id → 依赖它的 tasks
        self._in_degree: Dict[str, int] = {}             # task_id → 未完成的依赖数

    def add_task(self, task: Task) -> None:
        """添加任务到 DAG。

        Raises:
            ValueError: task_id 重复。
        """
        if task.task_id in self._tasks:
            raise ValueError(f"任务 ID 重复: {task.task_id}")

        self._tasks[task.task_id] = task
        self._in_degree[task.task_id] = len(task.dependencies)
        self._adjacency.setdefault(task.task_id, set())

        # 构建反向邻接表
        for dep_id in task.dependencies:
            self._adjacency.setdefault(dep_id, set()).add(task.task_id)

    def add_tasks(self, tasks: List[Task]) -> None:
        """批量添加任务。"""
        for t in tasks:
            self.add_task(t)

    def get_ready_tasks(self) -> List[Task]:
        """返回所有依赖已满足且状态为 PENDING 的任务。"""
        ready: List[Task] = []
        for tid, task in self._tasks.items():
            if task.status != TaskStatus.PENDING:
                continue
            if self._in_degree.get(tid, 0) == 0:
                ready.append(task)
        return ready

    def mark_completed(self, task_id: str, result: Dict[str, Any]) -> None:
        """标记任务完成，并解除下游依赖。"""
        task = self._tasks.get(task_id)
        if task is None:
            raise ValueError(f"未知任务: {task_id}")

        task.status = TaskStatus.COMPLETED
        task.result = result
        task.completed_at = datetime.now(timezone.utc)

        # 减少下游任务的入度
        for downstream_id in self._adjacency.get(task_id, set()):
            self._in_degree[downstream_id] = max(0, self._in_degree.get(downstream_id, 0) - 1)

    def mark_failed(self, task_id: str, error: str) -> None:
        """标记任务失败。"""
        task = self._tasks.get(task_id)
        if task is None:
            raise ValueError(f"未知任务: {task_id}")
        task.status = TaskStatus.FAILED
        task.error = error
        task.completed_at = datetime.now(timezone.utc)

    def mark_running(self, task_id: str) -> None:
        """标记任务开始执行。"""
        task = self._tasks.get(task_id)
        if task is None:
            raise ValueError(f"未知任务: {task_id}")
        task.status = TaskStatus.RUNNING

    def get_task(self, task_id: str) -> Optional[Task]:
        """按 ID 获取任务。"""
        return self._tasks.get(task_id)

    def get_all_tasks(self) -> List[Task]:
        """返回所有任务。"""
        return list(self._tasks.values())

    def is_complete(self) -> bool:
        """所有任务是否均已到达终态。"""
        terminal = {TaskStatus.COMPLETED, TaskStatus.FAILED, TaskStatus.SKIPPED}
        return all(t.status in terminal for t in self._tasks.values())

    def has_failures(self) -> bool:
        """是否有任务失败。"""
        return any(t.status == TaskStatus.FAILED for t in self._tasks.values())

    def topological_order(self) -> List[Task]:
        """返回拓扑排序的任务列表 (Kahn 算法)。

        Returns:
            拓扑排序后的任务列表。

        Raises:
            ValueError: 存在循环依赖。
        """
        in_deg = {tid: len(t.dependencies) for tid, t in self._tasks.items()}
        adj: Dict[str, List[str]] = {}
        for tid, t in self._tasks.items():
            for dep in t.dependencies:
                adj.setdefault(dep, []).append(tid)

        queue = [tid for tid, deg in in_deg.items() if deg == 0]
        result: List[Task] = []

        while queue:
            tid = queue.pop(0)
            result.append(self._tasks[tid])
            for neighbor in adj.get(tid, []):
                in_deg[neighbor] -= 1
                if in_deg[neighbor] == 0:
                    queue.append(neighbor)

        if len(result) != len(self._tasks):
            raise ValueError("任务 DAG 存在循环依赖")
        return result

    @property
    def task_count(self) -> int:
        return len(self._tasks)


# ============================================================
# AgentRouter — orchestrator_spec.md §2.3
# ============================================================

@dataclass
class RouteRule:
    """路由规则 — 任务类型到目标 Agent 的映射。"""

    task_type: TaskType
    """任务类型。"""

    target_agent: str
    """目标 Agent 名称。"""

    priority: int = 0
    """优先级 (数字越大越优先匹配)。"""


class AgentRouter:
    """Agent 路由器 — 根据任务类型将任务路由到目标 Agent。

    路由规则来源: spec/orchestrator_spec.md §2.3
    """

    # 内置路由表 — spec/orchestrator_spec.md §2.3
    DEFAULT_ROUTES: List[RouteRule] = [
        RouteRule(TaskType.TASK_CREATE_ITINERARY, "planning_agent", priority=10),
        RouteRule(TaskType.TASK_REVISE_ITINERARY, "planning_agent", priority=10),
        RouteRule(TaskType.TASK_VALIDATE_FEASIBILITY, "execution_agent", priority=10),
        RouteRule(TaskType.TASK_EVALUATE_PLAN, "evaluation_agent", priority=10),
        RouteRule(TaskType.TASK_EVALUATE_CODE, "evaluation_agent", priority=10),
        RouteRule(TaskType.TASK_EVALUATE_CONTRIBUTION, "evaluation_agent", priority=10),
    ]

    def __init__(self, registry: Optional[AgentRegistry] = None):
        self._routes: List[RouteRule] = list(self.DEFAULT_ROUTES)
        self._registry = registry

    def add_route(self, rule: RouteRule) -> None:
        """添加自定义路由规则。"""
        self._routes.append(rule)
        self._routes.sort(key=lambda r: r.priority, reverse=True)

    def resolve(self, task_type: TaskType) -> Optional[str]:
        """根据任务类型解析目标 Agent 名称。

        Returns:
            Agent 名称，无匹配返回 None。
        """
        for rule in self._routes:
            if rule.task_type == task_type:
                return rule.target_agent
        return None

    async def discover_agent(self, task_type: TaskType) -> Optional[AgentIdentity]:
        """通过 Registry 发现目标 Agent 的完整信息。

        Returns:
            AgentIdentity，未注册返回 None。
        """
        target_name = self.resolve(task_type)
        if target_name is None or self._registry is None:
            return None
        return await self._registry.get_agent(target_name)

    def route_task(self, task: Task) -> Optional[str]:
        """为任务解析路由目标。

        Returns:
            Agent 名称。
        """
        agent = self.resolve(task.task_type)
        if agent:
            task.assigned_agent = agent
        return agent


# ============================================================
# RetryManager — agent_contract.md §5.2
# ============================================================

class RetryManager:
    """重试管理器 — 指数退避重试策略。

    来源: spec/agent_contract.md §5.2, agent_contract.md §5.1
    """

    def __init__(
        self,
        max_retries: int = MAX_RETRIES,
        backoff_seconds: List[float] = None,
        timeout_seconds: float = 30.0,
    ):
        self.max_retries = max_retries
        self.backoff_seconds = backoff_seconds or list(RETRY_BACKOFF)
        self.timeout_seconds = timeout_seconds
        self._attempt_counts: Dict[str, int] = {}

    def can_retry(self, task_id: str) -> bool:
        """检查任务是否还有重试配额。"""
        return self._attempt_counts.get(task_id, 0) < self.max_retries

    def next_delay(self, task_id: str) -> float:
        """获取下一次重试的等待时间 (秒)。"""
        attempt = self._attempt_counts.get(task_id, 0)
        if attempt < len(self.backoff_seconds):
            delay = self.backoff_seconds[attempt]
        else:
            delay = self.backoff_seconds[-1] if self.backoff_seconds else 1.0
        return delay

    def record_attempt(self, task_id: str) -> int:
        """记录一次尝试，返回当前尝试次数 (1-based)。"""
        current = self._attempt_counts.get(task_id, 0) + 1
        self._attempt_counts[task_id] = current
        return current

    def reset(self, task_id: str) -> None:
        """重置任务的重试计数。"""
        self._attempt_counts.pop(task_id, None)

    def reset_all(self) -> None:
        """重置所有任务的重试计数。"""
        self._attempt_counts.clear()

    async def execute_with_retry(
        self,
        task_id: str,
        coro_factory: Callable[[], Coroutine[Any, Any, Any]],
    ) -> Any:
        """带重试的异步执行包装器。

        Args:
            task_id: 任务标识 (用于跟踪重试次数)
            coro_factory: 返回可等待对象的工厂函数 (每次重试创建新的)

        Returns:
            协程的返回值。

        Raises:
            TimeoutError: 所有重试均超时。
            Exception: 所有重试均失败 (抛出最后一次异常)。
        """
        last_error: Optional[Exception] = None

        while self.can_retry(task_id):
            attempt = self.record_attempt(task_id)
            try:
                result = await asyncio.wait_for(
                    coro_factory(),
                    timeout=self.timeout_seconds,
                )
                # 成功后重置计数
                self.reset(task_id)
                return result
            except asyncio.TimeoutError:
                last_error = TimeoutError(
                    f"任务 {task_id} 第 {attempt} 次尝试超时 ({self.timeout_seconds}s)"
                )
                logger.warning(str(last_error))
            except Exception as exc:
                last_error = exc
                logger.warning(f"任务 {task_id} 第 {attempt} 次尝试失败: {exc}")

            # 检查是否还有重试配额
            if self.can_retry(task_id):
                delay = self.next_delay(task_id)
                logger.info(f"任务 {task_id} 将于 {delay}s 后重试")
                await asyncio.sleep(delay)

        # 所有重试耗尽
        self.reset(task_id)
        if last_error:
            raise last_error
        raise RuntimeError(f"任务 {task_id} 重试耗尽但无异常记录")


# ============================================================
# ResultAssembler — orchestrator_spec.md §2.4
# ============================================================

class ResultAssembler:
    """结果整合器 — 将各 Agent 产出合并为 FinalTravelPlan。

    来源: spec/orchestrator_spec.md §2.4
    """

    def assemble(
        self,
        draft: Optional[Dict[str, Any]],
        validation: Optional[Dict[str, Any]],
        quality: Optional[Dict[str, Any]],
        iteration_count: int = 0,
        degraded: bool = False,
        degraded_reason: Optional[str] = None,
    ) -> Dict[str, Any]:
        """整合 Planning + Execution + Evaluation 产出为最终方案。

        Args:
            draft: TravelPlanDraft (来自 Planning Agent)
            validation: ValidationReport (来自 Execution Agent)
            quality: PlanQualityReport (来自 Evaluation Agent)
            iteration_count: 修订迭代轮次
            degraded: 是否降级输出
            degraded_reason: 降级原因

        Returns:
            FinalTravelPlan 字典。
        """
        draft = draft or {}
        validation = validation or {}
        quality = quality or {}

        # 从 draft 提取各组件，缺失时用占位符
        transportation = draft.get("transportation") or {
            "outbound": {}, "return": {}, "local": {},
        }
        accommodation = draft.get("accommodation") or []
        daily_itinerary = draft.get("daily_itinerary") or []
        budget_allocation = draft.get("budget_allocation") or {}

        # 构建预算分解
        budget_breakdown = {
            "transportation": budget_allocation.get("transportation", 0),
            "accommodation": budget_allocation.get("accommodation", 0),
            "activities": budget_allocation.get("activities", 0),
            "meals": budget_allocation.get("meals", 0),
            "buffer": budget_allocation.get("buffer", 0),
        }

        # 从 draft 中提取总预算
        total_budget = draft.get("total_budget", sum(budget_breakdown.values()))

        summary = {
            "destination": draft.get("destination", ""),
            "duration_days": len(daily_itinerary) or draft.get("duration_days", 0),
            "total_budget": total_budget,
            "overall_score": quality.get("composite_score", 0),
            "degraded": degraded,
            "degraded_reason": degraded_reason,
        }

        return {
            "plan_id": str(uuid4()),
            "summary": summary,
            "transportation": transportation,
            "accommodation": accommodation,
            "daily_itinerary": daily_itinerary,
            "budget_breakdown": budget_breakdown,
            "quality_report": quality,
            "metadata": {
                "iteration_count": iteration_count,
                "validation_passed": validation.get("overall_status") == "feasible",
                "assembled_at": datetime.now(timezone.utc).isoformat(),
            },
        }

    def build_task_queue(self, request: Dict[str, Any]) -> TaskDAG:
        """从用户需求构建标准任务 DAG。

        标准 4 任务分解 (orchestrator_spec.md §2.2):
        T1: 交通方案 (无依赖)
        T2: 住宿方案 (无依赖)
        T3: 每日行程 (依赖 T1, T2)
        T4: 预算分配 (依赖 T1, T2, T3)

        Args:
            request: StructuredRequest 字典

        Returns:
            包含 T1-T4 的 TaskDAG。
        """
        dag = TaskDAG()

        t1 = Task(
            task_id="T1",
            title="交通方案规划",
            task_type=TaskType.TASK_CREATE_ITINERARY,
            payload={"aspect": "transportation", "request": request},
            dependencies=[],
        )

        t2 = Task(
            task_id="T2",
            title="住宿方案规划",
            task_type=TaskType.TASK_CREATE_ITINERARY,
            payload={"aspect": "accommodation", "request": request},
            dependencies=[],
        )

        t3 = Task(
            task_id="T3",
            title="每日行程规划",
            task_type=TaskType.TASK_CREATE_ITINERARY,
            payload={"aspect": "daily_itinerary", "request": request},
            dependencies=["T1", "T2"],
        )

        t4 = Task(
            task_id="T4",
            title="预算分配方案",
            task_type=TaskType.TASK_CREATE_ITINERARY,
            payload={"aspect": "budget_allocation", "request": request},
            dependencies=["T1", "T2", "T3"],
        )

        dag.add_tasks([t1, t2, t3, t4])
        return dag
