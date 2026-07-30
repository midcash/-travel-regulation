from __future__ import annotations

from decimal import Decimal

import pytest

from src.application.trip_state_integration import TripStateIntegration
from src.domain.errors import InvalidStateTransitionError
from src.domain.models.enums import InteractionMode, WorkflowStatus
from src.domain.models.routing import RouteDecision, RouteReasonCode
from src.domain.models.state import TripState


def _state(status: WorkflowStatus = WorkflowStatus.COLLECTING) -> TripState:
    return TripState(
        trip_id="trip-1",
        session_id="session-1",
        status=status,
    )


def _decision(
    mode: InteractionMode,
    *,
    current_plan_ref: str | None = None,
) -> RouteDecision:
    reason = {
        InteractionMode.ANSWER: RouteReasonCode.ANSWER_REQUEST,
        InteractionMode.CLARIFY: RouteReasonCode.CLARIFICATION_REQUIRED,
        InteractionMode.PLAN: RouteReasonCode.PLAN_REQUEST,
        InteractionMode.REFINE: RouteReasonCode.REFINE_CURRENT_PLAN,
        InteractionMode.COMPARE: RouteReasonCode.COMPARE_REQUEST,
        InteractionMode.REPLAN: RouteReasonCode.REPLAN_CURRENT_PLAN,
        InteractionMode.ACTION: RouteReasonCode.EXPLICIT_ACTION,
        InteractionMode.UNSUPPORTED: RouteReasonCode.UNSUPPORTED_REQUEST,
    }[mode]
    return RouteDecision(
        mode=mode.value,
        confidence=Decimal("0.9"),
        reason_codes=(reason,),
        current_plan_ref=current_plan_ref,
    )


@pytest.mark.parametrize("mode", [InteractionMode.PLAN, InteractionMode.COMPARE])
def test_trip_state_integration_moves_ready_planning_routes_to_researching(
    mode: InteractionMode,
) -> None:
    state = _state()

    updated = TripStateIntegration().apply_route_decision(state, _decision(mode))

    assert state.status is WorkflowStatus.COLLECTING
    assert state.version == 1
    assert updated.status is WorkflowStatus.RESEARCHING
    assert updated.version == 2


def test_trip_state_integration_moves_clarification_route_to_clarifying() -> None:
    updated = TripStateIntegration().apply(_state(), _decision(InteractionMode.CLARIFY))

    assert updated.status is WorkflowStatus.CLARIFYING
    assert updated.version == 2


def test_trip_state_integration_allows_collection_after_user_clarification() -> None:
    state = _state(WorkflowStatus.CLARIFYING)

    updated = TripStateIntegration().apply_route_decision(state, _decision(InteractionMode.PLAN))

    assert updated.status is WorkflowStatus.RESEARCHING
    assert updated.version == 2


def test_trip_state_integration_moves_valid_replan_from_stale_to_replanning() -> None:
    state = _state(WorkflowStatus.STALE)

    updated = TripStateIntegration().apply_route_decision(
        state,
        _decision(InteractionMode.REPLAN, current_plan_ref="plan-1"),
    )

    assert updated.status is WorkflowStatus.REPLANNING
    assert updated.version == 2


@pytest.mark.parametrize(
    "mode",
    [
        InteractionMode.ANSWER,
        InteractionMode.ACTION,
        InteractionMode.REFINE,
        InteractionMode.UNSUPPORTED,
    ],
)
def test_trip_state_integration_does_not_change_state_for_non_transitioning_m2_modes(
    mode: InteractionMode,
) -> None:
    state = _state()
    decision = _decision(
        mode,
        current_plan_ref="plan-1" if mode is InteractionMode.REFINE else None,
    )

    updated = TripStateIntegration().apply_route_decision(state, decision)

    assert updated is state
    assert updated.status is WorkflowStatus.COLLECTING
    assert updated.version == 1


def test_trip_state_integration_never_enters_drafting_from_a_route() -> None:
    state = _state()

    updated = TripStateIntegration().apply_route_decision(
        state,
        _decision(InteractionMode.PLAN),
    )

    assert updated.status is not WorkflowStatus.DRAFTING
    assert updated.status is WorkflowStatus.RESEARCHING


def test_trip_state_integration_rejects_forbidden_transition_without_mutation() -> None:
    state = _state(WorkflowStatus.DRAFTING)

    with pytest.raises(InvalidStateTransitionError, match="drafting -> researching"):
        TripStateIntegration().apply_route_decision(state, _decision(InteractionMode.PLAN))

    assert state.status is WorkflowStatus.DRAFTING
    assert state.version == 1


def test_trip_state_integration_rejects_replan_before_a_replan_eligible_state() -> None:
    state = _state()

    with pytest.raises(InvalidStateTransitionError, match="collecting -> replanning"):
        TripStateIntegration().apply_route_decision(
            state,
            _decision(InteractionMode.REPLAN, current_plan_ref="plan-1"),
        )


def test_trip_state_integration_rejects_untyped_runtime_inputs() -> None:
    integration = TripStateIntegration()
    state = _state()
    decision = _decision(InteractionMode.PLAN)

    with pytest.raises(TypeError, match="TripState"):
        integration.apply_route_decision("not-state", decision)  # type: ignore[arg-type]
    with pytest.raises(TypeError, match="RouteDecision"):
        integration.apply_route_decision(state, "not-decision")  # type: ignore[arg-type]
