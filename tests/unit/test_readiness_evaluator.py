from __future__ import annotations

from datetime import UTC, date, datetime
from decimal import Decimal

import pytest

from src.domain.models.constraint import Constraint, ConstraintSnapshot, ConstraintSource
from src.domain.models.enums import ConstraintHardness, InteractionMode
from src.domain.models.readiness import (
    ActionPreconditions,
    ReadinessAssumptionCode,
    ReadinessBlockerCode,
)
from src.domain.models.value_objects import DateRange, Money
from src.domain.services.readiness_evaluator import (
    ReadinessEvaluationContext,
    ReadinessEvaluator,
)


def _constraint(
    constraint_id: str,
    category: str,
    value: object,
    *,
    hardness: ConstraintHardness = ConstraintHardness.SOFT,
    conflict_group: str | None = None,
) -> Constraint:
    return Constraint(
        id=constraint_id,
        category=category,
        normalized_value=value,
        hardness=hardness,
        priority=10,
        scope="trip",
        source=ConstraintSource.USER,
        confidence=Decimal("0.9"),
        conflict_group=conflict_group,
    )


def _snapshot(*constraints: Constraint) -> ConstraintSnapshot:
    return ConstraintSnapshot(
        version=1,
        created_at=datetime(2026, 7, 29, 12, tzinfo=UTC),
        request_id="request-1",
        constraints=tuple(constraints),
    )


def _ready_trip_snapshot(*extra: Constraint) -> ConstraintSnapshot:
    return _snapshot(
        _constraint("origin-1", "origin", "Shanghai", hardness=ConstraintHardness.HARD),
        _constraint("destination-1", "destination", "Hangzhou", hardness=ConstraintHardness.HARD),
        _constraint(
            "date-1",
            "date_range",
            DateRange(start=date(2026, 8, 1), end=date(2026, 8, 3)),
            hardness=ConstraintHardness.HARD,
        ),
        _constraint("travelers-1", "travelers", 2, hardness=ConstraintHardness.HARD),
        *extra,
    )


def _codes(result: object) -> set[ReadinessBlockerCode]:
    return {blocker.code for blocker in result.blockers}  # type: ignore[union-attr]


def test_readiness_evaluator_accepts_complete_plan_and_exposes_missing_budget_assumption() -> None:
    snapshot = _ready_trip_snapshot()

    first = ReadinessEvaluator().evaluate(snapshot, trace_id="trace-1")
    second = ReadinessEvaluator().evaluate(snapshot, trace_id="trace-1")

    assert first.ready is True
    assert first.blockers == ()
    assert first == second
    assert first.assumptions[0].code is ReadinessAssumptionCode.BUDGET_NOT_SPECIFIED
    assert first.confidence == Decimal("0.9")


def test_readiness_evaluator_blocks_explicit_past_date_before_external_research() -> None:
    result = ReadinessEvaluator().evaluate(
        _ready_trip_snapshot(),
        trace_id="trace-past-date",
        context=ReadinessEvaluationContext(
            mode=InteractionMode.PLAN,
            reference_date=date(2026, 8, 7),
        ),
    )

    assert result.ready is False
    blockers = [
        item for item in result.blockers if item.code is ReadinessBlockerCode.DATE_RANGE_IN_PAST
    ]
    assert len(blockers) == 1
    assert blockers[0].field == "date_range"
    assert blockers[0].constraint_refs == ("date-1",)


def test_readiness_evaluator_keeps_future_date_plannable() -> None:
    result = ReadinessEvaluator().evaluate(
        _ready_trip_snapshot(),
        trace_id="trace-future-date",
        context=ReadinessEvaluationContext(
            mode=InteractionMode.PLAN,
            reference_date=date(2026, 7, 30),
        ),
    )

    assert result.ready is True
    assert ReadinessBlockerCode.DATE_RANGE_IN_PAST not in _codes(result)
def test_readiness_evaluator_blocks_missing_critical_trip_fields_without_fallback() -> None:
    result = ReadinessEvaluator().evaluate(_snapshot(), trace_id="trace-1")

    assert result.ready is False
    assert _codes(result) == {
        ReadinessBlockerCode.MISSING_ORIGIN,
        ReadinessBlockerCode.MISSING_DESTINATION,
        ReadinessBlockerCode.DATE_OR_DURATION_UNDETERMINED,
        ReadinessBlockerCode.TRAVELER_COUNT_UNDETERMINED,
    }
    assert result.confidence == Decimal("0")


def test_readiness_evaluator_blocks_unknown_special_population_and_date_duration_conflict() -> None:
    snapshot = _ready_trip_snapshot(
        _constraint(
            "duration-1",
            "duration_days",
            4,
            hardness=ConstraintHardness.HARD,
        ),
        _constraint(
            "special-1",
            "special_population",
            "unknown",
            hardness=ConstraintHardness.UNKNOWN,
        ),
    )

    result = ReadinessEvaluator().evaluate(snapshot, trace_id="trace-1")

    assert _codes(result) == {
        ReadinessBlockerCode.DATE_DURATION_CONFLICT,
        ReadinessBlockerCode.SPECIAL_POPULATION_UNDETERMINED,
    }


def test_readiness_evaluator_blocks_hard_constraint_conflict_with_structured_refs() -> None:
    snapshot = _ready_trip_snapshot(
        _constraint(
            "transport-1",
            "transport",
            "train",
            hardness=ConstraintHardness.HARD,
            conflict_group="conflict-transport",
        ),
        _constraint(
            "transport-2",
            "transport",
            "flight",
            hardness=ConstraintHardness.HARD,
            conflict_group="conflict-transport",
        ),
    )

    result = ReadinessEvaluator().evaluate(snapshot, trace_id="trace-1")
    blocker = next(
        item for item in result.blockers if item.code is ReadinessBlockerCode.CONSTRAINT_CONFLICT
    )

    assert result.ready is False
    assert blocker.conflict_group == "conflict-transport"
    assert blocker.constraint_refs == ("transport-1", "transport-2")


def test_readiness_evaluator_blocks_budget_range_semantic_conflict() -> None:
    snapshot = _ready_trip_snapshot(
        _constraint("budget-min", "budget_min", Money(amount=Decimal("5000"), currency="CNY")),
        _constraint("budget-max", "budget_max", Money(amount=Decimal("3000"), currency="CNY")),
    )

    result = ReadinessEvaluator().evaluate(snapshot, trace_id="trace-1")

    assert ReadinessBlockerCode.BUDGET_SEMANTIC_CONFLICT in _codes(result)
    assert result.blockers[0].field == "budget"


def test_readiness_evaluator_requires_current_plan_for_refine_and_replan() -> None:
    evaluator = ReadinessEvaluator()
    missing = evaluator.evaluate(
        _ready_trip_snapshot(),
        trace_id="trace-1",
        context=ReadinessEvaluationContext(mode=InteractionMode.REFINE),
    )
    present = evaluator.evaluate(
        _ready_trip_snapshot(),
        trace_id="trace-1",
        context=ReadinessEvaluationContext(
            mode=InteractionMode.REPLAN,
            current_plan_ref="plan-1",
        ),
    )

    assert _codes(missing) == {ReadinessBlockerCode.CURRENT_PLAN_REQUIRED}
    assert present.ready is True


def test_readiness_evaluator_requires_action_authorization_and_identity() -> None:
    evaluator = ReadinessEvaluator()
    blocked = evaluator.evaluate(
        _snapshot(),
        trace_id="trace-1",
        context=ReadinessEvaluationContext(mode=InteractionMode.ACTION),
    )
    ready = evaluator.evaluate(
        _snapshot(),
        trace_id="trace-1",
        context=ReadinessEvaluationContext(
            mode=InteractionMode.ACTION,
            action_preconditions=ActionPreconditions(
                authenticated=True,
                authorized=True,
                identity_ref="principal-1",
            ),
        ),
    )

    assert _codes(blocked) == {
        ReadinessBlockerCode.ACTION_AUTHORIZATION_REQUIRED,
        ReadinessBlockerCode.ACTION_IDENTITY_REQUIRED,
    }
    assert ready.ready is True


def test_readiness_evaluator_keeps_nonblocking_unknown_as_explicit_assumption() -> None:
    snapshot = _ready_trip_snapshot(
        _constraint(
            "preference-1",
            "preference",
            "unknown",
            hardness=ConstraintHardness.UNKNOWN,
        )
    )

    result = ReadinessEvaluator().evaluate(snapshot, trace_id="trace-1")

    assert result.ready is True
    assert any(
        assumption.code is ReadinessAssumptionCode.NON_BLOCKING_UNKNOWN
        and assumption.constraint_refs == ("preference-1",)
        for assumption in result.assumptions
    )


def test_readiness_evaluator_rejects_untyped_runtime_inputs() -> None:
    with pytest.raises(TypeError, match="ConstraintSnapshot"):
        ReadinessEvaluator().evaluate("not-a-snapshot", trace_id="trace-1")  # type: ignore[arg-type]
