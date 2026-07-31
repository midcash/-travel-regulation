"""参与规划的标准化候选契约。"""

from __future__ import annotations

import re
from datetime import datetime
from decimal import Decimal
from typing import Annotated, Literal, Self, TypeAlias

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from src.domain.models.enums import CandidateRejectCode
from src.domain.models.value_objects import (
    CandidateId,
    ConstraintId,
    EvidenceId,
    GeoPoint,
    Money,
    StableId,
)


class CandidateProvenance(BaseModel):
    """候选的单一供应商来源，用于去重后的合并追溯。"""

    model_config = ConfigDict(extra="forbid", frozen=True, str_strip_whitespace=True)

    provider: str = Field(min_length=1, max_length=64)
    entity_id: StableId
    source_ref: str = Field(min_length=1, max_length=2048)


class CandidatePrice(BaseModel):
    """候选的统一总价、包含项和价格证据。"""

    model_config = ConfigDict(extra="forbid", frozen=True, str_strip_whitespace=True)

    total: Money
    inclusions: tuple[str, ...] = ()
    evidence_refs: tuple[EvidenceId, ...] = Field(min_length=1)

    @field_validator("inclusions", "evidence_refs")
    @classmethod
    def validate_unique_values(cls, values: tuple[str, ...]) -> tuple[str, ...]:
        """拒绝重复的价格包含项和证据引用。"""
        if len(values) != len(set(values)):
            raise ValueError("candidate price values must be unique")
        return values


class CandidateRating(BaseModel):
    """保留来源与量纲的候选评分，禁止跨来源直接比较。"""

    model_config = ConfigDict(extra="forbid", frozen=True, str_strip_whitespace=True)

    value: Decimal = Field(ge=Decimal("0"))
    scale: Decimal = Field(gt=Decimal("0"))
    source: str = Field(min_length=1, max_length=64)
    evidence_refs: tuple[EvidenceId, ...] = Field(min_length=1)

    @field_validator("value", "scale", mode="before")
    @classmethod
    def reject_float_values(cls, value: object) -> object:
        """拒绝 float，避免评分在领域层产生二进制精度漂移。"""
        if isinstance(value, float):
            raise ValueError("candidate rating values must not be float")
        return value

    @field_validator("evidence_refs")
    @classmethod
    def validate_unique_evidence_refs(
        cls, values: tuple[EvidenceId, ...]
    ) -> tuple[EvidenceId, ...]:
        """拒绝同一评分中重复的证据引用。"""
        if len(values) != len(set(values)):
            raise ValueError("candidate rating evidence_refs must be unique")
        return values

    @model_validator(mode="after")
    def validate_scale(self) -> Self:
        """确保评分值不会超过声明的评分量纲。"""
        if self.value > self.scale:
            raise ValueError("candidate rating value must not exceed scale")
        return self


class CandidateBase(BaseModel):
    """所有候选共享的可引用、可追溯字段。"""

    model_config = ConfigDict(extra="forbid", frozen=True, str_strip_whitespace=True)

    candidate_id: CandidateId
    name: str = Field(min_length=1, max_length=256)
    evidence_refs: tuple[EvidenceId, ...] = Field(min_length=1)
    provenance: tuple[CandidateProvenance, ...] = Field(min_length=1)
    timezone: str = Field(min_length=1, max_length=64)
    tags: tuple[str, ...] = ()
    location: GeoPoint | None = None
    price: CandidatePrice | None = None
    rating: CandidateRating | None = None

    @field_validator("timezone")
    @classmethod
    def validate_timezone(cls, value: str) -> str:
        """只接受 IANA 时区名称格式，不依赖运行环境是否安装时区数据库。"""
        if value != "UTC" and re.fullmatch(
            r"[A-Za-z][A-Za-z0-9._+-]*(?:/[A-Za-z0-9._+-]+)+", value
        ) is None:
            raise ValueError("candidate timezone must be an IANA timezone name")
        return value

    @field_validator("evidence_refs", "tags")
    @classmethod
    def validate_unique_values(cls, values: tuple[str, ...]) -> tuple[str, ...]:
        """拒绝重复的候选证据引用和标签。"""
        if len(values) != len(set(values)):
            raise ValueError("candidate values must be unique")
        return values

    @field_validator("provenance")
    @classmethod
    def validate_unique_provenance(
        cls, values: tuple[CandidateProvenance, ...]
    ) -> tuple[CandidateProvenance, ...]:
        """确保每个候选来源只保留一次。"""
        keys = tuple((value.provider, value.entity_id, value.source_ref) for value in values)
        if len(keys) != len(set(keys)):
            raise ValueError("candidate provenance must be unique")
        return values

    @model_validator(mode="after")
    def validate_nested_evidence_refs(self) -> Self:
        """要求价格和评分的证据均属于候选整体证据集合。"""
        candidate_refs = set(self.evidence_refs)
        nested_refs: set[EvidenceId] = set()
        if self.price is not None:
            nested_refs.update(self.price.evidence_refs)
        if self.rating is not None:
            nested_refs.update(self.rating.evidence_refs)
        if not nested_refs.issubset(candidate_refs):
            raise ValueError("price and rating evidence_refs must belong to candidate")
        return self


class TransportCandidate(CandidateBase):
    """交通候选。"""

    kind: Literal["transport"] = "transport"
    mode: str = Field(min_length=1, max_length=64)
    origin: str = Field(min_length=1, max_length=256)
    destination: str = Field(min_length=1, max_length=256)
    departure_at: datetime | None = None
    arrival_at: datetime | None = None

    @model_validator(mode="after")
    def validate_schedule(self) -> Self:
        """确保交通时间均带时区且到达时间不早于出发时间。"""
        for value in (self.departure_at, self.arrival_at):
            if value is not None and value.tzinfo is None:
                raise ValueError("transport candidate times must be timezone-aware")
        if (
            self.departure_at is not None
            and self.arrival_at is not None
            and self.arrival_at < self.departure_at
        ):
            raise ValueError("transport arrival_at must not be earlier than departure_at")
        return self


class StayCandidate(CandidateBase):
    """住宿候选。"""

    kind: Literal["stay"] = "stay"
    area: str = Field(min_length=1, max_length=256)
    check_in: datetime | None = None
    check_out: datetime | None = None

    @model_validator(mode="after")
    def validate_stay_window(self) -> Self:
        """确保住宿时间均带时区且退房时间晚于入住时间。"""
        for value in (self.check_in, self.check_out):
            if value is not None and value.tzinfo is None:
                raise ValueError("stay candidate times must be timezone-aware")
        if (
            self.check_in is not None
            and self.check_out is not None
            and self.check_out <= self.check_in
        ):
            raise ValueError("stay check_out must be later than check_in")
        return self


class PlaceCandidate(CandidateBase):
    """景点、餐饮或活动候选。"""

    kind: Literal["place"] = "place"
    category: str = Field(min_length=1, max_length=64)
    address: str | None = Field(default=None, max_length=512)


class ContextCandidate(CandidateBase):
    """只在适合进入规划时使用的环境上下文候选。"""

    kind: Literal["context"] = "context"
    context_type: str = Field(min_length=1, max_length=64)
    scope: StableId


Candidate: TypeAlias = Annotated[
    TransportCandidate | StayCandidate | PlaceCandidate | ContextCandidate,
    Field(discriminator="kind"),
]


class CandidateRejectReason(BaseModel):
    """记录候选被剪枝的确定性原因。"""

    model_config = ConfigDict(extra="forbid", frozen=True, str_strip_whitespace=True)

    code: CandidateRejectCode
    message: str = Field(min_length=1, max_length=256)
    constraint_ref: ConstraintId | None = None
    evidence_ref: EvidenceId | None = None


class CandidateRejection(BaseModel):
    """候选与其全部拒绝原因的不可变组合。"""

    model_config = ConfigDict(extra="forbid", frozen=True)

    candidate: Candidate
    reasons: tuple[CandidateRejectReason, ...] = Field(min_length=1)

    @field_validator("reasons")
    @classmethod
    def validate_unique_reasons(
        cls, values: tuple[CandidateRejectReason, ...]
    ) -> tuple[CandidateRejectReason, ...]:
        """拒绝重复输出同一个证据或约束导致的原因。"""
        keys = tuple((value.code, value.constraint_ref, value.evidence_ref) for value in values)
        if len(keys) != len(set(keys)):
            raise ValueError("candidate rejection reasons must be unique")
        return values


class CandidatePoolResult(BaseModel):
    """Candidate Pool 的入选、淘汰和待后续阶段处理结果。"""

    model_config = ConfigDict(extra="forbid", frozen=True)

    evidence_snapshot_id: StableId
    constraint_snapshot_version: int = Field(ge=1)
    candidates: tuple[Candidate, ...] = ()
    rejected: tuple[CandidateRejection, ...] = ()
    deferred_hard_constraint_refs: tuple[ConstraintId, ...] = ()

    @model_validator(mode="after")
    def validate_candidate_partition(self) -> Self:
        """确保每个标准化候选只会入选或以一个聚合拒绝项出现。"""
        candidate_ids = tuple(candidate.candidate_id for candidate in self.candidates)
        rejected_ids = tuple(item.candidate.candidate_id for item in self.rejected)
        if len(candidate_ids) != len(set(candidate_ids)):
            raise ValueError("candidate pool candidates must be unique")
        if len(rejected_ids) != len(set(rejected_ids)):
            raise ValueError("candidate pool rejected candidates must be unique")
        if set(candidate_ids).intersection(rejected_ids):
            raise ValueError("candidate pool candidates and rejected candidates must not overlap")
        if len(self.deferred_hard_constraint_refs) != len(
            set(self.deferred_hard_constraint_refs)
        ):
            raise ValueError("deferred_hard_constraint_refs must be unique")
        return self
