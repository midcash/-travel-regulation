from __future__ import annotations

from pathlib import Path

from evaluation.business_travel.contracts import EvalView, FirstFailedStage
from evaluation.business_travel.offline_runner import (
    normalized_result_hash,
    run_offline_baseline,
)
from evaluation.business_travel.registry import BusinessTravelCaseRegistry

FORMAL = Path("evaluation/datasets/business-travel-m4.1-v1.jsonl")


def test_registry_produces_multiple_read_only_views() -> None:
    registry = BusinessTravelCaseRegistry.load(FORMAL)

    component = registry.cases_for(EvalView.COMPONENT)
    integration = registry.cases_for(EvalView.INTEGRATION)

    assert len(component) == 12
    assert len(integration) == 12
    assert {case.case_id for case in component} == {case.case_id for case in integration}


def test_offline_baseline_is_complete_and_deterministic() -> None:
    first = run_offline_baseline(FORMAL)
    second = run_offline_baseline(FORMAL)

    assert len(first.case_results) == 12
    assert len(second.case_results) == 12
    assert normalized_result_hash(first) == normalized_result_hash(second)
    assert first.run_status == "COMPLETED"


def test_missing_scope_is_business_failure_not_evaluator_error() -> None:
    result = run_offline_baseline(FORMAL)
    case = next(item for item in result.case_results if item.case_id == "BT-M41-001")

    assert case.first_failed_stage is FirstFailedStage.SCOPE
    assert case.run_status == "COMPLETED"
    assert case.evaluator_error is None


def test_case_failure_does_not_abort_full_batch() -> None:
    result = run_offline_baseline(FORMAL)

    assert {item.case_id for item in result.case_results} == {
        f"BT-M41-{index:03d}" for index in range(1, 13)
    }
