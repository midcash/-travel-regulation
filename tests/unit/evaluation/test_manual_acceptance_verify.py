from __future__ import annotations

from pathlib import Path

from evaluation.manual_acceptance.artifacts import write_artifacts
from evaluation.manual_acceptance.verify import verify_artifact


def _payload(*, decision: str = "PENDING") -> dict[str, object]:
    return {
        "actual": {
            "run_id": "run-1",
            "stage": "M2",
            "case_id": "BT-ACC-001",
            "acceptance_eligibility": "ELIGIBLE",
            "route": "clarify",
        },
        "expected": {
            "stage": "M2",
            "case_id": "BT-ACC-001",
            "business_transition_baseline": "BASELINE_FAIL",
            "required_outputs": ["route"],
        },
        "machine_checks": {
            "machine_assertion": "PASS",
            "artifact_schema": "PASS",
        },
        "runtime": {
            "run_id": "run-1",
            "stage": "M2",
            "case_id": "BT-ACC-001",
            "runner_status": "OBSERVATION_READY",
            "acceptance_eligibility": "ELIGIBLE",
        },
        "observation": "# Observation\n",
        "human_review": (
            "---\n"
            "stage: M2\n"
            "case_id: BT-ACC-001\n"
            "run_id: run-1\n"
            "reviewer: pending\n"
            "reviewed_at: pending\n"
            "checked_assertions: []\n"
            "observed_differences: []\n"
            "mutation_result: NOT_RUN\n"
            "independent_review_result: NOT_RUN\n"
            "historical_contract_acceptance: PENDING\n"
            "business_transition_baseline: BASELINE_FAIL\n"
            f"decision: {decision}\n"
            "reason: pending\n"
            "---\n"
        ),
    }


def _complete_review(payload: dict[str, object]) -> None:
    payload["human_review"] = (
        str(payload["human_review"])
        .replace("reviewer: pending", "reviewer: maintainer")
        .replace(
            "reviewed_at: pending",
            'reviewed_at: "2026-08-17T12:00:00+08:00"',
        )
        .replace("checked_assertions: []", 'checked_assertions: ["checked"]')
        .replace("reason: pending", "reason: completed manual review")
        .replace("mutation_result: NOT_RUN", "mutation_result: PASS")
        .replace("independent_review_result: NOT_RUN", "independent_review_result: PASS")
        .replace(
            "historical_contract_acceptance: PENDING", "historical_contract_acceptance: ACCEPTED"
        )
    )


def test_verify_reports_pending_without_opening_gate(tmp_path: Path) -> None:
    write_artifacts(tmp_path, _payload())

    result = verify_artifact(tmp_path)

    assert result.stage_gate_state == "HUMAN_REVIEW_PENDING"
    assert result.gate_open is False


def test_verify_recomputes_gate_from_review_fields(tmp_path: Path) -> None:
    payload = _payload(decision="ACCEPTED")
    _complete_review(payload)
    write_artifacts(tmp_path, payload)

    result = verify_artifact(tmp_path)

    assert result.stage_gate_state == "ACCEPTED"
    assert result.gate_open is True


def test_verify_uses_runtime_status_even_when_review_says_accepted(tmp_path: Path) -> None:
    payload = _payload(decision="ACCEPTED")
    payload["runtime"] = {
        **payload["runtime"],
        "runner_status": "BLOCKED",
    }
    payload["human_review"] = (
        str(payload["human_review"])
        .replace("mutation_result: NOT_RUN", "mutation_result: PASS")
        .replace("independent_review_result: NOT_RUN", "independent_review_result: PASS")
        .replace(
            "historical_contract_acceptance: PENDING", "historical_contract_acceptance: ACCEPTED"
        )
    )
    write_artifacts(tmp_path, payload)

    result = verify_artifact(tmp_path)

    assert result.stage_gate_state == "BLOCKED"
    assert result.gate_open is False


def test_verify_blocks_non_acceptance_run_even_when_review_says_accepted(
    tmp_path: Path,
) -> None:
    payload = _payload(decision="ACCEPTED")
    payload["runtime"] = {
        **payload["runtime"],
        "acceptance_eligibility": "NON_ACCEPTANCE_RUN",
    }
    payload["actual"] = {
        **payload["actual"],
        "acceptance_eligibility": "NON_ACCEPTANCE_RUN",
    }
    _complete_review(payload)
    write_artifacts(tmp_path, payload)

    result = verify_artifact(tmp_path)

    assert result.runner_status == "NON_ACCEPTANCE_RUN"
    assert result.stage_gate_state == "BLOCKED"
    assert result.gate_open is False


def test_verify_recomputes_required_outputs_after_actual_is_mutated(
    tmp_path: Path,
) -> None:
    payload = _payload(decision="ACCEPTED")
    _complete_review(payload)
    payload["actual"] = {
        "run_id": "run-1",
        "stage": "M2",
        "case_id": "BT-ACC-001",
        "acceptance_eligibility": "ELIGIBLE",
    }
    write_artifacts(tmp_path, payload)

    result = verify_artifact(tmp_path)

    assert result.machine_assertion == "FAIL"
    assert result.stage_gate_state == "REJECTED"
    assert result.gate_open is False


def test_verify_requires_completed_human_record_before_acceptance(
    tmp_path: Path,
) -> None:
    payload = _payload(decision="ACCEPTED")
    payload["human_review"] = (
        str(payload["human_review"])
        .replace("mutation_result: NOT_RUN", "mutation_result: PASS")
        .replace("independent_review_result: NOT_RUN", "independent_review_result: PASS")
        .replace(
            "historical_contract_acceptance: PENDING", "historical_contract_acceptance: ACCEPTED"
        )
    )
    write_artifacts(tmp_path, payload)

    result = verify_artifact(tmp_path)

    assert result.stage_gate_state == "HUMAN_REVIEW_PENDING"
    assert result.gate_open is False
