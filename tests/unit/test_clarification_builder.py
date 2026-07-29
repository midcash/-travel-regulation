from __future__ import annotations

from decimal import Decimal

import pytest

from src.domain.models.clarification import ClarificationRequest
from src.domain.models.enums import InteractionMode
from src.domain.models.readiness import (
    ReadinessBlocker,
    ReadinessBlockerCode,
    ReadinessResult,
)
from src.domain.services.clarification_builder import ClarificationBuilder


def _blocker(
    issue_id: str,
    code: ReadinessBlockerCode,
    field: str,
    *,
    priority: int,
    constraint_refs: tuple[str, ...] = (),
    conflict_group: str | None = None,
) -> ReadinessBlocker:
    return ReadinessBlocker(
        issue_id=issue_id,
        code=code,
        field=field,
        message=f"blocker: {field}",
        constraint_refs=constraint_refs,
        conflict_group=conflict_group,
        priority=priority,
    )


def _result(*blockers: ReadinessBlocker, trace_id: str = "trace-1") -> ReadinessResult:
    return ReadinessResult(
        trace_id=trace_id,
        request_id="request-1",
        snapshot_version=2,
        mode=InteractionMode.PLAN,
        ready=False,
        confidence=Decimal("0.8"),
        blockers=blockers,
    )


def test_clarification_builder_orders_by_blocking_priority_and_caps_at_three() -> None:
    result = _result(
        _blocker(
            "b-4",
            ReadinessBlockerCode.TRAVELER_COUNT_UNDETERMINED,
            "travelers",
            priority=23,
        ),
        _blocker(
            "b-2",
            ReadinessBlockerCode.MISSING_DESTINATION,
            "destination",
            priority=21,
        ),
        _blocker(
            "b-1",
            ReadinessBlockerCode.MISSING_ORIGIN,
            "origin",
            priority=20,
        ),
        _blocker(
            "b-3",
            ReadinessBlockerCode.DATE_OR_DURATION_UNDETERMINED,
            "date_range_or_duration_days",
            priority=22,
        ),
    )

    request = ClarificationBuilder().build(result)

    assert request is not None
    assert [question.blocker_ref for question in request.questions] == ["b-1", "b-2", "b-3"]
    assert request.deferred_blocker_refs == ("b-4",)
    assert len(request.questions) <= 3


def test_clarification_builder_maps_blocker_refs_and_conflict_group() -> None:
    result = _result(
        _blocker(
            "budget-issue",
            ReadinessBlockerCode.BUDGET_SEMANTIC_CONFLICT,
            "budget",
            priority=30,
            constraint_refs=("budget-1", "budget-2"),
            conflict_group="conflict-budget",
        )
    )

    request = ClarificationBuilder().build(result)

    assert request is not None
    question = request.questions[0]
    assert question.code is ReadinessBlockerCode.BUDGET_SEMANTIC_CONFLICT
    assert question.field == "budget"
    assert question.constraint_refs == ("budget-1", "budget-2")
    assert question.conflict_group == "conflict-budget"
    assert question.question == "请确认预算金额、币种及预算口径。"


def test_clarification_builder_ignores_non_blocking_assumptions() -> None:
    ready = ReadinessResult(
        trace_id="trace-1",
        request_id="request-1",
        snapshot_version=1,
        mode=InteractionMode.PLAN,
        ready=True,
        confidence=Decimal("0.9"),
        assumptions=(),
    )

    assert ClarificationBuilder().build(ready) is None


def test_clarification_builder_question_ids_are_stable_across_trace_ids() -> None:
    blocker = _blocker(
        "origin-issue",
        ReadinessBlockerCode.MISSING_ORIGIN,
        "origin",
        priority=20,
    )

    first = ClarificationBuilder().build(_result(blocker, trace_id="trace-1"))
    second = ClarificationBuilder().build(_result(blocker, trace_id="trace-2"))

    assert first is not None
    assert second is not None
    assert first.questions == second.questions
    assert first.trace_id != second.trace_id


@pytest.mark.parametrize(
    ("code", "field", "expected"),
    [
        (
            ReadinessBlockerCode.MISSING_ORIGIN,
            "origin",
            "请补充出发地。",
        ),
        (
            ReadinessBlockerCode.MISSING_DESTINATION,
            "destination",
            "请补充目的地。",
        ),
        (
            ReadinessBlockerCode.DATE_DURATION_CONFLICT,
            "date_range_or_duration_days",
            "请确认出行日期范围与旅行天数，二者目前不一致。",
        ),
        (
            ReadinessBlockerCode.TRAVELER_COUNT_UNDETERMINED,
            "travelers",
            "请确认出行人数。",
        ),
        (
            ReadinessBlockerCode.SPECIAL_POPULATION_UNDETERMINED,
            "special_population",
            "请说明是否有儿童、老人、婴幼儿或无障碍需求。",
        ),
        (
            ReadinessBlockerCode.CONSTRAINT_CONFLICT,
            "transport",
            "请确认互斥约束中需要保留的条件。",
        ),
        (
            ReadinessBlockerCode.ACTION_AUTHORIZATION_REQUIRED,
            "authorization",
            "请完成身份认证并确认当前操作已获授权。",
        ),
        (
            ReadinessBlockerCode.ACTION_IDENTITY_REQUIRED,
            "identity_ref",
            "请提供已验证的操作主体身份。",
        ),
        (
            ReadinessBlockerCode.CURRENT_PLAN_REQUIRED,
            "current_plan_ref",
            "请提供可引用的当前计划。",
        ),
    ],
)
def test_clarification_builder_has_explicit_template_for_each_blocker(
    code: ReadinessBlockerCode,
    field: str,
    expected: str,
) -> None:
    request = ClarificationBuilder().build(_result(_blocker("issue-1", code, field, priority=1)))

    assert request is not None
    assert request.questions[0].question == expected


def test_clarification_request_rejects_more_than_three_questions() -> None:
    blockers = tuple(
        _blocker(
            f"issue-{index}",
            ReadinessBlockerCode.MISSING_ORIGIN,
            f"origin-{index}",
            priority=index,
        )
        for index in range(4)
    )
    questions = tuple(
        ClarificationBuilder().build(_result(blocker)).questions[0]  # type: ignore[union-attr]
        for blocker in blockers
    )

    with pytest.raises(ValueError, match="at most 3|less than or equal to 3"):
        ClarificationRequest(
            trace_id="trace-1",
            request_id="request-1",
            snapshot_version=1,
            mode=InteractionMode.PLAN,
            questions=questions,
        )


def test_clarification_builder_rejects_untyped_runtime_inputs() -> None:
    with pytest.raises(TypeError, match="ReadinessResult"):
        ClarificationBuilder().build("not-a-result")  # type: ignore[arg-type]
