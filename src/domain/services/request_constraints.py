"""Deterministic validation for hard constraints owned by TripRequest."""

from __future__ import annotations

from src.domain.errors import WorkflowError
from src.domain.models.constraint import ConstraintSnapshot
from src.domain.models.enums import ErrorCategory
from src.domain.models.trip_request import TripRequest
from src.domain.models.value_objects import TraceId

REQUEST_LEVEL_CONSTRAINT_CATEGORIES = frozenset(
    {"traveler", "travelers", "people", "person_count", "traveler_count"}
)


def is_request_level_constraint_category(category: str) -> bool:
    """Return whether a constraint is owned by the structured TripRequest."""
    return category.casefold() in REQUEST_LEVEL_CONSTRAINT_CATEGORIES


class RequestConstraintService:
    """Validate hard constraints that are not candidate-level properties."""

    def validate(
        self,
        request: TripRequest,
        snapshot: ConstraintSnapshot,
        *,
        trace_id: TraceId,
    ) -> None:
        """Ensure request-owned hard constraints match the frozen snapshot."""
        if not isinstance(request, TripRequest):
            raise TypeError("request must be a TripRequest")
        if not isinstance(snapshot, ConstraintSnapshot):
            raise TypeError("snapshot must be a ConstraintSnapshot")
        if request.request_id != snapshot.request_id:
            raise WorkflowError(
                trace_id=trace_id,
                stage="request_constraint_service",
                category=ErrorCategory.STATE_CONFLICT,
                code="REQUEST_LEVEL_SNAPSHOT_REQUEST_MISMATCH",
                safe_message="request and constraint snapshot do not belong together",
                upstream_refs=(request.request_id, snapshot.request_id),
            )

        for constraint in snapshot.hard_constraints:
            if not is_request_level_constraint_category(constraint.category):
                continue
            if type(constraint.normalized_value) is not int:
                raise WorkflowError(
                    trace_id=trace_id,
                    stage="request_constraint_service",
                    category=ErrorCategory.VALIDATION,
                    code="REQUEST_LEVEL_TRAVELERS_INVALID",
                    safe_message="request-level traveler constraint is invalid",
                    upstream_refs=(constraint.id,),
                )
            if constraint.normalized_value != request.travelers.total_count:
                raise WorkflowError(
                    trace_id=trace_id,
                    stage="request_constraint_service",
                    category=ErrorCategory.VALIDATION,
                    code="REQUEST_LEVEL_TRAVELERS_MISMATCH",
                    safe_message="request-level traveler constraint does not match the request",
                    upstream_refs=(constraint.id,),
                )


__all__ = [
    "REQUEST_LEVEL_CONSTRAINT_CATEGORIES",
    "RequestConstraintService",
    "is_request_level_constraint_category",
]
