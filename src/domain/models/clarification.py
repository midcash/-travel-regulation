"""M2 ClarificationRequest 的结构化澄清契约。"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field, field_validator

from src.domain.models.enums import InteractionMode
from src.domain.models.readiness import ReadinessBlockerCode
from src.domain.models.value_objects import (
    ConstraintId,
    IssueId,
    RequestId,
    StableId,
    TraceId,
)


class ClarificationQuestion(BaseModel):
    """一个由 G1 blocker 直接映射出的、必须回答的问题。"""

    model_config = ConfigDict(extra="forbid", frozen=True, str_strip_whitespace=True)

    question_id: StableId
    blocker_ref: IssueId
    code: ReadinessBlockerCode
    field: str = Field(min_length=1, max_length=128)
    question: str = Field(min_length=1, max_length=512)
    constraint_refs: tuple[ConstraintId, ...] = ()
    conflict_group: StableId | None = None
    priority: int = Field(ge=0)

    @field_validator("constraint_refs")
    @classmethod
    def validate_unique_constraint_refs(
        cls,
        values: tuple[ConstraintId, ...],
    ) -> tuple[ConstraintId, ...]:
        """拒绝重复引用，确保用户回答只回写一次相关约束。"""
        if len(values) != len(set(values)):
            raise ValueError("clarification constraint references must be unique")
        return values


class ClarificationRequest(BaseModel):
    """当前约束快照需要用户补充的最少必要澄清请求。"""

    model_config = ConfigDict(extra="forbid", frozen=True, str_strip_whitespace=True)

    trace_id: TraceId
    request_id: RequestId
    snapshot_version: int = Field(ge=1)
    mode: InteractionMode
    questions: tuple[ClarificationQuestion, ...] = Field(min_length=1, max_length=3)
    deferred_blocker_refs: tuple[IssueId, ...] = ()

    @field_validator("questions")
    @classmethod
    def validate_unique_blockers(
        cls,
        values: tuple[ClarificationQuestion, ...],
    ) -> tuple[ClarificationQuestion, ...]:
        """一个 blocker 只能生成一个问题，避免重复追问。"""
        blocker_refs = tuple(question.blocker_ref for question in values)
        if len(blocker_refs) != len(set(blocker_refs)):
            raise ValueError("clarification blocker references must be unique")
        return values

    @field_validator("deferred_blocker_refs")
    @classmethod
    def validate_unique_deferred_blockers(
        cls,
        values: tuple[IssueId, ...],
    ) -> tuple[IssueId, ...]:
        """拒绝重复记录尚未提问的 blocker。"""
        if len(values) != len(set(values)):
            raise ValueError("deferred clarification blocker references must be unique")
        return values
