"""证据契约。"""

from __future__ import annotations

from datetime import date, datetime, timedelta
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

from src.domain.models.enums import EvidenceStatus, EvidenceTtlCategory
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


_EVIDENCE_SCHEMA_VERSION = "m3.evidence.v1"


class EvidenceTtlPolicy(BaseModel):
    """集中配置各类证据的最大有效期。"""

    model_config = ConfigDict(extra="forbid", frozen=True)

    static_geography: timedelta
    business_hours_policy: timedelta
    weather_forecast: timedelta
    transport_schedule: timedelta
    quote_inventory: timedelta
    exchange_rate: timedelta

    @field_validator(
        "static_geography",
        "business_hours_policy",
        "weather_forecast",
        "transport_schedule",
        "quote_inventory",
        "exchange_rate",
    )
    @classmethod
    def validate_positive_ttl(cls, value: timedelta) -> timedelta:
        """拒绝零或负 TTL，避免生成注册即过期的隐式策略。"""
        if value <= timedelta():
            raise ValueError("evidence TTL must be greater than zero")
        return value

    def valid_until_for(
        self,
        *,
        category: EvidenceTtlCategory,
        observed_at: datetime,
        provider_valid_until: datetime | None,
    ) -> datetime:
        """返回不超过供应商声明期限的策略有效期。"""
        policy_valid_until = observed_at + self._ttl_for(category)
        if provider_valid_until is None:
            return policy_valid_until
        return min(provider_valid_until, policy_valid_until)

    def _ttl_for(self, category: EvidenceTtlCategory) -> timedelta:
        """根据业务类别读取对应的集中 TTL 配置。"""
        return {
            EvidenceTtlCategory.STATIC_GEOGRAPHY: self.static_geography,
            EvidenceTtlCategory.BUSINESS_HOURS_POLICY: self.business_hours_policy,
            EvidenceTtlCategory.WEATHER_FORECAST: self.weather_forecast,
            EvidenceTtlCategory.TRANSPORT_SCHEDULE: self.transport_schedule,
            EvidenceTtlCategory.QUOTE_INVENTORY: self.quote_inventory,
            EvidenceTtlCategory.EXCHANGE_RATE: self.exchange_rate,
        }[category]


class _EvidenceRegistrationFields(BaseModel):
    """证据注册与已注册证据共享的不可变字段。"""

    model_config = ConfigDict(extra="forbid", frozen=True, str_strip_whitespace=True)

    entity_id: StableId
    fact_type: str = Field(min_length=1, max_length=128)
    value: Annotated[EvidenceValue, Field(description="已标准化的事实值")]
    provider: str = Field(min_length=1, max_length=64)
    source: str = Field(min_length=1, max_length=128)
    source_ref: str = Field(min_length=1, max_length=2048)
    observed_at: datetime
    valid_until: datetime | None = None
    ttl_category: EvidenceTtlCategory
    status: EvidenceStatus
    confidence: Decimal = Field(ge=Decimal("0"), le=Decimal("1"))
    raw_payload_ref: StableId | None = None
    query_fingerprint: StableId
    schema_version: str = Field(default=_EVIDENCE_SCHEMA_VERSION, min_length=1, max_length=64)
    constraint_refs: tuple[ConstraintId, ...] = ()

    @field_validator("observed_at", "valid_until")
    @classmethod
    def validate_timezone(cls, value: datetime | None) -> datetime | None:
        """要求动态证据时间携带时区。"""
        if value is not None and value.tzinfo is None:
            raise ValueError("evidence times must be timezone-aware")
        return value

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


class EvidenceRegistration(_EvidenceRegistrationFields):
    """交由 EvidenceRepository 注册的、尚未分配 ID 的事实。"""

    def to_item(self, evidence_id: EvidenceId) -> EvidenceItem:
        """根据仓储分配的稳定 ID 构造已注册证据。"""
        return EvidenceItem(evidence_id=evidence_id, **self.model_dump())


class EvidenceItem(_EvidenceRegistrationFields):
    """可被候选和方案引用的单条已注册事实。"""

    evidence_id: EvidenceId


class EvidenceSnapshotQuery(BaseModel):
    """描述当前证据快照的筛选范围与完整性要求。"""

    model_config = ConfigDict(extra="forbid", frozen=True, str_strip_whitespace=True)

    entity_id: StableId | None = None
    fact_type: str | None = Field(default=None, min_length=1, max_length=128)
    query_fingerprint: StableId | None = None
    required_fact_types: tuple[str, ...] = ()

    @field_validator("required_fact_types")
    @classmethod
    def validate_required_fact_types(cls, values: tuple[str, ...]) -> tuple[str, ...]:
        """要求完整性分母中的事实类型有效且不重复。"""
        if any(not value.strip() or len(value) > 128 for value in values):
            raise ValueError("required_fact_types must contain non-empty fact types")
        if len(values) != len(set(values)):
            raise ValueError("required_fact_types must be unique")
        return values


class EvidenceSnapshot(BaseModel):
    """某一时点可供规划使用的证据快照。"""

    model_config = ConfigDict(extra="forbid", frozen=True)

    snapshot_id: StableId
    created_at: datetime
    evidence_items: tuple[EvidenceItem, ...] = ()
    coverage: Decimal = Field(default=Decimal("0"), ge=Decimal("0"), le=Decimal("1"))
    freshness: Decimal = Field(default=Decimal("0"), ge=Decimal("0"), le=Decimal("1"))
    conflict_refs: tuple[EvidenceId, ...] = ()
    missing_fact_types: tuple[str, ...] = ()
    unavailable_capabilities: tuple[str, ...] = ()

    @field_validator("created_at")
    @classmethod
    def validate_created_at_timezone(cls, value: datetime) -> datetime:
        """确保快照创建时刻可与证据有效期确定性比较。"""
        if value.tzinfo is None:
            raise ValueError("snapshot created_at must be timezone-aware")
        return value

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
        if len(self.missing_fact_types) != len(set(self.missing_fact_types)):
            raise ValueError("missing_fact_types must be unique")
        if any(not fact_type for fact_type in self.missing_fact_types):
            raise ValueError("missing_fact_types must not contain empty values")
        if any(not capability for capability in self.unavailable_capabilities):
            raise ValueError("unavailable_capabilities must not contain empty values")
        if len(self.unavailable_capabilities) != len(set(self.unavailable_capabilities)):
            raise ValueError("unavailable_capabilities must be unique")
        return self
