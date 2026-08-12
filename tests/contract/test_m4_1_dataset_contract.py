from __future__ import annotations

from pathlib import Path

import pytest

from evaluation.business_travel.contracts import AgentEvalCase, EvalView
from evaluation.business_travel.registry import BusinessTravelCaseRegistry, DatasetContractError
from tests.unit.evaluation.test_m4_1_contracts import valid_case_payload


def case(
    *,
    case_id: str,
    input_text: str,
    views: list[str] | None = None,
    tags: list[str] | None = None,
) -> AgentEvalCase:
    payload = valid_case_payload()
    payload["case_id"] = case_id
    payload["input_text"] = input_text
    if views is not None:
        payload["applicable_views"] = views
    if tags is not None:
        payload["tags"] = tags
    return AgentEvalCase.model_validate(payload)


def test_registry_rejects_duplicate_case_id() -> None:
    first = case(case_id="BT-M41-001", input_text="first")
    duplicate = case(case_id="BT-M41-001", input_text="second")

    with pytest.raises(DatasetContractError, match="duplicate case_id"):
        BusinessTravelCaseRegistry.from_cases((first, duplicate))


def test_registry_rejects_duplicate_input_across_partitions() -> None:
    formal_case = case(case_id="BT-M41-001", input_text="same input")
    dev_case = case(case_id="BT-M41-D01", input_text="same input")

    with pytest.raises(DatasetContractError, match="duplicate input_text"):
        BusinessTravelCaseRegistry.from_cases((formal_case, dev_case))


def test_registry_requires_live_blocking_view_for_blocking_tag() -> None:
    payload = valid_case_payload()
    payload["applicable_views"] = [EvalView.COMPONENT.value]
    with pytest.raises(DatasetContractError, match="blocking_live_stability"):
        BusinessTravelCaseRegistry.from_cases((AgentEvalCase.model_validate(payload),))


def test_registry_exposes_read_only_views_and_tag_selection() -> None:
    plan_case = case(case_id="BT-M41-001", input_text="plan")
    clarify_case = case(
        case_id="BT-M41-002",
        input_text="clarify",
        views=[EvalView.COMPONENT.value],
        tags=["clarification"],
    )
    registry = BusinessTravelCaseRegistry.from_cases((plan_case, clarify_case))

    assert registry.cases_for(EvalView.LIVE_BLOCKING) == (plan_case,)
    assert registry.select(tags=frozenset({"complete_plan"})) == (plan_case,)
    assert registry.select(case_ids=frozenset({"BT-M41-002"})) == (clarify_case,)


def test_loader_reports_path_line_and_case_id_for_schema_error(tmp_path: Path) -> None:
    path = tmp_path / "cases.jsonl"
    path.write_text('{"case_id":"BT-M41-001","input_text":1}\n', encoding="utf-8")

    with pytest.raises(DatasetContractError, match=r"cases\.jsonl:1:BT-M41-001"):
        BusinessTravelCaseRegistry.load(path)


def test_registry_rejects_empty_input() -> None:
    with pytest.raises(DatasetContractError, match="at least one case"):
        BusinessTravelCaseRegistry.from_cases(())


def test_frozen_partitions_have_12_formal_and_6_dev_cases() -> None:
    formal = BusinessTravelCaseRegistry.load(
        Path("evaluation/datasets/business-travel-m4.1-v1.jsonl")
    )
    dev = BusinessTravelCaseRegistry.load(
        Path("evaluation/datasets/business-travel-m4.1-dev-v1.jsonl")
    )

    assert len(formal.cases) == 12
    assert len(dev.cases) == 6
    assert {case.dataset_version for case in formal.cases} == {"business-travel-m4.1-v1"}
    assert {case.dataset_version for case in dev.cases} == {"business-travel-m4.1-dev-v1"}
    assert {case.input_text for case in formal.cases}.isdisjoint(
        {case.input_text for case in dev.cases}
    )


def test_formal_dataset_covers_all_frozen_behavior_slices() -> None:
    registry = BusinessTravelCaseRegistry.load(
        Path("evaluation/datasets/business-travel-m4.1-v1.jsonl")
    )
    required_tags = {
        "same_day_no_lodging",
        "pre_meeting_lodging",
        "candidate_level_lodging",
        "cross_midnight",
        "missing_venue_clarify",
        "meeting_timezone_conflict",
        "policy_limit",
        "hotel_price_semantics",
        "lodging_failure_isolated",
        "route_unreachable",
        "policy_evidence_conflict",
        "return_out_of_scope",
        "provider_failure",
        "legacy_transport_only_regression",
        "forbidden_sightseeing_output",
    }

    observed = {tag for case in registry.cases for tag in case.tags}
    assert required_tags <= observed


def test_formal_dataset_has_exactly_four_blocking_live_cases() -> None:
    registry = BusinessTravelCaseRegistry.load(
        Path("evaluation/datasets/business-travel-m4.1-v1.jsonl")
    )

    blocking = registry.select(tags=frozenset({"blocking_live_stability"}))
    assert len(blocking.cases if hasattr(blocking, "cases") else blocking) == 4
    assert {case.case_id for case in blocking} == {
        "BT-M41-001",
        "BT-M41-005",
        "BT-M41-012",
        "BT-M41-003",
    }


def test_every_case_references_fixture_and_policies() -> None:
    for path in (
        Path("evaluation/datasets/business-travel-m4.1-v1.jsonl"),
        Path("evaluation/datasets/business-travel-m4.1-dev-v1.jsonl"),
    ):
        registry = BusinessTravelCaseRegistry.load(path)
        for case in registry.cases:
            assert case.fixture_refs
            assert case.timing_policy_ref == "timing-policy-cn-domestic-v1"
            assert case.lodging_policy_ref == "pre-meeting-lodging-policy-v1"
            assert case.meeting_readiness_policy_ref == "meeting-readiness-policy-v1"
            assert case.policy_applicability_ref == "universal-business-travel-policy-v1"
