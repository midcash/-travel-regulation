"""M4 规划 Use Case 与 CLI 组合根适配。"""

from __future__ import annotations

import asyncio
from datetime import timedelta
from decimal import Decimal
from typing import NoReturn

from src.agents.itinerary_composer import ItineraryComposer, PlanCandidate
from src.application.fake_provider_workflow import (
    FakeProviderWorkflow,
    FakeProviderWorkflowResult,
    ResearchProviders,
    ScheduleInputBuilder,
    ScheduleInputs,
)
from src.config import Settings
from src.domain.errors import WorkflowError
from src.domain.models.candidates import CandidatePoolResult, PlaceCandidate
from src.domain.models.constraint import ConstraintSnapshot
from src.domain.models.enums import ErrorCategory
from src.domain.models.evidence import EvidenceSnapshot, EvidenceTtlPolicy
from src.domain.models.routing import RouteDecision
from src.domain.models.state import TripState
from src.domain.models.trip_request import TripRequest
from src.domain.models.value_objects import TraceId
from src.domain.services.schedule_service import ActivitySpec
from src.gateway.deepseek_adapter import DeepSeekLLMGateway
from src.infrastructure.evidence.in_memory import InMemoryEvidenceRepository
from src.infrastructure.tools.amap import create_amap_bindings
from src.infrastructure.tools.assembly import ToolProviderAssembly, assemble_tool_providers
from src.infrastructure.tools.tuniu import create_tuniu_bindings
from src.obs.errors import from_exception
from src.ports.clock import Clock, SystemClock
from src.ports.llm_gateway import LLMGateway
from src.ports.state_repository import StateRepository
from src.ports.tool_errors import ToolConfigurationError


class M4PlanUseCase:
    """将 M2 路由结果显式交给 M4 主链路。"""

    def __init__(
        self,
        settings: Settings,
        *,
        state_repository: StateRepository,
        workflow: FakeProviderWorkflow,
        provider_assembly: ToolProviderAssembly | None = None,
        clock: Clock | None = None,
        plan_variant: str = "balanced",
        context_types: tuple[str, ...] = (),
        place_category: str | None = None,
        stay_area: str | None = None,
    ) -> None:
        """保存一个请求生命周期内显式注入的 M4 依赖。"""
        if not isinstance(settings, Settings):
            raise TypeError("settings must be a Settings instance")
        if not isinstance(state_repository, StateRepository):
            raise TypeError("state_repository must implement StateRepository")
        if not isinstance(workflow, FakeProviderWorkflow):
            raise TypeError("workflow must be a FakeProviderWorkflow instance")
        if not plan_variant.strip():
            raise ValueError("plan_variant must not be empty")
        if any(not value.strip() for value in context_types):
            raise ValueError("context_types must not contain empty values")
        self._settings = settings
        self._state_repository = state_repository
        self._workflow = workflow
        self._provider_assembly = provider_assembly
        self._clock = clock or SystemClock()
        self._plan_variant = plan_variant
        self._context_types = context_types
        self._place_category = place_category
        self._stay_area = stay_area

    @classmethod
    def from_settings(
        cls,
        settings: Settings,
        *,
        state_repository: StateRepository,
        llm_gateway: LLMGateway | None = None,
        clock: Clock | None = None,
        schedule_input_builder: ScheduleInputBuilder | None = None,
        plan_variant: str = "balanced",
        context_types: tuple[str, ...] = (),
        place_category: str | None = None,
        stay_area: str | None = None,
    ) -> M4PlanUseCase:
        """从一个已校验 Settings 快照组装 M4 Use Case。"""
        if not isinstance(settings, Settings):
            raise TypeError("settings must be a Settings instance")
        active_clock = clock or SystemClock()
        if not isinstance(active_clock, Clock):
            raise TypeError("clock must implement Clock")
        assembly = assemble_tool_providers(
            settings,
            amap_factory=create_amap_bindings,
            tuniu_factory=create_tuniu_bindings,
        )
        repository = InMemoryEvidenceRepository(
            clock=active_clock,
            ttl_policy=_default_ttl_policy(),
        )
        workflow = FakeProviderWorkflow(
            state_repository=state_repository,
            evidence_repository=repository,
            providers=ResearchProviders(
                geo=assembly.geo or _MissingProvider("geo"),
                transport=assembly.transport or _MissingProvider("transport"),
                stay=assembly.stay or _MissingProvider("stay"),
                place=assembly.place or _MissingProvider("place"),
                context=assembly.context or _MissingProvider("context"),
            ),
            composer=ItineraryComposer(llm_gateway or DeepSeekLLMGateway(), settings),
            schedule_input_builder=schedule_input_builder or CliScheduleInputBuilder(),
        )
        return cls(
            settings,
            state_repository=state_repository,
            workflow=workflow,
            provider_assembly=assembly,
            clock=active_clock,
            plan_variant=plan_variant,
            context_types=context_types,
            place_category=place_category,
            stay_area=stay_area,
        )

    def execute_routed(
        self,
        request: TripRequest,
        *,
        state: TripState,
        route_decision: RouteDecision,
        constraint_snapshot: ConstraintSnapshot,
        raw_input: str,
        trace_id: TraceId,
    ) -> FakeProviderWorkflowResult:
        """执行已经通过 M2 Router 的 PLAN 请求。"""
        del raw_input
        if state.trip_id != request.trip_id or state.trip_request != request:
            raise WorkflowError(
                trace_id=trace_id,
                stage="m4_use_case",
                category=ErrorCategory.STATE_CONFLICT,
                code="M4_REQUEST_STATE_MISMATCH",
                safe_message="M4 use case request and state do not match",
                upstream_refs=(request.trip_id,),
            )
        if state.constraint_snapshot != constraint_snapshot:
            raise WorkflowError(
                trace_id=trace_id,
                stage="m4_use_case",
                category=ErrorCategory.STATE_CONFLICT,
                code="M4_CONSTRAINT_SNAPSHOT_MISMATCH",
                safe_message="M4 use case received a different constraint snapshot",
                upstream_refs=(request.request_id,),
            )
        try:
            return self._execute_workflow(state, route_decision, trace_id=trace_id)
        except WorkflowError:
            raise
        except Exception as exc:
            failure = from_exception(exc, trace_id=trace_id, stage="m4_use_case")
            raise WorkflowError(
                trace_id=failure.payload.trace_id,
                stage=failure.payload.stage,
                category=failure.payload.category,
                code=failure.payload.code,
                safe_message=failure.payload.safe_message,
                retryable=failure.payload.retryable,
                cause=exc,
            ) from exc

    def _execute_workflow(
        self,
        state: TripState,
        route_decision: RouteDecision,
        *,
        trace_id: TraceId,
    ) -> FakeProviderWorkflowResult:
        """以同步 CLI 边界调用异步 M4 Workflow。"""

        async def run_and_close() -> FakeProviderWorkflowResult:
            try:
                return await self._workflow.run(
                    state,
                    route_decision,
                    trace_id=trace_id,
                    as_of=self._clock.now(),
                    plan_variant=self._plan_variant,
                    context_types=self._context_types,
                    place_category=self._place_category,
                    stay_area=self._stay_area,
                )
            finally:
                if self._provider_assembly is not None:
                    await self._provider_assembly.aclose()

        return asyncio.run(run_and_close())


class CliScheduleInputBuilder:
    """为 M4 CLI 提供无外部写操作的确定性排程输入。"""

    def __init__(self, *, activity_duration_minutes: int = 120) -> None:
        if activity_duration_minutes <= 0:
            raise ValueError("activity_duration_minutes must be positive")
        self._activity_duration_minutes = activity_duration_minutes

    def build(
        self,
        *,
        request: TripRequest,
        candidate_pool: CandidatePoolResult,
        evidence_snapshot: EvidenceSnapshot,
        plan_candidate: PlanCandidate,
    ) -> ScheduleInputs:
        """仅为已选地点生成显式活动时长，不猜测营业时间或路线。"""
        del request, evidence_snapshot
        candidates = {candidate.candidate_id: candidate for candidate in candidate_pool.candidates}
        activity_specs = tuple(
            ActivitySpec(
                candidate_id=candidate_id,
                duration_minutes=self._activity_duration_minutes,
                flex_buffer_minutes=15,
                evidence_refs=candidates[candidate_id].evidence_refs,
            )
            for candidate_id in plan_candidate.selected_candidate_refs
            if isinstance(candidates[candidate_id], PlaceCandidate)
        )
        return ScheduleInputs(activity_specs=activity_specs)


class _MissingProvider:
    """显式表示未配置能力，绝不生成默认成功响应。"""

    def __init__(self, capability: str) -> None:
        self._capability = capability

    async def search(self, query: object, *, timeout_seconds: Decimal) -> NoReturn:
        """在调用未配置能力时 fail-fast。"""
        del query, timeout_seconds
        raise ToolConfigurationError(
            provider="m4-composition",
            operation=f"{self._capability}_search",
            safe_message=f"M4 provider capability is not configured: {self._capability}",
        )


def _default_ttl_policy() -> EvidenceTtlPolicy:
    """提供 M4 组合根所需的显式 TTL 策略。"""
    return EvidenceTtlPolicy(
        static_geography=timedelta(days=30),
        business_hours_policy=timedelta(days=1),
        weather_forecast=timedelta(days=1),
        transport_schedule=timedelta(days=1),
        quote_inventory=timedelta(days=1),
        exchange_rate=timedelta(days=1),
    )


__all__ = ["CliScheduleInputBuilder", "M4PlanUseCase"]
