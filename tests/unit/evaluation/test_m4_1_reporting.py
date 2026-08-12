from __future__ import annotations

from evaluation.business_travel.reporting import compare_reports, render_report


def test_same_report_self_diff_is_zero() -> None:
    report = {"metric_summary": {"pass_at_1": 0.5}, "cases": []}

    diff = compare_reports(report, report)

    assert diff.status == "COMPARABLE"
    assert diff.metric_changes == {"pass_at_1": 0.0}


def test_diff_rejects_different_configuration() -> None:
    baseline = {"runtime_fingerprint": "a", "metric_summary": {"pass_at_1": 0.5}}
    current = {"runtime_fingerprint": "b", "metric_summary": {"pass_at_1": 1.0}}

    diff = compare_reports(baseline, current)

    assert diff.status == "NON_COMPARABLE_CONFIGURATION"
    assert diff.metric_changes == {}


def test_missing_fingerprint_makes_reports_non_comparable() -> None:
    assert compare_reports(
        {"runtime_fingerprint": "same"},
        {"runtime_fingerprint": "same"},
    ).status == "NON_COMPARABLE_CONFIGURATION"


def test_report_redacts_credentials_prompt_and_supplier_payload() -> None:
    rendered = render_report(
        {
            "api_key": "secret",
            "prompt": "private",
            "supplier_payload": {"token": "secret-token"},
            "metric_summary": {"pass_at_1": 1.0},
        }
    )

    assert "secret" not in rendered
    assert "private" not in rendered
    assert "pass_at_1" in rendered
