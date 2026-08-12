from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from evaluation.business_travel.fingerprints import normalize_for_fingerprint


@dataclass(frozen=True, slots=True)
class ReportDiff:
    status: str
    metric_changes: dict[str, float]


def compare_reports(baseline: dict[str, Any], current: dict[str, Any]) -> ReportDiff:
    fingerprints = (
        "runtime_fingerprint",
        "dataset_fingerprint",
        "policy_fingerprint",
        "view_fixture_fingerprint",
    )
    if not baseline and not current:
        return ReportDiff("COMPARABLE", {})
    if all(
        fingerprint not in baseline and fingerprint not in current
        for fingerprint in fingerprints
    ):
        baseline_metrics = baseline.get("metric_summary", {})
        current_metrics = current.get("metric_summary", {})
        if isinstance(baseline_metrics, dict) and isinstance(current_metrics, dict):
            keys = sorted(set(baseline_metrics) | set(current_metrics))
            return ReportDiff(
                "COMPARABLE",
                {
                    key: float(current_metrics.get(key, 0))
                    - float(baseline_metrics.get(key, 0))
                    for key in keys
                },
            )
    if any(
        fingerprint not in baseline or fingerprint not in current
        for fingerprint in fingerprints
    ):
        return ReportDiff("NON_COMPARABLE_CONFIGURATION", {})
    for fingerprint in fingerprints:
        if baseline[fingerprint] != current[fingerprint]:
            return ReportDiff("NON_COMPARABLE_CONFIGURATION", {})
    baseline_metrics = baseline.get("metric_summary", {})
    current_metrics = current.get("metric_summary", {})
    if not isinstance(baseline_metrics, dict) or not isinstance(current_metrics, dict):
        return ReportDiff("EVALUATOR_ERROR", {})
    keys = sorted(set(baseline_metrics) | set(current_metrics))
    return ReportDiff(
        "COMPARABLE",
        {
            key: float(current_metrics.get(key, 0)) - float(baseline_metrics.get(key, 0))
            for key in keys
        },
    )


def render_report(report: dict[str, Any]) -> str:
    safe = normalize_for_fingerprint(report)
    metrics = safe.get("metric_summary", {}) if isinstance(safe, dict) else {}
    lines = ["# M4.1 Evaluation Report", "", "## Metric summary", ""]
    if isinstance(metrics, dict):
        lines.extend(f"- `{key}`: {value}" for key, value in sorted(metrics.items()))
    for title, key in (
        ("Failure distribution", "failure_distribution"),
        ("Latency summary", "latency_summary"),
        ("Cost summary", "cost_summary"),
    ):
        section = safe.get(key) if isinstance(safe, dict) else None
        if isinstance(section, dict):
            lines.extend(["", f"## {title}", ""])
            lines.extend(f"- `{item_key}`: {value}" for item_key, value in sorted(section.items()))
    return "\n".join(lines) + "\n"
