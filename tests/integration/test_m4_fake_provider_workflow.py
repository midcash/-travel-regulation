"""M4 step ten: Fake Provider vertical-slice integration tests."""

from __future__ import annotations

import asyncio
import json
import socket
from contextlib import contextmanager
from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest

from src.application.budget_policy import BudgetPolicy
from src.application.fake_provider_workflow import (
    FakeProviderWorkflow,
    ResearchProviders,
    ScheduleInputs,
)
from src.domain.errors import WorkflowError
from src.domain.models.enums import (
    ErrorCategory,
    InteractionMode,
    WorkflowStatus,
)
from src.domain.models.evidence import EvidenceTtlPolicy
from src.domain.models.provider import (
    ContextProviderResult,
    ContextResultItem,
    PlaceProviderResult,
    PlaceResultItem,
    StayProviderResult,
    StayResultItem,
    TransportProviderResult,
    TransportResultItem,
)
from src.domain.models.routing import RouteDecision, RouteReasonCode
from src.domain.models.state import TripState
from src.domain.models.trip_request import BudgetSemantics, BudgetSpec, TravelerProfile, TripRequest
from src.domain.models.value_objects import DateRange, GeoPoint, Money
from src.domain.services.schedule_service import ActivitySpec, OpeningWindow
from src.infrastructure.evidence.in_memory import InMemoryEvidenceRepository
from src.infrastructure.persistence.in_memory import InMemoryStateRepository
from src.ports.llm_gateway import LLMOutputMode
from src.ports.tool_errors import ToolEmptyResultError
from tests.support.clock_fakes import FakeClock
from tests.support.provider_fakes import (
    FakeContextProvider,
    FakePlaceProvider,
    FakeStayProvider,
    FakeTransportProvider,
)

_AS_OF = datetime(2026, 8, 6, 9, tzinfo=UTC)
_NATIVE_SOCKET = socket.socket


@contextmanager
def _event_loop_socket() -> object:
    """Allow asyncio's internal socketpair under the no-network test guard."""
    guarded_socket = socket.socket
    socket.socket = _NATIVE_SOCKET
    try:
        yield
    finally:
        socket.socket = guarded_socket


def _request() -> TripRequest:
    return TripRequest(
        request_id="request:m4-step10",
        trip_id="trip:m4-step10",
        session_id="session:m4-step10",
        origin="Shanghai",
        destinations=("Hangzhou",),
        date_range=DateRange(start="2026-08-10", end="2026-08-12"),
        travelers=TravelerProfile(adults=2),
        budget=BudgetSpec(
            semantics=BudgetSemantics.MAXIMUM,
            maximum=Money(amount=Decimal("3000"), currency="CNY"),
        ),
        locale="en-US",
        timezone="Asia/Shanghai",
    )


def _state() -> tuple[TripState, InMemoryStateRepository]:
    request = _request()
    from src.domain.models.constraint import ConstraintSnapshot

    state = TripState(
        trip_id=request.trip_id,
        session_id=request.session_id,
        status=WorkflowStatus.RESEARCHING,
        trip_request=request,
        constraint_snapshot=ConstraintSnapshot(
            version=1,
            created_at=_AS_OF,
            request_id=request.request_id,
        ),
    )
    repository = InMemoryStateRepository()
    repository.create(state)
    return state, repository


def _route(*capabilities: str) -> RouteDecision:
    return RouteDecision(
        mode=InteractionMode.PLAN.value,
        confidence=Decimal("1"),
        reason_codes=(RouteReasonCode.PLAN_REQUEST,),
        required_capabilities=capabilities,
    )


def _providers(*, transport_error: BaseException | None = None) -> ResearchProviders:
    transport_item = TransportProviderResult(
        query_id="provider-query:transport",
        provider="fake-transport",
        observed_at=_AS_OF,
        source_ref="source:transport",
        items=(
            TransportResultItem(
                entity_id="entity:transport",
                mode="rail",
                name="G123",
                origin="Shanghai",
                destination="Hangzhou",
                departure_at=datetime(2026, 8, 10, 8, tzinfo=UTC),
                arrival_at=datetime(2026, 8, 10, 9, tzinfo=UTC),
                total_price=Money(amount=Decimal("120"), currency="CNY"),
                source_ref="source:transport:item",
            ),
        ),
    )
    stay_item = StayProviderResult(
        query_id="provider-query:stay",
        provider="fake-stay",
        observed_at=_AS_OF,
        source_ref="source:stay",
        items=(
            StayResultItem(
                entity_id="entity:stay",
                name="Lake Hotel",
                area="West Lake",
                check_in=datetime(2026, 8, 10, 15, tzinfo=UTC),
                check_out=datetime(2026, 8, 12, 11, tzinfo=UTC),
                total_price=Money(amount=Decimal("900"), currency="CNY"),
                source_ref="source:stay:item",
            ),
        ),
    )
    place_item = PlaceProviderResult(
        query_id="provider-query:place",
        provider="fake-place",
        observed_at=_AS_OF,
        source_ref="source:place",
        items=(
            PlaceResultItem(
                entity_id="entity:place",
                name="West Lake",
                category="scenic",
                location=GeoPoint(latitude=30.25, longitude=120.13),
                address="West Lake Road",
                tags=("outdoor",),
                total_price=Money(amount=Decimal("200"), currency="CNY"),
                source_ref="source:place:item",
            ),
        ),
    )
    context_item = ContextResultItem(
        entity_id="entity:weather",
        context_type="weather",
        summary="Clear weather",
        valid_from=datetime(2026, 8, 10, tzinfo=UTC),
        valid_until=datetime(2026, 8, 12, 23, tzinfo=UTC),
        source_ref="source:weather:item",
    )
    transport_responses: list[object] = [transport_error or transport_item]
    return ResearchProviders(
        transport=FakeTransportProvider(transport_responses),
        stay=FakeStayProvider([stay_item]),
        place=FakePlaceProvider([place_item]),
        context=FakeContextProvider(
            [
                ContextProviderResult(
                    query_id="provider-query:context",
                    provider="fake-context",
                    observed_at=_AS_OF,
                    source_ref="source:context",
                    items=(context_item,),
                )
            ]
        ),
    )


class _PromptDrivenComposerGateway:
    """Generate a deterministic Fake LLM response from structured Composer data."""

    def __init__(self) -> None:
        self.calls: list[tuple[str, LLMOutputMode]] = []

    def complete(
        self,
        prompt: str,
        *,
        settings: object,
        output_mode: LLMOutputMode = LLMOutputMode.TEXT,
    ) -> str:
        del settings
        self.calls.append((prompt, output_mode))
        candidate_block = prompt.split("<CANDIDATE_DATA>\n", 1)[1].split("\n</CANDIDATE_DATA>", 1)[
            0
        ]
        candidates = json.loads(candidate_block)
        by_kind = {candidate["kind"]: candidate for candidate in candidates}
        selected = tuple(by_kind[kind] for kind in ("transport", "place", "stay"))

        def plan(variant: str, values: tuple[dict[str, object], ...]) -> dict[str, object]:
            refs = [value["candidate_id"] for value in values]
            evidence_refs = [
                evidence_ref for value in values for evidence_ref in value["evidence_refs"]
            ]
            return {
                "variant": variant,
                "title": f"{variant} fixture plan",
                "rationale": "all references come from the verified fixture",
                "day_skeleton": [
                    {
                        "day_number": index + 1,
                        "candidate_refs": [candidate["candidate_id"]],
                        "focus": f"day {index + 1}",
                    }
                    for index, candidate in enumerate(values)
                ],
                "selected_candidate_refs": refs,
                "constraint_refs": [],
                "evidence_refs": list(dict.fromkeys(evidence_refs)),
                "tradeoffs": ["deterministic fixture tradeoff"],
                "assumptions": [],
                "warnings": [],
            }

        return json.dumps(
            {
                "plans": (
                    plan("budget", selected[:1]),
                    plan("balanced", selected[:2]),
                    plan("comfort", selected[1:]),
                ),
                "reduction_reason": None,
            }
        )


class _DeterministicScheduleInputs:
    """Use explicit candidate evidence as fixture scheduling evidence."""

    def build(
        self,
        *,
        request: TripRequest,
        candidate_pool: object,
        evidence_snapshot: object,
        plan_candidate: object,
    ) -> ScheduleInputs:
        del request, evidence_snapshot
        candidates = {candidate.candidate_id: candidate for candidate in candidate_pool.candidates}
        activity_specs = tuple(
            ActivitySpec(
                candidate_id=candidate_id,
                duration_minutes=120,
                flex_buffer_minutes=15,
                evidence_refs=candidates[candidate_id].evidence_refs,
            )
            for candidate_id in plan_candidate.selected_candidate_refs
            if candidates[candidate_id].kind == "place"
        )
        opening_windows = tuple(
            OpeningWindow(
                candidate_id=candidate_id,
                day_number=2,
                opens_at=datetime(2026, 8, 11, 0, tzinfo=UTC),
                closes_at=datetime(2026, 8, 11, 14, tzinfo=UTC),
                evidence_refs=candidates[candidate_id].evidence_refs,
            )
            for candidate_id in plan_candidate.selected_candidate_refs
            if candidates[candidate_id].kind == "place"
        )
        return ScheduleInputs(
            opening_windows=opening_windows,
            activity_specs=activity_specs,
        )


def _workflow(
    *,
    transport_error: BaseException | None = None,
    budget_policy: BudgetPolicy | None = None,
) -> tuple[FakeProviderWorkflow, TripState, InMemoryStateRepository, _PromptDrivenComposerGateway]:
    state, state_repository = _state()
    evidence_repository = InMemoryEvidenceRepository(
        clock=FakeClock(_AS_OF),
        ttl_policy=EvidenceTtlPolicy(
            static_geography=timedelta(days=30),
            business_hours_policy=timedelta(days=1),
            weather_forecast=timedelta(days=1),
            transport_schedule=timedelta(days=1),
            quote_inventory=timedelta(days=1),
            exchange_rate=timedelta(days=1),
        ),
    )
    gateway = _PromptDrivenComposerGateway()
    from src.agents.itinerary_composer import ItineraryComposer
    from src.config import Settings

    workflow = FakeProviderWorkflow(
        state_repository=state_repository,
        evidence_repository=evidence_repository,
        providers=_providers(transport_error=transport_error),
        composer=ItineraryComposer(gateway, Settings()),
        schedule_input_builder=_DeterministicScheduleInputs(),
        budget_policy=budget_policy,
    )
    return workflow, state, state_repository, gateway


def _run(workflow: FakeProviderWorkflow, state: TripState, route: RouteDecision) -> object:
    with _event_loop_socket():
        return workflow.execute(
            state,
            route,
            trace_id="trace:m4-step10",
            as_of=_AS_OF,
            context_types=("weather",),
            place_category="scenic",
            plan_variant="balanced",
        )


def test_fake_provider_workflow_completes_research_to_budget_with_aligned_references() -> None:
    workflow, state, state_repository, gateway = _workflow()

    result = _run(workflow, state, _route("transport", "stay", "place", "context"))

    assert result.trace_id == "trace:m4-step10"
    assert result.orchestration.state.status is WorkflowStatus.DRAFTING
    assert state_repository.get(state.trip_id).status is WorkflowStatus.DRAFTING
    assert len(result.candidate_pool.candidates) == 3
    assert result.composition.plan_candidates[1].variant == "balanced"
    assert result.schedule.variant == "balanced"
    assert result.budget.budget_breakdown.total.amount == Decimal("320")
    assert result.budget.budget_breakdown.total.currency == "CNY"
    assert len(result.schedule.plan.items) == 2
    assert gateway.calls[0][1] is LLMOutputMode.JSON_OBJECT
    assert result.evidence_snapshot.coverage > Decimal("0")


def test_fake_provider_workflow_is_deterministic_for_same_fake_inputs() -> None:
    first_workflow, first_state, _, _ = _workflow()
    second_workflow, second_state, _, _ = _workflow()

    first = _run(first_workflow, first_state, _route("transport", "stay", "place", "context"))
    second = _run(second_workflow, second_state, _route("transport", "stay", "place", "context"))

    assert first.orchestration.graph == second.orchestration.graph
    assert first.candidate_pool == second.candidate_pool
    assert first.schedule.plan == second.schedule.plan
    assert first.budget == second.budget


def test_fake_provider_workflow_propagates_provider_empty_result_without_partial_success() -> None:
    empty_error = ToolEmptyResultError(
        provider="fake-transport",
        operation="transport_search",
        safe_message="no transport results",
        trace_id="trace:m4-step10",
        query_id="provider-query:transport",
    )
    workflow, state, state_repository, gateway = _workflow(transport_error=empty_error)

    with pytest.raises(WorkflowError) as caught:
        _run(workflow, state, _route("transport", "place"))

    assert caught.value.payload.code == "TOOL_EMPTY_RESULT_ERROR"
    assert caught.value.payload.category is ErrorCategory.TOOL
    assert state_repository.get(state.trip_id).status is WorkflowStatus.FAILED
    assert gateway.calls == []


def test_fake_provider_workflow_stops_on_unsupported_dependency_task() -> None:
    workflow, state, state_repository, gateway = _workflow()

    with pytest.raises(WorkflowError) as caught:
        _run(workflow, state, _route("geo", "transport"))

    assert caught.value.payload.code == "FAKE_PROVIDER_CAPABILITY_UNSUPPORTED"
    assert state_repository.get(state.trip_id).status is WorkflowStatus.FAILED
    assert gateway.calls == []


def test_fake_provider_workflow_fails_preflight_when_budget_is_exhausted() -> None:
    workflow, state, state_repository, gateway = _workflow(
        budget_policy=BudgetPolicy(max_total_tool_calls=0)
    )

    with pytest.raises(WorkflowError) as caught:
        _run(workflow, state, _route("transport", "stay", "place", "context"))

    assert caught.value.payload.code == "BUDGET_EXHAUSTED"
    assert caught.value.payload.category is ErrorCategory.BUDGET
    assert state_repository.get(state.trip_id).status is WorkflowStatus.FAILED
    assert gateway.calls == []


class _BlockingTransportProvider:
    """Record whether the Provider coroutine receives cancellation."""

    def __init__(self) -> None:
        self.started = asyncio.Event()
        self.cancelled = asyncio.Event()

    async def search(self, query: object, *, timeout_seconds: Decimal) -> object:
        del query, timeout_seconds
        self.started.set()
        try:
            await asyncio.Event().wait()
        except asyncio.CancelledError:
            self.cancelled.set()
            raise


async def _cancel_workflow() -> None:
    workflow, state, _, _ = _workflow()
    blocking = _BlockingTransportProvider()
    workflow._providers = ResearchProviders(
        transport=blocking,  # type: ignore[arg-type]
        stay=workflow._providers.stay,
        place=workflow._providers.place,
        context=workflow._providers.context,
    )

    with _event_loop_socket():
        running = asyncio.create_task(
            workflow.run(
                state,
                _route("transport"),
                trace_id="trace:m4-step10-cancel",
                as_of=_AS_OF,
            )
        )
        await blocking.started.wait()
        running.cancel()
        with pytest.raises(asyncio.CancelledError):
            await running

    assert blocking.cancelled.is_set()


def test_fake_provider_workflow_propagates_cancellation_to_provider() -> None:
    with _event_loop_socket():
        asyncio.run(_cancel_workflow())
