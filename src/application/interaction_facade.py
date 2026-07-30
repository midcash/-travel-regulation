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
from src.obs.errors import WorkflowFailure, from_exception
from src.obs.log import get_logger
from src.obs.stage import observe_stage
from src.obs.trace import trace_workflow_request
from src.ports.llm_gateway import LLMGateway
from src.ports.state_repository import StateRepository

logger = get_logger(__name__)


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
        trace_id = f"route:{request.trip_id}:{request.request_id}"
        try:
            state = self._load_or_create_state(request)
        except Exception as exc:
            failure = from_exception(exc, trace_id=trace_id)
            logger.error("workflow_failed", **failure.event_fields())
            raise
        active_state = state
        security_context = context or _default_cli_security_context()

        with trace_workflow_request(
            trace_id=trace_id,
            request_id=str(request.request_id),
            trip_id=str(request.trip_id),
            session_id=str(request.session_id),
            workflow_status=state.status.value,
            state_version=state.version,
        ):
            try:
                with observe_stage("g0") as stage:
                    g0_result = self._g0_validator.validate(raw_input, context=security_context)
                    stage.add_summary(
                        schema_version="m2.g0.v1",
                        input_count=1,
                        output_count=1,
                        passed=g0_result.passed,
                        issue_codes=tuple(issue.code.value for issue in g0_result.issues),
                        safety_flags=tuple(flag.value for flag in g0_result.safety_flags),
                        pii_detected=g0_result.pii_detected,
                    )
                with observe_stage("interpreter") as stage:
                    interpretation = self._interpreter.interpret(
                        raw_input,
                        context=security_context,
                        trace_id=trace_id,
                        conversation_summary=conversation_summary,
                        current_state=state,
                        allowed_modes=tuple(InteractionMode),
                        redacted_input=redacted_input,
                    )
                    stage.add_summary(
                        schema_version="m2.interpretation.v1",
                        input_count=1,
                        output_count=1,
                        mode_hint=(
                            interpretation.mode_hint.value
                            if interpretation.mode_hint is not None
                            else None
                        ),
                        candidate_count=len(interpretation.constraint_candidates),
                        candidate_categories=tuple(
                            sorted(
                                {
                                    candidate.category
                                    for candidate in interpretation.constraint_candidates
                                }
                            )
                        ),
                        entity_count=len(interpretation.extracted_entities),
                        confidence=float(interpretation.overall_confidence),
                    )
                created_at = self._clock()
                with observe_stage("constraint_service") as stage:
                    snapshot = self._constraint_service.build_snapshot(
                        interpretation,
                        request_id=request.request_id,
                        trace_id=trace_id,
                        created_at=created_at,
                        previous_snapshot=state.constraint_snapshot,
                        negation_text=raw_input,
                        reference_date=reference_date or created_at.date(),
                    )
                    stage.add_summary(
                        schema_version="m2.constraint_snapshot.v1",
                        input_count=len(interpretation.constraint_candidates),
                        output_count=len(snapshot.constraints),
                        snapshot_version=snapshot.version,
                        constraint_count=len(snapshot.constraints),
                        categories=tuple(sorted({item.category for item in snapshot.constraints})),
                        conflict_group_count=len(
                            {
                                item.conflict_group
                                for item in snapshot.constraints
                                if item.conflict_group is not None
                            }
                        ),
                    )
                with observe_stage("readiness_evaluator") as stage:
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
                    stage.add_summary(
                        schema_version="m2.readiness.v1",
                        input_count=len(snapshot.constraints),
                        output_count=1,
                        snapshot_version=readiness.snapshot_version,
                        blocker_count=len(readiness.blockers),
                        assumption_count=len(readiness.assumptions),
                        ready=readiness.ready,
                        blocker_codes=tuple(blocker.code.value for blocker in readiness.blockers),
                        blocker_ids=tuple(str(blocker.issue_id) for blocker in readiness.blockers),
                        assumption_codes=tuple(
                            assumption.code.value for assumption in readiness.assumptions
                        ),
                        confidence=float(readiness.confidence),
                    )
                with observe_stage("router") as stage:
                    decision = self._router.route(
                        interpretation,
                        readiness,
                        g0_result=g0_result,
                        current_plan_ref=current_plan_ref,
                    )
                    stage.add_summary(
                        schema_version="m2.route.v1",
                        input_count=1,
                        output_count=1,
                        mode=decision.mode,
                        decision_code=decision.reason_codes[0].value,
                        reason_codes=tuple(code.value for code in decision.reason_codes),
                        required_capabilities=decision.required_capabilities,
                        missing_blocker_ids=tuple(
                            str(blocker_id) for blocker_id in decision.missing_blockers
                        ),
                    )
                with observe_stage("state") as stage:
                    stage.add_summary(
                        schema_version="m2.state.v1",
                        input_count=1,
                        output_count=1,
                        state_before=state.status.value,
                        state_version_before=state.version,
                    )
                    active_state = self._apply_and_save_state(
                        state,
                        decision,
                        request=request,
                        constraint_snapshot=snapshot,
                    )
                    stage.add_summary(
                        state_after=active_state.status.value,
                        state_version=active_state.version,
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
            except Exception as exc:
                failure = from_exception(
                    exc,
                    trace_id=trace_id,
                )
                logger.error("workflow_failed", **failure.event_fields())
                self._mark_failed(active_state, failure)
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

    def _mark_failed(self, state: TripState, failure: WorkflowFailure) -> None:
        if state.status is WorkflowStatus.FAILED or not state.can_transition_to(
            WorkflowStatus.FAILED
        ):
            return
        failed = state.transition_to(WorkflowStatus.FAILED).model_copy(
            update={"last_error": failure.payload}
        )
        try:
            self._state_repository.save(failed, expected_version=state.version)
        except Exception as persistence_error:
            persistence_failure = from_exception(
                persistence_error,
                trace_id=str(failure.payload.trace_id),
                stage="state_persistence",
            )
            logger.error(
                "state_persistence_failed",
                **persistence_failure.event_fields(),
                root_failure_code=failure.payload.code,
            )


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
