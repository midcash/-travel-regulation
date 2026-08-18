from __future__ import annotations

import json
from pathlib import Path

import pytest

from evaluation.manual_acceptance.runner import run_manual_acceptance
from evaluation.manual_acceptance.verify import verify_artifact

CASES = (
    ("M0", "M0-ACC-001"),
    ("M1", "M1-ACC-001"),
    ("M2", "BT-ACC-001"),
    ("M2.1", "M2.1-ACC-001"),
    ("M3", "M3-ACC-001"),
    ("M4", "M4-ACC-001"),
    ("M4.1", "M4.1-ACC-001"),
)


@pytest.mark.integration
@pytest.mark.parametrize(("stage", "case_id"), CASES)
def test_offline_manual_acceptance_exposes_stage_boundary(
    stage: str,
    case_id: str,
    tmp_path: Path,
) -> None:
    artifact_dir = tmp_path / stage.replace(".", "")

    result = run_manual_acceptance(
        stage=stage,
        case_id=case_id,
        mode="offline",
        artifact_dir=artifact_dir,
        root=Path.cwd(),
    )

    actual = json.loads((artifact_dir / "actual.json").read_text(encoding="utf-8"))
    expected = json.loads((artifact_dir / "expected.json").read_text(encoding="utf-8"))
    verification = verify_artifact(artifact_dir)

    assert result.runner_status == "OBSERVATION_READY"
    assert verification.gate_open is False
    assert all(field in actual for field in expected["required_outputs"])

    if stage == "M2.1":
        event_names = [event["event"] for event in actual["events"]]
        assert "workflow_started" in event_names
        assert "workflow_completed" in event_names
    elif stage in {"M3", "M4"}:
        assert actual["public_route"] is True
        assert actual["task_graph"]
        assert actual["task_results"]
    elif stage == "M4.1":
        assert actual["status_distinction"]["business_assertion"] == "separate"
