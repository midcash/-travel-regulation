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


def _string_set(value: Any) -> frozenset[str]:
    """Normalize an Oracle or run collection as a set of strings."""
    if value is None or isinstance(value, (str, bytes)):
        return frozenset() if value is None else frozenset({str(value)})
    try:
        return frozenset(str(item) for item in value)
    except TypeError:
        return frozenset({str(value)})


def _dependency_set(value: Any) -> frozenset[tuple[str, str]]:
    """Normalize task dependency edges without relying on list ordering."""
    if value is None or isinstance(value, (str, bytes)):
        return frozenset()
    dependencies: set[tuple[str, str]] = set()
    try:
        for edge in value:
            if isinstance(edge, (str, bytes)) or len(edge) != 2:
                continue
            dependencies.add((str(edge[0]), str(edge[1])))
    except (TypeError, ValueError):
        return frozenset()
    return frozenset(dependencies)


def _candidate_set_map(value: Any) -> dict[str, frozenset[str]]:
    """Normalize candidate-scoped scope/capability maps for exact comparison."""
    if not isinstance(value, Mapping):
        return {}
    return {str(candidate): _string_set(items) for candidate, items in value.items()}


def _distinct_alternative_count(alternatives: Any) -> int:
    """Count alternatives after removing display-only labels."""
    if not isinstance(alternatives, Sequence) or isinstance(alternatives, (str, bytes)):
        return 0
    normalized = tuple(item for item in alternatives if isinstance(item, Mapping))
    return len({_alternative_signature(item) for item in normalized})


def _actual_error_type(run: Mapping[str, Any], predicted: Mapping[str, Any]) -> str | None:
    """Read an explicit error type, then a safe structured workflow error code."""
    value = predicted.get("error_type")
    if value is not None and str(value).strip():
        return str(value)
    workflow_error = run.get("workflow_error")
    if isinstance(workflow_error, Mapping):
        for key in ("cause_code", "code", "error_type"):
            value = workflow_error.get(key)
            if value is not None and str(value).strip():
                return str(value)
    return None


def _failure_semantics_metric(
    *,
    actual_error_type: str | None,
    expected_error_type: Any,
    applicable: bool,
) -> Decimal | None:
    """Score expected errors and reject unexpected errors for success cases."""
    if not applicable:
        return None
    if expected_error_type is None:
        return Decimal("1") if actual_error_type is None else Decimal("0")
    return _metric(actual_error_type, str(expected_error_type))


def _trajectory_validity(
    predicted: Mapping[str, Any],
    expected: Mapping[str, Any],
) -> Decimal:
    """Check the observable action path without requiring one internal log sequence."""
    trajectory = predicted.get("trajectory")
    if not isinstance(trajectory, Sequence) or isinstance(trajectory, (str, bytes)):
        return Decimal("0")
    nodes = tuple(str(node) for node in trajectory)
    if not nodes:
        return Decimal("0")

    positions: dict[str, int] = {}
    for index, node in enumerate(nodes):
        positions.setdefault(node, index)

    fixed_order = (
        "g0",
        "interpreter",
        "constraint_service",
        "readiness_evaluator",
        "scope",
        "router",
        "task_graph",
        "composer",
        "delivery",
    )
    present_order = [positions[node] for node in fixed_order if node in positions]
    if present_order != sorted(present_order):
        return Decimal("0")

    dependencies = _dependency_set(predicted.get("task_dependencies"))
    dependencies |= _dependency_set(predicted.get("initial_task_dependencies"))
    dependencies |= _dependency_set(predicted.get("expanded_task_dependencies"))
    expected_dependencies = _dependency_set(expected.get("initial_task_dependencies"))
    expected_dependencies |= _dependency_set(expected.get("expanded_task_dependencies"))
    if expected_dependencies and not dependencies:
        return Decimal("0")
    for predecessor, successor in dependencies:
        predecessor_index = positions.get(predecessor)
        successor_index = positions.get(successor)
        if (
            predecessor_index is None
            or successor_index is None
            or predecessor_index >= successor_index
        ):
            return Decimal("0")

    forbidden = _string_set(expected.get("forbidden_outputs"))
    actual_forbidden = _string_set(predicted.get("forbidden_outputs"))
    if forbidden & actual_forbidden:
        return Decimal("0")
    return Decimal("1")


def _trajectory_from_run(run: Mapping[str, Any]) -> tuple[str, ...] | None:
    """Extract a safe stage trajectory from a structured run when supplied."""
    trajectory = run.get("trajectory")
    if isinstance(trajectory, Sequence) and not isinstance(trajectory, (str, bytes)):
        return tuple(str(node) for node in trajectory)
    stage_outputs = run.get("stage_outputs")
    if not isinstance(stage_outputs, Sequence) or isinstance(stage_outputs, (str, bytes)):
        return None
    stages = tuple(
        str(item.get("stage"))
        for item in stage_outputs
        if isinstance(item, Mapping) and item.get("stage")
    )
    return stages or None


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
            "initial_task_dependencies": value("expected_initial_task_dependencies"),
            "expanded_scope_by_candidate": value("expected_expanded_scope_by_candidate"),
            "expanded_capabilities_by_candidate": value(
                "expected_expanded_capabilities_by_candidate"
            ),
            "expanded_task_dependencies": value("expected_expanded_task_dependencies"),
            "lodging": value("expected_candidate_pre_meeting_lodging"),
            "min_distinct_alternatives": value("expected_min_distinct_alternatives"),
            "recommendation_evidence_types": value("expected_recommendation_evidence_types"),
            "terminal_status": value("expected_terminal_status"),
            "error_type": value("expected_error_type"),
            "forbidden_outputs": value("forbidden_outputs"),
            "required_scope": oracle.expected_initial_scope.status.value == "value",
            "required_capabilities": oracle.expected_initial_capabilities.status.value == "value",
            "required_initial_task_dependencies": (
                oracle.expected_initial_task_dependencies.status.value == "value"
            ),
            "required_expanded_scope": (
                oracle.expected_expanded_scope_by_candidate.status.value == "value"
            ),
            "required_expanded_capabilities": (
                oracle.expected_expanded_capabilities_by_candidate.status.value == "value"
            ),
            "required_expanded_task_dependencies": (
                oracle.expected_expanded_task_dependencies.status.value == "value"
            ),
            "required_lodging": (
                oracle.expected_candidate_pre_meeting_lodging.status.value == "value"
            ),
            "required_min_distinct_alternatives": (
                oracle.expected_min_distinct_alternatives.status.value == "value"
            ),
            "required_evidence": (
                oracle.expected_recommendation_evidence_types.status.value == "value"
            ),
            "required_terminal_status": oracle.expected_terminal_status.status.value == "value",
            "required_failure_semantics": True,
            "required_forbidden_output_check": oracle.forbidden_outputs.status.value == "value",
            "required_trajectory": True,
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
        "required_initial_task_dependencies",
        "required_expanded_scope",
        "required_expanded_capabilities",
        "required_expanded_task_dependencies",
        "required_min_distinct_alternatives",
        "required_terminal_status",
        "required_failure_semantics",
        "required_trajectory",
    ):
        if key in oracle:
            payload[key] = oracle[key]
    payload.setdefault("required_scope", True)
    payload.setdefault("required_capabilities", True)
    payload.setdefault("required_lodging", False)
    payload.setdefault("required_evidence", "recommendation_evidence_types" in payload)
    payload.setdefault("required_forbidden_output_check", "forbidden_outputs" in payload)
    for field in (
        "required_initial_task_dependencies",
        "required_expanded_scope",
        "required_expanded_capabilities",
        "required_expanded_task_dependencies",
        "required_min_distinct_alternatives",
        "required_terminal_status",
        "required_failure_semantics",
        "required_trajectory",
    ):
        expected_key = {
            "required_expanded_scope": "expanded_scope_by_candidate",
            "required_expanded_capabilities": "expanded_capabilities_by_candidate",
            "required_expanded_task_dependencies": "expanded_task_dependencies",
            "required_initial_task_dependencies": "initial_task_dependencies",
            "required_min_distinct_alternatives": "min_distinct_alternatives",
            "required_terminal_status": "terminal_status",
            "required_failure_semantics": "error_type",
            "required_trajectory": "trajectory",
        }.get(field, field.removeprefix("required_"))
        payload.setdefault(field, expected_key in payload)
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
    actual_error_type = _actual_error_type(run, predicted)
    expected_initial_dependencies = _dependency_set(expected.get("initial_task_dependencies"))
    expected_expanded_dependencies = _dependency_set(expected.get("expanded_task_dependencies"))
    predicted_initial_dependencies = _dependency_set(predicted.get("initial_task_dependencies"))
    predicted_expanded_dependencies = _dependency_set(predicted.get("expanded_task_dependencies"))
    initial_dependency_metric = _metric(
        predicted_initial_dependencies,
        expected_initial_dependencies,
        bool(oracle_payload.get("required_initial_task_dependencies", False)),
    )
    expanded_dependency_metric = _metric(
        predicted_expanded_dependencies,
        expected_expanded_dependencies,
        bool(oracle_payload.get("required_expanded_task_dependencies", False)),
    )
    dependency_metrics = [
        value for value in (initial_dependency_metric, expanded_dependency_metric) if value is not None
    ]
    dependency_accuracy = (
        None
        if not dependency_metrics
        else Decimal("1")
        if all(value == Decimal("1") for value in dependency_metrics)
        else Decimal("0")
    )
    expected_min_alternatives = expected.get("min_distinct_alternatives")
    minimum_alternatives_metric: Decimal | None = None
    if oracle_payload.get("required_min_distinct_alternatives", False):
        if isinstance(expected_min_alternatives, bool) or not isinstance(
            expected_min_alternatives, (int, str)
        ):
            minimum_alternatives_metric = None
        else:
            try:
                minimum = int(expected_min_alternatives)
            except ValueError:
                minimum_alternatives_metric = None
            else:
                minimum_alternatives_metric = _metric(
                    _distinct_alternative_count(predicted.get("alternatives", ())) >= minimum,
                    True,
                )
    expected_error_type = expected.get("error_type")
    observed = dict(predicted)
    for key in ("terminal_status", "trajectory"):
        if key not in observed and key in run:
            observed[key] = run[key]
    if "trajectory" not in observed:
        trajectory = _trajectory_from_run(run)
        if trajectory is not None:
            observed["trajectory"] = trajectory
    trajectory_required = bool(oracle_payload.get("required_trajectory", False)) or (
        "trajectory" in observed
    )
    metrics: dict[str, Decimal | None] = {
        "mode_accuracy": _metric(predicted.get("mode"), expected.get("mode")),
        "clarification_precision": _clarification_precision(predicted, expected),
        "clarification_recall": _clarification_recall(predicted, expected),
        "scope_exact_match": _metric(
            _string_set(predicted.get("scope")),
            _string_set(expected.get("scope")),
            bool(oracle_payload.get("required_scope", True)),
        ),
        "capability_exact_match": _metric(
            set(predicted.get("capabilities", [])), set(expected.get("capabilities", [])),
            bool(oracle_payload.get("required_capabilities", True)),
        ),
        "initial_task_dependency_exact_match": initial_dependency_metric,
        "expanded_scope_exact_match": _metric(
            _candidate_set_map(predicted.get("expanded_scope_by_candidate")),
            _candidate_set_map(expected.get("expanded_scope_by_candidate")),
            bool(oracle_payload.get("required_expanded_scope", False)),
        ),
        "expanded_capability_exact_match": _metric(
            _candidate_set_map(predicted.get("expanded_capabilities_by_candidate")),
            _candidate_set_map(expected.get("expanded_capabilities_by_candidate")),
            bool(oracle_payload.get("required_expanded_capabilities", False)),
        ),
        "expanded_task_dependency_exact_match": expanded_dependency_metric,
        "task_dependency_accuracy": dependency_accuracy,
        "candidate_pre_meeting_lodging_exact_match": _metric(
            predicted.get("lodging"),
            expected.get("lodging"),
            bool(oracle_payload.get("required_lodging", False)),
        ),
        "recommendation_grounding_rate": _metric(
            set(predicted.get("recommendation_evidence_types") or []),
            set(expected.get("recommendation_evidence_types") or []),
            bool(oracle_payload.get("required_evidence", False)),
        ),
        "alternative_diversity_pass_rate": alternative_diversity(
            tuple(item for item in predicted.get("alternatives", []) if isinstance(item, Mapping))
        ),
        "minimum_distinct_alternatives": minimum_alternatives_metric,
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
        "terminal_status_accuracy": _metric(
            observed.get("terminal_status"),
            expected.get("terminal_status"),
            bool(oracle_payload.get("required_terminal_status", False)),
        ),
        "failure_semantics_accuracy": _failure_semantics_metric(
            actual_error_type=actual_error_type,
            expected_error_type=expected_error_type,
            applicable=bool(oracle_payload.get("required_failure_semantics", False)),
        ),
        "trajectory_validity": (
            _trajectory_validity(observed, expected)
            if trajectory_required
            else None
        ),
        "forbidden_output_rate": _metric(
            not bool(_string_set(predicted.get("forbidden_outputs"))),
            True,
            bool(oracle_payload.get("required_forbidden_output_check", False)),
        ),
    }
    if availability is ComponentAvailability.NOT_IMPLEMENTED_IN_BASELINE:
        for name in (
            "scope_exact_match",
            "initial_task_dependency_exact_match",
            "expanded_scope_exact_match",
            "expanded_capability_exact_match",
            "expanded_task_dependency_exact_match",
            "task_dependency_accuracy",
            "trajectory_validity",
        ):
            metrics[name] = None
    applicable_metrics = [item for item in metrics.values() if item is not None]
    business_assertion = (
        BusinessAssertion.FAIL
        if availability is ComponentAvailability.NOT_IMPLEMENTED_IN_BASELINE
        or status is not RunStatus.COMPLETED
        or any(item != Decimal("1") for item in applicable_metrics)
        else BusinessAssertion.PASS
    )
    if business_assertion is BusinessAssertion.FAIL and first_failed is None:
        first_failed = _infer_first_failed_stage(metrics, availability)
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


def _infer_first_failed_stage(
    metrics: Mapping[str, Decimal | None],
    availability: ComponentAvailability,
) -> FirstFailedStage:
    """Attribute the first observable blocking metric to its owning stage."""
    if availability is ComponentAvailability.NOT_IMPLEMENTED_IN_BASELINE:
        return FirstFailedStage.SCOPE
    stage_metrics = (
        (FirstFailedStage.INTERPRETER, ("mode_accuracy", "clarification_precision", "clarification_recall")),
        (FirstFailedStage.SCOPE, ("scope_exact_match", "expanded_scope_exact_match")),
        (FirstFailedStage.ROUTER, ("capability_exact_match", "expanded_capability_exact_match")),
        (
            FirstFailedStage.TASK_GRAPH,
            (
                "initial_task_dependency_exact_match",
                "expanded_task_dependency_exact_match",
                "task_dependency_accuracy",
                "trajectory_validity",
            ),
        ),
        (
            FirstFailedStage.TOOL_OR_EVIDENCE,
            ("forbidden_output_rate", "evidence_coverage", "recommendation_grounding_rate"),
        ),
        (
            FirstFailedStage.PLANNING,
            ("candidate_pre_meeting_lodging_exact_match", "minimum_distinct_alternatives"),
        ),
        (FirstFailedStage.DELIVERY, ("terminal_status_accuracy", "failure_semantics_accuracy")),
    )
    for stage, names in stage_metrics:
        if any(metrics.get(name) == Decimal("0") for name in names):
            return stage
    return FirstFailedStage.INTERPRETER


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
