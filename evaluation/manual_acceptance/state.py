from __future__ import annotations

from evaluation.manual_acceptance.contracts import (
    BusinessTransitionBaseline,
    HumanDecision,
    IndependentReviewResult,
    MachineAssertion,
    MutationResult,
    RunnerStatus,
    StageGateState,
)


def derive_stage_gate(
    *,
    runner_status: RunnerStatus,
    machine_assertion: MachineAssertion,
    mutation_result: MutationResult,
    independent_review_result: IndependentReviewResult,
    business_transition_baseline: BusinessTransitionBaseline,
    human_decision: HumanDecision,
    historical_contract_acceptance: HumanDecision,
) -> StageGateState:
    """Derive the stage state; callers cannot force an accepted state."""
    if runner_status is not RunnerStatus.OBSERVATION_READY:
        return StageGateState.BLOCKED
    if human_decision is HumanDecision.BLOCKED:
        return StageGateState.BLOCKED
    if any(
        (
            human_decision is HumanDecision.REJECTED,
            historical_contract_acceptance is HumanDecision.REJECTED,
            machine_assertion is MachineAssertion.FAIL,
            mutation_result is MutationResult.FAIL,
            independent_review_result is IndependentReviewResult.FAIL,
        )
    ):
        return StageGateState.REJECTED
    if (
        human_decision is HumanDecision.ACCEPTED
        and historical_contract_acceptance is HumanDecision.ACCEPTED
        and machine_assertion is MachineAssertion.PASS
        and mutation_result is MutationResult.PASS
        and independent_review_result is IndependentReviewResult.PASS
        and business_transition_baseline
        in {
            BusinessTransitionBaseline.CAPTURED_PASS,
            BusinessTransitionBaseline.BASELINE_FAIL,
            BusinessTransitionBaseline.NOT_APPLICABLE,
        }
    ):
        return StageGateState.ACCEPTED
    return StageGateState.HUMAN_REVIEW_PENDING
