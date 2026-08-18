from __future__ import annotations

import json
from pathlib import Path

import pytest

from evaluation.manual_acceptance.artifacts import (
    ArtifactExistsError,
    UnsafeArtifactError,
    write_artifacts,
)
from evaluation.manual_acceptance.cases import load_case
from evaluation.manual_acceptance.contracts import (
    BusinessTransitionBaseline,
    HumanDecision,
    IndependentReviewResult,
    MachineAssertion,
    MutationResult,
    RunnerStatus,
    StageGateState,
)
from evaluation.manual_acceptance.review import parse_human_review, render_human_review
from evaluation.manual_acceptance.state import derive_stage_gate


def test_blocked_run_cannot_be_derived_as_accepted() -> None:
    state = derive_stage_gate(
        runner_status=RunnerStatus.BLOCKED,
        machine_assertion=MachineAssertion.PASS,
        mutation_result=MutationResult.PASS,
        independent_review_result=IndependentReviewResult.PASS,
        business_transition_baseline=BusinessTransitionBaseline.NOT_APPLICABLE,
        human_decision=HumanDecision.ACCEPTED,
        historical_contract_acceptance=HumanDecision.ACCEPTED,
    )

    assert state is StageGateState.BLOCKED


def test_accepted_gate_requires_all_independent_conditions() -> None:
    state = derive_stage_gate(
        runner_status=RunnerStatus.OBSERVATION_READY,
        machine_assertion=MachineAssertion.PASS,
        mutation_result=MutationResult.PASS,
        independent_review_result=IndependentReviewResult.PASS,
        business_transition_baseline=BusinessTransitionBaseline.BASELINE_FAIL,
        human_decision=HumanDecision.ACCEPTED,
        historical_contract_acceptance=HumanDecision.ACCEPTED,
    )

    assert state is StageGateState.ACCEPTED


def test_case_expected_is_loaded_without_actual_values() -> None:
    case = load_case(Path("evaluation/manual_cases/business-travel-v1/BT-ACC-001.json"))

    assert case.case_id == "BT-ACC-001"
    assert case.expected_key_fields["origin"] == "杭州"
    assert "actual" not in case.expected_key_fields


def test_artifacts_are_write_once(tmp_path: Path) -> None:
    payload = {
        "actual": {"route": "clarify"},
        "expected": {"route": "clarify"},
        "machine_checks": {"artifact_schema": "PASS"},
        "runtime": {"run_id": "run-1"},
        "observation": "# Observation\n",
        "human_review": "---\ndecision: PENDING\n---\n",
    }
    write_artifacts(tmp_path, payload)

    with pytest.raises(ArtifactExistsError):
        write_artifacts(tmp_path, payload)

    assert json.loads((tmp_path / "actual.json").read_text(encoding="utf-8")) == payload["actual"]


def test_human_review_starts_pending_and_round_trips(tmp_path: Path) -> None:
    case = load_case(Path("evaluation/manual_cases/business-travel-v1/BT-ACC-001.json"))
    content = render_human_review(case, run_id="run-1")
    path = tmp_path / "human-review.md"
    path.write_text(content, encoding="utf-8")

    review = parse_human_review(path)

    assert review.decision is HumanDecision.PENDING
    assert review.mutation_result is MutationResult.NOT_RUN
    assert review.independent_review_result is IndependentReviewResult.NOT_RUN
    assert review.run_id == "run-1"


def test_sensitive_artifact_content_is_rejected(tmp_path: Path) -> None:
    payload = {
        "actual": {"authorization": "Bearer secret"},
        "expected": {},
        "machine_checks": {},
        "runtime": {},
        "observation": "# Observation\n",
        "human_review": "---\ndecision: PENDING\n---\n",
    }

    with pytest.raises(UnsafeArtifactError):
        write_artifacts(tmp_path, payload)
