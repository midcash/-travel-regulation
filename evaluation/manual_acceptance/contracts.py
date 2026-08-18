from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Any


class RunnerStatus(str, Enum):
    OBSERVATION_READY = "OBSERVATION_READY"
    BLOCKED = "BLOCKED"
    RUNTIME_FAILURE = "RUNTIME_FAILURE"
    EVALUATOR_ERROR = "EVALUATOR_ERROR"
    NON_ACCEPTANCE_RUN = "NON_ACCEPTANCE_RUN"


class MachineAssertion(str, Enum):
    PASS = "PASS"
    FAIL = "FAIL"
    NOT_RUN = "NOT_RUN"


class MutationResult(str, Enum):
    PASS = "PASS"
    FAIL = "FAIL"
    NOT_RUN = "NOT_RUN"


class IndependentReviewResult(str, Enum):
    PASS = "PASS"
    FAIL = "FAIL"
    NOT_RUN = "NOT_RUN"


class BusinessAssertion(str, Enum):
    PASS = "PASS"
    FAIL = "FAIL"
    NOT_SCORABLE = "NOT_SCORABLE"
    PENDING = "PENDING"


class HumanDecision(str, Enum):
    PENDING = "PENDING"
    ACCEPTED = "ACCEPTED"
    REJECTED = "REJECTED"
    BLOCKED = "BLOCKED"


class StageGateState(str, Enum):
    NOT_STARTED = "NOT_STARTED"
    RUNNING = "RUNNING"
    OBSERVATION_READY = "OBSERVATION_READY"
    HUMAN_REVIEW_PENDING = "HUMAN_REVIEW_PENDING"
    ACCEPTED = "ACCEPTED"
    REJECTED = "REJECTED"
    BLOCKED = "BLOCKED"


class BusinessTransitionBaseline(str, Enum):
    CAPTURED_PASS = "CAPTURED_PASS"
    BASELINE_FAIL = "BASELINE_FAIL"
    NOT_APPLICABLE = "NOT_APPLICABLE"


@dataclass(frozen=True, slots=True)
class ManualCase:
    case_id: str
    stage: str
    input: str
    reference_now: str
    expected_stage_behavior: str
    expected_key_fields: dict[str, Any]
    expected_failure_or_success_semantics: str
    human_assertions: tuple[str, ...]
    historical_contract_acceptance: HumanDecision
    business_transition_baseline: BusinessTransitionBaseline
    required_outputs: tuple[str, ...]
    mutation_target: str
    independent_review_prompt: str
