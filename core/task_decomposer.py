"""LLM 驱动的动态任务分解器。

取代 ResultAssembler.build_task_queue() 的硬编码 T1-T4 四任务分解，
由 LLM 根据用户请求的语义内容动态决定任务数量、类型和依赖关系。

LLM 不可用时自动 fallback 到现有硬编码逻辑。

来源: spec/orchestrator_spec.md §2.2
"""

from __future__ import annotations

import json
import logging
from typing import Any, Dict, List, Optional

from .llm_client import LLMClient, LLMError
from .message import TaskType
from .orchestration_engine import Task, TaskDAG

logger = logging.getLogger(__name__)

# ============================================================
# LLM Prompt 模板
# ============================================================

_TASK_DECOMPOSER_SYSTEM = """你是一个旅行规划任务分解专家。根据用户的旅行需求，将规划过程分解为原子任务。

## 可用任务类型
- TASK_CREATE_ITINERARY: 创意生成类任务 (交通规划、住宿推荐、每日行程编排、预算分配)
- TASK_VALIDATE_FEASIBILITY: 可行性验证 (价格合理性、时间冲突、地理绕路、约束满足)
- TASK_EVALUATE_PLAN: 质量评估 (完整性、可行性、体验质量、信息准确性)
- TASK_REVISE_ITINERARY: 行程修订 (根据反馈修改已有方案)

## 分解规则
1. 每个任务必须有唯一 task_id (T1, T2, ...)
2. 交通和住宿任务可并行 (无相互依赖)，每日行程依赖交通和住宿完成，预算分配依赖所有任务完成
3. 多目的地场景下，每个目的地可有独立的交通/住宿/行程任务
4. 简单场景 (单日/低预算/本地游) 可减少任务数量
5. 复杂场景 (多目的地/长行程/特殊需求) 需更细粒度分解
6. 任务数量应在 2-8 个之间

## 输出格式
严格输出以下 JSON 结构 (不要包含其他文字):
{
  "tasks": [
    {
      "task_id": "T1",
      "title": "交通方案规划",
      "task_type": "TASK_CREATE_ITINERARY",
      "dependencies": [],
      "payload": {"aspect": "transportation"}
    }
  ]
}
"""

_TASK_DECOMPOSER_USER = """请将以下旅行需求分解为原子任务。

## 目的地
{destination}

## 日期
{dates}

## 预算
{budget}

## 人数
{travelers}

## 偏好
{preferences}

请分解为原子任务并输出 JSON。"""

# ============================================================
# 输出 Schema
# ============================================================

_TASK_LIST_SCHEMA = {
    "type": "object",
    "required": ["tasks"],
    "properties": {
        "tasks": {
            "type": "array",
            "items": {
                "type": "object",
                "required": ["task_id", "title", "task_type"],
                "properties": {
                    "task_id": {"type": "string"},
                    "title": {"type": "string"},
                    "task_type": {"type": "string"},
                    "dependencies": {"type": "array"},
                    "payload": {"type": "object"},
                },
            },
        },
    },
}

_VALID_TASK_TYPE_VALUES = {t.value for t in TaskType if t.is_request()}


# ============================================================
# TaskDecomposer
# ============================================================

class TaskDecomposer:
    """LLM 驱动的动态任务分解器。

    使用 LLM 根据用户需求动态生成任务 DAG，LLM 不可用时 fallback 到
    ResultAssembler.build_task_queue() 的硬编码逻辑。

    Usage:
        decomposer = TaskDecomposer(llm_client)
        task_dag = await decomposer.decompose(request_dict)
    """

    def __init__(self, llm_client: Optional[LLMClient] = None):
        """初始化分解器。

        Args:
            llm_client: LLM 客户端。为 None 时始终使用 fallback。
        """
        self._llm_client = llm_client

    @property
    def llm_available(self) -> bool:
        """LLM 是否可用于动态分解。"""
        return self._llm_client is not None and self._llm_client.available

    # -- 公共 API --

    async def decompose(self, request: Dict[str, Any]) -> TaskDAG:
        """将用户请求分解为原子任务 DAG。

        LLM 可用时：动态生成任务列表 → 校验 → 构建 TaskDAG
        LLM 不可用时：fallback 到硬编码 build_task_queue

        Args:
            request: StructuredRequest.to_dict() 的输出。

        Returns:
            TaskDAG，含动态或静态分解的任务。
        """
        if not self.llm_available:
            logger.info("LLM 不可用，使用硬编码任务分解")
            return self._build_fallback_dag(request)

        try:
            llm_output = await self._call_llm(request)
            tasks = self._parse_and_validate(llm_output)
            dag = self._build_dag(tasks)
            logger.info(
                "LLM 动态分解完成: %d 个任务 [%s]",
                dag.task_count,
                ", ".join(t.task_id for t in dag.get_all_tasks()),
            )
            return dag
        except (LLMError, ValueError, json.JSONDecodeError, KeyError) as exc:
            logger.warning("LLM 动态分解失败，fallback 到硬编码: %s", exc)
            return self._build_fallback_dag(request)

    # -- 内部方法 --

    async def _call_llm(self, request: Dict[str, Any]) -> Dict[str, Any]:
        """调用 LLM 生成任务分解。"""
        user_prompt = _TASK_DECOMPOSER_USER.format(
            destination=self._fmt_destination(request),
            dates=self._fmt_dates(request),
            budget=self._fmt_budget(request),
            travelers=self._fmt_travelers(request),
            preferences=self._fmt_preferences(request),
        )
        return await self._llm_client.generate(
            system_prompt=_TASK_DECOMPOSER_SYSTEM,
            user_prompt=user_prompt,
            output_schema=_TASK_LIST_SCHEMA,
        )

    @staticmethod
    def _parse_and_validate(llm_output: Dict[str, Any]) -> List[Dict[str, Any]]:
        """校验 LLM 输出并返回合法任务列表。

        Raises:
            ValueError: 输出不合规且无法修复。
        """
        raw_tasks: list = llm_output.get("tasks", [])
        if not raw_tasks:
            raise ValueError("LLM 返回了空任务列表")
        if len(raw_tasks) > 12:
            raise ValueError(f"任务数量过多: {len(raw_tasks)} > 12")

        valid_tasks: List[Dict[str, Any]] = []
        seen_ids: set = set()

        for raw in raw_tasks:
            task_id = str(raw.get("task_id", "")).strip()
            if not task_id:
                raise ValueError(f"任务缺少 task_id: {raw}")
            if task_id in seen_ids:
                raise ValueError(f"重复的 task_id: {task_id}")
            seen_ids.add(task_id)

            task_type_str = raw.get("task_type", "")
            if task_type_str not in _VALID_TASK_TYPE_VALUES:
                logger.warning(
                    "任务 %s 的 task_type '%s' 无效，已修正为 TASK_CREATE_ITINERARY",
                    task_id, task_type_str,
                )
                task_type_str = TaskType.TASK_CREATE_ITINERARY.value

            deps = raw.get("dependencies", [])
            if not isinstance(deps, list):
                deps = []

            payload = raw.get("payload", {})
            if not isinstance(payload, dict):
                payload = {}

            valid_tasks.append({
                "task_id": task_id,
                "title": str(raw.get("title", f"任务 {task_id}")),
                "task_type": task_type_str,
                "dependencies": [str(d) for d in deps],
                "payload": payload,
            })

        _check_cycles(valid_tasks)
        _check_orphans(valid_tasks)
        return valid_tasks

    @staticmethod
    def _build_dag(task_dicts: List[Dict[str, Any]]) -> TaskDAG:
        """将任务字典列表构建为 TaskDAG。"""
        dag = TaskDAG()
        for td in task_dicts:
            dag.add_task(Task(
                task_id=td["task_id"],
                title=td["title"],
                task_type=TaskType(td["task_type"]),
                payload=td.get("payload", {}),
                dependencies=td.get("dependencies", []),
            ))
        return dag

    # -- Fallback --

    @staticmethod
    def _build_fallback_dag(request: Dict[str, Any]) -> TaskDAG:
        """LLM 不可用时的硬编码 fallback —— 标准 T1-T4 四任务分解。"""
        dag = TaskDAG()
        dag.add_tasks([
            Task("T1", "交通方案规划", TaskType.TASK_CREATE_ITINERARY,
                 {"aspect": "transportation", "request": request}, []),
            Task("T2", "住宿方案规划", TaskType.TASK_CREATE_ITINERARY,
                 {"aspect": "accommodation", "request": request}, []),
            Task("T3", "每日行程规划", TaskType.TASK_CREATE_ITINERARY,
                 {"aspect": "daily_itinerary", "request": request}, ["T1", "T2"]),
            Task("T4", "预算分配方案", TaskType.TASK_CREATE_ITINERARY,
                 {"aspect": "budget_allocation", "request": request}, ["T1", "T2", "T3"]),
        ])
        logger.info("使用硬编码 fallback: 标准 4 任务分解 [T1, T2, T3, T4]")
        return dag

    # -- 格式化辅助 --

    @staticmethod
    def _fmt_destination(req: Dict[str, Any]) -> str:
        d = req.get("destination", {})
        if isinstance(d, dict):
            city = d.get("city", "未知")
            country = d.get("country", "")
            return f"{city}, {country}" if country else str(city)
        return str(d)

    @staticmethod
    def _fmt_dates(req: Dict[str, Any]) -> str:
        d = req.get("dates", {})
        if not isinstance(d, dict):
            return "未指定"
        parts = []
        if d.get("arrival"):
            parts.append(f"出发: {d['arrival']}")
        if d.get("departure"):
            parts.append(f"返回: {d['departure']}")
        if d.get("duration_days"):
            parts.append(f"天数: {d['duration_days']}天")
        return ", ".join(parts) if parts else "未指定"

    @staticmethod
    def _fmt_budget(req: Dict[str, Any]) -> str:
        b = req.get("budget", {})
        if not isinstance(b, dict):
            return "未指定"
        total = b.get("total", 0)
        currency = b.get("currency", "CNY")
        return f"{total} {currency}" if total else "未指定"

    @staticmethod
    def _fmt_travelers(req: Dict[str, Any]) -> str:
        t = req.get("travelers", {})
        if not isinstance(t, dict):
            return "1人"
        parts = []
        if t.get("adults"):
            parts.append(f"{t['adults']}成人")
        if t.get("children"):
            parts.append(f"{t['children']}儿童")
        return ", ".join(parts) if parts else "1人"

    @staticmethod
    def _fmt_preferences(req: Dict[str, Any]) -> str:
        p = req.get("preferences", {})
        if not isinstance(p, dict):
            return "无特殊偏好"
        parts = []
        if p.get("style"):
            parts.append(f"偏好: {', '.join(p['style'])}")
        if p.get("pace"):
            parts.append(f"节奏: {p['pace']}")
        if p.get("dietary"):
            parts.append(f"饮食限制: {', '.join(p['dietary'])}")
        return "; ".join(parts) if parts else "无特殊偏好"


# ============================================================
# 模块级校验函数 (供外部测试使用)
# ============================================================

def _check_cycles(tasks: List[Dict[str, Any]]) -> None:
    """Kahn 算法检测循环依赖。

    Raises:
        ValueError: 存在循环依赖。
    """
    all_ids = {t["task_id"] for t in tasks}
    in_degree: Dict[str, int] = {t["task_id"]: 0 for t in tasks}
    adj: Dict[str, List[str]] = {t["task_id"]: [] for t in tasks}

    for t in tasks:
        for dep in t.get("dependencies", []):
            if dep in all_ids:
                in_degree[t["task_id"]] += 1
                adj.setdefault(dep, []).append(t["task_id"])

    queue = [tid for tid, deg in in_degree.items() if deg == 0]
    visited = 0
    while queue:
        tid = queue.pop(0)
        visited += 1
        for nb in adj.get(tid, []):
            in_degree[nb] -= 1
            if in_degree[nb] == 0:
                queue.append(nb)

    if visited != len(tasks):
        raise ValueError(f"循环依赖: 仅 {visited}/{len(tasks)} 节点可达")


def _check_orphans(tasks: List[Dict[str, Any]]) -> None:
    """检测依赖了不存在的任务。

    Raises:
        ValueError: 存在孤立依赖。
    """
    all_ids = {t["task_id"] for t in tasks}
    for t in tasks:
        for dep in t.get("dependencies", []):
            if dep not in all_ids:
                raise ValueError(f"任务 {t['task_id']} 依赖不存在的: {dep}")


__all__ = ["TaskDecomposer", "_check_cycles", "_check_orphans"]
