"""M4 step eleven: explicit CLI Use Case configuration tests."""

from __future__ import annotations

from datetime import UTC, date, datetime
from decimal import Decimal

import pytest

import main
from src.application.interaction_facade import _execute_plan
from src.application.use_cases.m4_plan import M4PlanUseCase
from src.application.use_cases.plan_trip import PlanTripResult
from src.config import ConfigurationError, Settings, load_settings
from src.domain.models.constraint import ConstraintSnapshot
from src.domain.models.enums import InteractionMode, WorkflowStatus
from src.domain.models.routing import RouteDecision, RouteReasonCode
from src.domain.models.state import TripState
from src.domain.models.trip_request import TravelerProfile, TripRequest
from src.domain.models.value_objects import DateRange
from src.infrastructure.persistence.in_memory import InMemoryStateRepository


def test_settings_default_to_m4_and_legacy_requires_explicit_switch() -> None:
    assert load_settings({"DEEPSEEK_API_KEY": "key"}).workflow_use_case == "m4"
    assert (
        load_settings({"DEEPSEEK_API_KEY": "key", "WORKFLOW_USE_CASE": "legacy"}).workflow_use_case
        == "legacy"
    )
    with pytest.raises(ConfigurationError, match="WORKFLOW_USE_CASE"):
        Settings(deepseek_api_key="key", workflow_use_case="unknown")  # type: ignore[arg-type]


def test_cli_composition_root_builds_m4_use_case_by_default(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    settings = Settings(deepseek_api_key="key")
    state_repository = InMemoryStateRepository()
    sentinel = object()
    seen: dict[str, object] = {}

    def fake_from_settings(
        cls: type[M4PlanUseCase],
        received_settings: Settings,
        *,
        state_repository: InMemoryStateRepository,
    ) -> object:
        seen["settings"] = received_settings
        seen["state_repository"] = state_repository
        return sentinel

    monkeypatch.setattr(
        M4PlanUseCase,
        "from_settings",
        classmethod(fake_from_settings),
    )

    result = main._build_cli_plan_executor(settings, state_repository=state_repository)

    assert result is sentinel
    assert seen == {"settings": settings, "state_repository": state_repository}


def test_cli_composition_root_selects_legacy_only_when_explicitly_configured(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    settings = Settings(deepseek_api_key="key", workflow_use_case="legacy")
    state_repository = InMemoryStateRepository()

    class FakeLegacyUseCase:
        def __init__(self, received_settings: Settings) -> None:
            assert received_settings is settings

    monkeypatch.setattr(main, "PlanTripUseCase", FakeLegacyUseCase)

    result = main._build_cli_plan_executor(settings, state_repository=state_repository)

    assert isinstance(result, FakeLegacyUseCase)


def test_facade_plan_bridge_passes_frozen_m2_context_to_new_use_case() -> None:
    request = TripRequest(
        request_id="request:m4-step11",
        trip_id="trip:m4-step11",
        session_id="session:m4-step11",
        origin="Shanghai",
        destinations=("Hangzhou",),
        date_range=DateRange(start=date(2026, 8, 10), end=date(2026, 8, 11)),
        travelers=TravelerProfile(adults=1),
    )
    snapshot = ConstraintSnapshot(
        version=1,
        created_at=datetime(2026, 8, 7, tzinfo=UTC),
        request_id=request.request_id,
    )
    state = TripState(
        trip_id=request.trip_id,
        session_id=request.session_id,
        status=WorkflowStatus.RESEARCHING,
        trip_request=request,
        constraint_snapshot=snapshot,
    )
    decision = RouteDecision(
        mode=InteractionMode.PLAN.value,
        confidence=Decimal("1"),
        reason_codes=(RouteReasonCode.PLAN_REQUEST,),
        required_capabilities=("transport",),
    )
    seen: dict[str, object] = {}

    class RoutedUseCase:
        def execute_routed(
            self,
            received_request: TripRequest,
            *,
            state: TripState,
            route_decision: RouteDecision,
            constraint_snapshot: ConstraintSnapshot,
            raw_input: str,
            trace_id: str,
        ) -> PlanTripResult:
            seen["request"] = received_request
            seen.update(
                {
                    "state": state,
                    "route_decision": route_decision,
                    "constraint_snapshot": constraint_snapshot,
                    "raw_input": raw_input,
                    "trace_id": trace_id,
                }
            )
            return PlanTripResult(
                request_id=request.request_id,
                trip_id=request.trip_id,
                session_id=request.session_id,
                plan="fixture",
                rounds=0,
                issues_found=(),
            )

    result = _execute_plan(
        RoutedUseCase(),
        request,
        "下周一去杭州",
        state=state,
        route_decision=decision,
        constraint_snapshot=snapshot,
        trace_id="trace:m4-step11",
    )

    assert isinstance(result, PlanTripResult)
    assert result.plan == "fixture"
    assert seen == {
        "request": request,
        "state": state,
        "route_decision": decision,
        "constraint_snapshot": snapshot,
        "raw_input": "下周一去杭州",
        "trace_id": "trace:m4-step11",
    }


def test_m4_use_case_can_be_composed_without_creating_fake_success_provider() -> None:
    settings = Settings(deepseek_api_key="key")
    state_repository = InMemoryStateRepository()

    use_case = M4PlanUseCase.from_settings(
        settings,
        state_repository=state_repository,
    )

    assert isinstance(use_case, M4PlanUseCase)
    assert settings.workflow_use_case == "m4"
