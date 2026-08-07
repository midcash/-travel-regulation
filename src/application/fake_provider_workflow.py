"""M4 step ten: compose the deterministic Fake Provider vertical slice.

The workflow is intentionally an application composition root. It wires the
existing Orchestrator, Research Agents, Evidence Registry, Candidate Pool,
Composer, ScheduleService, and BudgetService without fallback behavior.
"""

from __future__ import annotations

import asyncio
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from typing import NoReturn, Protocol, Self

from pydantic import BaseModel, ConfigDict, Field, model_validator

from src.agents.itinerary_composer import ComposerContext, ComposerResult, PlanCandidate
from src.agents.research import (
    AgentBudget,
    AgentContext,
    AgentResult,
    CandidateDraft,
    ContextPolicyAgent,
    GeoResearchAgent,
    PlaceResearchAgent,
    StayResearchAgent,
    TransportResearchAgent,
)
from src.application.budget_policy import BudgetPolicy
from src.application.orchestrator import Orchestrator, OrchestratorResult, TaskRunContext
from src.application.task_graph import TaskGraph, TaskResult, TaskSpec, TaskStatus
from src.application.task_graph_builder import TaskGraphBuilder, TaskGraphValidator
from src.domain.errors import WorkflowError
from src.domain.models.candidates import (
    Candidate,
    CandidatePoolResult,
    CandidatePrice,
    PlaceCandidate,
    StayCandidate,
    TransportCandidate,
)
from src.domain.models.constraint import ConstraintSnapshot
from src.domain.models.enums import ErrorCategory, WorkflowStatus
from src.domain.models.evidence import (
    EvidenceItem,
    EvidenceSnapshot,
    EvidenceSnapshotQuery,
)
from src.domain.models.routing import RouteDecision
from src.domain.models.state import TripState
from src.domain.models.trip_request import TripRequest
from src.domain.models.value_objects import StableId, TraceId
from src.domain.services.budget_service import (
    BudgetContext,
    BudgetResult,
    BudgetService,
    ExchangeRate,
)
from src.domain.services.candidate_pool import CandidatePool
from src.domain.services.schedule_service import (
    ActivitySpec,
    OpeningWindow,
    RouteLeg,
    ScheduleContext,
    SchedulePolicy,
    ScheduleResult,
    ScheduleService,
)
from src.ports.evidence_repository import EvidenceRepository
from src.ports.state_repository import StateRepository
from src.ports.tool_provider import (
    ContextProvider,
    GeoProvider,
    PlaceProvider,
    StayProvider,
    TransportProvider,
)

_CONTEXT_CATEGORIES = frozenset(
    {"event", "events", "opening_hours", "policy", "weather", "holiday"}
)
_PLACE_CATEGORIES = frozenset(
    {
        "place",
        "place_category",
        "category",
        "scenic",
        "sightseeing",
        "attraction",
        "restaurant",
        "food",
    }
)


def _snapshot_context_types(snapshot: ConstraintSnapshot) -> tuple[str, ...]:
    """Extract only explicit context type constraints from the frozen snapshot."""
    values: set[str] = set()
    for constraint in snapshot.constraints:
        category = constraint.category.casefold()
        if category in {"context_type", "context_types"}:
            value = constraint.normalized_value
            if isinstance(value, str):
                values.add(value)
            elif isinstance(value, tuple):
                values.update(item for item in value if isinstance(item, str))
        elif category in _CONTEXT_CATEGORIES:
            values.add(category)
    return tuple(sorted(values))


def _snapshot_place_category(snapshot: ConstraintSnapshot) -> str | None:
    """Extract one explicit place category without inventing a default."""
    for constraint in snapshot.constraints:
        category = constraint.category.casefold()
        value = constraint.normalized_value
        if category in {"place_category", "category"} and isinstance(value, str):
            return value
        if category in _PLACE_CATEGORIES and category not in {"place", "category"}:
            return category
    return None


class ComposerPort(Protocol):
    """Compose verified candidates into plan skeletons."""

    def compose(self, context: ComposerContext) -> ComposerResult:
        """Return a validated Composer result."""


class ScheduleInputBuilder(Protocol):
    """Build typed timing inputs for ScheduleService."""

    def build(
        self,
        *,
        request: TripRequest,
        candidate_pool: CandidatePoolResult,
        evidence_snapshot: EvidenceSnapshot,
        plan_candidate: PlanCandidate,
    ) -> ScheduleInputs:
        """Return only deterministic scheduling inputs."""


@dataclass(frozen=True, slots=True)
class ResearchProviders:
    """Explicit provider ports used by the five M4 research agents."""

    geo: GeoProvider
    transport: TransportProvider
    stay: StayProvider
    place: PlaceProvider
    context: ContextProvider


class ScheduleInputs(BaseModel):
    """Typed boundary between plan composition and ScheduleService."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    opening_windows: tuple[OpeningWindow, ...] = ()
    activity_specs: tuple[ActivitySpec, ...] = ()
    route_legs: tuple[RouteLeg, ...] = ()
    policy: SchedulePolicy = Field(default_factory=SchedulePolicy)


class FakeProviderWorkflowResult(BaseModel):
    """Complete typed result of the M4 step-ten vertical slice."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    trace_id: TraceId
    orchestration: OrchestratorResult
    evidence_snapshot: EvidenceSnapshot
    candidate_pool: CandidatePoolResult
    composition: ComposerResult
    schedule: ScheduleResult
    budget: BudgetResult

    @model_validator(mode="after")
    def validate_chain_alignment(self) -> Self:
        """Ensure every stage points at the same snapshots and plan."""
        if self.trace_id != self.orchestration.trace_id:
            raise ValueError("workflow and orchestration trace IDs differ")
        if self.composition.trace_id != self.trace_id:
            raise ValueError("composer trace ID differs from workflow trace ID")
        if self.schedule.trace_id != self.trace_id:
            raise ValueError("schedule trace ID differs from workflow trace ID")
        if self.budget.trace_id != self.trace_id:
            raise ValueError("budget trace ID differs from workflow trace ID")
        if self.composition.evidence_snapshot_id != self.evidence_snapshot.snapshot_id:
            raise ValueError("composer consumed a different evidence snapshot")
        if self.candidate_pool.evidence_snapshot_id != self.evidence_snapshot.snapshot_id:
            raise ValueError("candidate pool consumed a different evidence snapshot")
        if self.schedule.plan_candidate_id != self.budget.plan_id:
            raise ValueError("budget result does not belong to scheduled plan")
        return self


class _FakeProviderTaskGraphBuilder:
    """Build a no-geo graph without the legacy geo dependency."""

    _templates = {
        "transport": ("transport_research", "CandidateDraft", 90.0, 6, 0),
        "stay": ("stay_research", "CandidateDraft", 90.0, 6, 0),
        "place": ("place_research", "CandidateDraft", 90.0, 6, 0),
        "context": ("context_research", "EvidenceDraft", 60.0, 4, 1),
    }

    def build(
        self,
        route_decision: RouteDecision,
        constraint_snapshot: ConstraintSnapshot,
        *,
        trip_id: StableId,
    ) -> TaskGraph | None:
        """Build a valid graph or delegate explicit geo routes."""
        if "geo" in route_decision.required_capabilities:
            return TaskGraphBuilder().build(
                route_decision,
                constraint_snapshot,
                trip_id=trip_id,
            )
        try:
            tasks = tuple(
                TaskSpec(
                    task_id=f"task-{capability}",
                    task_type=self._templates[capability][0],
                    capability=capability,
                    expected_output_type=self._templates[capability][1],
                    timeout=self._templates[capability][2],
                    tool_call_budget=self._templates[capability][3],
                    model_call_budget=self._templates[capability][4],
                )
                for capability in route_decision.required_capabilities
            )
        except KeyError as exc:
            raise WorkflowError(
                trace_id=f"graph:{trip_id}",
                stage="fake_provider_graph",
                category=ErrorCategory.VALIDATION,
                code="FAKE_PROVIDER_CAPABILITY_UNSUPPORTED",
                safe_message="fake provider workflow has no graph template for this capability",
                upstream_refs=(str(exc.args[0]),),
            ) from exc
        graph = TaskGraph(
            graph_id=f"graph-{trip_id}-{constraint_snapshot.version}-{route_decision.mode}",
            trip_id=trip_id,
            constraint_snapshot_id=(
                f"snapshot-{constraint_snapshot.request_id}-{constraint_snapshot.version}"
            ),
            tasks=tasks,
            graph_version=constraint_snapshot.version,
        )
        return TaskGraphValidator().validate(
            graph,
            route_decision,
            constraint_snapshot,
            trip_id=trip_id,
        )


class FakeProviderWorkflow:
    """Run the M4 research, composition, scheduling, and budget chain."""

    def __init__(
        self,
        *,
        state_repository: StateRepository,
        evidence_repository: EvidenceRepository,
        providers: ResearchProviders,
        composer: ComposerPort,
        schedule_input_builder: ScheduleInputBuilder,
        candidate_pool: CandidatePool | None = None,
        schedule_service: ScheduleService | None = None,
        budget_service: BudgetService | None = None,
        budget_policy: BudgetPolicy | None = None,
    ) -> None:
        self._state_repository = state_repository
        self._evidence_repository = evidence_repository
        self._providers = providers
        self._composer = composer
        self._schedule_input_builder = schedule_input_builder
        self._candidate_pool = candidate_pool or CandidatePool()
        self._schedule_service = schedule_service or ScheduleService()
        self._budget_service = budget_service or BudgetService()
        self._budget_policy = budget_policy or BudgetPolicy()

    def execute(
        self,
        state: TripState,
        route_decision: RouteDecision,
        *,
        trace_id: TraceId,
        as_of: datetime,
        plan_variant: str = "balanced",
        context_types: tuple[str, ...] = (),
        place_category: str | None = None,
        stay_area: str | None = None,
        target_currency: str | None = None,
        exchange_rates: tuple[ExchangeRate, ...] = (),
        contingency_rate: Decimal = Decimal("0"),
    ) -> FakeProviderWorkflowResult:
        """Execute the async workflow from a synchronous caller."""
        return asyncio.run(
            self.run(
                state,
                route_decision,
                trace_id=trace_id,
                as_of=as_of,
                plan_variant=plan_variant,
                context_types=context_types,
                place_category=place_category,
                stay_area=stay_area,
                target_currency=target_currency,
                exchange_rates=exchange_rates,
                contingency_rate=contingency_rate,
            )
        )

    async def run(
        self,
        state: TripState,
        route_decision: RouteDecision,
        *,
        trace_id: TraceId,
        as_of: datetime,
        plan_variant: str = "balanced",
        context_types: tuple[str, ...] = (),
        place_category: str | None = None,
        stay_area: str | None = None,
        target_currency: str | None = None,
        exchange_rates: tuple[ExchangeRate, ...] = (),
        contingency_rate: Decimal = Decimal("0"),
    ) -> FakeProviderWorkflowResult:
        """Execute one fail-fast vertical slice."""
        request, snapshot = self._require_planning_inputs(state, trace_id)
        runner = _ResearchTaskRunner(
            request=request,
            constraint_snapshot=snapshot,
            providers=self._providers,
            context_types=context_types,
            place_category=place_category,
            stay_area=stay_area,
        )
        orchestrator = Orchestrator(
            state_repository=self._state_repository,
            task_runner=runner,
            task_graph_builder=_FakeProviderTaskGraphBuilder(),
            budget_policy=self._budget_policy,
        )
        orchestration = await orchestrator.run(
            state,
            route_decision,
            trace_id=trace_id,
            constraint_snapshot=snapshot,
        )

        try:
            evidence_snapshot, candidate_pool = self._register_research_results(
                runner.results,
                trace_id=trace_id,
                constraint_snapshot=snapshot,
            )
            composition = self._composer.compose(
                ComposerContext(
                    trace_id=trace_id,
                    request=request,
                    constraint_snapshot=snapshot,
                    candidate_pool=candidate_pool,
                    evidence_snapshot=evidence_snapshot,
                    as_of=as_of,
                )
            )
            plan_candidate = _select_plan(composition, plan_variant, trace_id)
            schedule_inputs = self._schedule_input_builder.build(
                request=request,
                candidate_pool=candidate_pool,
                evidence_snapshot=evidence_snapshot,
                plan_candidate=plan_candidate,
            )
            if not isinstance(schedule_inputs, ScheduleInputs):
                raise TypeError("schedule input builder must return ScheduleInputs")
            schedule = self._schedule_service.schedule(
                ScheduleContext(
                    trace_id=trace_id,
                    as_of=as_of,
                    request=request,
                    constraint_snapshot_version=snapshot.version,
                    evidence_snapshot_id=evidence_snapshot.snapshot_id,
                    candidate_pool=candidate_pool,
                    evidence_snapshot=evidence_snapshot,
                    plan_candidate=plan_candidate,
                    opening_windows=schedule_inputs.opening_windows,
                    activity_specs=schedule_inputs.activity_specs,
                    route_legs=schedule_inputs.route_legs,
                    policy=schedule_inputs.policy,
                )
            )
            budget = self._budget_service.calculate(
                BudgetContext(
                    trace_id=trace_id,
                    as_of=as_of,
                    request=request,
                    candidate_pool=candidate_pool,
                    evidence_snapshot=evidence_snapshot,
                    schedule_result=schedule,
                    target_currency=target_currency,
                    exchange_rates=exchange_rates,
                    contingency_rate=contingency_rate,
                )
            )
        except WorkflowError as exc:
            self._persist_downstream_failure(orchestration.state, exc)
            raise
        except Exception as exc:
            failure = WorkflowError(
                trace_id=trace_id,
                stage="fake_provider_workflow",
                category=ErrorCategory.VALIDATION,
                code="FAKE_PROVIDER_WORKFLOW_FAILED",
                safe_message="fake provider workflow failed",
                cause=exc,
            )
            self._persist_downstream_failure(orchestration.state, failure)
            raise failure from exc

        return FakeProviderWorkflowResult(
            trace_id=trace_id,
            orchestration=orchestration,
            evidence_snapshot=evidence_snapshot,
            candidate_pool=candidate_pool,
            composition=composition,
            schedule=schedule,
            budget=budget,
        )

    def _register_research_results(
        self,
        results: Mapping[StableId, AgentResult],
        *,
        trace_id: TraceId,
        constraint_snapshot: ConstraintSnapshot,
    ) -> tuple[EvidenceSnapshot, CandidatePoolResult]:
        """Persist drafts and create one candidate pool snapshot."""
        evidence_by_draft: dict[StableId, EvidenceItem] = {}
        for task_id in sorted(results):
            result = results[task_id]
            for draft in result.evidence_drafts:
                if draft.draft_id in evidence_by_draft:
                    _raise_workflow_error(
                        trace_id,
                        "FAKE_PROVIDER_DUPLICATE_EVIDENCE_DRAFT",
                        "research results contain a duplicate evidence draft",
                        category=ErrorCategory.EVIDENCE,
                        upstream_refs=(draft.draft_id,),
                    )
                evidence_by_draft[draft.draft_id] = self._evidence_repository.register(
                    draft.registration
                )

        evidence_snapshot = self._evidence_repository.snapshot(EvidenceSnapshotQuery())
        candidates = tuple(
            _materialize_candidate(
                draft,
                evidence_by_draft,
                trace_id=trace_id,
            )
            for task_id in sorted(results)
            for draft in results[task_id].candidate_drafts
        )
        candidate_pool = self._candidate_pool.build(
            candidates,
            evidence_snapshot=evidence_snapshot,
            constraint_snapshot=constraint_snapshot,
        )
        return evidence_snapshot, candidate_pool

    def _require_planning_inputs(
        self,
        state: TripState,
        trace_id: TraceId,
    ) -> tuple[TripRequest, ConstraintSnapshot]:
        """Require the exact request and frozen constraint snapshot."""
        request = state.trip_request
        snapshot = state.constraint_snapshot
        if request is None or snapshot is None:
            failure = WorkflowError(
                trace_id=trace_id,
                stage="fake_provider_workflow",
                category=ErrorCategory.VALIDATION,
                code="FAKE_PROVIDER_INPUT_INVALID",
                safe_message="fake provider workflow requires a request and constraint snapshot",
                upstream_refs=(state.trip_id,),
            )
            self._persist_downstream_failure(state, failure)
            raise failure
        return request, snapshot

    def _persist_downstream_failure(
        self,
        state: TripState,
        failure: WorkflowError,
    ) -> None:
        """Persist a downstream failure without hiding state errors."""
        if state.status is WorkflowStatus.FAILED:
            return
        if not state.can_transition_to(WorkflowStatus.FAILED):
            raise WorkflowError(
                trace_id=failure.trace_id,
                stage="state_persistence",
                category=ErrorCategory.STATE_CONFLICT,
                code="FAKE_PROVIDER_FAILED_STATE_TRANSITION_INVALID",
                safe_message="workflow failure cannot be persisted from the current state",
                upstream_refs=(state.trip_id,),
                cause=failure,
            ) from failure
        failed = state.transition_to(WorkflowStatus.FAILED).model_copy(
            update={"last_error": failure.public_payload()}
        )
        self._state_repository.save(failed, expected_version=state.version)


class _ResearchTaskRunner:
    """Map graph task capabilities to isolated Research Agents."""

    def __init__(
        self,
        *,
        request: TripRequest,
        constraint_snapshot: ConstraintSnapshot,
        providers: ResearchProviders,
        context_types: tuple[str, ...],
        place_category: str | None,
        stay_area: str | None,
    ) -> None:
        self._request = request
        self._constraint_snapshot = constraint_snapshot
        self._context_types = context_types or _snapshot_context_types(constraint_snapshot)
        self._place_category = place_category or _snapshot_place_category(constraint_snapshot)
        self._stay_area = stay_area
        self._agents: Mapping[str, object] = {
            "geo": GeoResearchAgent(providers.geo),
            "transport": TransportResearchAgent(providers.transport),
            "stay": StayResearchAgent(providers.stay),
            "place": PlaceResearchAgent(providers.place),
            "context": ContextPolicyAgent(providers.context),
        }
        self._results: dict[StableId, AgentResult] = {}

    @property
    def results(self) -> Mapping[StableId, AgentResult]:
        """Expose completed AgentResults in stable task order."""
        return dict(self._results)

    async def run(self, context: TaskRunContext) -> TaskResult:
        """Run one Research Agent task without calling another agent."""
        agent = self._agents.get(context.task_spec.capability)
        if agent is None:
            raise WorkflowError(
                trace_id=context.trace_id,
                stage="fake_provider_research",
                category=ErrorCategory.VALIDATION,
                code="FAKE_PROVIDER_CAPABILITY_UNSUPPORTED",
                safe_message="fake provider workflow has no agent for this capability",
                upstream_refs=(context.task_spec.task_id,),
            )
        agent_context = AgentContext(
            trace_id=context.trace_id,
            task_spec=context.task_spec,
            constraint_snapshot_ref=(
                f"snapshot-{self._request.request_id}-{self._constraint_snapshot.version}"
            ),
            request=self._request,
            constraint_snapshot=self._constraint_snapshot,
            allowed_tools=(_tool_name(context.task_spec.capability),),
            prior_evidence_refs=context.prior_evidence_refs,
            prior_candidate_refs=context.prior_candidate_refs,
            budget=AgentBudget(
                max_tool_calls=context.task_spec.tool_call_budget,
                max_model_calls=context.task_spec.model_call_budget,
                timeout_seconds=Decimal(str(context.task_spec.timeout)),
                max_results=20,
            ),
            locale=self._request.locale,
            timezone=self._request.timezone,
            context_types=self._context_types,
            place_category=self._place_category,
            stay_area=self._stay_area,
        )
        result = await agent.run(agent_context)  # type: ignore[union-attr]
        self._results[context.task_spec.task_id] = result
        return TaskResult(
            task_id=context.task_spec.task_id,
            status=TaskStatus.SUCCEEDED,
            output_ref=f"agent-result:{context.task_spec.task_id}",
            evidence_refs=tuple(draft.draft_id for draft in result.evidence_drafts),
            candidate_refs=tuple(draft.candidate_id for draft in result.candidate_drafts),
            metrics=result.metrics,
        )


def _tool_name(capability: str) -> str:
    """Map a graph capability to the provider tool allowlist."""
    return {
        "geo": "geo_search",
        "transport": "transport_search",
        "stay": "stay_search",
        "place": "place_search",
        "context": "context_search",
    }.get(capability, f"{capability}_search")


def _materialize_candidate(
    draft: CandidateDraft,
    evidence_by_draft: Mapping[StableId, EvidenceItem],
    *,
    trace_id: TraceId,
) -> Candidate:
    """Convert an Agent CandidateDraft into a domain Candidate."""
    missing = tuple(ref for ref in draft.evidence_draft_refs if ref not in evidence_by_draft)
    if missing:
        _raise_workflow_error(
            trace_id,
            "FAKE_PROVIDER_EVIDENCE_DRAFT_MISSING",
            "candidate draft references unknown evidence",
            category=ErrorCategory.EVIDENCE,
            upstream_refs=missing,
        )
    evidence_refs = tuple(evidence_by_draft[ref].evidence_id for ref in draft.evidence_draft_refs)
    price = None
    if draft.price is not None:
        if draft.price_evidence_draft_ref is None:
            _raise_workflow_error(
                trace_id,
                "FAKE_PROVIDER_PRICE_EVIDENCE_MISSING",
                "priced candidate is missing price evidence",
                category=ErrorCategory.EVIDENCE,
                upstream_refs=(draft.candidate_id,),
            )
        if draft.price_evidence_draft_ref not in evidence_by_draft:
            _raise_workflow_error(
                trace_id,
                "FAKE_PROVIDER_PRICE_EVIDENCE_DRAFT_MISSING",
                "candidate price references unknown evidence",
                category=ErrorCategory.EVIDENCE,
                upstream_refs=(draft.candidate_id, draft.price_evidence_draft_ref),
            )
        price = CandidatePrice(
            total=draft.price,
            evidence_refs=(evidence_by_draft[draft.price_evidence_draft_ref].evidence_id,),
        )

    common = {
        "candidate_id": draft.candidate_id,
        "name": draft.name,
        "evidence_refs": evidence_refs,
        "provenance": draft.provenance,
        "timezone": draft.timezone,
        "tags": draft.tags,
        "location": draft.location,
        "price": price,
    }
    if draft.kind == "transport":
        return TransportCandidate(
            **common,
            mode=draft.mode,
            origin=draft.origin,
            destination=draft.destination,
            departure_at=draft.departure_at,
            arrival_at=draft.arrival_at,
        )
    if draft.kind == "stay":
        return StayCandidate(
            **common,
            area=draft.area,
            check_in=draft.check_in,
            check_out=draft.check_out,
        )
    if draft.kind == "place":
        return PlaceCandidate(
            **common,
            category=draft.category,
            address=draft.address,
        )
    raise ValueError("unsupported candidate draft kind")


def _select_plan(
    composition: ComposerResult,
    variant: str,
    trace_id: TraceId,
) -> PlanCandidate:
    """Select one explicitly requested plan variant."""
    for plan in composition.plan_candidates:
        if plan.variant == variant:
            return plan
    _raise_workflow_error(
        trace_id,
        "FAKE_PROVIDER_PLAN_VARIANT_MISSING",
        "requested plan variant is not present in Composer output",
        category=ErrorCategory.VALIDATION,
    )


def _raise_workflow_error(
    trace_id: TraceId,
    code: str,
    safe_message: str,
    *,
    category: ErrorCategory,
    upstream_refs: tuple[StableId, ...] = (),
) -> NoReturn:
    """Raise one safe, structured workflow failure."""
    raise WorkflowError(
        trace_id=trace_id,
        stage="fake_provider_workflow",
        category=category,
        code=code,
        safe_message=safe_message,
        upstream_refs=upstream_refs,
    )


__all__ = [
    "ComposerPort",
    "FakeProviderWorkflow",
    "FakeProviderWorkflowResult",
    "ResearchProviders",
    "ScheduleInputBuilder",
    "ScheduleInputs",
]
