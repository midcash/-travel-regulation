"""M2 Interaction Router 的结构化路由决策契约。"""

from __future__ import annotations

from decimal import Decimal
from enum import Enum
from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from src.domain.models.business_trip import BusinessTripScope, CapabilityReason
from src.domain.models.interpretation import SafetyFlag
from src.domain.models.value_objects import IssueId, StableId

RouteConfidence = Annotated[Decimal, Field(ge=Decimal("0"), le=Decimal("1"))]


class RouteReasonCode(str, Enum):
    """可审计的路由原因代码。"""

    G0_BLOCKED = "G0_BLOCKED"
    EXPLICIT_ACTION = "EXPLICIT_ACTION"
    ACTION_PRECONDITION_MISSING = "ACTION_PRECONDITION_MISSING"
    REFINE_CURRENT_PLAN = "REFINE_CURRENT_PLAN"
    REPLAN_CURRENT_PLAN = "REPLAN_CURRENT_PLAN"
    PLAN_CONTEXT_MISSING = "PLAN_CONTEXT_MISSING"
    CLARIFICATION_REQUIRED = "CLARIFICATION_REQUIRED"
    ANSWER_REQUEST = "ANSWER_REQUEST"
    COMPARE_REQUEST = "COMPARE_REQUEST"
    PLAN_REQUEST = "PLAN_REQUEST"
    UNSUPPORTED_REQUEST = "UNSUPPORTED_REQUEST"
    MULTI_TRAVELER_UNSUPPORTED = "MULTI_TRAVELER_UNSUPPORTED"
    TOURISM_UNSUPPORTED = "TOURISM_UNSUPPORTED"
    ROUTE_UNCERTAIN = "ROUTE_UNCERTAIN"


class RouteDecision(BaseModel):
    """Interaction Router 产出的不可变工作模式决策。"""

    model_config = ConfigDict(extra="forbid", frozen=True, str_strip_whitespace=True)

    mode: str
    confidence: RouteConfidence
    reason_codes: tuple[RouteReasonCode, ...] = Field(min_length=1)
    required_capabilities: tuple[str, ...] = ()
    missing_blockers: tuple[IssueId, ...] = ()
    risk_flags: tuple[SafetyFlag, ...] = ()
    current_plan_ref: StableId | None = None
    business_scope: BusinessTripScope | None = None
    scope_version: str | None = None
    capability_reasons: tuple[CapabilityReason, ...] = ()
    continue_to_planner: bool = True

    @field_validator("mode")
    @classmethod
    def validate_mode(cls, value: str) -> str:
        """要求模式使用 InteractionMode 的稳定字符串值。"""
        from src.domain.models.enums import InteractionMode

        allowed = {mode.value for mode in InteractionMode}
        if value not in allowed:
            raise ValueError("mode must be a supported InteractionMode value")
        return value

    @field_validator("reason_codes", "required_capabilities", "missing_blockers", "risk_flags")
    @classmethod
    def validate_unique_items(cls, values: tuple[object, ...]) -> tuple[object, ...]:
        """拒绝重复的路由原因、能力、阻断项或风险标记。"""
        if len(values) != len(set(values)):
            raise ValueError("route items must be unique")
        return values

    @field_validator("required_capabilities")
    @classmethod
    def validate_capabilities(cls, values: tuple[str, ...]) -> tuple[str, ...]:
        """拒绝空能力名，避免下游任务图收到不可执行的占位符。"""
        if any(not value.strip() for value in values):
            raise ValueError("required capabilities must not contain empty values")
        return values

    @field_validator("capability_reasons")
    @classmethod
    def validate_unique_capability_reasons(
        cls,
        values: tuple[CapabilityReason, ...],
    ) -> tuple[CapabilityReason, ...]:
        """拒绝同一能力重复出现多个理由。"""
        capabilities = tuple(item.capability for item in values)
        if len(capabilities) != len(set(capabilities)):
            raise ValueError("capability reasons must be unique")
        return values

    @model_validator(mode="after")
    def validate_current_plan_reference(self) -> RouteDecision:
        """要求局部修改和重规划必须携带当前计划引用。"""
        if self.mode in {"refine", "replan"} and self.current_plan_ref is None:
            raise ValueError("refine and replan routes require current_plan_ref")
        if self.business_scope is not None:
            if self.scope_version != self.business_scope.scope_version:
                raise ValueError("route scope_version must match business_scope")
            if self.capability_reasons != self.business_scope.capability_reasons:
                raise ValueError("route capability_reasons must match business_scope")
        return self
