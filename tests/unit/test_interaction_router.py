from __future__ import annotations

from decimal import Decimal

import pytest

from src.application.interaction_router import InteractionRouter
from src.domain.models.enums import ConstraintHardness, InteractionMode
from src.domain.models.interpretation import (
    ConstraintCandidate,
    InterpretationResult,
    SafetyFlag,
)
from src.domain.models.readiness import (
    ReadinessBlocker,
    ReadinessBlockerCode,
    ReadinessResult,
)
from src.domain.models.routing import RouteReasonCode
from src.guard.g0 import G0Issue, G0IssueCode, G0ValidationResult


def _interpretation(
    mode: InteractionMode | None,
    *,
    categories: tuple[str, ...] = (),
    safety_flags: tuple[SafetyFlag, ...] = (),
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
        safety_flags=safety_flags,
    )


def _readiness(
    mode: InteractionMode,
    *,
    blockers: tuple[ReadinessBlocker, ...] = (),
) -> ReadinessResult:
    return ReadinessResult(
        trace_id="trace-1",
        request_id="request-1",
        snapshot_version=1,
        mode=mode,
        ready=not blockers,
        confidence=Decimal("0.8"),
        blockers=blockers,
    )


def _g0(
    *,
    passed: bool = True,
    safety_flags: tuple[SafetyFlag, ...] = (),
    issues: tuple[G0Issue, ...] = (),
) -> G0ValidationResult:
    return G0ValidationResult(
        passed=passed,
        input_length=10,
        pii_detected=SafetyFlag.PII in safety_flags,
        safety_flags=safety_flags,
        issues=issues,
    )


def _blocker(
    issue_id: str = "missing-origin",
    code: ReadinessBlockerCode = ReadinessBlockerCode.MISSING_ORIGIN,
) -> ReadinessBlocker:
    return ReadinessBlocker(
        issue_id=issue_id,
        code=code,
        field="origin",
        message="origin is missing",
        priority=20,
    )


def test_interaction_router_routes_ready_plan_and_selects_research_capabilities() -> None:
    decision = InteractionRouter().route(
        _interpretation(InteractionMode.PLAN, categories=("hotel",)),
        _readiness(InteractionMode.PLAN),
        g0_result=_g0(),
    )

    assert decision.mode == InteractionMode.PLAN.value
    assert decision.reason_codes == (RouteReasonCode.PLAN_REQUEST,)
    assert decision.required_capabilities == ("geo", "transport", "stay")
    assert decision.missing_blockers == ()


@pytest.mark.parametrize(
    ("mode", "expected_capabilities", "reason"),
    [
        (InteractionMode.ANSWER, (), RouteReasonCode.ANSWER_REQUEST),
        (
            InteractionMode.COMPARE,
            ("geo",),
            RouteReasonCode.COMPARE_REQUEST,
        ),
        (
            InteractionMode.REFINE,
            ("plan_refinement",),
            RouteReasonCode.REFINE_CURRENT_PLAN,
        ),
        (
            InteractionMode.REPLAN,
            ("plan_replanning",),
            RouteReasonCode.REPLAN_CURRENT_PLAN,
        ),
        (
            InteractionMode.ACTION,
            ("action_confirmation",),
            RouteReasonCode.EXPLICIT_ACTION,
        ),
    ],
)
def test_interaction_router_routes_ready_modes_with_typed_reasons(
    mode: InteractionMode,
    expected_capabilities: tuple[str, ...],
    reason: RouteReasonCode,
) -> None:
    decision = InteractionRouter().route(
        _interpretation(mode),
        _readiness(mode),
        g0_result=_g0(),
        current_plan_ref=(
            "plan-1"
            if mode in {InteractionMode.REFINE, InteractionMode.REPLAN}
            else None
        ),
    )

    assert decision.mode == mode.value
    assert decision.required_capabilities == expected_capabilities
    assert decision.reason_codes == (reason,)
    if mode in {InteractionMode.REFINE, InteractionMode.REPLAN}:
        assert decision.current_plan_ref == "plan-1"


def test_interaction_router_prioritizes_g0_block_over_explicit_action() -> None:
    decision = InteractionRouter().route(
        _interpretation(InteractionMode.ACTION),
        _readiness(InteractionMode.ACTION),
        g0_result=_g0(
            passed=False,
            safety_flags=(SafetyFlag.DANGEROUS_ACTION,),
            issues=(
                G0Issue(
                    code=G0IssueCode.DANGEROUS_ACTION,
                    safe_message="dangerous action requires a safety boundary",
                    blocking=True,
                ),
            ),
        ),
    )

    assert decision.mode == InteractionMode.UNSUPPORTED.value
    assert decision.reason_codes == (RouteReasonCode.G0_BLOCKED,)
    assert decision.required_capabilities == ()
    assert SafetyFlag.DANGEROUS_ACTION in decision.risk_flags


def test_interaction_router_keeps_nonblocking_pii_as_risk_without_changing_route() -> None:
    decision = InteractionRouter().route(
        _interpretation(InteractionMode.ANSWER, safety_flags=(SafetyFlag.PII,)),
        _readiness(InteractionMode.ANSWER),
        g0_result=_g0(safety_flags=(SafetyFlag.PII,)),
    )

    assert decision.mode == InteractionMode.ANSWER.value
    assert decision.risk_flags == (SafetyFlag.PII,)


def test_interaction_router_routes_readiness_blockers_to_clarify_without_guessing() -> None:
    blocker = _blocker()
    decision = InteractionRouter().route(
        _interpretation(InteractionMode.PLAN),
        _readiness(InteractionMode.PLAN, blockers=(blocker,)),
        g0_result=_g0(),
    )

    assert decision.mode == InteractionMode.CLARIFY.value
    assert decision.reason_codes == (RouteReasonCode.CLARIFICATION_REQUIRED,)
    assert decision.missing_blockers == ("missing-origin",)
    assert decision.required_capabilities == ()


def test_interaction_router_routes_action_preconditions_to_clarify() -> None:
    blocker = _blocker(
        "auth-required",
        ReadinessBlockerCode.ACTION_AUTHORIZATION_REQUIRED,
    )
    decision = InteractionRouter().route(
        _interpretation(InteractionMode.ACTION),
        _readiness(InteractionMode.ACTION, blockers=(blocker,)),
        g0_result=_g0(),
    )

    assert decision.mode == InteractionMode.CLARIFY.value
    assert decision.reason_codes == (
        RouteReasonCode.EXPLICIT_ACTION,
        RouteReasonCode.ACTION_PRECONDITION_MISSING,
        RouteReasonCode.CLARIFICATION_REQUIRED,
    )
    assert decision.missing_blockers == ("auth-required",)


@pytest.mark.parametrize("mode", [InteractionMode.REFINE, InteractionMode.REPLAN])
def test_interaction_router_requires_current_plan_for_local_routes(mode: InteractionMode) -> None:
    decision = InteractionRouter().route(
        _interpretation(mode),
        _readiness(mode),
        g0_result=_g0(),
    )

    assert decision.mode == InteractionMode.CLARIFY.value
    assert RouteReasonCode.PLAN_CONTEXT_MISSING in decision.reason_codes
    assert decision.current_plan_ref is None


def test_interaction_router_does_not_default_unknown_mode_to_plan() -> None:
    decision = InteractionRouter().route(
        _interpretation(None),
        _readiness(InteractionMode.PLAN),
        g0_result=_g0(),
    )

    assert decision.mode == InteractionMode.CLARIFY.value
    assert decision.reason_codes == (RouteReasonCode.ROUTE_UNCERTAIN,)
    assert decision.required_capabilities == ()


def test_interaction_router_preserves_explicit_unsupported_mode() -> None:
    decision = InteractionRouter().route(
        _interpretation(InteractionMode.UNSUPPORTED),
        _readiness(InteractionMode.UNSUPPORTED),
        g0_result=_g0(),
    )

    assert decision.mode == InteractionMode.UNSUPPORTED.value
    assert decision.reason_codes == (RouteReasonCode.UNSUPPORTED_REQUEST,)


def test_interaction_router_rejects_untyped_runtime_inputs() -> None:
    router = InteractionRouter()
    readiness = _readiness(InteractionMode.PLAN)
    interpretation = _interpretation(InteractionMode.PLAN)
    g0_result = _g0()

    with pytest.raises(TypeError, match="InterpretationResult"):
        router.route("not-an-interpretation", readiness, g0_result=g0_result)  # type: ignore[arg-type]
    with pytest.raises(TypeError, match="ReadinessResult"):
        router.route(interpretation, "not-readiness", g0_result=g0_result)  # type: ignore[arg-type]
    with pytest.raises(TypeError, match="G0ValidationResult"):
        router.route(interpretation, readiness, g0_result="not-g0")  # type: ignore[arg-type]


def test_interaction_router_enables_place_only_for_explicit_place_category() -> None:
    decision = InteractionRouter().route(
        _interpretation(InteractionMode.PLAN, categories=("place_category",)),
        _readiness(InteractionMode.PLAN),
        g0_result=_g0(),
    )

    assert decision.required_capabilities == ("geo", "transport", "place")


def test_interaction_router_enables_answer_context_only_for_explicit_context_type() -> None:
    decision = InteractionRouter().route(
        _interpretation(InteractionMode.ANSWER, categories=("weather",)),
        _readiness(InteractionMode.ANSWER),
        g0_result=_g0(),
    )

    assert decision.required_capabilities == ("context",)
