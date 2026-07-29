"""参与规划的标准化候选契约。"""

from __future__ import annotations

from datetime import datetime
from typing import Annotated, Literal, TypeAlias

from pydantic import BaseModel, ConfigDict, Field

from src.domain.models.value_objects import CandidateId, EvidenceId, GeoPoint, Money, StableId


class CandidateBase(BaseModel):
    """所有候选共享的可引用字段。"""

    model_config = ConfigDict(extra="forbid", frozen=True, str_strip_whitespace=True)

    candidate_id: CandidateId
    name: str = Field(min_length=1, max_length=256)
    evidence_refs: tuple[EvidenceId, ...] = ()
    tags: tuple[str, ...] = ()
    location: GeoPoint | None = None


class TransportCandidate(CandidateBase):
    """交通候选。"""

    kind: Literal["transport"] = "transport"
    mode: str = Field(min_length=1, max_length=64)
    origin: str = Field(min_length=1, max_length=256)
    destination: str = Field(min_length=1, max_length=256)
    departure_at: datetime | None = None
    arrival_at: datetime | None = None


class StayCandidate(CandidateBase):
    """住宿候选。"""

    kind: Literal["stay"] = "stay"
    area: str = Field(min_length=1, max_length=256)
    check_in: datetime | None = None
    check_out: datetime | None = None
    total_price: Money | None = None


class PlaceCandidate(CandidateBase):
    """景点、餐饮或活动候选。"""

    kind: Literal["place"] = "place"
    category: str = Field(min_length=1, max_length=64)
    address: str | None = Field(default=None, max_length=512)


class ContextCandidate(CandidateBase):
    """不直接作为行程项目的环境上下文候选。"""

    kind: Literal["context"] = "context"
    context_type: str = Field(min_length=1, max_length=64)
    scope: StableId


Candidate: TypeAlias = Annotated[
    TransportCandidate | StayCandidate | PlaceCandidate | ContextCandidate,
    Field(discriminator="kind"),
]
