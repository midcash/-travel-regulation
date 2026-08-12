from __future__ import annotations

from datetime import UTC

import pytest
from pydantic import ValidationError

from evaluation.business_travel.contracts import (
    AgentEvalCase,
    EvalView,
    OracleStatus,
    OracleValue,
)


def oracle(value: object) -> dict[str, object]:
    return {"status": OracleStatus.VALUE.value, "value": value}


def valid_case_payload() -> dict[str, object]:
    not_applicable = {"status": OracleStatus.NOT_APPLICABLE.value}
    return {
        "case_id": "BT-M41-001",
        "dataset_version": "business-travel-m4.1-v1",
        "input_text": "我明天从上海到杭州参加上午十点的会议。",
        "fixed_now": "2026-08-12T09:00:00+08:00",
        "fixture_refs": ["fixture:bt-001"],
        "timing_policy_ref": "timing-policy-cn-domestic-v1",
        "lodging_policy_ref": "pre-meeting-lodging-policy-v1",
        "meeting_readiness_policy_ref": "meeting-readiness-policy-v1",
        "policy_applicability_ref": "universal-business-travel-policy-v1",
        "expected_mode": oracle("plan"),
        "expected_clarification_fields": not_applicable,
        "expected_initial_scope": oracle(["meeting_arrival_ready"]),
        "expected_initial_capabilities": oracle(["transport"]),
        "expected_initial_task_dependencies": oracle([]),
        "expected_expanded_scope_by_candidate": not_applicable,
        "expected_expanded_capabilities_by_candidate": not_applicable,
        "expected_expanded_task_dependencies": not_applicable,
        "expected_candidate_pre_meeting_lodging": oracle("not_required"),
        "expected_min_distinct_alternatives": oracle(1),
        "expected_recommendation_evidence_types": oracle(["transport_quote"]),
        "expected_terminal_status": oracle("planned"),
        "expected_error_type": not_applicable,
        "forbidden_outputs": oracle(["return_plan"]),
        "tags": ["complete_plan", "blocking_live_stability"],
        "applicable_views": [EvalView.COMPONENT.value, EvalView.LIVE_BLOCKING.value],
        "oracle_version": "business-travel-m4.1-oracle-v1",
    }


def test_valid_case_requires_explicit_oracle_wrappers() -> None:
    case = AgentEvalCase.model_validate(valid_case_payload())

    assert case.case_id == "BT-M41-001"
    assert case.fixed_now.tzinfo == UTC or case.fixed_now.utcoffset() is not None
    assert case.expected_mode.status is OracleStatus.VALUE
    assert case.expected_error_type.status is OracleStatus.NOT_APPLICABLE


def test_contract_rejects_extra_fields() -> None:
    payload = valid_case_payload()
    payload["unexpected"] = True

    with pytest.raises(ValidationError):
        AgentEvalCase.model_validate(payload)


def test_not_applicable_requires_explicit_value_wrapper() -> None:
    payload = valid_case_payload()
    payload.pop("expected_expanded_scope_by_candidate")

    with pytest.raises(ValidationError):
        AgentEvalCase.model_validate(payload)


def test_not_applicable_cannot_contain_a_value() -> None:
    with pytest.raises(ValidationError):
        OracleValue.model_validate({"status": "not_applicable", "value": "hidden"})


def test_value_oracle_cannot_omit_value() -> None:
    with pytest.raises(ValidationError):
        OracleValue.model_validate({"status": "value"})
