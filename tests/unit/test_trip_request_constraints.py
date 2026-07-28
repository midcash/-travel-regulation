from __future__ import annotations

from datetime import UTC, date, datetime
from decimal import Decimal

import pytest
from pydantic import ValidationError

from src.domain.models.constraint import (
    Constraint,
    ConstraintHardness,
    ConstraintSnapshot,
    ConstraintSource,
)
from src.domain.models.trip_request import (
    BudgetSemantics,
    BudgetSpec,
    TravelerProfile,
    TripRequest,
)
from src.domain.models.value_objects import DateRange, Money


def _money(amount: str, currency: str = "CNY") -> Money:
    return Money(amount=Decimal(amount), currency=currency)


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


def _constraint(
    constraint_id: str,
    value: object,
    *,
    hardness: ConstraintHardness = ConstraintHardness.SOFT,
    conflict_group: str | None = None,
) -> Constraint:
    return Constraint(
        id=constraint_id,
        category="transport",
        normalized_value=value,
        hardness=hardness,
        priority=10,
        scope="trip",
        source=ConstraintSource.USER,
        confidence=Decimal("0.9"),
        conflict_group=conflict_group,
    )


def test_trip_request_accepts_date_range_and_serializes_without_unknown_fields() -> None:
    request = _request(
        budget=BudgetSpec(
            semantics=BudgetSemantics.MAXIMUM,
            maximum=_money("5000"),
        ),
        preferences=("人文",),
        explicit_exclusions=("红眼航班",),
    )

    assert request.date_range is not None
    assert request.date_range.days == 3
    assert request.travelers.total_count == 2
    assert request.budget is not None
    assert request.model_validate_json(request.model_dump_json()) == request
    with pytest.raises(ValidationError):
        _request(unknown_field="rejected")


def test_trip_request_accepts_duration_only_and_rejects_missing_or_inconsistent_dates() -> None:
    request = _request(date_range=None, duration_days=5)
    assert request.duration_days == 5

    with pytest.raises(ValidationError, match="date_range or duration_days"):
        _request(date_range=None)
    with pytest.raises(ValidationError, match="must agree"):
        _request(duration_days=2)


def test_trip_request_rejects_empty_destinations_and_invalid_travelers() -> None:
    with pytest.raises(ValidationError):
        _request(destinations=())
    with pytest.raises(ValidationError):
        _request(travelers=TravelerProfile(adults=0))
    with pytest.raises(ValidationError):
        TravelerProfile(adults=1, accessibility_needs=("",))


def test_budget_spec_validates_maximum_range_target_and_currency() -> None:
    assert BudgetSpec(
        semantics=BudgetSemantics.RANGE,
        minimum=_money("1000"),
        maximum=_money("2000"),
    ).maximum == _money("2000")
    assert BudgetSpec(
        semantics=BudgetSemantics.TARGET,
        target=_money("1500"),
    ).target == _money("1500")

    with pytest.raises(ValidationError):
        BudgetSpec(semantics=BudgetSemantics.MAXIMUM)
    with pytest.raises(ValidationError):
        BudgetSpec(
            semantics=BudgetSemantics.RANGE,
            minimum=_money("2000"),
            maximum=_money("1000"),
        )
    with pytest.raises(ValidationError):
        BudgetSpec(
            semantics=BudgetSemantics.RANGE,
            minimum=_money("1000", "CNY"),
            maximum=_money("2000", "USD"),
        )


def test_constraint_has_typed_fields_and_rejects_unstructured_values() -> None:
    constraint = _constraint("constraint-1", "avoid_red_eye")

    assert constraint.source == ConstraintSource.USER
    assert constraint.normalized_value == "avoid_red_eye"
    with pytest.raises(ValidationError):
        _constraint("constraint-2", {"unsafe": "dict"})
    with pytest.raises(ValidationError):
        Constraint(
            id="constraint-3",
            category="transport",
            normalized_value="x",
            hardness=ConstraintHardness.HARD,
            priority=1,
            scope="trip",
            source=ConstraintSource.USER,
            confidence=Decimal("1.1"),
        )


def test_constraint_snapshot_is_immutable_queryable_and_versioned() -> None:
    snapshot = ConstraintSnapshot(
        version=1,
        created_at=datetime(2026, 8, 1, tzinfo=UTC),
        request_id="request-1",
        constraints=(
            _constraint("hard-1", "no_red_eye", hardness=ConstraintHardness.HARD),
            _constraint("soft-1", "museum", hardness=ConstraintHardness.SOFT),
        ),
    )
    next_snapshot = snapshot.new_version(
        constraints=snapshot.constraints,
        created_at=datetime(2026, 8, 2, tzinfo=UTC),
    )

    assert len(snapshot.hard_constraints) == 1
    assert len(snapshot.soft_constraints) == 1
    assert snapshot.version == 1
    assert next_snapshot.version == 2
    with pytest.raises(ValidationError):
        snapshot.version = 2
    with pytest.raises(ValidationError):
        snapshot.constraints += (_constraint("soft-2", "food"),)


def test_constraint_snapshot_preserves_explicit_hard_conflicts_and_rejects_implicit_conflicts() -> (
    None
):
    explicit = ConstraintSnapshot(
        version=1,
        created_at=datetime(2026, 8, 1, tzinfo=UTC),
        request_id="request-1",
        constraints=(
            _constraint(
                "hard-1",
                "budget_low",
                hardness=ConstraintHardness.HARD,
                conflict_group="budget-conflict",
            ),
            _constraint(
                "hard-2",
                "budget_high",
                hardness=ConstraintHardness.HARD,
                conflict_group="budget-conflict",
            ),
        ),
    )
    assert tuple(item.id for item in explicit.hard_constraints) == ("hard-1", "hard-2")

    with pytest.raises(ValidationError, match="conflict_group"):
        ConstraintSnapshot(
            version=1,
            created_at=datetime(2026, 8, 1, tzinfo=UTC),
            request_id="request-1",
            constraints=(
                _constraint("hard-1", "budget_low", hardness=ConstraintHardness.HARD),
                _constraint("hard-2", "budget_high", hardness=ConstraintHardness.HARD),
            ),
        )

    with pytest.raises(ValidationError, match="unique"):
        ConstraintSnapshot(
            version=1,
            created_at=datetime(2026, 8, 1, tzinfo=UTC),
            request_id="request-1",
            constraints=(_constraint("same", "a"), _constraint("same", "b")),
        )
