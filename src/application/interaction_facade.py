"""M2 交互 Facade：把解释、约束、就绪、路由和状态更新接到应用入口。"""

from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, date, datetime
from typing import Protocol

from pydantic import BaseModel, ConfigDict

from src.agents.request_interpreter import RequestInterpreter
from src.application.interaction_router import InteractionRouter
from src.application.trip_state_integration import TripStateIntegration
from src.application.use_cases.plan_trip import PlanTripResult
from src.config import Settings
from src.domain.errors import WorkflowError
from src.domain.models.clarification import ClarificationRequest
from src.domain.models.constraint import ConstraintSnapshot
from src.domain.models.enums import ErrorCategory, InteractionMode, WorkflowStatus
from src.domain.models.interpretation import InterpretationResult
from src.domain.models.readiness import (
    ActionPreconditions,
    ReadinessResult,
)
from src.domain.models.routing import RouteDecision
from src.domain.models.state import TripState
from src.domain.models.trip_request import TripRequest
from src.domain.models.value_objects import StableId
from src.domain.services.clarification_builder import ClarificationBuilder
from src.domain.services.constraint_service import ConstraintService
from src.domain.services.readiness_evaluator import ReadinessEvaluationContext, ReadinessEvaluator
from src.domain.state_repository_errors import StateNotFoundError
from src.gateway.deepseek_adapter import DeepSeekLLMGateway
from src.guard.g0 import G0SecurityContext, G0Validator
from src.infrastructure.persistence.in_memory import InMemoryStateRepository
from src.obs.trace import trace_workflow_request
from src.ports.llm_gateway import LLMGateway
from src.ports.state_repository import StateRepository


class PlanExecutor(Protocol):
    """现有 PLAN Facade 的最小调用契约。"""

    def execute(self, request: TripRequest) -> PlanTripResult:
        """执行已有的 PLAN 规划流程。"""


class TripInteractionResult(BaseModel):
    """M2 应用入口返回的结构化交互结果。"""

    model_config = ConfigDict(extra="forbid", frozen=True)

    route_decision: RouteDecision
    state: TripState
    constraint_snapshot: ConstraintSnapshot
    readiness: ReadinessResult
    clarification: ClarificationRequest | None = None
    plan_result: PlanTripResult | None = None


class TripInteractionFacade:
    """编排 M2 控制平面，不创建外部旅行工具任务。"""

    def __init__(
        self,
        settings: Settings,
        *,
        planner: PlanExecutor,
        gateway: LLMGateway | None = None,
        state_repository: StateRepository | None = None,
        g0_validator: G0Validator | None = None,
        interpreter: RequestInterpreter | None = None,
        constraint_service: ConstraintService | None = None,
        readiness_evaluator: ReadinessEvaluator | None = None,
        router: InteractionRouter | None = None,
        state_integration: TripStateIntegration | None = None,
        clarification_builder: ClarificationBuilder | None = None,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self._settings = settings
        self._planner = planner
        self._state_repository = state_repository or InMemoryStateRepository()
        self._g0_validator = g0_validator or G0Validator()
        self._gateway = gateway or DeepSeekLLMGateway()
        self._interpreter = interpreter or RequestInterpreter(
            self._gateway,
            settings,
            g0_validator=self._g0_validator,
        )
        self._constraint_service = constraint_service or ConstraintService()
        self._readiness_evaluator = readiness_evaluator or ReadinessEvaluator()
        self._router = router or InteractionRouter()
        self._state_integration = state_integration or TripStateIntegration()
        self._clarification_builder = clarification_builder or ClarificationBuilder()
        self._clock = clock or (lambda: datetime.now(UTC))

    def execute(
        self,
        request: TripRequest,
        raw_input: str,
        *,
        context: G0SecurityContext | None = None,
        conversation_summary: str = "",
        current_plan_ref: StableId | None = None,
        redacted_input: str | None = None,
        reference_date: date | None = None,
    ) -> TripInteractionResult:
        """执行一次 M2 交互请求并返回路由、快照和状态。

        Args:
            request: 已完成 Schema 校验的旅行请求。
            raw_input: 本轮用户原始输入，仅在本次调用内使用。
            context: G0 所需的认证、授权和脱敏引用上下文。
            conversation_summary: 已脱敏且有界的会话摘要。
            current_plan_ref: REFINE/REPLAN 可引用的当前计划 ID。
            redacted_input: PII 输入对应的脱敏文本。
            reference_date: 相对日期解析使用的日期；默认使用当前 UTC 日期。

        Returns:
            TripInteractionResult: 类型化路由结果和状态快照。

        Raises:
            WorkflowError: 解释、约束或 Facade 的结构化流程失败。
        """
        if not isinstance(request, TripRequest):
            raise TypeError("request must be a TripRequest")
        state = self._load_or_create_state(request)
        active_state = state
        security_context = context or _default_cli_security_context()
        trace_id = f"route:{request.trip_id}:{request.request_id}"

        with trace_workflow_request(
            trace_id=trace_id,
            request_id=str(request.request_id),
            trip_id=str(request.trip_id),
            session_id=str(request.session_id),
            workflow_status=state.status.value,
            state_version=state.version,
        ):
            try:
                g0_result = self._g0_validator.validate(raw_input, context=security_context)
                interpretation = self._interpreter.interpret(
                    raw_input,
                    context=security_context,
                    trace_id=trace_id,
                    conversation_summary=conversation_summary,
                    current_state=state,
                    allowed_modes=tuple(InteractionMode),
                    redacted_input=redacted_input,
                )
                created_at = self._clock()
                snapshot = self._constraint_service.build_snapshot(
                    interpretation,
                    request_id=request.request_id,
                    trace_id=trace_id,
                    created_at=created_at,
                    previous_snapshot=state.constraint_snapshot,
                    negation_text=raw_input,
                    reference_date=reference_date or created_at.date(),
                )
                readiness = self._readiness_evaluator.evaluate(
                    snapshot,
                    trace_id=trace_id,
                    interpretation=interpretation,
                    context=_readiness_context(
                        interpretation=interpretation,
                        request=request,
                        current_plan_ref=current_plan_ref,
                        security_context=security_context,
                    ),
                )
                decision = self._router.route(
                    interpretation,
                    readiness,
                    g0_result=g0_result,
                    current_plan_ref=current_plan_ref,
                )
                active_state = self._apply_and_save_state(
                    state,
                    decision,
                    request=request,
                    constraint_snapshot=snapshot,
                )
                clarification = (
                    self._clarification_builder.build(readiness)
                    if decision.mode == InteractionMode.CLARIFY.value
                    else None
                )
                plan_result = None
                if decision.mode == InteractionMode.PLAN.value:
                    plan_result = self._planner.execute(request)
                return TripInteractionResult(
                    route_decision=decision,
                    state=active_state,
                    constraint_snapshot=snapshot,
                    readiness=readiness,
                    clarification=clarification,
                    plan_result=plan_result,
                )
            except Exception:
                self._mark_failed(active_state)
                raise

    def _load_or_create_state(self, request: TripRequest) -> TripState:
        try:
            state = self._state_repository.get(request.trip_id)
        except StateNotFoundError:
            return self._state_repository.create(
                TripState(
                    trip_id=request.trip_id,
                    session_id=request.session_id,
                    trip_request=request,
                )
            )
        if state.session_id != request.session_id:
            raise WorkflowError(
                f"route:{request.trip_id}:{request.request_id}",
                "state_repository",
                ErrorCategory.STATE_CONFLICT,
                "STATE_SESSION_MISMATCH",
                "trip state belongs to another session",
            )
        return state

    def _apply_and_save_state(
        self,
        state: TripState,
        decision: RouteDecision,
        *,
        request: TripRequest,
        constraint_snapshot: ConstraintSnapshot,
    ) -> TripState:
        updated = self._state_integration.apply_route_decision(state, decision)
        if updated is state:
            if (
                state.trip_request == request
                and state.constraint_snapshot == constraint_snapshot
            ):
                return state
            updated = state.model_copy(
                update={
                    "version": state.version + 1,
                    "trip_request": request,
                    "constraint_snapshot": constraint_snapshot,
                }
            )
        else:
            updated = updated.model_copy(
                update={
                    "trip_request": request,
                    "constraint_snapshot": constraint_snapshot,
                }
            )
        return self._state_repository.save(updated, expected_version=state.version)

    def _mark_failed(self, state: TripState) -> None:
        if state.status is WorkflowStatus.FAILED or not state.can_transition_to(
            WorkflowStatus.FAILED
        ):
            return
        failed = state.transition_to(WorkflowStatus.FAILED)
        self._state_repository.save(failed, expected_version=state.version)


def _default_cli_security_context() -> G0SecurityContext:
    """为本地 CLI 提供显式、最小的已认证调用上下文。"""
    return G0SecurityContext(
        principal_ref="cli",
        authenticated=True,
        authorized=True,
    )


def _readiness_context(
    *,
    interpretation: InterpretationResult,
    request: TripRequest,
    current_plan_ref: StableId | None,
    security_context: G0SecurityContext,
) -> ReadinessEvaluationContext:
    """把已校验入口上下文转换为 G1 所需的类型化上下文。"""
    mode = interpretation.mode_hint or request.requested_mode
    return ReadinessEvaluationContext(
        mode=mode,
        current_plan_ref=current_plan_ref,
        action_preconditions=ActionPreconditions(
            authenticated=security_context.authenticated,
            authorized=security_context.authorized,
            identity_ref=security_context.principal_ref,
        ),
    )
