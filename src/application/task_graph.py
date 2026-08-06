"""M4 第一步：Task Graph 的不可变领域契约。"""

from __future__ import annotations

from collections.abc import Mapping
from enum import Enum
from math import isfinite
from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from src.domain.models.value_objects import CandidateId, EvidenceId, StableId

TaskId = StableId
TaskType = Annotated[str, Field(min_length=1, max_length=64)]
Capability = Annotated[str, Field(min_length=1, max_length=64)]
OutputType = Annotated[str, Field(min_length=1, max_length=128)]


class TaskStatus(str, Enum):
    """TaskResult 的执行状态。"""

    PENDING = "pending"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    CANCELLED = "cancelled"


class TaskSpec(BaseModel):
    """描述一个可由 Orchestrator 调度的单一任务。"""

    model_config = ConfigDict(extra="forbid", frozen=True, str_strip_whitespace=True)

    task_id: TaskId
    task_type: TaskType
    capability: Capability
    dependencies: tuple[TaskId, ...] = ()
    input_refs: tuple[StableId, ...] = ()
    expected_output_type: OutputType
    timeout: float = Field(gt=0)
    tool_call_budget: int = Field(default=0, ge=0)
    model_call_budget: int = Field(default=0, ge=0)
    priority: int = Field(default=0)

    @field_validator("dependencies", "input_refs")
    @classmethod
    def validate_unique_refs(cls, values: tuple[str, ...]) -> tuple[str, ...]:
        """拒绝重复引用，保持任务定义稳定且可预测。"""
        if len(values) != len(set(values)):
            raise ValueError("task references must be unique")
        return values

    @field_validator("timeout")
    @classmethod
    def validate_timeout(cls, value: float) -> float:
        """拒绝 NaN 和无穷大超时。"""
        if not isfinite(value):
            raise ValueError("timeout must be finite")
        return value


class TaskResult(BaseModel):
    """记录单个任务的结构化执行结果，不携带完整对象。"""

    model_config = ConfigDict(extra="forbid", frozen=True, str_strip_whitespace=True)

    task_id: TaskId
    status: TaskStatus
    output_ref: StableId | None = None
    evidence_refs: tuple[EvidenceId, ...] = ()
    candidate_refs: tuple[CandidateId, ...] = ()
    metrics: Mapping[str, float] = Field(default_factory=dict)
    error_ref: StableId | None = None

    @field_validator("evidence_refs", "candidate_refs")
    @classmethod
    def validate_unique_result_refs(cls, values: tuple[str, ...]) -> tuple[str, ...]:
        """拒绝重复证据或候选引用。"""
        if len(values) != len(set(values)):
            raise ValueError("result references must be unique")
        return values

    @field_validator("metrics")
    @classmethod
    def validate_metrics(cls, values: Mapping[str, float]) -> Mapping[str, float]:
        """限制指标键和值，避免把任意对象塞入结果。"""
        if any(not key.strip() for key in values):
            raise ValueError("metric names must not be empty")
        if any(not isfinite(value) for value in values.values()):
            raise ValueError("metric values must be finite")
        return values

    @model_validator(mode="after")
    def validate_status_references(self) -> TaskResult:
        """确保成功和失败结果分别携带必要的引用。"""
        if self.status is TaskStatus.SUCCEEDED and self.output_ref is None:
            raise ValueError("succeeded task result requires output_ref")
        if self.status is TaskStatus.FAILED and self.error_ref is None:
            raise ValueError("failed task result requires error_ref")
        return self


class TaskGraph(BaseModel):
    """绑定约束快照版本的不可变 DAG 定义。"""

    model_config = ConfigDict(extra="forbid", frozen=True, str_strip_whitespace=True)

    graph_id: StableId
    trip_id: StableId
    constraint_snapshot_id: StableId
    tasks: tuple[TaskSpec, ...]
    graph_version: int = Field(ge=1)

    @model_validator(mode="after")
    def validate_graph(self) -> TaskGraph:
        """校验任务 ID、依赖存在性和 DAG 无环约束。"""
        task_by_id = {task.task_id: task for task in self.tasks}
        if len(task_by_id) != len(self.tasks):
            raise ValueError("task_id must be unique")

        for task in self.tasks:
            if task.task_id in task.dependencies:
                raise ValueError("task cannot depend on itself")
            missing = set(task.dependencies).difference(task_by_id)
            if missing:
                raise ValueError("task dependency does not exist")

        visiting: set[str] = set()
        visited: set[str] = set()

        def visit(task_id: str) -> None:
            if task_id in visiting:
                raise ValueError("task graph must be acyclic")
            if task_id in visited:
                return
            visiting.add(task_id)
            for dependency in task_by_id[task_id].dependencies:
                visit(dependency)
            visiting.remove(task_id)
            visited.add(task_id)

        for task in self.tasks:
            visit(task.task_id)
        return self
