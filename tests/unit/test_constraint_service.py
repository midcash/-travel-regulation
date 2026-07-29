from __future__ import annotations

from datetime import UTC, date, datetime
from decimal import Decimal

import pytest

from src.domain.errors import WorkflowError
from src.domain.models.constraint import ConstraintSnapshot, ConstraintSource
from src.domain.models.enums import ConstraintHardness
from src.domain.models.interpretation import ConstraintCandidate, InterpretationResult
from src.domain.services.constraint_service import ConstraintObservation, ConstraintService


def _candidate(
    category: str,
    value: object,
    *,
    hardness: ConstraintHardness = ConstraintHardness.SOFT,
    scope: str = "trip",
    confidence: str = "0.9",
) -> ConstraintCandidate:
    return ConstraintCandidate(
        category=category,
        value=value,
        hardness=hardness,
        scope=scope,
        confidence=Decimal(confidence),
    )


def _interpretation(*candidates: ConstraintCandidate) -> InterpretationResult:
    return InterpretationResult(
        mode_hint=None,
        extracted_entities=(),
        constraint_candidates=tuple(candidates),
        explicit_questions=(),
        references_to_current_plan=(),
        field_confidence={},
        overall_confidence=Decimal("0.9"),
        safety_flags=(),
    )


def _build(
    interpretation: InterpretationResult,
    **kwargs: object,
) -> ConstraintSnapshot:
    return ConstraintService().build_snapshot(
        interpretation,
        request_id="request-1",
        trace_id="trace-1",
        created_at=datetime(2026, 7, 29, 12, tzinfo=UTC),
        **kwargs,
    )


def test_constraint_service_normalizes_dates_currency_travelers_and_places() -> None:
    snapshot = _build(
        _interpretation(
            _candidate(
                "date_range",
                "2026年8月1日至2026年8月3日",
                hardness=ConstraintHardness.HARD,
            ),
            _candidate("budget", "¥5,000"),
            _candidate("travelers", "两位成人"),
            _candidate("destination", "  Ｂｅｉｊｉｎｇ  "),
        )
    )

    by_category = {constraint.category: constraint for constraint in snapshot.constraints}
    date_range = by_category["date_range"].normalized_value
    budget = by_category["budget"].normalized_value
    assert date_range.start == date(2026, 8, 1)  # type: ignore[union-attr]
    assert date_range.end == date(2026, 8, 3)  # type: ignore[union-attr]
    assert budget.amount == Decimal("5000")  # type: ignore[union-attr]
    assert budget.currency == "CNY"  # type: ignore[union-attr]
    assert by_category["travelers"].normalized_value == 2
    assert by_category["destination"].normalized_value == "Beijing"


def test_constraint_service_merges_same_type_and_preserves_multi_destination_order() -> None:
    snapshot = _build(
        _interpretation(
            _candidate("destination", "杭州", hardness=ConstraintHardness.HARD),
            _candidate("destination", "苏州", hardness=ConstraintHardness.HARD),
            _candidate("destination", "杭州", confidence="0.7"),
        )
    )

    assert len(snapshot.constraints) == 1
    assert snapshot.constraints[0].normalized_value == ("杭州", "苏州")
    assert snapshot.constraints[0].hardness is ConstraintHardness.HARD


def test_constraint_service_applies_source_priority_without_dropping_current_conflicts() -> None:
    snapshot = _build(
        _interpretation(_candidate("budget", "3000元")),
        context_observations=(
            ConstraintObservation(
                candidate=_candidate("budget", "8000元"),
                source=ConstraintSource.PROFILE,
            ),
            ConstraintObservation(
                candidate=_candidate("budget", "6000元"),
                source=ConstraintSource.ASSUMPTION,
            ),
        ),
    )

    assert len(snapshot.constraints) == 1
    assert snapshot.constraints[0].normalized_value.amount == Decimal("3000")  # type: ignore[union-attr]
    assert snapshot.constraints[0].source is ConstraintSource.USER

    conflicting = _build(
        _interpretation(
            _candidate("origin", "上海", hardness=ConstraintHardness.HARD),
            _candidate("origin", "北京", hardness=ConstraintHardness.HARD),
        )
    )
    assert len(conflicting.constraints) == 2
    assert {item.conflict_group for item in conflicting.constraints} == {
        conflicting.constraints[0].conflict_group
    }
    assert conflicting.constraints[0].conflict_group is not None


def test_constraint_service_creates_new_snapshot_without_mutating_previous_snapshot() -> None:
    first = _build(_interpretation(_candidate("destination", "杭州")))
    second = _build(
        _interpretation(_candidate("destination", "苏州")),
        previous_snapshot=first,
    )

    assert first.version == 1
    assert second.version == 2
    assert first.constraints[0].normalized_value == "杭州"
    assert set(second.constraints[0].normalized_value) == {"杭州", "苏州"}  # type: ignore[arg-type]


def test_constraint_service_uses_negation_as_unknown_recall_only() -> None:
    snapshot = _build(
        _interpretation(_candidate("activity", "户外活动", hardness=ConstraintHardness.SOFT)),
        negation_text="不想爬山",
    )

    recall = [item for item in snapshot.constraints if item.category == "negation_recall"]
    assert recall
    assert all(item.hardness is ConstraintHardness.UNKNOWN for item in recall)
    assert all(item.hardness is not ConstraintHardness.HARD for item in snapshot.constraints)


@pytest.mark.parametrize(
    "candidate",
    [
        _candidate("date_range", "not-a-date"),
        _candidate("budget", "没有金额"),
        _candidate("travelers", "零人"),
    ],
)
def test_constraint_service_rejects_unnormalizable_candidate_without_fallback(
    candidate: ConstraintCandidate,
) -> None:
    with pytest.raises(WorkflowError) as raised:
        _build(_interpretation(candidate))

    assert raised.value.stage == "constraint_service"
    assert raised.value.payload.code == "INTERPRETATION_INVALID"
    assert raised.value.retryable is False


def test_constraint_service_rejects_naive_snapshot_time_and_mismatched_previous_request() -> None:
    with pytest.raises(WorkflowError, match="timezone"):
        ConstraintService().build_snapshot(
            _interpretation(),
            request_id="request-1",
            trace_id="trace-1",
            created_at=datetime(2026, 7, 29, 12),
        )

    previous = _build(_interpretation())
    with pytest.raises(WorkflowError, match="another request"):
        ConstraintService().build_snapshot(
            _interpretation(),
            request_id="request-2",
            trace_id="trace-1",
            created_at=datetime(2026, 7, 29, 12, tzinfo=UTC),
            previous_snapshot=previous,
        )
