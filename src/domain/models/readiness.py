"""G1 Readiness Gate 的结构化结果契约。"""

from __future__ import annotations

from decimal import Decimal
from enum import Enum
from typing import Annotated, Self

from pydantic import BaseModel, ConfigDict, Field, StrictBool, field_validator, model_validator

from src.domain.models.enums import InteractionMode
from src.domain.models.value_objects import ConstraintId, IssueId, RequestId, StableId, TraceId

ReadinessConfidence = Annotated[Decimal, Field(ge=Decimal("0"), le=Decimal("1"))]


class ReadinessBlockerCode(str, Enum):
    """会阻止当前工作模式继续执行的确定性原因。"""

    MISSING_ORIGIN = "MISSING_ORIGIN"
    MISSING_DESTINATION = "MISSING_DESTINATION"
    DATE_OR_DURATION_UNDETERMINED = "DATE_OR_DURATION_UNDETERMINED"
    DATE_DURATION_CONFLICT = "DATE_DURATION_CONFLICT"
    DATE_RANGE_IN_PAST = "DATE_RANGE_IN_PAST"
    TRAVELER_COUNT_UNDETERMINED = "TRAVELER_COUNT_UNDETERMINED"
    SPECIAL_POPULATION_UNDETERMINED = "SPECIAL_POPULATION_UNDETERMINED"
    BUDGET_SEMANTIC_CONFLICT = "BUDGET_SEMANTIC_CONFLICT"
    CONSTRAINT_CONFLICT = "CONSTRAINT_CONFLICT"
    HARD_CONSTRAINT_CONFLICT = "CONSTRAINT_CONFLICT"
    ACTION_AUTHORIZATION_REQUIRED = "ACTION_AUTHORIZATION_REQUIRED"
    ACTION_IDENTITY_REQUIRED = "ACTION_IDENTITY_REQUIRED"
    CURRENT_PLAN_REQUIRED = "CURRENT_PLAN_REQUIRED"
    MISSING_MEETING_CITY = "MISSING_MEETING_CITY"
    MISSING_MEETING_LOCATION = "MISSING_MEETING_LOCATION"
    MISSING_MEETING_START = "MISSING_MEETING_START"
    MISSING_MEETING_TIMEZONE = "MISSING_MEETING_TIMEZONE"


class ReadinessAssumptionCode(str, Enum):
    """不会阻止当前模式、但必须在后续交付中显式展示的假设。"""

    BUDGET_NOT_SPECIFIED = "BUDGET_NOT_SPECIFIED"
    EXPLICIT_ASSUMPTION = "EXPLICIT_ASSUMPTION"
    NON_BLOCKING_UNKNOWN = "NON_BLOCKING_UNKNOWN"
    MEETING_TIMEZONE_DERIVED_FROM_CITY = "MEETING_TIMEZONE_DERIVED_FROM_CITY"
    TRAVELER_COUNT_DEFAULTED_TO_ONE = "TRAVELER_COUNT_DEFAULTED_TO_ONE"


class ReadinessBlocker(BaseModel):
    """一个可映射到后续 ClarificationBuilder 的 G1 阻断项。"""

    model_config = ConfigDict(extra="forbid", frozen=True, str_strip_whitespace=True)

    issue_id: IssueId
    code: ReadinessBlockerCode
    field: str = Field(min_length=1, max_length=128)
    message: str = Field(min_length=1, max_length=512)
    constraint_refs: tuple[ConstraintId, ...] = ()
    conflict_group: StableId | None = None
    priority: int = Field(ge=0)

    @field_validator("constraint_refs")
    @classmethod
    def validate_unique_constraint_refs(
        cls,
        values: tuple[ConstraintId, ...],
    ) -> tuple[ConstraintId, ...]:
        """阻止同一个 blocker 重复引用同一条约束。"""
        if len(values) != len(set(values)):
            raise ValueError("readiness constraint references must be unique")
        return values


class ReadinessAssumption(BaseModel):
    """一个不阻断流程、但需要向用户公开的假设。"""

    model_config = ConfigDict(extra="forbid", frozen=True, str_strip_whitespace=True)

    code: ReadinessAssumptionCode
    field: str = Field(min_length=1, max_length=128)
    message: str = Field(min_length=1, max_length=512)
    constraint_refs: tuple[ConstraintId, ...] = ()

    @field_validator("constraint_refs")
    @classmethod
    def validate_unique_constraint_refs(
        cls,
        values: tuple[ConstraintId, ...],
    ) -> tuple[ConstraintId, ...]:
        """阻止假设重复引用同一条约束。"""
        if len(values) != len(set(values)):
            raise ValueError("readiness assumption references must be unique")
        return values


class ActionPreconditions(BaseModel):
    """ACTION 模式所需的认证、授权和主体身份前置条件。"""

    model_config = ConfigDict(extra="forbid", frozen=True)

    authenticated: StrictBool = False
    authorized: StrictBool = False
    identity_ref: StableId | None = None


class ReadinessResult(BaseModel):
    """G1 ReadinessEvaluator 的完整、不可变输出。"""

    model_config = ConfigDict(extra="forbid", frozen=True, str_strip_whitespace=True)

    trace_id: TraceId
    request_id: RequestId
    snapshot_version: int = Field(ge=1)
    mode: InteractionMode
    ready: StrictBool
    confidence: ReadinessConfidence
    blockers: tuple[ReadinessBlocker, ...] = ()
    assumptions: tuple[ReadinessAssumption, ...] = ()

    @model_validator(mode="after")
    def validate_ready_state(self) -> Self:
        """确保 ready 与 blocker 集合始终保持一致。"""
        if self.ready == bool(self.blockers):
            raise ValueError("ready must be the inverse of the presence of blockers")
        return self
