from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from enum import Enum
from typing import Generic, TypeVar

from pydantic import BaseModel, ConfigDict, Field, model_validator

from src.domain.models.enums import InteractionMode


class _FrozenModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class OracleStatus(str, Enum):
    VALUE = "value"
    NOT_APPLICABLE = "not_applicable"


class RunStatus(str, Enum):
    COMPLETED = "COMPLETED"
    EXTERNAL_FAILURE = "EXTERNAL_FAILURE"
    EVALUATOR_ERROR = "EVALUATOR_ERROR"
    NON_ACCEPTANCE_RUN = "NON_ACCEPTANCE_RUN"


class ComponentAvailability(str, Enum):
    IMPLEMENTED = "IMPLEMENTED"
    NOT_IMPLEMENTED_IN_BASELINE = "NOT_IMPLEMENTED_IN_BASELINE"
    NOT_APPLICABLE = "NOT_APPLICABLE"


class BusinessAssertion(str, Enum):
    PASS = "PASS"
    FAIL = "FAIL"
    NOT_SCORABLE = "NOT_SCORABLE"


class EvalView(str, Enum):
    COMPONENT = "component"
    INTEGRATION = "integration"
    LIVE_BLOCKING = "live_blocking"
    LIVE_OBSERVATION = "live_observation"


class FirstFailedStage(str, Enum):
    INPUT_CONTRACT = "INPUT_CONTRACT"
    INTERPRETER = "INTERPRETER"
    SCOPE = "SCOPE"
    ROUTER = "ROUTER"
    TASK_GRAPH = "TASK_GRAPH"
    TOOL_OR_EVIDENCE = "TOOL_OR_EVIDENCE"
    CANDIDATE_NORMALIZATION = "CANDIDATE_NORMALIZATION"
    PLANNING = "PLANNING"
    DELIVERY = "DELIVERY"
    EXTERNAL_DEPENDENCY = "EXTERNAL_DEPENDENCY"
    EVALUATOR = "EVALUATOR"


class FailureCategory(str, Enum):
    BUSINESS = "BUSINESS_FAILURE"
    EXTERNAL_DEPENDENCY = "EXTERNAL_DEPENDENCY_FAILURE"
    EVALUATOR = "EVALUATOR_ERROR"
    CONFIGURATION = "CONFIGURATION_ERROR"


OracleT = TypeVar("OracleT")


class OracleValue(_FrozenModel, Generic[OracleT]):
    status: OracleStatus
    value: OracleT | None = None

    @model_validator(mode="after")
    def validate_value_presence(self) -> OracleValue[OracleT]:
        if self.status is OracleStatus.VALUE and self.value is None:
            raise ValueError("value is required when status is value")
        if self.status is OracleStatus.NOT_APPLICABLE and self.value is not None:
            raise ValueError("value must be omitted when status is not_applicable")
        return self


class AgentEvalCase(_FrozenModel):
    case_id: str = Field(min_length=1)
    dataset_version: str = Field(min_length=1)
    input_text: str = Field(min_length=1)
    fixed_now: datetime
    fixture_refs: tuple[str, ...] = Field(min_length=1)
    timing_policy_ref: str = Field(min_length=1)
    lodging_policy_ref: str = Field(min_length=1)
    meeting_readiness_policy_ref: str = Field(min_length=1)
    policy_applicability_ref: str = Field(min_length=1)
    expected_mode: OracleValue[InteractionMode]
    expected_clarification_fields: OracleValue[tuple[str, ...]]
    expected_initial_scope: OracleValue[tuple[str, ...]]
    expected_initial_capabilities: OracleValue[tuple[str, ...]]
    expected_initial_task_dependencies: OracleValue[tuple[tuple[str, str], ...]]
    expected_expanded_scope_by_candidate: OracleValue[dict[str, tuple[str, ...]]]
    expected_expanded_capabilities_by_candidate: OracleValue[dict[str, tuple[str, ...]]]
    expected_expanded_task_dependencies: OracleValue[tuple[tuple[str, str], ...]]
    expected_candidate_pre_meeting_lodging: OracleValue[str]
    expected_min_distinct_alternatives: OracleValue[int | str]
    expected_recommendation_evidence_types: OracleValue[tuple[str, ...]]
    expected_terminal_status: OracleValue[str]
    expected_error_type: OracleValue[str]
    forbidden_outputs: OracleValue[tuple[str, ...]]
    tags: tuple[str, ...] = Field(min_length=1)
    applicable_views: tuple[EvalView, ...] = Field(min_length=1)
    oracle_version: str = Field(min_length=1)

    @model_validator(mode="after")
    def validate_case(self) -> AgentEvalCase:
        if len(set(self.fixture_refs)) != len(self.fixture_refs):
            raise ValueError("fixture_refs must be unique")
        if len(set(self.tags)) != len(self.tags):
            raise ValueError("tags must be unique")
        if len(set(self.applicable_views)) != len(self.applicable_views):
            raise ValueError("applicable_views must be unique")
        if self.fixed_now.tzinfo is None or self.fixed_now.utcoffset() is None:
            raise ValueError("fixed_now must include a timezone")
        return self


class StageOutput(_FrozenModel):
    stage: str = Field(min_length=1)
    status: str = Field(min_length=1)
    summary: str = ""


class WorkflowErrorSummary(_FrozenModel):
    error_type: str = Field(min_length=1)
    stage: str = Field(min_length=1)
    message: str = Field(min_length=1)


class TokenUsage(_FrozenModel):
    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0


class EstimatedCost(_FrozenModel):
    status: str = Field(min_length=1)
    amount: Decimal | None = None
    currency: str | None = None
    reason: str | None = None


class FingerprintBundle(_FrozenModel):
    runtime_fingerprint: str = Field(min_length=1)
    dataset_fingerprint: str = Field(min_length=1)
    view_fixture_fingerprint: str = Field(min_length=1)
    policy_fingerprint: str = Field(min_length=1)


class AgentRunResult(_FrozenModel):
    run_id: str = Field(min_length=1)
    case_id: str = Field(min_length=1)
    trace_id: str = Field(min_length=1)
    system_version: str = Field(min_length=1)
    dataset_hash: str = Field(min_length=1)
    dataset_partition: str = Field(min_length=1)
    mode: str = Field(min_length=1)
    provider: str = Field(min_length=1)
    model: str = Field(min_length=1)
    base_url_fingerprint: str = Field(min_length=1)
    prompt_version: str = Field(min_length=1)
    schema_version: str = Field(min_length=1)
    timing_policy_id: str = Field(min_length=1)
    timing_policy_hash: str = Field(min_length=1)
    lodging_policy_id: str = Field(min_length=1)
    lodging_policy_hash: str = Field(min_length=1)
    meeting_readiness_policy_id: str = Field(min_length=1)
    meeting_readiness_policy_hash: str = Field(min_length=1)
    policy_applicability_id: str = Field(min_length=1)
    policy_applicability_hash: str = Field(min_length=1)
    destination_timezone: str = Field(min_length=1)
    temperature: Decimal | str
    seed_status: str = Field(min_length=1)
    max_tokens: int = Field(gt=0)
    retry_count: int = Field(ge=0)
    repetition_policy_id: str = Field(min_length=1)
    runtime_fingerprint: str = Field(min_length=1)
    dataset_fingerprint: str = Field(min_length=1)
    view_fixture_fingerprint: str = Field(min_length=1)
    policy_fingerprint: str = Field(min_length=1)
    started_at: datetime
    duration_ms: float = Field(ge=0)
    token_usage: TokenUsage
    estimated_cost: EstimatedCost
    stage_outputs: tuple[StageOutput, ...]
    terminal_status: str = Field(min_length=1)
    workflow_error: WorkflowErrorSummary | None = None
    run_status: RunStatus
    component_availability: ComponentAvailability
    business_assertion: BusinessAssertion


class CaseResult(_FrozenModel):
    case_id: str = Field(min_length=1)
    passed: bool
    metric_values: tuple[tuple[str, str], ...] = ()
    failed_assertions: tuple[str, ...] = ()
    first_failed_stage: FirstFailedStage | None = None
    failure_category: FailureCategory | None = None
    evidence_refs: tuple[str, ...] = ()
    review_status: str = Field(min_length=1)
    run_status: RunStatus = RunStatus.COMPLETED
    component_availability: ComponentAvailability = ComponentAvailability.IMPLEMENTED
    business_assertion: BusinessAssertion = BusinessAssertion.PASS


class StageScorecard(_FrozenModel):
    run_id: str = Field(min_length=1)
    run_label: str = Field(min_length=1)
    dataset_id: str = Field(min_length=1)
    dataset_hash: str = Field(min_length=1)
    system_commit: str = Field(min_length=1)
    configuration: tuple[tuple[str, str], ...] = ()
    case_count: int = Field(ge=0)
    metric_summary: tuple[tuple[str, str], ...] = ()
    failure_distribution: tuple[tuple[str, int], ...] = ()
    latency_summary: tuple[tuple[str, float], ...] = ()
    cost_summary: tuple[tuple[str, str], ...] = ()
    report_paths: tuple[str, ...] = ()
