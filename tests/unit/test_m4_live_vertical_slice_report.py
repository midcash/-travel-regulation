"""M4 Live Vertical Slice report contract tests."""

from __future__ import annotations

from tests.support.m4_live_vertical_slice import M4LiveObservation, build_report


def _observation(*, case_id: str = "m4-live-normal", repetition: int = 1) -> M4LiveObservation:
    return M4LiveObservation(
        case_id=case_id,
        repetition=repetition,
        status="success",
        trace_id=f"trace:{case_id}:{repetition}",
        model="deepseek-chat",
        providers=("tuniu",),
        llm_calls=1,
        input_tokens=100,
        output_tokens=100,
        latency_ms=1000,
        tool_calls=3,
        model_calls=0,
        graph_task_count=3,
        candidate_count=3,
        plan_count=3,
        references_complete=True,
        hard_constraints_complete=True,
        hard_budget_within_limit=True,
    )


def test_m4_live_report_is_pending_before_manual_run() -> None:
    report = build_report(
        (),
        exit_status=0,
        configured_providers=(),
        model=None,
        run_executed=False,
    )

    assert report["stage"] == "M4"
    assert report["status"] == "PENDING_MANUAL_ACCEPTANCE"
    assert report["gate"] == "live_vertical_slice"


def test_m4_live_report_requires_all_repeat_cases_for_success() -> None:
    report = build_report(
        (_observation(),),
        exit_status=0,
        configured_providers=("tuniu",),
        model="deepseek-chat",
    )

    assert report["status"] == "FAILED"
    redaction = report["redaction"]
    assert isinstance(redaction, dict)
    assert redaction["credentials"] is False


def test_m4_live_report_accepts_complete_success_observations(monkeypatch) -> None:
    monkeypatch.setenv("DEEPSEEK_API_KEY", "test-key")
    monkeypatch.setenv("TUNIU_API_KEY", "test-key")
    observations = (
        _observation(case_id="m4-live-normal", repetition=1),
        _observation(case_id="m4-live-normal", repetition=2),
        _observation(case_id="m4-live-constraint", repetition=1),
        _observation(case_id="m4-live-complex", repetition=1),
    )
    report = build_report(
        observations,
        exit_status=0,
        configured_providers=("tuniu",),
        model="deepseek-chat",
    )

    assert report["status"] == "SUCCESS"
    budget = report["budget"]
    assert isinstance(budget, dict)
    assert budget["retry_count"] == 0
