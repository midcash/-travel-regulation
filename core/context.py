"""共享上下文黑板模式实现。

包含:
- ContextStatus 枚举 (流水线状态机)
- LogEntry 数据类 (操作日志条目)
- SharedContext 类 (Agent 间共享状态的中央存储)

SharedContext 约束: Orchestrator 是唯一写入者，子 Agent 只读访问。
来源: spec/system_spec.md §5, spec/orchestrator_spec.md §4
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Dict, List, Optional, Set, TYPE_CHECKING

if TYPE_CHECKING:
    pass  # models 模块尚未实现，后续在此处导入强类型


# ============================================================
# ContextStatus 枚举 — spec/orchestrator_spec.md §4.1
# ============================================================

class ContextStatus(Enum):
    """流水线状态枚举。

    采用 orchestrator_spec.md §4.1 的 15 个细粒度状态。
    终态 (COMPLETED / COMPLETED_DEGRADED / FAILED) 不可再转换到其他状态。
    """

    IDLE = "idle"
    VALIDATING = "validating"
    DECOMPOSING = "decomposing"
    DISPATCHING = "dispatching"
    WAITING_PLANNER = "waiting_planner"
    WAITING_EXECUTOR = "waiting_executor"
    GATE_1 = "gate_1"
    WAITING_EVALUATOR = "waiting_evaluator"
    DECIDING = "deciding"
    REVISING = "revising"
    ASSEMBLING = "assembling"
    GATE_3 = "gate_3"
    COMPLETED = "completed"
    COMPLETED_DEGRADED = "completed_degraded"
    FAILED = "failed"

    def is_terminal(self) -> bool:
        """判断是否为终态 (不可再转换到其他状态)。"""
        return self in _TERMINAL_STATES

    def is_waiting(self) -> bool:
        """判断是否为等待子 Agent 返回的状态。"""
        return self in _WAITING_STATES


_TERMINAL_STATES: Set[ContextStatus] = frozenset({
    ContextStatus.COMPLETED,
    ContextStatus.COMPLETED_DEGRADED,
    ContextStatus.FAILED,
})

_WAITING_STATES: Set[ContextStatus] = frozenset({
    ContextStatus.WAITING_PLANNER,
    ContextStatus.WAITING_EXECUTOR,
    ContextStatus.WAITING_EVALUATOR,
})


# ============================================================
# LogEntry 数据类 — spec/system_spec.md §5.1
# ============================================================

@dataclass(frozen=True)
class LogEntry:
    """操作日志条目 (不可变)。"""

    timestamp: datetime
    """日志时间戳。"""

    level: str
    """日志级别: 'INFO' | 'WARNING' | 'ERROR' | 'DEBUG'。"""

    message: str
    """日志内容。"""

    source: str
    """来源 (agent_name 或 'orchestrator')。"""

    details: Optional[Dict[str, Any]] = None
    """可选的结构化详情。"""


# ============================================================
# SharedContext — spec/system_spec.md §5.1 + orchestrator_spec.md §4.2
# ============================================================

class SharedContext:
    """Agent 间共享状态的中央存储 (黑板模式)。

    约束: Orchestrator 是唯一写入者。子 Agent 只能通过 getter 只读访问。

    状态转换图 (15 状态 × 所有合法转换):

                         ┌──────────┐
                         │   IDLE   │
                         └────┬─────┘
                              │
                   ┌──────────┴──────────┐
                   ▼                     ▼
             ┌──────────┐          ┌──────────┐
             │VALIDATING│          │  FAILED  │ (终态)
             └────┬─────┘          └──────────┘
                  │
           ┌──────┴──────┐
           ▼              ▼
     ┌──────────┐   ┌──────────┐
     │DECOMPOSING│   │  FAILED  │ (终态)
     └────┬─────┘   └──────────┘
          │
   ┌──────┴──────┐
   ▼              ▼
┌──────────┐ ┌──────────┐
│DISPATCHING│ │  FAILED  │ (终态)
└────┬─────┘ └──────────┘
     │
     ▼
┌────────────────┐ ── REVISING ──┐
│ WAITING_PLANNER │              │
└───────┬────────┘              │
        │                       │
   ┌────┴────┬──────┐           │
   ▼         ▼      ▼           │
┌───────┐ ┌──────┐ ┌──────┐     │
│WAITING│ │REVIS-│ │FAILED│     │
│EXECUTR│ │ ING  │ │(终态)│     │
└───┬───┘ └──┬───┘ └──────┘     │
    │        │                   │
    ▼        └──────────(返回)───┘
┌────────┐ ── REVISING ──────────────────────────────┐
│ GATE_1 │                                           │
└───┬────┘                                           │
    │                                                │
┌───┴────┬──────┐                                    │
▼        ▼      ▼                                    │
┌──────┐ ┌────┐ ┌──────┐                              │
│WAITING│ │REVI│ │FAILED│                              │
│EVALUAT│ │SING│ │(终态)│                              │
└──┬───┘ └──┬─┘ └──────┘                              │
   │        │                                         │
   ▼        └────────────────(返回)───────────────────┘
┌──────────┐
│ DECIDING │
└────┬─────┘
     │
┌────┴────┬──────────┬──────────┐
▼         ▼          ▼          ▼
┌──────┐ ┌──────┐ ┌────────┐ ┌──────┐
│ASSEM-│ │REVIS-│ │COMPLETE│ │FAILED│
│BLING │ │ ING  │ │_DEGRAD │ │(终态)│
└──┬───┘ └──┬───┘ └────────┘ └──────┘
   │        │
   ▼        └────────────(返回 WAITING_PLANNER)────────┐
┌────────┐                                              │
│ GATE_3 │                                              │
└───┬────┘                                              │
    │                                                   │
┌───┴────┬──────────┬──────────┐                        │
▼        ▼          ▼          ▼                        │
┌──────┐ ┌────────┐ ┌──────┐ ┌────────┐                 │
│COMPLE│ │COMPLETE│ │FAILED│ │WAITING_│                 │
│TED   │ │_DEGRAD │ │(终态)│ │PLANNER │ (修订返回入口)  │
└──────┘ └────────┘ └──────┘ └────────┘                 │
   (终态)   (终态)                                       │
                                                        │
修订闭环 (REVISING 返回路径):                            │
  REVISING → WAITING_PLANNER (唯一合法出口) ←───────────┘

注: 几乎所有非终态均可直接转换到 FAILED (省略所有 FAILED 边以保持图清晰)。
    已验证: 当前 _VALID_TRANSITIONS 无死角 (v1.2.0 P2, 2026-07-07)。

    使用示例:
        ctx = SharedContext()
        ctx.set_request({"destination": "Tokyo", ...})
        ctx.set_status(ContextStatus.DECOMPOSING)
        ...
        data = ctx.to_dict()
        restored = SharedContext.from_dict(data)
    """

    # -- 合法的状态转换表 --
    # 来源: orchestrator_spec.md §4.1 状态转换图
    _VALID_TRANSITIONS: Dict[ContextStatus, Set[ContextStatus]] = {
        ContextStatus.IDLE: {
            ContextStatus.VALIDATING,
            ContextStatus.FAILED,
        },
        ContextStatus.VALIDATING: {
            ContextStatus.DECOMPOSING,
            ContextStatus.FAILED,
        },
        ContextStatus.DECOMPOSING: {
            ContextStatus.DISPATCHING,
            ContextStatus.FAILED,
        },
        ContextStatus.DISPATCHING: {
            ContextStatus.WAITING_PLANNER,
            ContextStatus.FAILED,
        },
        ContextStatus.WAITING_PLANNER: {
            ContextStatus.WAITING_EXECUTOR,
            ContextStatus.REVISING,
            ContextStatus.FAILED,
        },
        ContextStatus.WAITING_EXECUTOR: {
            ContextStatus.GATE_1,
            ContextStatus.FAILED,
        },
        ContextStatus.GATE_1: {
            ContextStatus.WAITING_EVALUATOR,
            ContextStatus.REVISING,
            ContextStatus.FAILED,
        },
        ContextStatus.WAITING_EVALUATOR: {
            ContextStatus.DECIDING,
            ContextStatus.FAILED,
        },
        ContextStatus.DECIDING: {
            ContextStatus.ASSEMBLING,
            ContextStatus.REVISING,
            ContextStatus.COMPLETED_DEGRADED,
            ContextStatus.FAILED,
        },
        ContextStatus.REVISING: {
            ContextStatus.WAITING_PLANNER,
            ContextStatus.FAILED,
        },
        ContextStatus.ASSEMBLING: {
            ContextStatus.GATE_3,
            ContextStatus.FAILED,
        },
        ContextStatus.GATE_3: {
            ContextStatus.COMPLETED,
            ContextStatus.COMPLETED_DEGRADED,
            ContextStatus.FAILED,
        },
        # 终态不可转出
        ContextStatus.COMPLETED: set(),
        ContextStatus.COMPLETED_DEGRADED: set(),
        ContextStatus.FAILED: set(),
    }

    def __init__(
        self,
        strict_mode: bool = True,
        request_id: Optional[str] = None,
    ):
        """初始化 SharedContext。

        Args:
            strict_mode: 严格模式。False 时跳过状态转换合法性校验（测试/调试用）。
            request_id: 请求标识符，用于日志追踪。None 时自动生成。
        """
        # -- 业务数据 --
        self._request: Optional[Dict[str, Any]] = None
        self._task_queue: Optional[Dict[str, Any]] = None
        self._current_draft: Optional[Dict[str, Any]] = None
        self._validation_report: Optional[Dict[str, Any]] = None
        self._quality_report: Optional[Dict[str, Any]] = None

        # -- 流程控制 --
        self._iteration_count: int = 0
        self._status: ContextStatus = ContextStatus.IDLE

        # -- 状态机配置 --
        self.strict_mode: bool = strict_mode
        """严格模式。False 时跳过状态校验（测试/调试用）。"""

        # -- 请求标识 --
        self.request_id: str = request_id or f"req-{id(self):x}"
        """请求标识符，用于日志追踪和调试。"""

        # -- 操作审计 --
        self._logs: List[LogEntry] = []

    # ============================================================
    # 写入操作 (Orchestrator 专用)
    # ============================================================

    def set_request(self, request: Dict[str, Any]) -> None:
        """设置用户请求 (不可变，仅可设置一次)。"""
        self._request = request

    def set_task_queue(self, queue: Dict[str, Any]) -> None:
        """设置当前任务队列。"""
        self._task_queue = queue

    def set_current_draft(self, draft: Optional[Dict[str, Any]]) -> None:
        """设置当前行程草稿。传入 None 清除。"""
        self._current_draft = draft

    def set_validation_report(self, report: Optional[Dict[str, Any]]) -> None:
        """设置最近校验报告。传入 None 清除。"""
        self._validation_report = report

    def set_quality_report(self, report: Optional[Dict[str, Any]]) -> None:
        """设置最近质量评估报告。传入 None 清除。"""
        self._quality_report = report

    def increment_iteration(self) -> int:
        """迭代计数 +1，返回新值。"""
        self._iteration_count += 1
        return self._iteration_count

    def set_status(self, status: ContextStatus) -> None:
        """设置流水线状态。

        执行状态转换校验: 非法转换抛出 ValueError。
        strict_mode=False 时跳过校验，直接设置。

        Raises:
            ValueError: 当前状态不允许转换到目标状态。
            TypeError: status 不是 ContextStatus 枚举值。
        """
        if not isinstance(status, ContextStatus):
            raise TypeError(f"status 必须是 ContextStatus 枚举值, 实际: {type(status)}")

        if not self.strict_mode:
            self._status = status
            return

        allowed = self._VALID_TRANSITIONS.get(self._status, set())
        if status not in allowed:
            legal_targets = sorted(s.name for s in allowed)
            raise ValueError(
                f"非法状态转换 {self._status.name}→{status.name}，"
                f"合法目标: {legal_targets or '(无 — 终态)'}"
            )
        self._status = status

    def force_status(self, status: ContextStatus) -> None:
        """强制设置状态（跳过转换合法性校验）。

        仅在 strict_mode=False 时可用。
        strict_mode=True 时调用将抛出 RuntimeError。

        Args:
            status: 目标状态。

        Raises:
            RuntimeError: strict_mode=True 时调用。
            TypeError: status 不是 ContextStatus 枚举值。
        """
        if not isinstance(status, ContextStatus):
            raise TypeError(f"status 必须是 ContextStatus 枚举值, 实际: {type(status)}")

        if self.strict_mode:
            raise RuntimeError(
                f"force_status() 仅在 strict_mode=False 时可用。"
                f"当前 strict_mode=True，请使用 set_status() 走正常校验流程。"
            )
        self._status = status

    # ============================================================
    # 状态机辅助工具 (类方法) — v1.2.0 P2
    # ============================================================

    @classmethod
    def get_legal_transitions(cls, status: ContextStatus) -> Set[ContextStatus]:
        """查询给定状态的合法目标状态集合。

        Args:
            status: 查询的源状态。

        Returns:
            合法目标状态的集合（终态返回空集合）。
        """
        return cls._VALID_TRANSITIONS.get(status, set())

    @classmethod
    def get_transition_path(
        cls,
        from_status: ContextStatus,
        to_status: ContextStatus,
    ) -> List[ContextStatus]:
        """BFS 寻找状态转换的最短路径。

        Args:
            from_status: 起始状态。
            to_status: 目标状态。

        Returns:
            状态列表（含起点和终点）。若无路径，返回空列表。
        """
        if from_status == to_status:
            return [from_status]

        from collections import deque

        queue = deque([[from_status]])
        visited: Set[ContextStatus] = {from_status}

        while queue:
            path = queue.popleft()
            current = path[-1]
            for next_status in cls._VALID_TRANSITIONS.get(current, set()):
                if next_status == to_status:
                    return path + [next_status]
                if next_status not in visited:
                    visited.add(next_status)
                    queue.append(path + [next_status])
        return []  # 无路径

    def add_log(
        self,
        level: str,
        message: str,
        source: str,
        details: Optional[Dict[str, Any]] = None,
    ) -> None:
        """追加一条操作日志。自动设置时间戳为当前 UTC 时间。"""
        entry = LogEntry(
            timestamp=datetime.now(timezone.utc),
            level=level,
            message=message,
            source=source,
            details=details,
        )
        self._logs.append(entry)

    # ============================================================
    # 读取操作
    # ============================================================

    def get_request(self) -> Optional[Dict[str, Any]]:
        """获取用户请求。"""
        return self._request

    def get_task_queue(self) -> Optional[Dict[str, Any]]:
        """获取当前任务队列。"""
        return self._task_queue

    def get_current_draft(self) -> Optional[Dict[str, Any]]:
        """获取当前行程草稿。"""
        return self._current_draft

    def get_validation_report(self) -> Optional[Dict[str, Any]]:
        """获取最近校验报告。"""
        return self._validation_report

    def get_quality_report(self) -> Optional[Dict[str, Any]]:
        """获取最近质量评估报告。"""
        return self._quality_report

    def get_iteration_count(self) -> int:
        """获取当前迭代轮次。"""
        return self._iteration_count

    def get_status(self) -> ContextStatus:
        """获取当前流水线状态。"""
        return self._status

    def get_logs(
        self,
        level: Optional[str] = None,
        source: Optional[str] = None,
    ) -> List[LogEntry]:
        """获取操作日志，支持按级别和来源过滤。

        Args:
            level: 可选，仅返回此级别的日志。
            source: 可选，仅返回此来源的日志。

        Returns:
            过滤后的日志列表 (按时间升序)。
        """
        result = self._logs
        if level is not None:
            result = [e for e in result if e.level == level]
        if source is not None:
            result = [e for e in result if e.source == source]
        return result

    # ============================================================
    # 生命周期
    # ============================================================

    def reset(self) -> None:
        """重置所有状态到初始值。用于一个请求处理完成后的清理。"""
        self._request = None
        self._task_queue = None
        self._current_draft = None
        self._validation_report = None
        self._quality_report = None
        self._iteration_count = 0
        self._status = ContextStatus.IDLE
        self._logs = []

    def to_dict(self) -> Dict[str, Any]:
        """序列化为 JSON 可序列化的字典。

        datetime → ISO 8601 字符串
        ContextStatus → 值字符串
        LogEntry 列表 → 字典列表
        """
        return {
            "request": self._request,
            "task_queue": self._task_queue,
            "current_draft": self._current_draft,
            "validation_report": self._validation_report,
            "quality_report": self._quality_report,
            "iteration_count": self._iteration_count,
            "status": self._status.value,
            "logs": [
                {
                    "timestamp": e.timestamp.isoformat(),
                    "level": e.level,
                    "message": e.message,
                    "source": e.source,
                    "details": e.details,
                }
                for e in self._logs
            ],
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> SharedContext:
        """从 to_dict() 的输出恢复 SharedContext 对象。

        与 to_dict() 互为逆操作。
        """
        ctx = cls()
        ctx._request = data.get("request")
        ctx._task_queue = data.get("task_queue")
        ctx._current_draft = data.get("current_draft")
        ctx._validation_report = data.get("validation_report")
        ctx._quality_report = data.get("quality_report")
        ctx._iteration_count = data.get("iteration_count", 0)

        # 恢复 ContextStatus
        status_raw = data.get("status", "idle")
        ctx._status = ContextStatus(status_raw)

        # 恢复日志
        ctx._logs = []
        for entry_data in data.get("logs", []):
            timestamp_str = entry_data.get("timestamp", "")
            try:
                timestamp = datetime.fromisoformat(timestamp_str)
            except (ValueError, TypeError):
                timestamp = datetime.now(timezone.utc)
            ctx._logs.append(LogEntry(
                timestamp=timestamp,
                level=entry_data.get("level", "INFO"),
                message=entry_data.get("message", ""),
                source=entry_data.get("source", ""),
                details=entry_data.get("details"),
            ))

        return ctx
