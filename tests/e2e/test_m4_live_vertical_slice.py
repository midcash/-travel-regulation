"""M4 Live Vertical Slice Gate; runs only when explicitly selected."""

from __future__ import annotations

import time
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal

import pytest

from src.application.fake_provider_workflow import FakeProviderWorkflowResult
from src.application.task_graph import TaskStatus
from src.application.use_cases.m4_plan import M4PlanUseCase
from src.bootstrap import bootstrap_settings
from src.config import Settings
from src.domain.models.constraint import Constraint, ConstraintSnapshot, ConstraintSource
from src.domain.models.enums import ConstraintHardness, InteractionMode, WorkflowStatus
from src.domain.models.routing import RouteDecision, RouteReasonCode
from src.domain.models.state import TripState
from src.domain.models.trip_request import BudgetSemantics, BudgetSpec, TravelerProfile, TripRequest
from src.domain.models.value_objects import DateRange, Money
from src.gateway import deepseek
from src.gateway.deepseek import LLMCallRecord
from src.infrastructure.persistence.in_memory import InMemoryStateRepository
from src.ports.llm_gateway import LLMOutputMode
from tests.support.m4_live_vertical_slice import (
    EXPECTED_RUNS,
    M4LiveObservation,
    build_report,
    write_report,
)

pytestmark = [pytest.mark.slow, pytest.mark.live_e2e]
_LIVE_BUDGET = Money(amount=Decimal("100000"), currency="CNY")


@dataclass(frozen=True, slots=True)
class _LiveCase:
    case_id: str
    origin: str
    destination: str
    adults: int
    preferences: tuple[str, ...]


_CASES = (
    _LiveCase("m4-live-normal", "Shanghai", "Beijing", 1, ("history", "moderate pace")),
    _LiveCase("m4-live-constraint", "Beijing", "Shanghai", 2, ("public transit", "budget control")),
    _LiveCase(
        "m4-live-complex",
        "Guangzhou",
        "Chengdu",
        2,
        ("city culture", "flexible pace", "avoid long sessions"),
    ),
)
_observations: list[M4LiveObservation] = []
_failure_summary: str | None = None
_report_model: str | None = None
_report_providers: tuple[str, ...] = ()


@pytest.fixture(scope="module", autouse=True)
def _write_live_report() -> None:
    """Write one redacted report after an explicitly selected live run."""
    yield
    write_report(
        build_report(
            tuple(_observations),
            exit_status=0 if _failure_summary is None else 1,
            configured_providers=_report_providers,
            model=_report_model,
            failure_summary=_failure_summary,
        )
    )


def test_m4_live_vertical_slice_uses_real_llm_and_provider(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Run three cases and repeat the normal case without Fake or fallback."""
    global _failure_summary, _report_model, _report_providers
    try:
        settings = bootstrap_settings()
    except Exception as exc:
        _failure_summary = type(exc).__name__
        pytest.fail("M4 Live Vertical Slice requires real LLM/tool credentials")
    if settings.workflow_use_case != "m4" or not settings.tuniu_api_key:
        _failure_summary = "ConfigurationError"
        pytest.fail("M4 Live Vertical Slice requires WORKFLOW_USE_CASE=m4 and TUNIU_API_KEY")

    _report_model = settings.deepseek_model
    _report_providers = ("tuniu",)
    original_ask_llm = deepseek.ask_llm
    llm_records: list[LLMCallRecord] = []

    def observed_ask_llm(
        prompt: str,
        active_settings: Settings,
        *,
        output_mode: LLMOutputMode = LLMOutputMode.TEXT,
    ) -> str:
        return original_ask_llm(
            prompt, active_settings, output_mode=output_mode, observer=llm_records.append
        )

    monkeypatch.setattr(deepseek, "ask_llm", observed_ask_llm)
    for case_id, repetition in EXPECTED_RUNS:
        case = next(item for item in _CASES if item.case_id == case_id)
        started = time.perf_counter()
        before_llm = len(llm_records)
        trace_id = f"m4-live:{case_id}:{repetition}"
        try:
            result, request, snapshot = _run_case(
                case, repetition=repetition, settings=settings, trace_id=trace_id
            )
            _observations.append(
                _assert_live_result(
                    result,
                    request=request,
                    snapshot=snapshot,
                    case_id=case_id,
                    repetition=repetition,
                    trace_id=trace_id,
                    model=settings.deepseek_model,
                    llm_records=tuple(llm_records[before_llm:]),
                    latency_ms=max(0, int((time.perf_counter() - started) * 1000)),
                )
            )
        except Exception as exc:
            _failure_summary = type(exc).__name__
            records = llm_records[before_llm:]
            _observations.append(
                M4LiveObservation(
                    case_id=case_id,
                    repetition=repetition,
                    status="failure",
                    trace_id=trace_id,
                    model=settings.deepseek_model,
                    providers=_report_providers,
                    llm_calls=len(records),
                    input_tokens=sum(item.input_tokens for item in records),
                    output_tokens=sum(item.output_tokens for item in records),
                    latency_ms=max(0, int((time.perf_counter() - started) * 1000)),
                    tool_calls=0,
                    model_calls=0,
                    graph_task_count=0,
                    candidate_count=0,
                    plan_count=0,
                    references_complete=False,
                    hard_constraints_complete=False,
                    hard_budget_within_limit=False,
                    failure_type=type(exc).__name__,
                )
            )
            raise


def _run_case(
    case: _LiveCase,
    *,
    repetition: int,
    settings: Settings,
    trace_id: str,
) -> tuple[FakeProviderWorkflowResult, TripRequest, ConstraintSnapshot]:
    start = date.today() + timedelta(days=30)
    end = start + timedelta(days=2)
    request = TripRequest(
        request_id=f"request:{case.case_id}:{repetition}",
        trip_id=f"trip:{case.case_id}:{repetition}",
        session_id=f"session:{case.case_id}:{repetition}",
        origin=case.origin,
        destinations=(case.destination,),
        date_range=DateRange(start=start, end=end),
        travelers=TravelerProfile(adults=case.adults),
        budget=BudgetSpec(semantics=BudgetSemantics.MAXIMUM, maximum=_LIVE_BUDGET),
        preferences=case.preferences,
        locale="en-US",
        timezone="Asia/Shanghai",
        requested_mode=InteractionMode.PLAN,
    )
    snapshot = ConstraintSnapshot(
        version=1,
        created_at=datetime.now(UTC),
        request_id=request.request_id,
        constraints=(
            Constraint(
                id=f"constraint:{case.case_id}:{repetition}:budget",
                category="budget_max",
                normalized_value=_LIVE_BUDGET,
                hardness=ConstraintHardness.HARD,
                priority=100,
                scope="trip",
                source=ConstraintSource.USER,
                confidence=Decimal("1"),
                user_confirmed=True,
            ),
            *(
                Constraint(
                    id=f"constraint:{case.case_id}:{repetition}:preference:{index}",
                    category="preference",
                    normalized_value=value,
                    hardness=ConstraintHardness.SOFT,
                    priority=10,
                    scope="trip",
                    source=ConstraintSource.USER,
                    confidence=Decimal("1"),
                    user_confirmed=True,
                )
                for index, value in enumerate(case.preferences)
            ),
        ),
    )
    state = TripState(
        trip_id=request.trip_id,
        session_id=request.session_id,
        status=WorkflowStatus.RESEARCHING,
        trip_request=request,
        constraint_snapshot=snapshot,
    )
    repository = InMemoryStateRepository()
    repository.create(state)
    use_case = M4PlanUseCase.from_settings(
        settings,
        state_repository=repository,
        plan_variant="balanced",
    )
    route = RouteDecision(
        mode=InteractionMode.PLAN.value,
        confidence=Decimal("1"),
        reason_codes=(RouteReasonCode.PLAN_REQUEST,),
        # The M4 live gate uses the Tuniu hotel capability as its stable
        # real-provider path. Flight and ticket endpoints are separate M3
        # contracts and may legitimately have no inventory or certificate
        # availability for a future-dated probe.
        required_capabilities=("stay",),
    )
    result = use_case.execute_routed(
        request,
        state=state,
        route_decision=route,
        constraint_snapshot=snapshot,
        raw_input=(
            f"{case.origin} to {case.destination} from {start.isoformat()} to {end.isoformat()}"
        ),
        trace_id=trace_id,
    )
    return result, request, snapshot


def _assert_live_result(
    result: FakeProviderWorkflowResult,
    *,
    request: TripRequest,
    snapshot: ConstraintSnapshot,
    case_id: str,
    repetition: int,
    trace_id: str,
    model: str,
    llm_records: tuple[LLMCallRecord, ...],
    latency_ms: int,
) -> M4LiveObservation:
    assert result.trace_id == trace_id
    assert result.orchestration.state.status is WorkflowStatus.DRAFTING
    assert result.orchestration.graph.tasks
    assert all(item.status is TaskStatus.SUCCEEDED for item in result.orchestration.task_results)
    assert result.evidence_snapshot.evidence_items
    assert result.candidate_pool.candidates
    assert not result.candidate_pool.deferred_hard_constraint_refs

    evidence_ids = {item.evidence_id for item in result.evidence_snapshot.evidence_items}
    candidate_ids = {item.candidate_id for item in result.candidate_pool.candidates}
    hard_ids = {item.id for item in snapshot.hard_constraints}
    references_complete = all(
        set(candidate.evidence_refs).issubset(evidence_ids)
        for candidate in result.candidate_pool.candidates
    ) and all(
        set(plan.selected_candidate_refs).issubset(candidate_ids)
        and set(plan.evidence_refs).issubset(evidence_ids)
        for plan in result.composition.plan_candidates
    )
    hard_constraints_complete = all(
        hard_ids.issubset(set(plan.constraint_refs)) for plan in result.composition.plan_candidates
    )
    assert references_complete
    assert hard_constraints_complete
    assert result.budget.budget_breakdown.total.amount <= _LIVE_BUDGET.amount
    assert result.budget.budget_breakdown.total.currency == _LIVE_BUDGET.currency
    assert result.orchestration.state.trip_id == request.trip_id
    assert len(llm_records) == 1

    return M4LiveObservation(
        case_id=case_id,
        repetition=repetition,
        status="success",
        trace_id=trace_id,
        model=model,
        providers=("tuniu",),
        llm_calls=len(llm_records),
        input_tokens=sum(item.input_tokens for item in llm_records),
        output_tokens=sum(item.output_tokens for item in llm_records),
        latency_ms=latency_ms,
        tool_calls=result.orchestration.budget.total_tool_calls,
        model_calls=result.orchestration.budget.total_model_calls,
        graph_task_count=len(result.orchestration.graph.tasks),
        candidate_count=len(result.candidate_pool.candidates),
        plan_count=len(result.composition.plan_candidates),
        references_complete=references_complete,
        hard_constraints_complete=hard_constraints_complete,
        hard_budget_within_limit=True,
    )
