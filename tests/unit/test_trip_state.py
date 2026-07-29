from __future__ import annotations

from datetime import date

import pytest
from pydantic import ValidationError

from src.domain.errors import InvalidStateTransitionError
from src.domain.models.constraint import ConstraintSnapshot
from src.domain.models.enums import WorkflowStatus
from src.domain.models.state import ALLOWED_WORKFLOW_TRANSITIONS, TripState
from src.domain.models.trip_request import TravelerProfile, TripRequest
from src.domain.models.value_objects import DateRange


def _request(**overrides: object) -> TripRequest:
    values: dict[str, object] = {
        "request_id": "request-1",
        "trip_id": "trip-1",
        "session_id": "session-1",
        "origin": "上海",
        "destinations": ("杭州",),
        "date_range": DateRange(start=date(2026, 8, 1), end=date(2026, 8, 3)),
        "travelers": TravelerProfile(adults=2),
    }
    values.update(overrides)
    return TripRequest(**values)


def test_trip_state_accepts_typed_snapshots_and_round_trips() -> None:
    request = _request()
    state = TripState(
        trip_id="trip-1",
        session_id="session-1",
        trip_request=request,
        constraint_snapshot=ConstraintSnapshot(
            version=1,
            created_at="2026-08-01T00:00:00Z",
            request_id="request-1",
        ),
        plan_version=1,
    )

    assert state.status is WorkflowStatus.COLLECTING
    assert state.model_validate_json(state.model_dump_json()) == state


def test_trip_state_rejects_mismatched_request_or_snapshot_identity() -> None:
    request = _request()
    with pytest.raises(ValidationError, match="trip_request.trip_id"):
        TripState(trip_id="other-trip", session_id="session-1", trip_request=request)
    with pytest.raises(ValidationError, match="constraint_snapshot.request_id"):
        TripState(
            trip_id="trip-1",
            session_id="session-1",
            trip_request=request,
            constraint_snapshot=ConstraintSnapshot(
                version=1,
                created_at="2026-08-01T00:00:00Z",
                request_id="other-request",
            ),
        )


def test_trip_state_transition_increments_version_without_mutating_snapshot() -> None:
    state = TripState(trip_id="trip-1", session_id="session-1")

    next_state = state.transition_to(WorkflowStatus.CLARIFYING)

    assert state.status is WorkflowStatus.COLLECTING
    assert state.version == 1
    assert next_state.status is WorkflowStatus.CLARIFYING
    assert next_state.version == 2
    with pytest.raises(ValidationError):
        state.status = WorkflowStatus.CLARIFYING


@pytest.mark.parametrize(
    ("source", "target"),
    [
        (source, target)
        for source, targets in ALLOWED_WORKFLOW_TRANSITIONS.items()
        for target in targets
    ],
)
def test_trip_state_allows_every_whitelisted_transition(
    source: WorkflowStatus, target: WorkflowStatus
) -> None:
    state = TripState(trip_id="trip-1", session_id="session-1", status=source)

    assert state.can_transition_to(target)
    assert state.transition_to(target).status is target


@pytest.mark.parametrize(
    ("source", "target"),
    [
        (WorkflowStatus.COLLECTING, WorkflowStatus.DRAFTING),
        (WorkflowStatus.CLARIFYING, WorkflowStatus.DRAFTING),
        (WorkflowStatus.RESEARCHING, WorkflowStatus.VALIDATING),
        (WorkflowStatus.COMPLETED, WorkflowStatus.COLLECTING),
        (WorkflowStatus.FAILED, WorkflowStatus.RESEARCHING),
    ],
)
def test_trip_state_rejects_non_whitelisted_transition(
    source: WorkflowStatus, target: WorkflowStatus
) -> None:
    state = TripState(trip_id="trip-1", session_id="session-1", status=source)

    assert not state.can_transition_to(target)
    with pytest.raises(InvalidStateTransitionError, match="not allowed"):
        state.transition_to(target)


def test_trip_state_rejects_unknown_fields() -> None:
    with pytest.raises(ValidationError):
        TripState(trip_id="trip-1", session_id="session-1", unknown_field="rejected")
