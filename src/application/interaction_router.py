"""M2 Interaction Router：按安全、语义和就绪状态选择下一条工作路径。"""

from __future__ import annotations

from decimal import Decimal
from typing import Final

from src.domain.models.enums import InteractionMode
from src.domain.models.interpretation import InterpretationResult, SafetyFlag
from src.domain.models.readiness import ReadinessResult
from src.domain.models.routing import RouteDecision, RouteReasonCode
from src.domain.models.value_objects import StableId
from src.guard.g0 import G0ValidationResult

_BLOCKING_SAFETY_FLAGS: Final[frozenset[SafetyFlag]] = frozenset(
    {
        SafetyFlag.PROMPT_INJECTION,
        SafetyFlag.DANGEROUS_ACTION,
        SafetyFlag.UNAUTHORIZED_ACTION,
        SafetyFlag.INVALID_INPUT,
    }
)
_STAY_CATEGORIES: Final[frozenset[str]] = frozenset(
    {"accommodation", "hotel", "hotels", "lodging", "stay", "住宿", "酒店"}
)
_CONTEXT_CATEGORIES: Final[frozenset[str]] = frozenset(
    {
        "event",
        "events",
        "opening_hours",
        "policy",
        "weather",
        "holiday",
        "activity",
        "activities",
    }
)


class InteractionRouter:
    """只消费已校验的 G0、语义解释和 G1 结果，不调用外部旅行工具。"""

    def route(
        self,
        interpretation: InterpretationResult,
        readiness: ReadinessResult,
        *,
        g0_result: G0ValidationResult,
        current_plan_ref: StableId | None = None,
    ) -> RouteDecision:
        """根据固定优先级生成下一步路由决策。

        Args:
            interpretation: RequestInterpreter 生成的结构化语义结果。
            readiness: ReadinessEvaluator 生成的 G1 就绪结果。
            g0_result: 同一请求的 G0 安全与输入预检结果。
            current_plan_ref: 当前计划引用，仅供 REFINE/REPLAN 使用。

        Returns:
            RouteDecision: 可供状态机或后续任务图读取的类型化路由。

        Raises:
            TypeError: 任一上游结果不是声明的领域契约。
        """
        _validate_inputs(interpretation, readiness, g0_result)
        risk_flags = _unique_flags((*g0_result.safety_flags, *interpretation.safety_flags))
        if not g0_result.passed or _contains_blocking_safety(risk_flags):
            return _decision(
                mode=InteractionMode.UNSUPPORTED,
                confidence=Decimal("0"),
                reason_codes=(RouteReasonCode.G0_BLOCKED,),
                risk_flags=risk_flags,
            )

        mode = interpretation.mode_hint
        blockers = _blocker_refs(readiness)
        confidence = min(interpretation.overall_confidence, readiness.confidence)

        if mode is InteractionMode.ACTION:
            if blockers:
                return _clarification(
                    confidence=confidence,
                    blockers=blockers,
                    risk_flags=risk_flags,
                    reason_codes=(
                        RouteReasonCode.EXPLICIT_ACTION,
                        RouteReasonCode.ACTION_PRECONDITION_MISSING,
                        RouteReasonCode.CLARIFICATION_REQUIRED,
                    ),
                )
            return _decision(
                mode=InteractionMode.ACTION,
                confidence=confidence,
                reason_codes=(RouteReasonCode.EXPLICIT_ACTION,),
                risk_flags=risk_flags,
                required_capabilities=("action_confirmation",),
            )

        if mode in {InteractionMode.REFINE, InteractionMode.REPLAN}:
            if current_plan_ref is None:
                return _clarification(
                    confidence=confidence,
                    blockers=blockers,
                    risk_flags=risk_flags,
                    reason_codes=(
                        (
                            RouteReasonCode.REFINE_CURRENT_PLAN
                            if mode is InteractionMode.REFINE
                            else RouteReasonCode.REPLAN_CURRENT_PLAN
                        ),
                        RouteReasonCode.PLAN_CONTEXT_MISSING,
                        RouteReasonCode.CLARIFICATION_REQUIRED,
                    ),
                )
            if blockers:
                return _clarification(
                    confidence=confidence,
                    blockers=blockers,
                    risk_flags=risk_flags,
                    reason_codes=(RouteReasonCode.CLARIFICATION_REQUIRED,),
                )
            return _decision(
                mode=mode,
                confidence=confidence,
                reason_codes=(
                    RouteReasonCode.REFINE_CURRENT_PLAN
                    if mode is InteractionMode.REFINE
                    else RouteReasonCode.REPLAN_CURRENT_PLAN,
                ),
                risk_flags=risk_flags,
                required_capabilities=_required_capabilities(mode, interpretation),
                current_plan_ref=current_plan_ref,
            )

        if blockers:
            return _clarification(
                confidence=confidence,
                blockers=blockers,
                risk_flags=risk_flags,
                reason_codes=(RouteReasonCode.CLARIFICATION_REQUIRED,),
            )

        if mode is None:
            return _clarification(
                confidence=confidence,
                blockers=(),
                risk_flags=risk_flags,
                reason_codes=(RouteReasonCode.ROUTE_UNCERTAIN,),
            )
        if mode is InteractionMode.UNSUPPORTED:
            return _decision(
                mode=mode,
                confidence=confidence,
                reason_codes=(RouteReasonCode.UNSUPPORTED_REQUEST,),
                risk_flags=risk_flags,
            )

        reason_code = {
            InteractionMode.ANSWER: RouteReasonCode.ANSWER_REQUEST,
            InteractionMode.COMPARE: RouteReasonCode.COMPARE_REQUEST,
            InteractionMode.PLAN: RouteReasonCode.PLAN_REQUEST,
        }.get(mode)
        if reason_code is None:
            return _clarification(
                confidence=confidence,
                blockers=(),
                risk_flags=risk_flags,
                reason_codes=(RouteReasonCode.ROUTE_UNCERTAIN,),
            )
        return _decision(
            mode=mode,
            confidence=confidence,
            reason_codes=(reason_code,),
            risk_flags=risk_flags,
            required_capabilities=_required_capabilities(mode, interpretation),
        )


def _validate_inputs(
    interpretation: InterpretationResult,
    readiness: ReadinessResult,
    g0_result: G0ValidationResult,
) -> None:
    """在路由前拒绝未经过 Schema 校验的运行时对象。"""
    if not isinstance(interpretation, InterpretationResult):
        raise TypeError("interpretation must be an InterpretationResult")
    if not isinstance(readiness, ReadinessResult):
        raise TypeError("readiness must be a ReadinessResult")
    if not isinstance(g0_result, G0ValidationResult):
        raise TypeError("g0_result must be a G0ValidationResult")


def _contains_blocking_safety(flags: tuple[SafetyFlag, ...]) -> bool:
    """判断是否存在必须先停止后续语义路由的安全标记。"""
    return bool(set(flags).intersection(_BLOCKING_SAFETY_FLAGS))


def _unique_flags(flags: tuple[SafetyFlag, ...]) -> tuple[SafetyFlag, ...]:
    """按上游出现顺序合并 G0 与 Interpreter 的风险标记。"""
    return tuple(dict.fromkeys(flags))


def _blocker_refs(readiness: ReadinessResult) -> tuple[str, ...]:
    """提取稳定且去重的 G1 blocker 引用，供澄清和审计使用。"""
    return tuple(dict.fromkeys(blocker.issue_id for blocker in readiness.blockers))


def _clarification(
    *,
    confidence: Decimal,
    blockers: tuple[str, ...],
    risk_flags: tuple[SafetyFlag, ...],
    reason_codes: tuple[RouteReasonCode, ...],
) -> RouteDecision:
    """创建不猜测工作模式的 CLARIFY 决策。"""
    return _decision(
        mode=InteractionMode.CLARIFY,
        confidence=confidence,
        reason_codes=reason_codes,
        missing_blockers=blockers,
        risk_flags=risk_flags,
    )


def _decision(
    *,
    mode: InteractionMode,
    confidence: Decimal,
    reason_codes: tuple[RouteReasonCode, ...],
    required_capabilities: tuple[str, ...] = (),
    missing_blockers: tuple[str, ...] = (),
    risk_flags: tuple[SafetyFlag, ...] = (),
    current_plan_ref: StableId | None = None,
) -> RouteDecision:
    """集中创建 RouteDecision，确保所有分支经过同一 Schema。"""
    return RouteDecision(
        mode=mode.value,
        confidence=confidence,
        reason_codes=reason_codes,
        required_capabilities=required_capabilities,
        missing_blockers=missing_blockers,
        risk_flags=risk_flags,
        current_plan_ref=current_plan_ref,
    )


def _required_capabilities(
    mode: InteractionMode,
    interpretation: InterpretationResult,
) -> tuple[str, ...]:
    """把路由模式映射为有限能力名，不在本步骤创建任务或调用工具。"""
    if mode is InteractionMode.ANSWER:
        return ("context",)
    if mode is InteractionMode.COMPARE:
        return ("geo", "place", "context")
    if mode is InteractionMode.PLAN:
        categories = {
            candidate.category.strip().casefold()
            for candidate in interpretation.constraint_candidates
        }
        capabilities = ["geo", "transport", "place"]
        if categories.intersection(_STAY_CATEGORIES):
            capabilities.append("stay")
        if categories.intersection(_CONTEXT_CATEGORIES):
            capabilities.append("context")
        return tuple(capabilities)
    if mode is InteractionMode.REFINE:
        return ("plan_refinement",)
    if mode is InteractionMode.REPLAN:
        return ("plan_replanning",)
    if mode is InteractionMode.ACTION:
        return ("action_confirmation",)
    return ()
