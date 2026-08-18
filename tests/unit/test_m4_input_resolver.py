from __future__ import annotations

from datetime import UTC, date, datetime
from decimal import Decimal

import pytest

from src.application.m4_input_resolver import M4InputResolver
from src.domain.errors import WorkflowError
from src.domain.models.constraint import Constraint, ConstraintSnapshot, ConstraintSource
from src.domain.models.enums import ConstraintHardness, ErrorCategory
from src.domain.models.trip_request import BudgetSemantics, BudgetSpec, TravelerProfile, TripRequest
from src.domain.models.value_objects import DateRange, Money

_TRACE_ID = "trace:m4-input"


def _request() -> TripRequest:
    return TripRequest(
        request_id="request:m4-input",
        trip_id="trip:m4-input",
        session_id="session:m4-input",
        origin="Old origin",
        destinations=("Old destination",),
        date_range=DateRange(start=date(2026, 8, 10), end=date(2026, 8, 12)),
        travelers=TravelerProfile(adults=1),
        locale="en-US",
        timezone="Asia/Shanghai",
    )


def _constraint(
    category: str,
    value: object,
    *,
    hardness: ConstraintHardness = ConstraintHardness.HARD,
    source: ConstraintSource = ConstraintSource.USER,
) -> Constraint:
    return Constraint(
        id=f"constraint:{category}",
        category=category,
        normalized_value=value,
        hardness=hardness,
        priority=10,
        scope="trip",
        source=source,
        confidence=Decimal("1"),
        user_confirmed=True,
    )


def _snapshot(*constraints: Constraint) -> ConstraintSnapshot:
    return ConstraintSnapshot(
        version=3,
        created_at=datetime(2026, 8, 7, 9, tzinfo=UTC),
        request_id="request:m4-input",
        constraints=constraints,
    )


def test_m4_input_resolver_binds_snapshot_values_without_llm_or_defaults() -> None:
    snapshot = _snapshot(
        _constraint("origin", "Shanghai"),
        _constraint("destination", ("Hangzhou", "Ningbo")),
        _constraint("date_range", DateRange(start=date(2026, 9, 1), end=date(2026, 9, 3))),
        _constraint("travelers", 3),
        _constraint("budget_max", Money(amount=Decimal("5000"), currency="CNY")),
        _constraint("preference", "slow pace", hardness=ConstraintHardness.SOFT),
        _constraint("explicit_exclusion", "red eye", hardness=ConstraintHardness.HARD),
    )

    resolved = M4InputResolver().resolve(_request(), snapshot, trace_id=_TRACE_ID)

    assert resolved.origin == "Shanghai"
    assert resolved.destinations == ("Hangzhou", "Ningbo")
    assert resolved.date_range == DateRange(start=date(2026, 9, 1), end=date(2026, 9, 3))
    assert resolved.duration_days == 3
    assert resolved.travelers == TravelerProfile(adults=3)
    assert resolved.budget == BudgetSpec(
        semantics=BudgetSemantics.MAXIMUM,
        maximum=Money(amount=Decimal("5000"), currency="CNY"),
    )
    assert resolved.preferences == ("slow pace",)
    assert resolved.explicit_exclusions == ("red eye",)


def test_m4_input_resolver_rejects_ambiguous_snapshot_values() -> None:
    snapshot = _snapshot(
        _constraint("origin", "Shanghai"),
        _constraint("origin_alt", "Hangzhou"),
    ).model_copy(
        update={
            "constraints": (
                _constraint("origin", "Shanghai"),
                _constraint("origin", "Ningbo"),
            )
        }
    )

    with pytest.raises(WorkflowError) as caught:
        M4InputResolver().resolve(_request(), snapshot, trace_id=_TRACE_ID)

    assert caught.value.payload.code == "M4_INPUT_AMBIGUOUS"
    assert caught.value.payload.category is ErrorCategory.VALIDATION


def test_m4_input_resolver_carries_controlled_traveler_assumption() -> None:
    snapshot = _snapshot(
        _constraint(
            "travelers",
            1,
            hardness=ConstraintHardness.ASSUMPTION,
            source=ConstraintSource.ASSUMPTION,
        )
    )

    resolved = M4InputResolver().resolve(_request(), snapshot, trace_id=_TRACE_ID)

    assert resolved.travelers == TravelerProfile(adults=1)


def test_m4_input_resolver_ignores_uncontrolled_traveler_assumption() -> None:
    snapshot = _snapshot(
        _constraint(
            "travelers",
            3,
            hardness=ConstraintHardness.ASSUMPTION,
            source=ConstraintSource.USER,
        )
    )

    resolved = M4InputResolver().resolve(_request(), snapshot, trace_id=_TRACE_ID)

    assert resolved.travelers == TravelerProfile(adults=1)


def test_m4_input_resolver_rejects_request_snapshot_mismatch() -> None:
    snapshot = _snapshot().model_copy(update={"request_id": "request:other"})

    with pytest.raises(WorkflowError) as caught:
        M4InputResolver().resolve(_request(), snapshot, trace_id=_TRACE_ID)

    assert caught.value.payload.code == "M4_INPUT_SNAPSHOT_MISMATCH"
    assert caught.value.payload.category is ErrorCategory.STATE_CONFLICT

