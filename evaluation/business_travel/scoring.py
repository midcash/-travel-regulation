from __future__ import annotations

from collections.abc import Mapping, Sequence, Set
from decimal import Decimal
from typing import Any

from evaluation.business_travel.contracts import (
    AgentEvalCase,
    BusinessAssertion,
    ComponentAvailability,
    FailureCategory,
    FirstFailedStage,
    RunStatus,
)


def exact_match(predicted: Set[Any], expected: Set[Any]) -> Decimal:
    """集合完全相同时返回 1，否则返回 0。"""
    return Decimal("1") if set(predicted) == set(expected) else Decimal("0")


def _alternative_signature(alternative: Mapping[str, Any]) -> tuple[tuple[str, str], ...]:
    return tuple(
        sorted(
            (str(key), str(value))
            for key, value in alternative.items()
            if key not in {"label", "name", "display_name", "reason"}
        )
    )


def alternative_diversity(alternatives: Sequence[Mapping[str, Any]]) -> Decimal:
    """计算去除展示标签后的方案差异率。"""
    if len(alternatives) < 2:
        return Decimal("0")
    signatures = {_alternative_signature(item) for item in alternatives}
    return Decimal("1") if len(signatures) == len(alternatives) else Decimal("0")


def _metric(predicted: Any, expected: Any, applicable: bool = True) -> Decimal | None:
    if not applicable:
        return None
    return Decimal("1") if predicted == expected else Decimal("0")


def _as_enum(value: Any, enum_type: type[Any]) -> Any | None:
    try:
        return enum_type(value)
    except (ValueError, TypeError):
        return None


def _oracle_payload(oracle: AgentEvalCase | Mapping[str, Any]) -> dict[str, Any]:
    """从冻结 Golden Oracle 构造评分输入，不读取运行方自带的 expected。"""
    if isinstance(oracle, AgentEvalCase):
        def value(field: str) -> Any:
            item = getattr(oracle, field)
            return item.value if item.status.value == "value" else None

        return {
            "mode": value("expected_mode"),
            "clarification_fields": value("expected_clarification_fields"),
            "scope": value("expected_initial_scope"),
            "capabilities": value("expected_initial_capabilities"),
            "lodging": value("expected_candidate_pre_meeting_lodging"),
            "recommendation_evidence_types": value("expected_recommendation_evidence_types"),
            "forbidden_outputs": value("forbidden_outputs"),
            "required_scope": oracle.expected_initial_scope.status.value == "value",
            "required_capabilities": oracle.expected_initial_capabilities.status.value == "value",
            "required_lodging": (
                oracle.expected_candidate_pre_meeting_lodging.status.value == "value"
            ),
            "required_evidence": (
                oracle.expected_recommendation_evidence_types.status.value == "value"
            ),
            "required_forbidden_output_check": oracle.forbidden_outputs.status.value == "value",
        }
    expected = oracle.get("expected")
    if not isinstance(expected, Mapping):
        raise ValueError("score oracle must provide an explicit expected mapping")
    payload = dict(expected)
    for key in (
        "required_scope",
        "required_capabilities",
        "required_lodging",
        "required_evidence",
        "required_candidates",
        "required_return_disclosure",
        "required_forbidden_output_check",
    ):
        if key in oracle:
            payload[key] = oracle[key]
    payload.setdefault("required_scope", True)
    payload.setdefault("required_capabilities", True)
    payload.setdefault("required_lodging", False)
    payload.setdefault("required_evidence", False)
    payload.setdefault("required_forbidden_output_check", False)
    return payload


class ScoreResult:
    """确定性单案例评分结果，保留分母状态和失败归因。"""

    def __init__(
        self,
        *,
        metric_values: dict[str, Decimal | None],
        component_availability: ComponentAvailability,
        business_assertion: BusinessAssertion,
        first_failed_stage: FirstFailedStage | None,
        failure_category: FailureCategory | None,
        run_status: RunStatus,
    ) -> None:
        self.metric_values = metric_values
        self.component_availability = component_availability
        self.business_assertion = business_assertion
        self.first_failed_stage = first_failed_stage
        self.failure_category = failure_category
        self.run_status = run_status


def score_case(
    run: Mapping[str, Any],
    oracle: AgentEvalCase | Mapping[str, Any],
) -> ScoreResult:
    """按结构化运行结果和 Oracle 计算单案例指标。"""
    predicted = run.get("predicted", {})
    if not isinstance(predicted, Mapping):
        return ScoreResult(
            metric_values={},
            component_availability=ComponentAvailability.IMPLEMENTED,
            business_assertion=BusinessAssertion.NOT_SCORABLE,
            first_failed_stage=FirstFailedStage.EVALUATOR,
            failure_category=FailureCategory.EVALUATOR,
            run_status=RunStatus.EVALUATOR_ERROR,
        )

    try:
        oracle_payload = _oracle_payload(oracle)
        expected = oracle_payload
        availability = _as_enum(run.get("component_availability"), ComponentAvailability)
        status = _as_enum(run.get("run_status"), RunStatus)
        if availability is None or status is None:
            raise ValueError("run status fields are invalid or missing")
    except ValueError:
        return ScoreResult(
            metric_values={},
            component_availability=ComponentAvailability.IMPLEMENTED,
            business_assertion=BusinessAssertion.NOT_SCORABLE,
            first_failed_stage=FirstFailedStage.EVALUATOR,
            failure_category=FailureCategory.EVALUATOR,
            run_status=RunStatus.EVALUATOR_ERROR,
        )
    first_failed = _as_enum(run.get("first_failed_stage"), FirstFailedStage)
    category = _as_enum(run.get("failure_category"), FailureCategory)
    metrics: dict[str, Decimal | None] = {
        "mode_accuracy": _metric(predicted.get("mode"), expected.get("mode")),
        "clarification_precision": _clarification_precision(predicted, expected),
        "clarification_recall": _clarification_recall(predicted, expected),
        "scope_exact_match": _metric(
            predicted.get("scope"),
            expected.get("scope"),
            bool(oracle_payload.get("required_scope", True)),
        ),
        "capability_exact_match": _metric(
            set(predicted.get("capabilities", [])), set(expected.get("capabilities", [])),
            bool(oracle_payload.get("required_capabilities", True)),
        ),
        "candidate_pre_meeting_lodging_exact_match": _metric(
            predicted.get("lodging"),
            expected.get("lodging"),
            bool(oracle_payload.get("required_lodging", False)),
        ),
        "recommendation_grounding_rate": _metric(
            set(predicted.get("recommendation_evidence_types") or []),
            set(expected.get("recommendation_evidence_types") or []),
        ),
        "alternative_diversity_pass_rate": alternative_diversity(
            tuple(item for item in predicted.get("alternatives", []) if isinstance(item, Mapping))
        ),
        "evidence_coverage": _metric(
            set(predicted.get("evidence_refs") or []), set(expected.get("evidence_refs") or []),
            bool(oracle_payload.get("required_evidence", False)),
        ),
        "candidate_coverage": _metric(
            set(predicted.get("candidate_refs") or []), set(expected.get("candidate_refs") or []),
            bool(oracle_payload.get("required_candidates", False)),
        ),
        "return_scope_disclosure_rate": _metric(
            predicted.get("return_scope_disclosed"), expected.get("return_scope_disclosed"),
            bool(oracle_payload.get("required_return_disclosure", False)),
        ),
        "forbidden_output_rate": _metric(
            set(predicted.get("forbidden_outputs") or []),
            set(expected.get("forbidden_outputs") or []),
            bool(oracle_payload.get("required_forbidden_output_check", False)),
        ),
    }
    if availability is ComponentAvailability.NOT_IMPLEMENTED_IN_BASELINE:
        metrics["scope_exact_match"] = None
    applicable_metrics = [item for item in metrics.values() if item is not None]
    business_assertion = (
        BusinessAssertion.FAIL
        if availability is ComponentAvailability.NOT_IMPLEMENTED_IN_BASELINE
        or status is not RunStatus.COMPLETED
        or any(item != Decimal("1") for item in applicable_metrics)
        else BusinessAssertion.PASS
    )
    if business_assertion is BusinessAssertion.FAIL and first_failed is None:
        first_failed = (
            FirstFailedStage.SCOPE
            if availability is ComponentAvailability.NOT_IMPLEMENTED_IN_BASELINE
            else FirstFailedStage.INTERPRETER
        )
    if business_assertion is BusinessAssertion.FAIL and category is None:
        category = (
            FailureCategory.EXTERNAL_DEPENDENCY
            if status is RunStatus.EXTERNAL_FAILURE
            else FailureCategory.BUSINESS
        )
    return ScoreResult(
        metric_values=metrics,
        component_availability=availability,
        business_assertion=business_assertion,
        first_failed_stage=first_failed,
        failure_category=category,
        run_status=status,
    )


def _clarification_precision(predicted: Mapping[str, Any], expected: Mapping[str, Any]) -> Decimal:
    predicted_fields = set(predicted.get("clarification_fields", []))
    expected_fields = set(expected.get("clarification_fields") or [])
    if not predicted_fields:
        return Decimal("1") if not expected_fields else Decimal("0")
    return Decimal(len(predicted_fields & expected_fields)) / Decimal(len(predicted_fields))


def _clarification_recall(predicted: Mapping[str, Any], expected: Mapping[str, Any]) -> Decimal:
    predicted_fields = set(predicted.get("clarification_fields", []))
    expected_fields = set(expected.get("clarification_fields") or [])
    if not expected_fields:
        return Decimal("1") if not predicted_fields else Decimal("0")
    return Decimal(len(predicted_fields & expected_fields)) / Decimal(len(expected_fields))
