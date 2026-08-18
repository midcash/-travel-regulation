from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from evaluation.manual_acceptance.contracts import (
    BusinessTransitionBaseline,
    HumanDecision,
    MachineAssertion,
    RunnerStatus,
)
from evaluation.manual_acceptance.review import HumanReview, HumanReviewError, parse_human_review
from evaluation.manual_acceptance.state import derive_stage_gate


class ArtifactVerificationError(ValueError):
    """An acceptance artifact cannot be deterministically verified."""


@dataclass(frozen=True, slots=True)
class VerificationResult:
    stage: str
    case_id: str
    run_id: str
    runner_status: str
    machine_assertion: str
    stage_gate_state: str
    gate_open: bool


def verify_artifact(root: Path) -> VerificationResult:
    """Recompute the state machine from immutable outputs and review fields."""
    actual = _read_json(root / "actual.json")
    expected = _read_json(root / "expected.json")
    machine_checks = _read_json(root / "machine-checks.json")
    runtime = _read_json(root / "runtime.json")
    try:
        review = parse_human_review(root / "human-review.md")
    except HumanReviewError as exc:
        raise ArtifactVerificationError(str(exc)) from exc

    stage = _text(runtime, "stage")
    case_id = _text(runtime, "case_id")
    run_id = _text(runtime, "run_id")
    if stage != _text(expected, "stage") or case_id != _text(expected, "case_id"):
        raise ArtifactVerificationError("runtime and expected identity differ")
    if (review.stage, review.case_id, review.run_id) != (stage, case_id, run_id):
        raise ArtifactVerificationError("human review identity differs")
    if not actual:
        raise ArtifactVerificationError("actual output is empty")
    for field, expected_value in (
        ("run_id", run_id),
        ("stage", stage),
        ("case_id", case_id),
    ):
        if actual.get(field) != expected_value:
            raise ArtifactVerificationError(f"actual and runtime identity differ: {field}")
    if actual.get("acceptance_eligibility") != runtime.get("acceptance_eligibility"):
        raise ArtifactVerificationError("actual and runtime acceptance eligibility differ")

    try:
        runner_status = RunnerStatus(_text(runtime, "runner_status"))
        machine_assertion = MachineAssertion(_text(machine_checks, "machine_assertion"))
        baseline = BusinessTransitionBaseline(review.business_transition_baseline.value)
    except (TypeError, ValueError) as exc:
        raise ArtifactVerificationError("invalid derived state field") from exc

    expected_baseline = expected.get("business_transition_baseline")
    if expected_baseline != baseline.value:
        raise ArtifactVerificationError("business transition baseline was changed after run")

    required_outputs = expected.get("required_outputs", [])
    if not isinstance(required_outputs, list) or not all(
        isinstance(item, str) and item.strip() for item in required_outputs
    ):
        raise ArtifactVerificationError("expected required_outputs must be a string list")
    missing_outputs = [item for item in required_outputs if item not in actual]
    if missing_outputs:
        machine_assertion = MachineAssertion.FAIL

    acceptance_eligibility = _text(runtime, "acceptance_eligibility")
    if acceptance_eligibility not in {
        "ELIGIBLE",
        "NON_ACCEPTANCE_RUN",
        "OBSERVATION_ONLY",
    }:
        raise ArtifactVerificationError("invalid acceptance eligibility")
    if acceptance_eligibility != "ELIGIBLE":
        runner_status = RunnerStatus.NON_ACCEPTANCE_RUN

    human_decision = review.decision
    if review.decision is HumanDecision.ACCEPTED and not _human_review_complete(review):
        human_decision = HumanDecision.PENDING

    state = derive_stage_gate(
        runner_status=runner_status,
        machine_assertion=machine_assertion,
        mutation_result=review.mutation_result,
        independent_review_result=review.independent_review_result,
        business_transition_baseline=baseline,
        human_decision=human_decision,
        historical_contract_acceptance=review.historical_contract_acceptance,
    )
    return VerificationResult(
        stage=stage,
        case_id=case_id,
        run_id=run_id,
        runner_status=runner_status.value,
        machine_assertion=machine_assertion.value,
        stage_gate_state=state.value,
        gate_open=state.value == "ACCEPTED",
    )


def _read_json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ArtifactVerificationError(f"invalid JSON artifact: {path}") from exc
    if not isinstance(value, dict):
        raise ArtifactVerificationError(f"JSON artifact must be an object: {path}")
    return value


def _text(raw: dict[str, Any], field: str) -> str:
    value = raw.get(field)
    if not isinstance(value, str) or not value.strip():
        raise ArtifactVerificationError(f"missing text field: {field}")
    return value.strip()


def _human_review_complete(review: HumanReview) -> bool:
    return (
        review.reviewer.casefold() != "pending"
        and review.reviewed_at.casefold() != "pending"
        and bool(review.checked_assertions)
        and not review.reason.casefold().startswith("pending")
    )
