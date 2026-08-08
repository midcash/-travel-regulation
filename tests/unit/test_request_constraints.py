"""Request-level hard-constraint validation tests."""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal

import pytest

from src.domain.errors import WorkflowError
from src.domain.models.constraint import Constraint, ConstraintSnapshot, ConstraintSource
from src.domain.models.enums import ConstraintHardness, ErrorCategory
from src.domain.models.trip_request import TravelerProfile, TripRequest
from src.domain.models.value_objects import DateRange
from src.domain.services.request_constraints import RequestConstraintService


def _request(*, adults: int = 2) -> TripRequest:
    return TripRequest(
        request_id="request:request-constraints",
        trip_id="trip:request-constraints",
        session_id="session:request-constraints",
        origin="Shanghai",
        destinations=("Hangzhou",),
        date_range=DateRange(start="2026-08-10", end="2026-08-12"),
        travelers=TravelerProfile(adults=adults),
    )


def _snapshot(*, travelers: int = 2) -> ConstraintSnapshot:
    return ConstraintSnapshot(
        version=1,
        created_at=datetime(2026, 8, 8, tzinfo=UTC),
        request_id="request:request-constraints",
        constraints=(
            Constraint(
                id="constraint:travelers",
                category="travelers",
                normalized_value=travelers,
                hardness=ConstraintHardness.HARD,
                priority=100,
                scope="trip",
                source=ConstraintSource.USER,
                confidence=Decimal("1"),
                user_confirmed=True,
            ),
        ),
    )


def test_request_constraint_service_accepts_matching_traveler_constraint() -> None:
    RequestConstraintService().validate(
        _request(adults=2),
        _snapshot(travelers=2),
        trace_id="trace:request-constraints",
    )


def test_request_constraint_service_rejects_mismatched_traveler_constraint() -> None:
    with pytest.raises(WorkflowError) as raised:
        RequestConstraintService().validate(
            _request(adults=1),
            _snapshot(travelers=2),
            trace_id="trace:request-constraints",
        )

    assert raised.value.stage == "request_constraint_service"
    assert raised.value.category is ErrorCategory.VALIDATION
    assert raised.value.payload.code == "REQUEST_LEVEL_TRAVELERS_MISMATCH"
    assert raised.value.payload.upstream_refs == ("constraint:travelers",)
