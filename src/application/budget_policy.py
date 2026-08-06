"""M4 第三步：Task Graph 的确定性调用预算策略。"""

from __future__ import annotations

from decimal import Decimal
from typing import Final

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from src.application.task_graph import TaskGraph, TaskSpec

MAX_TASKS: Final[int] = 16
DEFAULT_MAX_CONCURRENT_TASKS: Final[int] = 4
DEFAULT_MAX_TOOL_CALLS: Final[int] = 32
DEFAULT_MAX_MODEL_CALLS: Final[int] = 8
DEFAULT_WORKFLOW_TIMEOUT_SECONDS: Final[float] = 300.0


class BudgetExhaustedError(RuntimeError):
    """工作流预算不足，调用方必须将工作流置为 FAILED。"""

    def __init__(
        self, resource: str, limit: Decimal | int | float, observed: Decimal | int | float
    ) -> None:
        self.resource = resource
        self.limit = Decimal(str(limit))
        self.observed = Decimal(str(observed))
        super().__init__(f"{resource} budget exhausted: {self.observed} > {self.limit}")


class BudgetPolicy(BaseModel):
    """声明一个工作流的硬预算上限。"""

    model_config = ConfigDict(extra="forbid", frozen=True)

    max_tasks: int = Field(default=MAX_TASKS, gt=0)
    max_concurrent_tasks: int = Field(default=DEFAULT_MAX_CONCURRENT_TASKS, gt=0)
    max_total_tool_calls: int = Field(default=DEFAULT_MAX_TOOL_CALLS, ge=0)
    max_model_calls: int = Field(default=DEFAULT_MAX_MODEL_CALLS, ge=0)
    workflow_timeout_seconds: float = Field(
        default=DEFAULT_WORKFLOW_TIMEOUT_SECONDS,
        gt=0,
    )
    max_estimated_cost: Decimal = Field(default=Decimal("0"), ge=Decimal("0"))

    @field_validator("workflow_timeout_seconds")
    @classmethod
    def validate_finite_timeout(cls, value: float) -> float:
        """拒绝 NaN 和无穷大，避免预算比较失去确定性。"""
        if value == float("inf") or value == float("-inf") or value != value:
            raise ValueError("workflow_timeout_seconds must be finite")
        return value

    @model_validator(mode="after")
    def validate_concurrency(self) -> BudgetPolicy:
        """并发上限不能超过任务总上限。"""
        if self.max_concurrent_tasks > self.max_tasks:
            raise ValueError("max_concurrent_tasks must not exceed max_tasks")
        return self

    def preflight(self, graph: TaskGraph) -> BudgetAllocation:
        """预检 Task Graph 的声明预算，超限时整体失败。"""
        if not isinstance(graph, TaskGraph):
            raise TypeError("graph must be a TaskGraph")

        task_count = len(graph.tasks)
        total_tool_calls = sum(task.tool_call_budget for task in graph.tasks)
        total_model_calls = sum(task.model_call_budget for task in graph.tasks)
        critical_path_timeout = _critical_path_timeout(graph)
        peak_concurrency = _peak_dependency_wave(graph)

        _ensure_within("max_tasks", task_count, self.max_tasks)
        _ensure_within("max_concurrent_tasks", peak_concurrency, self.max_concurrent_tasks)
        _ensure_within("max_total_tool_calls", total_tool_calls, self.max_total_tool_calls)
        _ensure_within("max_model_calls", total_model_calls, self.max_model_calls)
        _ensure_within(
            "workflow_timeout_seconds",
            critical_path_timeout,
            self.workflow_timeout_seconds,
        )

        return BudgetAllocation(
            graph_id=graph.graph_id,
            task_count=task_count,
            peak_concurrency=peak_concurrency,
            total_tool_calls=total_tool_calls,
            total_model_calls=total_model_calls,
            critical_path_timeout_seconds=critical_path_timeout,
            estimated_cost=Decimal("0"),
        )

    def check_usage(self, usage: BudgetUsage) -> None:
        """检查运行时消耗；不调整预算，也不吞掉超限错误。"""
        if not isinstance(usage, BudgetUsage):
            raise TypeError("usage must be a BudgetUsage")
        _ensure_within("max_tasks", usage.started_tasks, self.max_tasks)
        _ensure_within("max_concurrent_tasks", usage.active_tasks, self.max_concurrent_tasks)
        _ensure_within("max_total_tool_calls", usage.tool_calls, self.max_total_tool_calls)
        _ensure_within("max_model_calls", usage.model_calls, self.max_model_calls)
        _ensure_within(
            "workflow_timeout_seconds",
            usage.elapsed_seconds,
            self.workflow_timeout_seconds,
        )
        _ensure_within("max_estimated_cost", usage.estimated_cost, self.max_estimated_cost)


class BudgetUsage(BaseModel):
    """Orchestrator 可在执行中累加的不可变预算快照。"""

    model_config = ConfigDict(extra="forbid", frozen=True)

    started_tasks: int = Field(default=0, ge=0)
    active_tasks: int = Field(default=0, ge=0)
    tool_calls: int = Field(default=0, ge=0)
    model_calls: int = Field(default=0, ge=0)
    elapsed_seconds: float = Field(default=0.0, ge=0)
    estimated_cost: Decimal = Field(default=Decimal("0"), ge=Decimal("0"))

    @field_validator("elapsed_seconds")
    @classmethod
    def validate_finite_elapsed(cls, value: float) -> float:
        """拒绝非有限运行时长。"""
        if value == float("inf") or value == float("-inf") or value != value:
            raise ValueError("elapsed_seconds must be finite")
        return value


class BudgetAllocation(BaseModel):
    """Task Graph 预检后的确定性预算摘要。"""

    model_config = ConfigDict(extra="forbid", frozen=True)

    graph_id: str = Field(min_length=1)
    task_count: int = Field(ge=0)
    peak_concurrency: int = Field(ge=0)
    total_tool_calls: int = Field(ge=0)
    total_model_calls: int = Field(ge=0)
    critical_path_timeout_seconds: float = Field(ge=0)
    estimated_cost: Decimal = Field(ge=Decimal("0"))


def _ensure_within(
    resource: str, observed: Decimal | int | float, limit: Decimal | int | float
) -> None:
    if Decimal(str(observed)) > Decimal(str(limit)):
        raise BudgetExhaustedError(resource, limit, observed)


def _critical_path_timeout(graph: TaskGraph) -> float:
    task_by_id = {task.task_id: task for task in graph.tasks}
    durations: dict[str, float] = {}

    def duration(task: TaskSpec) -> float:
        if task.task_id not in durations:
            durations[task.task_id] = task.timeout + max(
                (duration(task_by_id[dependency]) for dependency in task.dependencies),
                default=0.0,
            )
        return durations[task.task_id]

    return max((duration(task) for task in graph.tasks), default=0.0)


def _peak_dependency_wave(graph: TaskGraph) -> int:
    task_by_id = {task.task_id: task for task in graph.tasks}
    levels: dict[str, int] = {}

    def level(task: TaskSpec) -> int:
        if task.task_id not in levels:
            levels[task.task_id] = 1 + max(
                (level(task_by_id[dependency]) for dependency in task.dependencies),
                default=-1,
            )
        return levels[task.task_id]

    for task in graph.tasks:
        level(task)
    waves: dict[int, int] = {}
    for task_level in levels.values():
        waves[task_level] = waves.get(task_level, 0) + 1
    return max(waves.values(), default=0)
