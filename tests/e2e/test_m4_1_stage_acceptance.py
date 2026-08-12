from __future__ import annotations

from pathlib import Path

from evaluation.stage_acceptance import run_stage_acceptance


def test_offline_stage_acceptance_runs_two_deterministic_baselines() -> None:
    result = run_stage_acceptance(stage="M4.1", mode="offline", root=Path("."))

    assert result.exit_code == 0
    assert result.checks["dataset_contract"] == "PASS"
    assert result.checks["offline_determinism"] == "PASS"
    assert result.checks["m4_before"] == "PASS"
    assert result.live_status is None


def test_invalid_stage_and_mode_return_nonzero() -> None:
    invalid_stage = run_stage_acceptance(stage="M4.0", mode="offline", root=Path("."))
    invalid_mode = run_stage_acceptance(stage="M4.1", mode="network", root=Path("."))

    assert invalid_stage.exit_code != 0
    assert invalid_mode.exit_code != 0


def test_live_failure_cannot_be_masked_by_old_success_artifact(monkeypatch) -> None:
    monkeypatch.setattr("evaluation.stage_acceptance.source_tree_status", lambda _: "clean")
    monkeypatch.setattr(
        "evaluation.stage_acceptance.run_live_semantic_from_environment",
        lambda: type("Live", (), {"status": "LIVE_ATTEMPT_RECORDED", "exit_code": 1})(),
    )
    result = run_stage_acceptance(stage="M4.1", mode="all", root=Path("."))

    assert result.exit_code != 0
    assert result.live_status == "LIVE_ATTEMPT_RECORDED"
