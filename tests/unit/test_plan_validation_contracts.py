from __future__ import annotations

from decimal import Decimal

import pytest
from pydantic import ValidationError

from src.domain.models.enums import IssueSeverity, WorkflowStatus
from src.domain.models.itinerary import (
    BudgetBreakdown,
    BudgetLine,
    ItineraryDay,
    ItineraryPlan,
    PlanAlternative,
    PlanBuffer,
    PlanItem,
)
from src.domain.models.validation import ValidationGate, ValidationIssue
from src.domain.models.value_objects import Money


def _plan(**overrides: object) -> ItineraryPlan:
    item = PlanItem(
        plan_item_id="item-1",
        candidate_id="place-1",
        day_number=1,
        title="西湖",
        evidence_refs=("evidence-1",),
    )
    values: dict[str, object] = {
        "plan_id": "plan-1",
        "version": 1,
        "status": WorkflowStatus.DRAFTING,
        "days": (ItineraryDay(day_number=1, item_refs=("item-1",)),),
        "items": (item,),
        "alternatives": (
            PlanAlternative(
                alternative_id="alternative-1", item_refs=("item-1",), rationale="更宽松"
            ),
        ),
        "budget": BudgetBreakdown(
            total=Money(amount=Decimal("1000"), currency="CNY"),
            lines=(
                BudgetLine(category="stay", amount=Money(amount=Decimal("800"), currency="CNY")),
            ),
        ),
        "buffers": (PlanBuffer(buffer_type="transfer", minutes=30),),
        "evidence_refs": ("evidence-1",),
    }
    values.update(overrides)
    return ItineraryPlan(**values)


def test_itinerary_plan_accepts_versioned_referenced_contracts() -> None:
    plan = _plan()

    assert plan.version == 1
    assert plan.days[0].item_refs == ("item-1",)
    assert plan.model_validate_json(plan.model_dump_json()) == plan


def test_itinerary_plan_rejects_orphaned_day_and_alternative_references() -> None:
    with pytest.raises(ValidationError, match="day item_refs"):
        _plan(days=(ItineraryDay(day_number=1, item_refs=("missing-item",)),))
    with pytest.raises(ValidationError, match="alternative item_refs"):
        _plan(
            alternatives=(
                PlanAlternative(
                    alternative_id="alternative-1", item_refs=("missing-item",), rationale="替代"
                ),
            )
        )


def test_validation_issue_is_structured_and_references_ids_only() -> None:
    issue = ValidationIssue(
        issue_id="issue-1",
        gate=ValidationGate.G3,
        severity=IssueSeverity.BLOCKING,
        type="budget_overrun",
        affected_ids=("plan-1", "item-1"),
        constraint_refs=("constraint-1",),
        evidence_refs=("evidence-1",),
        message="预算超过硬上限",
        repair_strategy="replace_candidate",
        retryable=False,
    )

    assert issue.gate.value == "g3"
    assert issue.model_validate_json(issue.model_dump_json()) == issue
    with pytest.raises(ValidationError):
        ValidationIssue(
            issue_id="issue-2",
            gate=ValidationGate.G2,
            severity=IssueSeverity.WARNING,
            type="raw",
            message="缺失证据",
            repair_strategy="query",
            raw_response={"must": "be rejected"},
        )
