from __future__ import annotations

import pytest
from prometheus_client import REGISTRY

from src.obs.metric import (
    MetricLabelError,
    record_candidate_pool,
    record_evidence_snapshot,
    record_tool_call,
    validate_metric_labels,
)


def _sample(name: str, labels: dict[str, str] | None = None) -> float:
    return float(REGISTRY.get_sample_value(name, labels=labels or {}) or 0)


def test_m3_tool_metrics_record_one_call_and_duration_without_ids() -> None:
    calls_before = _sample(
        "tool_calls_total",
        {"provider": "amap", "operation": "geo_search", "status": "success"},
    )
    duration_before = _sample(
        "tool_duration_seconds_count",
        {"provider": "amap", "operation": "geo_search"},
    )

    record_tool_call(
        provider="amap",
        operation="geo_search",
        status="success",
        duration_ms=12,
    )

    assert (
        _sample(
            "tool_calls_total",
            {"provider": "amap", "operation": "geo_search", "status": "success"},
        )
        == calls_before + 1
    )
    assert (
        _sample(
            "tool_duration_seconds_count",
            {"provider": "amap", "operation": "geo_search"},
        )
        == duration_before + 1
    )


def test_m3_evidence_metrics_record_quality_dimensions_without_fact_labels() -> None:
    snapshots_before = _sample("evidence_snapshots_total")
    verified_before = _sample("evidence_items_total", {"evidence_status": "verified"})
    conflicts_before = _sample("evidence_conflicts_total")
    missing_before = _sample("evidence_missing_total")
    coverage_before = _sample("evidence_snapshot_coverage_ratio_count")

    record_evidence_snapshot(
        statuses=("verified", "stale", "conflicting"),
        coverage=0.5,
        freshness=0.333,
        conflict_count=1,
        missing_count=2,
    )

    assert _sample("evidence_snapshots_total") == snapshots_before + 1
    assert _sample("evidence_items_total", {"evidence_status": "verified"}) == verified_before + 1
    assert _sample("evidence_conflicts_total") == conflicts_before + 1
    assert _sample("evidence_missing_total") == missing_before + 2
    assert _sample("evidence_snapshot_coverage_ratio_count") == coverage_before + 1


def test_m3_candidate_metrics_record_partition_and_rejection_reasons() -> None:
    accepted_before = _sample(
        "candidate_pool_candidates_total",
        {"candidate_kind": "place", "candidate_outcome": "accepted"},
    )
    rejected_before = _sample(
        "candidate_pool_candidates_total",
        {"candidate_kind": "stay", "candidate_outcome": "rejected"},
    )
    reason_before = _sample(
        "candidate_pool_rejections_total",
        {"reject_code": "evidence_missing"},
    )
    deferred_before = _sample("candidate_pool_deferred_constraints_total")

    record_candidate_pool(
        accepted_kinds=("place",),
        rejected_kinds=("stay",),
        rejection_codes=("evidence_missing", "hard_constraint_violation"),
        deferred_constraint_count=2,
    )

    assert (
        _sample(
            "candidate_pool_candidates_total",
            {"candidate_kind": "place", "candidate_outcome": "accepted"},
        )
        == accepted_before + 1
    )
    assert (
        _sample(
            "candidate_pool_candidates_total",
            {"candidate_kind": "stay", "candidate_outcome": "rejected"},
        )
        == rejected_before + 1
    )
    assert (
        _sample(
            "candidate_pool_rejections_total",
            {"reject_code": "evidence_missing"},
        )
        == reason_before + 1
    )
    assert _sample("candidate_pool_deferred_constraints_total") == deferred_before + 2


def test_m3_metric_allowlist_rejects_provider_ids_and_unknown_dimensions() -> None:
    with pytest.raises(MetricLabelError):
        validate_metric_labels({"provider": "provider-with-secret"})
    with pytest.raises(MetricLabelError):
        validate_metric_labels({"operation": "query-with-user-id"})
    with pytest.raises(MetricLabelError):
        validate_metric_labels({"evidence_status": "evidence-123"})
