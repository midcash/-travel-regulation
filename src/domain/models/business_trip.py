"""M4.2-S1 商务差旅会议与范围契约。"""

from __future__ import annotations

from datetime import datetime
from enum import Enum

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class ScopeRequirementState(str, Enum):
    """能力在当前范围中的确定性状态。"""

    REQUIRED = "required"
    CONDITIONAL = "conditional"
    EXCLUDED = "excluded"


class BusinessTripBoundaryCode(str, Enum):
    """当前商务差旅产品边界的拒答原因。"""

    MULTI_TRAVELER_UNSUPPORTED = "MULTI_TRAVELER_UNSUPPORTED"
    TOURISM_UNSUPPORTED = "TOURISM_UNSUPPORTED"


class MeetingRequirement(BaseModel):
    """首场会议的到达目标。"""

    model_config = ConfigDict(extra="forbid", frozen=True, str_strip_whitespace=True)

    meeting_id: str = Field(min_length=1, max_length=128)
    city: str = Field(min_length=1, max_length=128)
    location: str = Field(min_length=1, max_length=512)
    timezone: str = Field(min_length=1, max_length=64)
    starts_at: datetime
    traveler_count: int = Field(ge=1)

    @field_validator("starts_at")
    @classmethod
    def validate_starts_at_timezone(cls, value: datetime) -> datetime:
        """会议开始时间必须已经绑定显式会议时区。"""
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("meeting starts_at must be timezone-aware")
        return value


class CapabilityReason(BaseModel):
    """解释某项能力为什么被纳入或延后。"""

    model_config = ConfigDict(extra="forbid", frozen=True, str_strip_whitespace=True)

    capability: str = Field(min_length=1, max_length=64)
    state: ScopeRequirementState
    reason: str = Field(min_length=1, max_length=512)


class BusinessTripScope(BaseModel):
    """M4.2-S1 冻结的商务差旅范围。"""

    model_config = ConfigDict(extra="forbid", frozen=True, str_strip_whitespace=True)

    scope_version: str = Field(min_length=1, max_length=32)
    planning_horizon: str = Field(min_length=1, max_length=64)
    meeting: MeetingRequirement
    initial_required_capabilities: tuple[str, ...] = Field(min_length=1)
    required_capabilities: tuple[str, ...] = Field(min_length=1)
    conditional_capabilities: tuple[str, ...] = ()
    excluded_capabilities: tuple[str, ...] = ()
    capability_reasons: tuple[CapabilityReason, ...] = Field(min_length=1)
    return_scope: str = Field(min_length=1, max_length=64)
    unresolved_blockers: tuple[str, ...] = ()

    @field_validator(
        "initial_required_capabilities",
        "required_capabilities",
        "conditional_capabilities",
        "excluded_capabilities",
        "unresolved_blockers",
    )
    @classmethod
    def validate_unique_text_items(cls, values: tuple[str, ...]) -> tuple[str, ...]:
        """拒绝空名称和重复范围项。"""
        if any(not value.strip() for value in values):
            raise ValueError("scope items must not be empty")
        if len(values) != len(set(values)):
            raise ValueError("scope items must be unique")
        return values

    @field_validator("capability_reasons")
    @classmethod
    def validate_unique_capability_reasons(
        cls,
        values: tuple[CapabilityReason, ...],
    ) -> tuple[CapabilityReason, ...]:
        """确保每项能力只有一个解释。"""
        capabilities = tuple(item.capability for item in values)
        if len(capabilities) != len(set(capabilities)):
            raise ValueError("capability reasons must be unique")
        return values

    @model_validator(mode="after")
    def validate_scope_relationships(self) -> BusinessTripScope:
        """确保 required、conditional 和 excluded 不相互重叠。"""
        required = set(self.required_capabilities)
        conditional = set(self.conditional_capabilities)
        excluded = set(self.excluded_capabilities)
        if not set(self.initial_required_capabilities).issubset(required):
            raise ValueError("initial capabilities must be required capabilities")
        if required.intersection(conditional | excluded):
            raise ValueError("scope capability states must not overlap")
        if conditional.intersection(excluded):
            raise ValueError("conditional and excluded capabilities must not overlap")
        reason_capabilities = {item.capability for item in self.capability_reasons}
        if reason_capabilities != required | conditional | excluded:
            raise ValueError("every scoped capability must have one reason")
        return self
