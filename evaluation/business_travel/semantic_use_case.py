from __future__ import annotations

from datetime import UTC, date, datetime

from pydantic import BaseModel, ConfigDict, Field

from src.agents.request_interpreter import RequestInterpreter
from src.application.interaction_router import InteractionRouter
from src.config import Settings
from src.domain.models.business_trip import BusinessTripScope
from src.domain.models.constraint import ConstraintSnapshot
from src.domain.models.interpretation import InterpretationResult
from src.domain.models.readiness import ReadinessResult
from src.domain.models.routing import RouteDecision
from src.domain.models.trip_request import TripRequest
from src.domain.models.value_objects import TraceId
from src.domain.services.business_trip_assumption_resolver import (
    BusinessTripAssumptionResolver,
)
from src.domain.services.business_trip_boundary_resolver import (
    BusinessTripBoundaryResolver,
)
from src.domain.services.business_trip_scope_resolver import BusinessTripScopeResolver
from src.domain.services.constraint_service import ConstraintService
from src.domain.services.readiness_evaluator import (
    ReadinessEvaluationContext,
    ReadinessEvaluator,
)
from src.guard.g0 import G0SecurityContext, G0ValidationResult, G0Validator
from src.ports.llm_gateway import LLMGateway


class SemanticEvaluationResult(BaseModel):
    """只读语义评测结果，不包含 TripState 或规划结果。"""

    model_config = ConfigDict(extra="forbid", frozen=True)

    g0: G0ValidationResult
    interpretation: InterpretationResult
    constraint_snapshot: ConstraintSnapshot
    readiness: ReadinessResult
    route_decision: RouteDecision
    business_scope: BusinessTripScope | None = None
    trajectory: tuple[str, ...] = Field(min_length=1)


class SemanticEvaluationUseCase:
    """执行 G0 到 Router 的只读语义链路。"""

    def __init__(
        self,
        settings: Settings,
        *,
        gateway: LLMGateway,
        g0_validator: G0Validator | None = None,
        interpreter: RequestInterpreter | None = None,
        constraint_service: ConstraintService | None = None,
        readiness_evaluator: ReadinessEvaluator | None = None,
        router: InteractionRouter | None = None,
    ) -> None:
        self._settings = settings
        self._g0_validator = g0_validator or G0Validator()
        self._interpreter = interpreter or RequestInterpreter(
            gateway,
            settings,
            g0_validator=self._g0_validator,
        )
        self._constraint_service = constraint_service or ConstraintService()
        self._readiness_evaluator = readiness_evaluator or ReadinessEvaluator()
        self._router = router or InteractionRouter()
        self._business_assumption_resolver = BusinessTripAssumptionResolver()
        self._business_boundary_resolver = BusinessTripBoundaryResolver()
        self._business_scope_resolver = BusinessTripScopeResolver()

    def execute(
        self,
        request: TripRequest,
        input_text: str,
        *,
        reference_date: date,
        context: G0SecurityContext | None = None,
    ) -> SemanticEvaluationResult:
        """执行并返回只读语义阶段结果。"""
        if not isinstance(request, TripRequest):
            raise TypeError("request must be a TripRequest")
        trace_id: TraceId = f"semantic:{request.trip_id}:{request.request_id}"
        created_at = datetime.combine(reference_date, datetime.min.time(), tzinfo=UTC)
        security_context = context or G0SecurityContext(
            principal_ref="eval",
            authenticated=True,
            authorized=True,
        )
        trajectory: list[str] = []
        g0 = self._g0_validator.validate(input_text, context=security_context)
        trajectory.append("g0")
        if not g0.passed:
            raise ValueError("G0 validation failed")
        interpretation = self._interpreter.interpret(
            input_text,
            context=security_context,
            trace_id=trace_id,
            current_state=None,
            allowed_modes=(),
            reference_date=reference_date,
        )
        trajectory.append("interpreter")
        business_boundary = self._business_boundary_resolver.resolve(
            interpretation,
            input_text,
        )
        assumption_observations = self._business_assumption_resolver.resolve(
            interpretation,
            input_text,
        )
        snapshot = self._constraint_service.build_snapshot(
            interpretation,
            request_id=request.request_id,
            trace_id=trace_id,
            created_at=created_at,
            previous_snapshot=None,
            context_observations=assumption_observations,
            negation_text=input_text,
            reference_date=reference_date,
        )
        trajectory.append("constraint_service")
        readiness = self._readiness_evaluator.evaluate(
            snapshot,
            trace_id=trace_id,
            interpretation=interpretation,
            context=ReadinessEvaluationContext(
                mode=interpretation.mode_hint or request.requested_mode,
                reference_date=reference_date,
            ),
        )
        trajectory.append("readiness_evaluator")
        business_scope = (
            self._business_scope_resolver.resolve(snapshot) if readiness.ready else None
        )
        route = self._router.route(
            interpretation,
            readiness,
            g0_result=g0,
            business_scope=business_scope,
            business_boundary=business_boundary,
        )
        trajectory.append("router")
        return SemanticEvaluationResult(
            g0=g0,
            interpretation=interpretation,
            constraint_snapshot=snapshot,
            readiness=readiness,
            route_decision=route,
            business_scope=business_scope,
            trajectory=tuple(trajectory),
        )
