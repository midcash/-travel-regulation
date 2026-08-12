from __future__ import annotations

from decimal import Decimal

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
