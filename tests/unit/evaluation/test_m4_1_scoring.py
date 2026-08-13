from __future__ import annotations

from decimal import Decimal
from pathlib import Path

from evaluation.business_travel.contracts import (
    BusinessAssertion,
    ComponentAvailability,
    FirstFailedStage,
)
from evaluation.business_travel.scoring import (
    alternative_diversity,
    exact_match,
    score_case,
)
from evaluation.business_travel.registry import BusinessTravelCaseRegistry


def test_exact_match_rejects_extra_capability() -> None:
    assert exact_match({"transport"}, {"transport"}) == Decimal("1")
    assert exact_match({"transport", "lodging"}, {"transport"}) == Decimal("0")


def test_renamed_duplicate_alternative_does_not_pass_diversity() -> None:
    budget_copy = {"transport_id": "same", "price": "100", "lodging": "none"}
    comfort_copy = {"transport_id": "same", "price": "100", "lodging": "none", "label": "舒适"}

    assert alternative_diversity((budget_copy, comfort_copy)) == Decimal("0")


def test_missing_scope_component_is_not_counted_as_zero_but_stage_fails() -> None:
    result = score_case(
        {
            "component_availability": "NOT_IMPLEMENTED_IN_BASELINE",
            "business_assertion": "FAIL",
            "first_failed_stage": "SCOPE",
            "run_status": "COMPLETED",
            "predicted": {},
        },
        {"expected": {"scope": (), "required_scope": True}},
    )

    assert result.component_availability is ComponentAvailability.NOT_IMPLEMENTED_IN_BASELINE
    assert result.business_assertion is BusinessAssertion.FAIL
    assert result.first_failed_stage is FirstFailedStage.SCOPE
    assert result.metric_values["scope_exact_match"] is None


def test_score_case_separates_na_denominator_and_business_failure() -> None:
    result = score_case(
        {
            "component_availability": "IMPLEMENTED",
            "business_assertion": "FAIL",
            "first_failed_stage": "PLANNING",
            "run_status": "COMPLETED",
            "predicted": {
                "mode": "plan",
                "capabilities": ["transport"],
                "lodging": "required",
                "alternatives": [
                    {"id": "a", "price": 100},
                    {"id": "a", "price": 100, "label": "舒适"},
                ],
                "recommendation_evidence_types": ["transport_quote"],
            },
            "expected": {
                "mode": "plan",
                "capabilities": ["transport"],
                "lodging": "not_required",
                "alternatives": [{"id": "a", "price": 100}, {"id": "a", "price": 100}],
                "recommendation_evidence_types": ["transport_quote", "policy_rule"],
            },
        },
        {
            "expected": {
                "mode": "plan",
                "capabilities": ["transport"],
                "lodging": "not_required",
                "recommendation_evidence_types": ["transport_quote", "policy_rule"],
            },
            "required_scope": False,
            "required_lodging": True,
        },
    )

    assert result.metric_values["mode_accuracy"] == Decimal("1")
    assert result.metric_values["scope_exact_match"] is None
    assert result.metric_values["candidate_pre_meeting_lodging_exact_match"] == Decimal("0")
    assert result.metric_values["alternative_diversity_pass_rate"] == Decimal("0")
    assert result.business_assertion is BusinessAssertion.FAIL


def test_score_case_ignores_expected_values_embedded_in_run() -> None:
    result = score_case(
        {
            "predicted": {"mode": "clarify"},
            "expected": {"mode": "clarify"},
            "component_availability": "IMPLEMENTED",
            "run_status": "COMPLETED",
        },
        {"expected": {"mode": "plan"}},
    )

    assert result.metric_values["mode_accuracy"] == Decimal("0")
    assert result.business_assertion is BusinessAssertion.FAIL


def test_score_case_checks_initial_and_expanded_task_contracts() -> None:
    result = score_case(
        {
            "component_availability": "IMPLEMENTED",
            "run_status": "COMPLETED",
            "predicted": {
                "mode": "plan",
                "scope": ("meeting_arrival_ready",),
                "capabilities": ("transport",),
                "initial_task_dependencies": (("transport", "meeting_arrival"),),
                "expanded_scope_by_candidate": {
                    "direct": ("meeting_arrival_ready",),
                },
                "expanded_capabilities_by_candidate": {
                    "direct": ("transport", "lodging"),
                },
                "expanded_task_dependencies": (("transport", "meeting_arrival"),),
            },
        },
        {
            "expected": {
                "mode": "plan",
                "scope": ("meeting_arrival_ready",),
                "capabilities": ("transport",),
                "initial_task_dependencies": (),
                "expanded_scope_by_candidate": {
                    "direct": ("meeting_arrival_ready",),
                },
                "expanded_capabilities_by_candidate": {
                    "direct": ("transport",),
                },
                "expanded_task_dependencies": (("transport", "meeting_arrival"),),
            },
        },
    )

    assert result.metric_values["initial_task_dependency_exact_match"] == Decimal("0")
    assert result.metric_values["expanded_scope_exact_match"] == Decimal("1")
    assert result.metric_values["expanded_capability_exact_match"] == Decimal("0")
    assert result.metric_values["expanded_task_dependency_exact_match"] == Decimal("1")
    assert result.metric_values["task_dependency_accuracy"] == Decimal("0")
    assert result.business_assertion is BusinessAssertion.FAIL


def test_score_case_checks_terminal_failure_and_minimum_alternatives() -> None:
    result = score_case(
        {
            "component_availability": "IMPLEMENTED",
            "run_status": "COMPLETED",
            "predicted": {
                "terminal_status": "planned",
                "error_type": "UNCLASSIFIED_FAILURE",
                "alternatives": [{"id": "same"}],
            },
        },
        {
            "expected": {
                "terminal_status": "failed",
                "error_type": "ROUTE_UNREACHABLE",
                "min_distinct_alternatives": 2,
            },
        },
    )

    assert result.metric_values["terminal_status_accuracy"] == Decimal("0")
    assert result.metric_values["failure_semantics_accuracy"] == Decimal("0")
    assert result.metric_values["minimum_distinct_alternatives"] == Decimal("0")
    assert result.business_assertion is BusinessAssertion.FAIL


def test_score_case_rejects_forbidden_actions_and_invalid_dependency_trajectory() -> None:
    result = score_case(
        {
            "component_availability": "IMPLEMENTED",
            "run_status": "COMPLETED",
            "predicted": {
                "terminal_status": "planned",
                "trajectory": (
                    "g0",
                    "meeting_arrival",
                    "transport",
                ),
                "task_dependencies": (("transport", "meeting_arrival"),),
                "forbidden_outputs": ("return_plan",),
            },
        },
        {
            "expected": {
                "terminal_status": "planned",
                "forbidden_outputs": ("return_plan",),
            },
        },
    )

    assert result.metric_values["trajectory_validity"] == Decimal("0")
    assert result.metric_values["forbidden_output_rate"] == Decimal("0")
    assert result.business_assertion is BusinessAssertion.FAIL


def test_formal_oracle_blocking_fields_are_exposed_as_metrics() -> None:
    registry = BusinessTravelCaseRegistry.load(
        Path("evaluation/datasets/business-travel-m4.1-v1.jsonl")
    )
    result = score_case(
        {
            "component_availability": "IMPLEMENTED",
            "run_status": "COMPLETED",
            "predicted": {},
        },
        registry.cases[0],
    )

    assert {
        "initial_task_dependency_exact_match",
        "expanded_scope_exact_match",
        "expanded_capability_exact_match",
        "expanded_task_dependency_exact_match",
        "minimum_distinct_alternatives",
        "terminal_status_accuracy",
        "failure_semantics_accuracy",
        "trajectory_validity",
    }.issubset(result.metric_values)


def test_trajectory_does_not_borrow_expected_dependencies() -> None:
    result = score_case(
        {
            "component_availability": "IMPLEMENTED",
            "run_status": "COMPLETED",
            "predicted": {
                "trajectory": ("g0", "transport", "meeting_arrival"),
            },
        },
        {
            "expected": {
                "initial_task_dependencies": (("transport", "meeting_arrival"),),
                "required_initial_task_dependencies": True,
                "required_trajectory": True,
            },
        },
    )

    assert result.metric_values["initial_task_dependency_exact_match"] == Decimal("0")
    assert result.metric_values["trajectory_validity"] == Decimal("0")
