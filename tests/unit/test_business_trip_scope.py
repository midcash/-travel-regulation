from __future__ import annotations

from datetime import UTC, date, datetime
from decimal import Decimal

from src.application.interaction_router import InteractionRouter
from src.domain.models.business_trip import BusinessTripScope
from src.domain.models.constraint import Constraint, ConstraintSnapshot, ConstraintSource
from src.domain.models.enums import ConstraintHardness, InteractionMode
from src.domain.models.interpretation import ConstraintCandidate, InterpretationResult
from src.domain.models.readiness import ReadinessAssumptionCode, ReadinessBlockerCode
from src.domain.models.routing import RouteReasonCode
from src.domain.models.value_objects import DateRange
from src.domain.services.business_trip_scope_resolver import BusinessTripScopeResolver
from src.domain.services.readiness_evaluator import (
    ReadinessEvaluationContext,
    ReadinessEvaluator,
)
from src.guard.g0 import G0ValidationResult


def _constraint(constraint_id: str, category: str, value: object) -> Constraint:
    return Constraint(
        id=constraint_id,
        category=category,
        normalized_value=value,
        hardness=ConstraintHardness.HARD,
        priority=10,
        scope="trip",
        source=ConstraintSource.USER,
        confidence=Decimal("0.95"),
    )


def _snapshot(*, with_timezone: bool) -> ConstraintSnapshot:
    constraints = [
        _constraint("origin-1", "origin", "杭州"),
        _constraint("destination-1", "destination", "上海"),
        _constraint(
            "date-1",
            "date_range",
            DateRange(start=date(2026, 8, 22), end=date(2026, 8, 22)),
        ),
        _constraint("travelers-1", "travelers", 1),
        _constraint("meeting-city-1", "meeting_city", "上海"),
        _constraint("meeting-location-1", "meeting_location", "上海东方明珠塔"),
        _constraint("meeting-start-1", "meeting_starts_at", "2026-08-22T08:00:00"),
    ]
    if with_timezone:
        constraints.append(_constraint("meeting-timezone-1", "meeting_timezone", "Asia/Shanghai"))
    return ConstraintSnapshot(
        version=1,
        created_at=datetime(2026, 8, 16, 12, tzinfo=UTC),
        request_id="request-business-scope",
        constraints=tuple(constraints),
    )


def _interpretation() -> InterpretationResult:
    return InterpretationResult(
        mode_hint=InteractionMode.PLAN,
        extracted_entities=(),
        constraint_candidates=tuple(
            ConstraintCandidate(
                category=category,
                value=value,
                hardness=ConstraintHardness.HARD,
                scope="trip",
                confidence=Decimal("0.95"),
            )
            for category, value in (
                ("origin", "杭州"),
                ("destination", "上海"),
                ("date_range", "2026-08-22"),
                ("travelers", 1),
                ("meeting_city", "上海"),
                ("meeting_location", "上海东方明珠塔"),
                ("meeting_starts_at", "2026-08-22T08:00:00"),
                ("meeting_timezone", "Asia/Shanghai"),
            )
        ),
        explicit_questions=(),
        references_to_current_plan=(),
        field_confidence={},
        overall_confidence=Decimal("0.95"),
        safety_flags=(),
    )


def _g0() -> G0ValidationResult:
    return G0ValidationResult(
        passed=True,
        input_length=10,
        pii_detected=False,
        safety_flags=(),
        issues=(),
    )


def test_business_trip_readiness_blocks_missing_meeting_timezone_without_inference() -> None:
    result = ReadinessEvaluator().evaluate(
        _snapshot(with_timezone=False),
        trace_id="trace-business-missing-timezone",
        context=ReadinessEvaluationContext(
            mode=InteractionMode.PLAN,
            reference_date=date(2026, 8, 16),
        ),
    )

    assert result.ready is False
    assert {blocker.code for blocker in result.blockers} == {
        ReadinessBlockerCode.MISSING_MEETING_TIMEZONE
    }
    assert result.blockers[0].field == "meeting_timezone"


def test_business_trip_readiness_accepts_only_controlled_default_assumptions() -> None:
    base = _snapshot(with_timezone=False)
    constraints = [
        item for item in base.constraints if item.category != "travelers"
    ]
    constraints.extend(
        [
            Constraint(
                id="assumption-travelers-1",
                category="travelers",
                normalized_value=1,
                hardness=ConstraintHardness.ASSUMPTION,
                priority=10,
                scope="trip",
                source=ConstraintSource.ASSUMPTION,
                confidence=Decimal("0.90"),
            ),
            Constraint(
                id="assumption-timezone-1",
                category="meeting_timezone",
                normalized_value="Asia/Shanghai",
                hardness=ConstraintHardness.ASSUMPTION,
                priority=10,
                scope="meeting",
                source=ConstraintSource.ASSUMPTION,
                confidence=Decimal("0.90"),
            ),
        ]
    )
    snapshot = base.model_copy(update={"constraints": tuple(constraints)})

    result = ReadinessEvaluator().evaluate(
        snapshot,
        trace_id="trace-business-assumptions",
        context=ReadinessEvaluationContext(
            mode=InteractionMode.PLAN,
            reference_date=date(2026, 8, 16),
        ),
    )

    assert result.ready is True
    assert result.blockers == ()
    assert {
        item.code for item in result.assumptions
    } >= {
        ReadinessAssumptionCode.MEETING_TIMEZONE_DERIVED_FROM_CITY,
        ReadinessAssumptionCode.TRAVELER_COUNT_DEFAULTED_TO_ONE,
    }


def test_business_trip_scope_resolves_initial_capabilities_and_exclusions() -> None:
    scope = BusinessTripScopeResolver().resolve(_snapshot(with_timezone=True))

    assert isinstance(scope, BusinessTripScope)
    assert scope.planning_horizon == "meeting_arrival_ready"
    assert scope.initial_required_capabilities == (
        "geo",
        "policy",
        "intercity_transport",
    )
    assert scope.required_capabilities == (
        "geo",
        "policy",
        "intercity_transport",
        "local_transport",
    )
    assert scope.conditional_capabilities == ("stay",)
    assert scope.excluded_capabilities == ("place", "activity", "return_transport")
    assert scope.return_scope == "not_planned"
    assert {item.capability for item in scope.capability_reasons} == {
        "geo",
        "policy",
        "intercity_transport",
        "stay",
        "local_transport",
        "place",
        "activity",
        "return_transport",
    }


def test_router_consumes_business_scope_instead_of_tourism_default() -> None:
    scope = BusinessTripScopeResolver().resolve(_snapshot(with_timezone=True))
    readiness = ReadinessEvaluator().evaluate(
        _snapshot(with_timezone=True),
        trace_id="trace-business-route",
        interpretation=_interpretation(),
        context=ReadinessEvaluationContext(mode=InteractionMode.PLAN),
    )

    decision = InteractionRouter().route(
        _interpretation(),
        readiness,
        g0_result=_g0(),
        business_scope=scope,
    )

    assert decision.mode == InteractionMode.PLAN.value
    assert decision.reason_codes == (RouteReasonCode.PLAN_REQUEST,)
    assert decision.required_capabilities == (
        "geo",
        "policy",
        "intercity_transport",
    )
    assert decision.scope_version == scope.scope_version
    assert decision.continue_to_planner is False
    assert decision.capability_reasons
