"""领域模型包。"""

from __future__ import annotations

from src.domain.models.candidates import (
    Candidate,
    CandidateBase,
    ContextCandidate,
    PlaceCandidate,
    StayCandidate,
    TransportCandidate,
)
from src.domain.models.constraint import (
    Constraint,
    ConstraintSnapshot,
    ConstraintSource,
    ConstraintValue,
)
from src.domain.models.enums import (
    ConstraintHardness,
    ErrorCategory,
    EvidenceStatus,
    EvidenceTtlCategory,
    InteractionMode,
    IssueSeverity,
    WorkflowStatus,
)
from src.domain.models.evidence import (
    EvidenceItem,
    EvidenceRegistration,
    EvidenceSnapshot,
    EvidenceSnapshotQuery,
    EvidenceTtlPolicy,
    EvidenceValue,
)
from src.domain.models.itinerary import (
    BudgetBreakdown,
    BudgetLine,
    ItineraryDay,
    ItineraryPlan,
    PlanAlternative,
    PlanBuffer,
    PlanItem,
)
from src.domain.models.trip_request import (
    BudgetSemantics,
    BudgetSpec,
    TravelerProfile,
    TripRequest,
)
from src.domain.models.validation import ValidationGate, ValidationIssue
from src.domain.models.value_objects import (
    CandidateId,
    CheckpointId,
    ConstraintId,
    DateRange,
    EvidenceId,
    GeoPoint,
    IssueId,
    Money,
    PlanId,
    PlanItemId,
    RequestId,
    SessionId,
    StableId,
    TraceId,
    TripId,
)

__all__ = [
    "ALLOWED_WORKFLOW_TRANSITIONS",
    "BudgetBreakdown",
    "BudgetLine",
    "BudgetSemantics",
    "BudgetSpec",
    "Candidate",
    "CandidateBase",
    "CandidateId",
    "CheckpointId",
    "Constraint",
    "ConstraintHardness",
    "ConstraintId",
    "ConstraintSnapshot",
    "ConstraintSource",
    "ConstraintValue",
    "ContextCandidate",
    "DateRange",
    "ErrorCategory",
    "EvidenceId",
    "EvidenceItem",
    "EvidenceRegistration",
    "EvidenceSnapshot",
    "EvidenceSnapshotQuery",
    "EvidenceStatus",
    "EvidenceTtlCategory",
    "EvidenceTtlPolicy",
    "EvidenceValue",
    "GeoPoint",
    "InteractionMode",
    "IssueId",
    "IssueSeverity",
    "ItineraryDay",
    "ItineraryPlan",
    "Money",
    "PlaceCandidate",
    "PlanAlternative",
    "PlanBuffer",
    "PlanId",
    "PlanItem",
    "PlanItemId",
    "RequestId",
    "SessionId",
    "StableId",
    "StayCandidate",
    "TraceId",
    "TransportCandidate",
    "TravelerProfile",
    "TripId",
    "TripRequest",
    "TripState",
    "ValidationGate",
    "ValidationIssue",
    "WorkflowStatus",
]


def __getattr__(name: str) -> object:
    """按需加载状态模型，避免领域错误与模型包互相初始化。"""
    if name in {"ALLOWED_WORKFLOW_TRANSITIONS", "TripState"}:
        from src.domain.models.state import ALLOWED_WORKFLOW_TRANSITIONS, TripState

        return {
            "ALLOWED_WORKFLOW_TRANSITIONS": ALLOWED_WORKFLOW_TRANSITIONS,
            "TripState": TripState,
        }[name]
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
