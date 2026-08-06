"""M4 step six: shared Research Agent context and output contracts."""

from __future__ import annotations

import re
from collections.abc import Mapping
from datetime import datetime
from decimal import Decimal
from typing import Literal, Self, TypeAlias

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from src.application.task_graph import TaskSpec
from src.domain.models.candidates import CandidateProvenance
from src.domain.models.constraint import ConstraintSnapshot
from src.domain.models.enums import ErrorCategory
from src.domain.models.evidence import EvidenceRegistration
from src.domain.models.trip_request import TripRequest
from src.domain.models.value_objects import CandidateId, GeoPoint, Money, StableId, TraceId


class AgentBudget(BaseModel):
    """Explicit per-agent budget."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    max_tool_calls: int = Field(default=1, ge=0)
    max_model_calls: int = Field(default=0, ge=0)
    timeout_seconds: Decimal = Field(default=Decimal("15"), gt=Decimal("0"))
    max_results: int = Field(default=20, ge=1, le=100)

    @field_validator("timeout_seconds", mode="before")
    @classmethod
    def reject_float_timeout(cls, value: object) -> object:
        """Reject binary floating point timeout values."""
        if isinstance(value, float):
            raise ValueError("timeout_seconds must be Decimal, int, or decimal string")
        return value


class AgentContext(BaseModel):
    """Read-only, version-bound context for one Research Agent."""

    model_config = ConfigDict(extra="forbid", frozen=True, str_strip_whitespace=True)

    trace_id: TraceId
    task_spec: TaskSpec
    constraint_snapshot_ref: StableId
    request: TripRequest
    constraint_snapshot: ConstraintSnapshot
    allowed_tools: tuple[str, ...] = ()
    prior_evidence_refs: tuple[StableId, ...] = ()
    prior_candidate_refs: tuple[StableId, ...] = ()
    budget: AgentBudget
    locale: str = Field(min_length=2, max_length=16)
    timezone: str = Field(min_length=1, max_length=64)
    context_types: tuple[str, ...] = ()
    place_category: str | None = Field(default=None, min_length=1, max_length=64)
    stay_area: str | None = Field(default=None, min_length=1, max_length=256)

    @field_validator("allowed_tools", "prior_evidence_refs", "prior_candidate_refs")
    @classmethod
    def validate_unique_refs(cls, values: tuple[str, ...]) -> tuple[str, ...]:
        """Keep context references unique and deterministic."""
        if len(values) != len(set(values)):
            raise ValueError("context references must be unique")
        return values

    @field_validator("context_types")
    @classmethod
    def validate_context_types(cls, values: tuple[str, ...]) -> tuple[str, ...]:
        """Reject empty and duplicate context fact types."""
        if any(not value for value in values):
            raise ValueError("context_types must not contain empty values")
        if len(values) != len(set(values)):
            raise ValueError("context_types must be unique")
        return values

    @field_validator("timezone")
    @classmethod
    def validate_timezone(cls, value: str) -> str:
        """Accept only an IANA timezone name."""
        if value == "UTC":
            return value
        if re.fullmatch(r"[A-Za-z][A-Za-z0-9._+-]*(?:/[A-Za-z0-9._+-]+)+", value) is None:
            raise ValueError("timezone must be an IANA timezone name")
        return value

    @model_validator(mode="after")
    def validate_snapshot_binding(self) -> Self:
        """Bind the agent to one request and constraint snapshot version."""
        if self.constraint_snapshot.request_id != self.request.request_id:
            raise ValueError("constraint snapshot must belong to request")
        expected_ref = f"snapshot-{self.request.request_id}-{self.constraint_snapshot.version}"
        if self.constraint_snapshot_ref != expected_ref:
            raise ValueError("constraint_snapshot_ref does not match snapshot")
        if self.locale != self.request.locale:
            raise ValueError("agent locale must match request locale")
        if self.timezone != self.request.timezone:
            raise ValueError("agent timezone must match request timezone")
        return self


class AgentSummary(BaseModel):
    """Structured execution counts without free-text decisions."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    agent_type: str = Field(min_length=1, max_length=64)
    provider: str = Field(min_length=1, max_length=64)
    query_id: StableId
    evidence_draft_count: int = Field(ge=0)
    candidate_draft_count: int = Field(ge=0)


class AgentError(BaseModel):
    """Safe error summary that an Orchestrator may record."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    category: ErrorCategory
    code: str = Field(min_length=1, max_length=64)
    safe_message: str = Field(min_length=1, max_length=512)
    upstream_refs: tuple[StableId, ...] = ()
    retryable: bool = False


class EvidenceDraft(BaseModel):
    """EvidenceRegistration before the Orchestrator writes it to the registry."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    draft_id: StableId
    registration: EvidenceRegistration


class CandidateDraft(BaseModel):
    """Candidate draft whose evidence refs point to local EvidenceDraft IDs."""

    model_config = ConfigDict(extra="forbid", frozen=True, str_strip_whitespace=True)

    candidate_id: CandidateId
    kind: Literal["transport", "stay", "place"]
    entity_id: StableId
    name: str = Field(min_length=1, max_length=256)
    evidence_draft_refs: tuple[StableId, ...] = Field(min_length=1)
    price_evidence_draft_ref: StableId | None = None
    provenance: tuple[CandidateProvenance, ...] = Field(min_length=1)
    timezone: str = Field(min_length=1, max_length=64)
    tags: tuple[str, ...] = ()
    location: GeoPoint | None = None
    price: Money | None = None
    external_text_trust: Literal["untrusted"] = "untrusted"
    mode: str | None = Field(default=None, min_length=1, max_length=64)
    origin: str | None = Field(default=None, min_length=1, max_length=256)
    destination: str | None = Field(default=None, min_length=1, max_length=256)
    departure_at: datetime | None = None
    arrival_at: datetime | None = None
    area: str | None = Field(default=None, min_length=1, max_length=256)
    check_in: datetime | None = None
    check_out: datetime | None = None
    category: str | None = Field(default=None, min_length=1, max_length=64)
    address: str | None = Field(default=None, max_length=512)

    @field_validator("evidence_draft_refs", "tags")
    @classmethod
    def validate_unique_values(cls, values: tuple[str, ...]) -> tuple[str, ...]:
        """Reject duplicate draft references and tags."""
        if len(values) != len(set(values)):
            raise ValueError("candidate draft references must be unique")
        return values

    @field_validator("timezone")
    @classmethod
    def validate_candidate_timezone(cls, value: str) -> str:
        """Require an IANA timezone on every candidate draft."""
        if value == "UTC":
            return value
        if re.fullmatch(r"[A-Za-z][A-Za-z0-9._+-]*(?:/[A-Za-z0-9._+-]+)+", value) is None:
            raise ValueError("candidate timezone must be an IANA timezone name")
        return value

    @model_validator(mode="after")
    def validate_kind_fields(self) -> Self:
        """Validate the minimum shape without assigning a final schedule."""
        if self.price_evidence_draft_ref is not None:
            if self.price is None:
                raise ValueError("price evidence reference requires price")
            if self.price_evidence_draft_ref not in self.evidence_draft_refs:
                raise ValueError("price evidence reference must belong to candidate")
        if self.kind == "transport":
            if any(value is None for value in (self.mode, self.origin, self.destination)):
                raise ValueError("transport candidate draft requires route fields")
            _validate_ordered_times(self.departure_at, self.arrival_at, "transport")
        elif self.kind == "stay":
            if self.area is None:
                raise ValueError("stay candidate draft requires area")
            _validate_ordered_times(self.check_in, self.check_out, "stay", strict=True)
        elif self.category is None:
            raise ValueError("place candidate draft requires category")
        return self


def _validate_ordered_times(
    start: datetime | None,
    end: datetime | None,
    name: str,
    *,
    strict: bool = False,
) -> None:
    """Validate timezone presence and ordering of candidate times."""
    for value in (start, end):
        if value is not None and value.tzinfo is None:
            raise ValueError(f"{name} candidate draft times must be timezone-aware")
    if start is not None and end is not None:
        invalid = end <= start if strict else end < start
        if invalid:
            raise ValueError(f"{name} candidate draft time window is invalid")


class AgentResult(BaseModel):
    """Structured Research Agent result; persistence remains Orchestrator-owned."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    task_id: StableId
    agent_type: str = Field(min_length=1, max_length=64)
    summary: AgentSummary
    evidence_drafts: tuple[EvidenceDraft, ...] = ()
    candidate_drafts: tuple[CandidateDraft, ...] = ()
    draft_ids: tuple[StableId, ...] = ()
    metrics: Mapping[str, float] = Field(default_factory=dict)
    error: AgentError | None = None

    @field_validator("draft_ids")
    @classmethod
    def validate_unique_draft_ids(cls, values: tuple[StableId, ...]) -> tuple[StableId, ...]:
        """Keep every local draft ID unique."""
        if len(values) != len(set(values)):
            raise ValueError("draft_ids must be unique")
        return values

    @field_validator("metrics")
    @classmethod
    def validate_metrics(cls, values: Mapping[str, float]) -> Mapping[str, float]:
        """Allow only numeric metric values at the agent boundary."""
        if any(not key.strip() for key in values):
            raise ValueError("metric names must not be empty")
        if any(not isinstance(value, int | float) for value in values.values()):
            raise ValueError("metric values must be numeric")
        return values

    @model_validator(mode="after")
    def validate_result_partition(self) -> Self:
        """Reject empty success and any partial failed result."""
        evidence_count = len(self.evidence_drafts)
        candidate_count = len(self.candidate_drafts)
        if self.error is None and evidence_count + candidate_count == 0:
            raise ValueError("successful AgentResult must contain evidence or candidates")
        if self.summary.evidence_draft_count != evidence_count:
            raise ValueError("summary evidence count does not match result")
        if self.summary.candidate_draft_count != candidate_count:
            raise ValueError("summary candidate count does not match result")
        evidence_ids = {draft.draft_id for draft in self.evidence_drafts}
        candidate_refs = {
            ref for candidate in self.candidate_drafts for ref in candidate.evidence_draft_refs
        }
        if len(evidence_ids) != evidence_count:
            raise ValueError("evidence draft IDs must be unique")
        if not candidate_refs.issubset(evidence_ids):
            raise ValueError("candidate draft references an unknown evidence draft")
        if self.error is None and len(self.draft_ids) != evidence_count + candidate_count:
            raise ValueError("draft_ids must cover every draft")
        expected_ids = evidence_ids | {
            candidate.candidate_id for candidate in self.candidate_drafts
        }
        if set(self.draft_ids) != expected_ids:
            raise ValueError("draft_ids must match evidence and candidate drafts")
        if self.error is not None and evidence_count + candidate_count != 0:
            raise ValueError("failed AgentResult must not contain partial drafts")
        return self


AgentOutput: TypeAlias = AgentResult


__all__ = [
    "AgentBudget",
    "AgentContext",
    "AgentError",
    "AgentOutput",
    "AgentResult",
    "AgentSummary",
    "CandidateDraft",
    "EvidenceDraft",
]
