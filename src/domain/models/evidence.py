"""证据契约。"""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from typing import Annotated, Self, TypeAlias

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    StrictBool,
    StrictInt,
    StrictStr,
    field_validator,
    model_validator,
)

from src.domain.models.enums import EvidenceStatus
from src.domain.models.value_objects import (
    ConstraintId,
    DateRange,
    EvidenceId,
    GeoPoint,
    Money,
    StableId,
)

EvidenceValue: TypeAlias = (
    StrictStr
    | StrictBool
    | StrictInt
    | Decimal
    | date
    | datetime
    | tuple[StrictStr, ...]
    | Money
    | DateRange
    | GeoPoint
)


class EvidenceItem(BaseModel):
    """可被候选和方案引用的单条事实。"""

    model_config = ConfigDict(extra="forbid", frozen=True, str_strip_whitespace=True)

    evidence_id: EvidenceId
    entity_id: StableId
    fact_type: str = Field(min_length=1, max_length=128)
    value: Annotated[EvidenceValue, Field(description="已标准化的事实值")]
    source: str = Field(min_length=1, max_length=128)
    source_ref: str = Field(min_length=1, max_length=2048)
    observed_at: datetime
    valid_until: datetime | None = None
    status: EvidenceStatus
    confidence: Decimal = Field(ge=Decimal("0"), le=Decimal("1"))
    constraint_refs: tuple[ConstraintId, ...] = ()

    @field_validator("constraint_refs")
    @classmethod
    def validate_constraint_refs(cls, values: tuple[ConstraintId, ...]) -> tuple[ConstraintId, ...]:
        """拒绝同一证据中的重复约束引用。"""
        if len(values) != len(set(values)):
            raise ValueError("constraint_refs must be unique")
        return values

    @model_validator(mode="after")
    def validate_validity_window(self) -> Self:
        """确保有效期不会早于事实观测时间。"""
        if self.valid_until is not None and self.valid_until < self.observed_at:
            raise ValueError("valid_until must not be earlier than observed_at")
        return self


class EvidenceSnapshot(BaseModel):
    """某一时点可供规划使用的证据快照。"""

    model_config = ConfigDict(extra="forbid", frozen=True)

    snapshot_id: StableId
    created_at: datetime
    evidence_items: tuple[EvidenceItem, ...] = ()
    coverage: Decimal = Field(default=Decimal("0"), ge=Decimal("0"), le=Decimal("1"))
    freshness: Decimal = Field(default=Decimal("0"), ge=Decimal("0"), le=Decimal("1"))
    conflict_refs: tuple[EvidenceId, ...] = ()
    unavailable_capabilities: tuple[str, ...] = ()

    @model_validator(mode="after")
    def validate_references(self) -> Self:
        """确保快照内证据 ID 唯一且冲突引用确实存在。"""
        evidence_ids = tuple(item.evidence_id for item in self.evidence_items)
        if len(evidence_ids) != len(set(evidence_ids)):
            raise ValueError("evidence IDs must be unique")
        if len(self.conflict_refs) != len(set(self.conflict_refs)):
            raise ValueError("conflict_refs must be unique")
        if not set(self.conflict_refs).issubset(evidence_ids):
            raise ValueError("conflict_refs must reference snapshot evidence")
        if any(not capability for capability in self.unavailable_capabilities):
            raise ValueError("unavailable_capabilities must not contain empty values")
        return self
