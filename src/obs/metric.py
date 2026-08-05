"""Low-cardinality Prometheus metrics for the local workflow.

Metrics are deliberately kept in-process for M2.1. They are an aggregate
signal only; request-level diagnosis remains in the structured log and Trace.
Every production emission goes through the safe helpers below so a rejected
label or exporter failure can never change the business result.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from prometheus_client import Counter, Gauge, Histogram

from src.obs.log import get_logger

logger = get_logger(__name__)


class MetricLabelError(ValueError):
    """Raised when a metric label is not in the explicit low-cardinality allowlist."""


_ALLOWED_STAGES = frozenset(
    {
        "g0",
        "interpreter",
        "constraint_service",
        "readiness_evaluator",
        "router",
        "state",
    }
)

LABEL_ALLOWLIST: dict[str, frozenset[str]] = {
    "agent": frozenset({"planner_a", "planner_a_revision", "legacy_critic", "request_interpreter"}),
    "blocker_code": frozenset(
        {
            "MISSING_ORIGIN",
            "MISSING_DESTINATION",
            "DATE_OR_DURATION_UNDETERMINED",
            "DATE_DURATION_CONFLICT",
            "TRAVELER_COUNT_UNDETERMINED",
            "SPECIAL_POPULATION_UNDETERMINED",
            "BUDGET_SEMANTIC_CONFLICT",
            "CONSTRAINT_CONFLICT",
            "ACTION_AUTHORIZATION_REQUIRED",
            "ACTION_IDENTITY_REQUIRED",
            "CURRENT_PLAN_REQUIRED",
        }
    ),
    "category": frozenset(
        {
            "validation",
            "configuration",
            "llm",
            "tool",
            "evidence",
            "budget",
            "timeout",
            "state_conflict",
            "security",
            "internal",
        }
    ),
    "candidate_kind": frozenset({"transport", "stay", "place", "context"}),
    "candidate_outcome": frozenset({"accepted", "rejected"}),
    "event": frozenset({"requested", "completed", "exhausted"}),
    "evidence_status": frozenset({"verified", "conflicting", "stale", "unavailable"}),
    "finish_reason": frozenset(
        {"stop", "length", "tool_calls", "function_call", "content_filter", "unknown"}
    ),
    "kind": frozenset({"parse", "schema"}),
    "mode": frozenset(
        {"answer", "clarify", "plan", "refine", "compare", "replan", "action", "unsupported"}
    ),
    "model": frozenset({"deepseek-chat", "deepseek-reasoner", "deepseek-v4-flash"}),
    "operation": frozenset({"geo_search", "transport_search", "stay_search", "place_search"}),
    "phase": frozenset({"generation", "review", "revision"}),
    "provider": frozenset({"amap", "tuniu"}),
    "reject_code": frozenset(
        {
            "evidence_missing",
            "evidence_not_verified",
            "hard_constraint_violation",
            "hard_constraint_data_missing",
        }
    ),
    "reason": frozenset({"l2_review"}),
    "source": frozenset({"l1", "l2"}),
    "stage": _ALLOWED_STAGES,
    "status": frozenset({"success", "failure", "started", "completed", "requested", "failed"}),
    "type": frozenset({"input", "output"}),
}

# Kept as an alias for callers that used the private name while this module
# was being introduced during the earlier observability steps.
_LABEL_ALLOWLIST = LABEL_ALLOWLIST


def validate_metric_labels(labels: Mapping[str, object]) -> None:
    """Reject unknown or high-cardinality labels before they reach Prometheus."""
    for name, value in labels.items():
        if name not in LABEL_ALLOWLIST:
            raise MetricLabelError(f"metric label is not allowlisted: {name}")
        if name.endswith("_id") or name in {"trace_id", "request_id", "trip_id", "session_id"}:
            raise MetricLabelError(f"high-cardinality metric label is forbidden: {name}")
        if not isinstance(value, str):
            raise MetricLabelError(f"metric label must be a string: {name}")
        if value not in LABEL_ALLOWLIST[name]:
            raise MetricLabelError(f"metric label value is not allowlisted: {name}={value}")


def _metric_name(metric: Any) -> str:
    name = getattr(metric, "_name", None)
    return name if isinstance(name, str) else type(metric).__name__


def _validate_collector_labels(metric: Any, labels: Mapping[str, object]) -> None:
    expected = tuple(getattr(metric, "_labelnames", ()))
    if set(expected) != set(labels):
        raise MetricLabelError(
            f"metric labels do not match {_metric_name(metric)}: expected {expected}"
        )
    validate_metric_labels(labels)


def _report_emit_failure(metric: Any, exc: BaseException) -> None:
    """Report telemetry failure without allowing the warning path to escape."""
    try:
        logger.warning(
            "observability_emit_failed",
            metric=_metric_name(metric),
            error_type=type(exc).__name__,
        )
    except Exception:
        return


def safe_increment(metric: Any, *, amount: float = 1, **labels: str) -> bool:
    """Increment a metric without allowing telemetry failures to escape."""
    try:
        _validate_collector_labels(metric, labels)
        child = metric.labels(**labels) if labels else metric
        child.inc(amount)
    except Exception as exc:  # pragma: no cover - exercised through the public guard tests
        _report_emit_failure(metric, exc)
        return False
    return True


def safe_observe(metric: Any, value: float, **labels: str) -> bool:
    """Observe a histogram value without changing the workflow on failure."""
    try:
        _validate_collector_labels(metric, labels)
        child = metric.labels(**labels) if labels else metric
        child.observe(value)
    except Exception as exc:  # pragma: no cover - exercised through the public guard tests
        _report_emit_failure(metric, exc)
        return False
    return True


# ---- M2.0 compatibility metrics ----

AGENT_CALLS_TOTAL = Counter(
    "agent_calls_total",
    "Agent 调用总次数",
    ["agent", "status"],
)

AGENT_DURATION_SECONDS = Histogram(
    "agent_duration_seconds",
    "Agent 执行耗时（秒）",
    ["agent"],
    buckets=[0.1, 0.5, 1, 2, 5, 10, 30, 60],
)

LLM_CALLS_TOTAL = Counter(
    "llm_calls_total",
    "LLM API 调用总次数",
    ["model", "status"],
)

LLM_TOKENS_TOTAL = Counter(
    "llm_tokens_total",
    "LLM Token 消耗总量",
    ["model", "type"],
)

LLM_DURATION_SECONDS = Histogram(
    "llm_duration_seconds",
    "LLM API 调用耗时（秒）",
    ["model"],
    buckets=[1, 2, 5, 10, 20, 30, 60, 120],
)

PHASE_DURATION_SECONDS = Histogram(
    "phase_duration_seconds",
    "各 Phase 执行耗时（秒）",
    ["phase"],
    buckets=[0.01, 0.1, 0.5, 1, 2, 5, 10, 30, 60],
)

RETRY_COUNT_TOTAL = Counter(
    "retry_count_total",
    "重试总次数",
    ["agent", "reason"],
)

CURRENT_SESSION_GAUGE = Gauge(
    "current_session_phase",
    "当前活跃会话的阶段（兼容指标；使用低基数 phase）",
    ["phase"],
)


# ---- M2.1 aggregate metrics ----

WORKFLOW_REQUESTS_TOTAL = Counter(
    "workflow_requests_total",
    "Workflow 请求总次数",
    ["status"],
)

WORKFLOW_ERRORS_TOTAL = Counter(
    "workflow_errors_total",
    "Workflow 安全错误分类总次数",
    ["category"],
)

WORKFLOW_STAGE_EVENTS_TOTAL = Counter(
    "workflow_stage_events_total",
    "Workflow 阶段完成/失败总次数",
    ["stage", "status"],
)

WORKFLOW_STAGE_DURATION_SECONDS = Histogram(
    "workflow_stage_duration_seconds",
    "Workflow 阶段耗时（秒）",
    ["stage"],
    buckets=[0.001, 0.01, 0.1, 0.5, 1, 2, 5, 10, 30, 60],
)

ROUTE_MODES_TOTAL = Counter(
    "route_modes_total",
    "Router 模式选择总次数",
    ["mode"],
)

CLARIFICATION_BLOCKERS_TOTAL = Counter(
    "clarification_blockers_total",
    "Clarification blocker 总次数",
    ["blocker_code"],
)

INTERPRETER_FAILURES_TOTAL = Counter(
    "interpreter_failures_total",
    "Interpreter Schema/解析失败总次数",
    ["kind"],
)

LLM_FINISH_REASONS_TOTAL = Counter(
    "llm_finish_reasons_total",
    "LLM finish reason 总次数",
    ["finish_reason"],
)

LEGACY_REVIEW_ISSUES_TOTAL = Counter(
    "legacy_review_issues_total",
    "Legacy L1/L2 问题总次数",
    ["source"],
)

LEGACY_REVISION_EVENTS_TOTAL = Counter(
    "legacy_revision_events_total",
    "Legacy revision 请求/完成/耗尽总次数",
    ["event"],
)

LEGACY_REVISION_ROUNDS = Histogram(
    "legacy_revision_rounds",
    "Legacy revision 轮次",
    ["event"],
    buckets=[0, 1, 2, 3, 5, 8, 13],
)


# ---- M3 aggregate metrics ----

TOOL_CALLS_TOTAL = Counter(
    "tool_calls_total",
    "M3 Provider 工具调用总次数",
    ["provider", "operation", "status"],
)

TOOL_DURATION_SECONDS = Histogram(
    "tool_duration_seconds",
    "M3 Provider 工具调用耗时（秒）",
    ["provider", "operation"],
    buckets=[0.001, 0.01, 0.1, 0.5, 1, 2, 5, 10, 30, 60],
)

EVIDENCE_ITEMS_TOTAL = Counter(
    "evidence_items_total",
    "Evidence 快照中的证据状态总数",
    ["evidence_status"],
)

EVIDENCE_SNAPSHOTS_TOTAL = Counter(
    "evidence_snapshots_total",
    "Evidence 快照生成总次数",
)

EVIDENCE_SNAPSHOT_COVERAGE_RATIO = Histogram(
    "evidence_snapshot_coverage_ratio",
    "Evidence 快照事实覆盖率",
    buckets=[0, 0.25, 0.5, 0.75, 0.9, 1],
)

EVIDENCE_SNAPSHOT_FRESHNESS_RATIO = Histogram(
    "evidence_snapshot_freshness_ratio",
    "Evidence 快照新鲜度比例",
    buckets=[0, 0.25, 0.5, 0.75, 0.9, 1],
)

EVIDENCE_CONFLICTS_TOTAL = Counter(
    "evidence_conflicts_total",
    "Evidence 快照冲突引用总数",
)

EVIDENCE_MISSING_TOTAL = Counter(
    "evidence_missing_total",
    "Evidence 快照缺失事实类型总数",
)

CANDIDATE_POOL_CANDIDATES_TOTAL = Counter(
    "candidate_pool_candidates_total",
    "Candidate Pool 入选/拒绝候选总数",
    ["candidate_kind", "candidate_outcome"],
)

CANDIDATE_POOL_REJECTIONS_TOTAL = Counter(
    "candidate_pool_rejections_total",
    "Candidate Pool 结构化拒绝原因总数",
    ["reject_code"],
)

CANDIDATE_POOL_DEFERRED_CONSTRAINTS_TOTAL = Counter(
    "candidate_pool_deferred_constraints_total",
    "Candidate Pool 延后处理的硬约束总数",
)


def record_workflow_result(status: str) -> None:
    """Record a successful or failed workflow request."""
    safe_increment(WORKFLOW_REQUESTS_TOTAL, status=status)


def record_workflow_error(category: str) -> None:
    """Record a low-cardinality workflow error category."""
    safe_increment(WORKFLOW_ERRORS_TOTAL, category=category)


def record_stage(stage: str, status: str, duration_ms: int) -> None:
    """Record one M2.1 stage outcome and duration."""
    safe_increment(WORKFLOW_STAGE_EVENTS_TOTAL, stage=stage, status=status)
    safe_observe(WORKFLOW_STAGE_DURATION_SECONDS, max(duration_ms, 0) / 1000, stage=stage)


def record_route_mode(mode: str) -> None:
    """Record one router mode without request identifiers."""
    safe_increment(ROUTE_MODES_TOTAL, mode=mode)


def record_clarification_blockers(blocker_codes: tuple[str, ...]) -> None:
    """Record blocker occurrences for aggregate clarification analysis."""
    for code in blocker_codes:
        safe_increment(CLARIFICATION_BLOCKERS_TOTAL, blocker_code=code)


def record_interpreter_failure(kind: str) -> None:
    """Record whether interpreter output failed parsing or schema validation."""
    safe_increment(INTERPRETER_FAILURES_TOTAL, kind=kind)


def record_agent_call(agent: str, status: str, duration_ms: int) -> None:
    """Record a legacy agent call using only allowlisted labels."""
    safe_increment(AGENT_CALLS_TOTAL, agent=agent, status=status)
    safe_observe(AGENT_DURATION_SECONDS, max(duration_ms, 0) / 1000, agent=agent)


def record_retry(agent: str, reason: str) -> None:
    """Record a bounded revision/retry reason."""
    safe_increment(RETRY_COUNT_TOTAL, agent=agent, reason=reason)


def record_llm_call(
    *,
    model: str,
    status: str,
    duration_ms: int,
    input_tokens: int = 0,
    output_tokens: int = 0,
    finish_reason: str | None = None,
) -> None:
    """Record LLM aggregate metrics with a bounded model and finish reason."""
    safe_increment(LLM_CALLS_TOTAL, model=model, status=status)
    safe_observe(LLM_DURATION_SECONDS, max(duration_ms, 0) / 1000, model=model)
    if status == "success":
        safe_increment(LLM_TOKENS_TOTAL, model=model, type="input", amount=max(input_tokens, 0))
        safe_increment(LLM_TOKENS_TOTAL, model=model, type="output", amount=max(output_tokens, 0))
        safe_increment(LLM_FINISH_REASONS_TOTAL, finish_reason=finish_reason or "unknown")


def record_legacy_review_issues(*, l1_count: int, l2_count: int) -> None:
    """Record L1 and L2 issue counts separately."""
    safe_increment(LEGACY_REVIEW_ISSUES_TOTAL, source="l1", amount=max(l1_count, 0))
    safe_increment(LEGACY_REVIEW_ISSUES_TOTAL, source="l2", amount=max(l2_count, 0))


def record_legacy_revision(event: str, *, round: int | None = None) -> None:
    """Record revision lifecycle events and the observed round when available."""
    safe_increment(LEGACY_REVISION_EVENTS_TOTAL, event=event)
    if round is not None:
        safe_observe(LEGACY_REVISION_ROUNDS, max(round, 0), event=event)


def record_tool_call(
    *, provider: str, operation: str, status: str, duration_ms: int
) -> None:
    """记录一次 Provider 调用，不携带查询、追踪或供应商原始标识。"""
    safe_increment(TOOL_CALLS_TOTAL, provider=provider, operation=operation, status=status)
    safe_observe(
        TOOL_DURATION_SECONDS,
        max(duration_ms, 0) / 1000,
        provider=provider,
        operation=operation,
    )


def record_evidence_snapshot(
    *,
    statuses: tuple[str, ...],
    coverage: float,
    freshness: float,
    conflict_count: int,
    missing_count: int,
) -> None:
    """记录 Evidence 快照质量信号，不把 fact type 或 evidence ID 作为标签。"""
    safe_increment(EVIDENCE_SNAPSHOTS_TOTAL)
    for status in statuses:
        safe_increment(EVIDENCE_ITEMS_TOTAL, evidence_status=status)
    safe_observe(EVIDENCE_SNAPSHOT_COVERAGE_RATIO, _bounded_ratio(coverage))
    safe_observe(EVIDENCE_SNAPSHOT_FRESHNESS_RATIO, _bounded_ratio(freshness))
    if conflict_count > 0:
        safe_increment(EVIDENCE_CONFLICTS_TOTAL, amount=conflict_count)
    if missing_count > 0:
        safe_increment(EVIDENCE_MISSING_TOTAL, amount=missing_count)


def record_candidate_pool(
    *,
    accepted_kinds: tuple[str, ...],
    rejected_kinds: tuple[str, ...],
    rejection_codes: tuple[str, ...],
    deferred_constraint_count: int,
) -> None:
    """记录 Candidate Pool 聚合结果，拒绝使用候选 ID 和约束 ID。"""
    for kind in accepted_kinds:
        safe_increment(
            CANDIDATE_POOL_CANDIDATES_TOTAL,
            candidate_kind=kind,
            candidate_outcome="accepted",
        )
    for kind in rejected_kinds:
        safe_increment(
            CANDIDATE_POOL_CANDIDATES_TOTAL,
            candidate_kind=kind,
            candidate_outcome="rejected",
        )
    for code in rejection_codes:
        safe_increment(CANDIDATE_POOL_REJECTIONS_TOTAL, reject_code=code)
    if deferred_constraint_count > 0:
        safe_increment(
            CANDIDATE_POOL_DEFERRED_CONSTRAINTS_TOTAL,
            amount=deferred_constraint_count,
        )


def _bounded_ratio(value: float) -> float:
    """将观测比例限制在 Prometheus 直方图契约范围内。"""
    return min(max(float(value), 0.0), 1.0)
