from __future__ import annotations

import pytest
from prometheus_client import REGISTRY, CollectorRegistry, Counter

from src.obs.metric import (
    MetricLabelError,
    record_clarification_blockers,
    record_interpreter_failure,
    record_legacy_review_issues,
    record_legacy_revision,
    record_llm_call,
    record_route_mode,
    record_stage,
    record_workflow_error,
    record_workflow_result,
    safe_increment,
    validate_metric_labels,
)


def _sample(name: str, labels: dict[str, str]) -> float:
    return float(REGISTRY.get_sample_value(name, labels=labels) or 0)


def test_metrics_expose_m21_aggregate_signals_with_allowlisted_labels() -> None:
    workflow_before = _sample("workflow_requests_total", {"status": "success"})
    stage_before = _sample(
        "workflow_stage_events_total", {"stage": "g0", "status": "completed"}
    )
    route_before = _sample("route_modes_total", {"mode": "clarify"})
    blocker_before = _sample(
        "clarification_blockers_total", {"blocker_code": "MISSING_ORIGIN"}
    )
    interpreter_before = _sample("interpreter_failures_total", {"kind": "parse"})
    error_before = _sample("workflow_errors_total", {"category": "validation"})
    llm_before = _sample("llm_calls_total", {"model": "deepseek-chat", "status": "success"})
    review_before = _sample("legacy_review_issues_total", {"source": "l1"})
    revision_before = _sample("legacy_revision_events_total", {"event": "requested"})

    record_workflow_result("success")
    record_workflow_error("validation")
    record_stage("g0", "completed", 10)
    record_route_mode("clarify")
    record_clarification_blockers(("MISSING_ORIGIN",))
    record_interpreter_failure("parse")
    record_llm_call(
        model="deepseek-chat",
        status="success",
        duration_ms=10,
        input_tokens=3,
        output_tokens=2,
        finish_reason="stop",
    )
    record_legacy_review_issues(l1_count=1, l2_count=0)
    record_legacy_revision("requested", round=1)

    assert _sample("workflow_requests_total", {"status": "success"}) == workflow_before + 1
    assert _sample("workflow_errors_total", {"category": "validation"}) == error_before + 1
    assert (
        _sample("workflow_stage_events_total", {"stage": "g0", "status": "completed"})
        == stage_before + 1
    )
    assert _sample("route_modes_total", {"mode": "clarify"}) == route_before + 1
    assert (
        _sample("clarification_blockers_total", {"blocker_code": "MISSING_ORIGIN"})
        == blocker_before + 1
    )
    assert _sample("interpreter_failures_total", {"kind": "parse"}) == interpreter_before + 1
    assert (
        _sample("llm_calls_total", {"model": "deepseek-chat", "status": "success"})
        == llm_before + 1
    )
    assert _sample("legacy_review_issues_total", {"source": "l1"}) == review_before + 1
    assert _sample("legacy_revision_events_total", {"event": "requested"}) == revision_before + 1


def test_metric_label_allowlist_rejects_high_cardinality_values() -> None:
    with pytest.raises(MetricLabelError):
        validate_metric_labels({"trace_id": "route:trip:req"})
    with pytest.raises(MetricLabelError):
        validate_metric_labels({"mode": "route-with-user-id"})

    registry = CollectorRegistry()
    collector = Counter(
        "test_high_cardinality_rejection_total",
        "test",
        ["trace_id"],
        registry=registry,
    )
    assert safe_increment(collector, trace_id="route:trip:req") is False
    assert registry.get_sample_value(
        "test_high_cardinality_rejection_total", {"trace_id": "route:trip:req"}
    ) is None


def test_metric_emission_failure_is_isolated_from_business_code() -> None:
    class BrokenCollector:
        _name = "broken_metric"
        _labelnames = ("status",)

        def labels(self, **labels: str) -> BrokenCollector:
            raise RuntimeError("exporter unavailable")

    assert safe_increment(BrokenCollector(), status="success") is False
