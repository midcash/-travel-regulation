from __future__ import annotations

from decimal import Decimal

from src.application.interaction_router import InteractionRouter, _required_capabilities
from src.domain.models.enums import ConstraintHardness, InteractionMode
from src.domain.models.interpretation import ConstraintCandidate, InterpretationResult
from src.domain.models.readiness import (
    ReadinessBlocker,
    ReadinessBlockerCode,
    ReadinessResult,
)
from src.domain.models.routing import RouteReasonCode
from src.guard.g0 import G0ValidationResult


def _interpretation(
    mode: InteractionMode,
    *,
    categories: tuple[str, ...] = (),
) -> InterpretationResult:
    return InterpretationResult(
        mode_hint=mode,
        extracted_entities=(),
        constraint_candidates=tuple(
            ConstraintCandidate(
                category=category,
                value="provided",
                hardness=ConstraintHardness.SOFT,
                scope="trip",
                confidence=Decimal("0.9"),
            )
            for category in categories
        ),
        explicit_questions=(),
        references_to_current_plan=(),
        field_confidence={},
        overall_confidence=Decimal("0.9"),
        safety_flags=(),
    )


def _readiness(
    mode: InteractionMode,
    blockers: tuple[ReadinessBlocker, ...] = (),
) -> ReadinessResult:
    return ReadinessResult(
        trace_id="trace:router-edge",
        request_id="request:router-edge",
        snapshot_version=1,
        mode=mode,
        ready=not blockers,
        confidence=Decimal("0.8"),
        blockers=blockers,
    )


def _g0() -> G0ValidationResult:
    return G0ValidationResult(
        passed=True,
        input_length=1,
        pii_detected=False,
    )


def _blocker() -> ReadinessBlocker:
    return ReadinessBlocker(
        issue_id="blocker:router-edge",
        code=ReadinessBlockerCode.MISSING_DESTINATION,
        field="destination",
        message="destination is missing",
        priority=20,
    )


def test_interaction_router_clarifies_refine_and_replan_blockers() -> None:
    for mode in (InteractionMode.REFINE, InteractionMode.REPLAN):
        decision = InteractionRouter().route(
            _interpretation(mode),
            _readiness(mode, (_blocker(),)),
            g0_result=_g0(),
            current_plan_ref="plan:router-edge",
        )

        assert decision.mode == InteractionMode.CLARIFY.value
        assert decision.reason_codes == (RouteReasonCode.CLARIFICATION_REQUIRED,)


def test_interaction_router_clarifies_non_action_supported_modes_without_reason_mapping() -> None:
    decision = InteractionRouter().route(
        _interpretation(InteractionMode.CLARIFY),
        _readiness(InteractionMode.CLARIFY),
        g0_result=_g0(),
    )

    assert decision.mode == InteractionMode.CLARIFY.value
    assert decision.reason_codes == (RouteReasonCode.ROUTE_UNCERTAIN,)


def test_interaction_router_adds_only_explicit_stay_capability_for_plan() -> None:
    interpretation = _interpretation(
        InteractionMode.PLAN,
        categories=("hotel", "activity"),
    )

    assert _required_capabilities(InteractionMode.PLAN, interpretation) == (
        "geo",
        "transport",
        "stay",
    )
    assert _required_capabilities(InteractionMode.ACTION, interpretation) == (
        "action_confirmation",
    )

def test_interaction_router_does_not_enable_place_or_context_for_activity_alone() -> None:
    interpretation = _interpretation(InteractionMode.PLAN, categories=("activity",))

    assert _required_capabilities(InteractionMode.PLAN, interpretation) == (
        "geo",
        "transport",
    )


def test_interaction_router_enables_place_for_explicit_category() -> None:
    interpretation = _interpretation(InteractionMode.PLAN, categories=("scenic",))

    assert _required_capabilities(InteractionMode.PLAN, interpretation) == (
        "geo",
        "transport",
        "place",
    )




def test_interaction_router_enables_context_for_explicit_context_type() -> None:
    interpretation = _interpretation(InteractionMode.PLAN, categories=("weather",))

    assert _required_capabilities(InteractionMode.PLAN, interpretation) == (
        "geo",
        "transport",
        "context",
    )
