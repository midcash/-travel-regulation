from __future__ import annotations

import hashlib
import json
import socket
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timedelta
from decimal import Decimal
from pathlib import Path
from typing import Any, cast

from evaluation.business_travel.contracts import (
    AgentEvalCase,
    BusinessAssertion,
    ComponentAvailability,
    FailureCategory,
    FirstFailedStage,
    RunStatus,
)
from evaluation.business_travel.registry import BusinessTravelCaseRegistry
from evaluation.business_travel.scoring import score_case
from evaluation.business_travel.semantic_use_case import SemanticEvaluationResult
from src.agents.itinerary_composer import ItineraryComposer, PlanCandidate
from src.application.fake_provider_workflow import (
    FakeProviderWorkflow,
    FakeProviderWorkflowResult,
    ResearchProviders,
    ScheduleInputs,
)
from src.application.interaction_facade import TripInteractionFacade, TripInteractionResult
from src.application.use_cases.m4_plan import M4PlanUseCase
from src.config import Settings
from src.domain.models.candidates import CandidatePoolResult
from src.domain.models.enums import InteractionMode
from src.domain.models.evidence import EvidenceSnapshot, EvidenceTtlPolicy
from src.domain.models.provider import (
    GeoProviderResult,
    GeoResultItem,
    StayProviderResult,
    StayResultItem,
    TransportProviderResult,
    TransportResultItem,
)
from src.domain.models.trip_request import (
    BudgetSemantics,
    BudgetSpec,
    TravelerProfile,
    TripRequest,
)
from src.domain.models.value_objects import DateRange, GeoPoint, Money
from src.domain.services.schedule_service import RouteLeg
from src.infrastructure.evidence.in_memory import InMemoryEvidenceRepository
from src.infrastructure.persistence.in_memory import InMemoryStateRepository
from src.ports.llm_gateway import LLMOutputMode
from src.ports.tool_provider import (
    ContextProvider,
    GeoProvider,
    PlaceProvider,
    StayProvider,
    TransportProvider,
)

_NATIVE_SOCKET = socket.socket


@contextmanager
def _event_loop_socket() -> Iterator[None]:
    """为离线异步编排恢复 asyncio socketpair，不放开外部网络。"""
    guarded_socket = socket.socket
    setattr(socket, "socket", _NATIVE_SOCKET)  # noqa: B010
    try:
        yield
    finally:
        setattr(socket, "socket", guarded_socket)  # noqa: B010


class _DeterministicInterpreterGateway:
    """用于离线语义链的显式 Fake；没有默认响应队列或网络行为。"""

    def complete(
        self,
        prompt: str,
        *,
        settings: Settings,
        output_mode: LLMOutputMode = LLMOutputMode.TEXT,
    ) -> str:
        del prompt, settings, output_mode
        return (
            '{"mode_hint":"plan","extracted_entities":[],"constraint_candidates":['
            '{"category":"origin","value":"Shanghai","hardness":"hard",'
            '"scope":"trip","confidence":0.95},{"category":"destination",'
            '"value":"Hangzhou","hardness":"hard","scope":"trip",'
            '"confidence":0.95},{"category":"date_range","value":"2026-08-13",'
            '"hardness":"hard","scope":"trip","confidence":0.95},'
            '{"category":"travelers","value":1,"hardness":"hard",'
            '"scope":"trip","confidence":0.95}],"explicit_questions":[],'
            '"references_to_current_plan":[],"field_confidence":{},'
            '"overall_confidence":0.95,"safety_flags":[]}'
        )


class _FixedClock:
    def __init__(self, current: datetime) -> None:
        self._current = current

    def now(self) -> datetime:
        return self._current


class _ExplicitProvider:
    def __init__(self, responses: tuple[object, ...]) -> None:
        self._responses = list(responses)
        self.calls = 0

    async def search(self, query: object, *, timeout_seconds: Decimal) -> object:
        del query, timeout_seconds
        self.calls += 1
        if not self._responses:
            raise RuntimeError("offline fixture provider response exhausted")
        response = self._responses.pop(0)
        if isinstance(response, BaseException):
            raise response
        return response


class _ComposerGateway:
    """根据 Composer 已验证候选生成结构化、可重复的三种方案。"""

    def complete(
        self,
        prompt: str,
        *,
        settings: Settings,
        output_mode: LLMOutputMode = LLMOutputMode.TEXT,
    ) -> str:
        del settings, output_mode
        block = prompt.split("<CANDIDATE_DATA>\n", 1)[1].split("\n</CANDIDATE_DATA>", 1)[0]
        candidates = json.loads(block)
        constraint_block = prompt.split("<CONSTRAINT_DATA>\n", 1)[1].split(
            "\n</CONSTRAINT_DATA>", 1
        )[0]
        constraint_refs = [item["id"] for item in json.loads(constraint_block)]
        selected = tuple(
            sorted(
                candidates[:3],
                key=lambda value: (
                    value.get("departure_at", ""),
                    value["candidate_id"],
                ),
            )
        )
        if len(selected) < 2:
            raise RuntimeError("offline fixture must provide two candidates")

        def plan(variant: str, values: tuple[dict[str, Any], ...]) -> dict[str, Any]:
            refs = [value["candidate_id"] for value in values]
            evidence = list(
                dict.fromkeys(ref for value in values for ref in value["evidence_refs"])
            )
            return {
                "variant": variant,
                "title": f"offline {variant}",
                "rationale": "selected from explicit offline fixture evidence",
                "day_skeleton": [
                    {
                        "day_number": 1,
                        "candidate_refs": [value["candidate_id"] for value in values],
                        "focus": "meeting arrival day",
                    }
                ],
                "selected_candidate_refs": refs,
                "constraint_refs": constraint_refs,
                "evidence_refs": evidence,
                "tradeoffs": ["fixture tradeoff"],
                "assumptions": [],
                "warnings": [],
            }

        return json.dumps(
            {
                "plans": (
                    plan("budget", selected[:1]),
                    plan("balanced", selected[:2]),
                    plan("comfort", selected),
                ),
                "reduction_reason": None,
            }
        )


class _NoopProvider:
    async def search(self, query: object, *, timeout_seconds: Decimal) -> object:
        del query, timeout_seconds
        raise RuntimeError("offline fixture capability was not configured")


class _ScheduleBuilder:
    def build(
        self,
        *,
        request: TripRequest,
        candidate_pool: CandidatePoolResult,
        evidence_snapshot: EvidenceSnapshot,
        plan_candidate: PlanCandidate,
    ) -> ScheduleInputs:
        del request, evidence_snapshot
        candidates = {candidate.candidate_id: candidate for candidate in candidate_pool.candidates}
        selected = tuple(plan_candidate.selected_candidate_refs)
        route_legs = tuple(
            RouteLeg(
                from_candidate_id=from_id,
                to_candidate_id=to_id,
                duration_minutes=0,
                transfer_buffer_minutes=0,
                transfer_count=0,
                evidence_refs=(candidates[from_id].evidence_refs[0],),
            )
            for from_id, to_id in zip(selected, selected[1:], strict=False)
        )
        return ScheduleInputs(route_legs=route_legs)


@dataclass(frozen=True, slots=True)
class OfflineCaseResult:
    case_id: str
    passed: bool
    first_failed_stage: FirstFailedStage | None
    run_status: str
    component_availability: ComponentAvailability
    business_assertion: BusinessAssertion
    failure_category: FailureCategory | None
    evaluator_error: str | None
    metrics: tuple[tuple[str, str], ...]


@dataclass(frozen=True, slots=True)
class OfflineBaselineResult:
    dataset_path: str
    dataset_hash: str
    run_status: str
    case_results: tuple[OfflineCaseResult, ...]
    runner_kind: str = "component"


def _file_hash(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _request(case_id: str, when: datetime) -> TripRequest:
    date_value = when.date() + timedelta(days=1)
    return TripRequest(
        request_id=f"offline-request-{case_id}",
        trip_id=f"offline-trip-{case_id}",
        session_id=f"offline-session-{case_id}",
        origin="Shanghai",
        destinations=("Hangzhou",),
        date_range=DateRange(start=date_value, end=date_value),
        travelers=TravelerProfile(adults=1),
        budget=BudgetSpec(
            semantics=BudgetSemantics.MAXIMUM,
            maximum=Money(amount=Decimal("3000"), currency="CNY"),
        ),
        requested_mode=InteractionMode.PLAN,
    )


def _predicted_semantic(
    result: SemanticEvaluationResult | TripInteractionResult,
) -> dict[str, Any]:
    route = result.route_decision
    blockers = tuple(blocker.field for blocker in result.readiness.blockers)
    return {
        "mode": route.mode,
        "clarification_fields": blockers,
        "scope": (),
        "capabilities": route.required_capabilities,
        "lodging": "not_required",
        "recommendation_evidence_types": (),
        "forbidden_outputs": (),
    }


def _score_result(
    case: AgentEvalCase, predicted: dict[str, Any], *, kind: str
) -> OfflineCaseResult:
    availability = (
        ComponentAvailability.IMPLEMENTED
        if kind == "integration"
        else ComponentAvailability.NOT_IMPLEMENTED_IN_BASELINE
    )
    result = score_case(
        {
            "predicted": predicted,
            "component_availability": availability.value,
            "run_status": RunStatus.COMPLETED.value,
            "failure_category": FailureCategory.BUSINESS.value,
        },
        case,
    )
    return OfflineCaseResult(
        case_id=case.case_id,
        passed=result.business_assertion is BusinessAssertion.PASS,
        first_failed_stage=result.first_failed_stage,
        run_status=result.run_status.value,
        component_availability=result.component_availability,
        business_assertion=result.business_assertion,
        failure_category=result.failure_category,
        evaluator_error=None,
        metrics=tuple(
            (name, "not_scored" if value is None else str(value))
            for name, value in sorted(result.metric_values.items())
        ),
    )


def _run_component_case(case: AgentEvalCase) -> OfflineCaseResult:
    try:
        when = case.fixed_now
        request = _request(case.case_id, when)
        from evaluation.business_travel.semantic_use_case import SemanticEvaluationUseCase

        result = SemanticEvaluationUseCase(
            Settings(deepseek_api_key="offline-eval", deepseek_model="offline-eval"),
            gateway=_DeterministicInterpreterGateway(),
        ).execute(request, case.input_text, reference_date=when.date())
        return _score_result(case, _predicted_semantic(result), kind="component")
    except Exception as exc:
        return OfflineCaseResult(
            case_id=case.case_id,
            passed=False,
            first_failed_stage=FirstFailedStage.EVALUATOR,
            run_status=RunStatus.EVALUATOR_ERROR.value,
            component_availability=ComponentAvailability.IMPLEMENTED,
            business_assertion=BusinessAssertion.NOT_SCORABLE,
            failure_category=FailureCategory.EVALUATOR,
            evaluator_error=type(exc).__name__,
            metrics=(),
        )


def _providers(when: datetime) -> ResearchProviders:
    service_day = when + timedelta(days=1)
    transport_items = tuple(
        TransportResultItem(
            entity_id=f"offline-transport-{index}",
            mode="rail",
            name=f"G{index}",
            origin="Shanghai",
            destination="Hangzhou",
            departure_at=service_day + timedelta(hours=1 + index * 3),
            arrival_at=service_day + timedelta(hours=2 + index * 3),
            total_price=Money(amount=Decimal(str(100 + index * 20)), currency="CNY"),
            source_ref=f"fixture:transport:{index}",
        )
        for index in range(3)
    )
    transport = TransportProviderResult(
        query_id="offline-query-transport",
        provider="offline-fixture",
        observed_at=when,
        source_ref="fixture:transport",
        items=transport_items,
    )
    stay = StayProviderResult(
        query_id="offline-query-stay",
        provider="offline-fixture",
        observed_at=when,
        source_ref="fixture:stay",
        items=(
            StayResultItem(
                entity_id="offline-stay",
                name="Offline Hotel",
                area="Hangzhou East",
                location=GeoPoint(latitude=30.27, longitude=120.15),
                check_in=service_day + timedelta(hours=15),
                check_out=service_day + timedelta(days=1, hours=11),
                total_price=Money(amount=Decimal("500"), currency="CNY"),
                source_ref="fixture:stay:item",
            ),
        ),
    )
    geo = GeoProviderResult(
        query_id="offline-query-geo",
        provider="offline-fixture",
        observed_at=when,
        source_ref="fixture:geo",
        items=(
            GeoResultItem(
                entity_id="offline-geo",
                name="Shanghai-Hangzhou",
                location=GeoPoint(latitude=30.27, longitude=120.15),
                address="Hangzhou East",
                confidence=Decimal("1"),
            ),
        ),
    )
    return ResearchProviders(
        geo=cast(GeoProvider, _ExplicitProvider((geo, geo))),
        transport=cast(TransportProvider, _ExplicitProvider((transport,))),
        stay=cast(StayProvider, _ExplicitProvider((stay,))),
        place=cast(PlaceProvider, _NoopProvider()),
        context=cast(ContextProvider, _NoopProvider()),
    )


def _workflow(
    request: TripRequest, when: datetime
) -> tuple[M4PlanUseCase, InMemoryStateRepository]:
    repository = InMemoryStateRepository()
    evidence = InMemoryEvidenceRepository(
        clock=_FixedClock(when),
        ttl_policy=EvidenceTtlPolicy(
            static_geography=timedelta(days=30),
            business_hours_policy=timedelta(days=1),
            weather_forecast=timedelta(days=1),
            transport_schedule=timedelta(days=1),
            quote_inventory=timedelta(days=1),
            exchange_rate=timedelta(days=1),
        ),
    )
    workflow = FakeProviderWorkflow(
        state_repository=repository,
        evidence_repository=evidence,
        providers=_providers(when),
        composer=ItineraryComposer(_ComposerGateway(), Settings(deepseek_api_key="offline-eval")),
        schedule_input_builder=_ScheduleBuilder(),
    )
    return (
        M4PlanUseCase(
            Settings(deepseek_api_key="offline-eval"),
            state_repository=repository,
            workflow=workflow,
            clock=_FixedClock(when),
        ),
        repository,
    )


def _run_integration_case(case: AgentEvalCase) -> OfflineCaseResult:
    try:
        when = case.fixed_now
        request = _request(case.case_id, when)
        planner, repository = _workflow(request, when)
        facade = TripInteractionFacade(
            Settings(deepseek_api_key="offline-eval", deepseek_model="offline-eval"),
            planner=planner,
            gateway=_DeterministicInterpreterGateway(),
            state_repository=repository,
            clock=_FixedClock(when),
        )
        with _event_loop_socket():
            result = facade.execute(request, case.input_text, reference_date=when.date())
        predicted = _predicted_semantic(result)
        plan_result = result.plan_result
        if isinstance(plan_result, FakeProviderWorkflowResult):
            predicted["alternatives"] = [
                {"plan": plan.variant, "selected": plan.selected_candidate_refs}
                for plan in plan_result.composition.plan_candidates
            ]
            predicted["recommendation_evidence_types"] = tuple(
                sorted(
                    {
                        "lodging_quote" if candidate.kind == "stay" else "transport_quote"
                        for candidate in plan_result.candidate_pool.candidates
                        if candidate.kind in {"stay", "transport"}
                    }
                )
            )
            predicted["lodging"] = (
                "required"
                if any(
                    candidate.kind == "stay"
                    for candidate in plan_result.candidate_pool.candidates
                )
                else "not_required"
            )
        return _score_result(case, predicted, kind="integration")
    except Exception as exc:
        return OfflineCaseResult(
            case_id=case.case_id,
            passed=False,
            first_failed_stage=FirstFailedStage.EVALUATOR,
            run_status=RunStatus.EVALUATOR_ERROR.value,
            component_availability=ComponentAvailability.IMPLEMENTED,
            business_assertion=BusinessAssertion.NOT_SCORABLE,
            failure_category=FailureCategory.EVALUATOR,
            evaluator_error=type(exc).__name__,
            metrics=(),
        )


def _run(
    path: Path,
    case_runner: Callable[[AgentEvalCase], OfflineCaseResult],
    kind: str,
) -> OfflineBaselineResult:
    registry = BusinessTravelCaseRegistry.load(path)
    return OfflineBaselineResult(
        dataset_path=str(path),
        dataset_hash=_file_hash(path),
        run_status=RunStatus.COMPLETED.value,
        case_results=tuple(case_runner(case) for case in registry.cases),
        runner_kind=kind,
    )


def run_offline_baseline(path: Path) -> OfflineBaselineResult:
    """运行真实 M4.1 Component Baseline 的公开语义组件链。"""
    return _run(path, _run_component_case, "component")


def run_offline_integration(path: Path) -> OfflineBaselineResult:
    """通过 TripInteractionFacade 与 M4PlanUseCase 执行离线集成基线。"""
    return _run(path, _run_integration_case, "integration")


def normalized_result_hash(result: OfflineBaselineResult) -> str:
    """排除运行标识后对业务结果计算稳定 hash。"""
    payload: dict[str, Any] = {
        "dataset_hash": result.dataset_hash,
        "run_status": result.run_status,
        "runner_kind": result.runner_kind,
        "case_results": [
            {
                "case_id": item.case_id,
                "passed": item.passed,
                "first_failed_stage": (
                    item.first_failed_stage.value if item.first_failed_stage is not None else None
                ),
                "run_status": item.run_status,
                "component_availability": item.component_availability.value,
                "business_assertion": item.business_assertion.value,
                "failure_category": (
                    item.failure_category.value if item.failure_category is not None else None
                ),
                "metrics": item.metrics,
            }
            for item in result.case_results
        ],
    }
    encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()
