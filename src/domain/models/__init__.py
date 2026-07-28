"""领域模型包。"""

from __future__ import annotations

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
    InteractionMode,
    IssueSeverity,
    WorkflowStatus,
)
from src.domain.models.trip_request import (
    BudgetSemantics,
    BudgetSpec,
    TravelerProfile,
    TripRequest,
)
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
    "BudgetSemantics",
    "BudgetSpec",
    "CandidateId",
    "CheckpointId",
    "Constraint",
    "ConstraintHardness",
    "ConstraintId",
    "ConstraintSnapshot",
    "ConstraintSource",
    "ConstraintValue",
    "DateRange",
    "ErrorCategory",
    "EvidenceId",
    "EvidenceStatus",
    "GeoPoint",
    "InteractionMode",
    "IssueId",
    "IssueSeverity",
    "Money",
    "PlanId",
    "PlanItemId",
    "RequestId",
    "SessionId",
    "StableId",
    "TraceId",
    "TravelerProfile",
    "TripId",
    "TripRequest",
    "WorkflowStatus",
]
