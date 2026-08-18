from __future__ import annotations

from decimal import Decimal

from src.domain.models.business_trip import BusinessTripBoundaryCode
from src.domain.models.enums import ConstraintHardness
from src.domain.models.interpretation import ConstraintCandidate, InterpretationResult
from src.domain.services.business_trip_boundary_resolver import (
    BusinessTripBoundaryResolver,
)


def _interpretation(*categories: str, travelers: int | None = None) -> InterpretationResult:
    candidates = [
        ConstraintCandidate(
            category=category,
            value=(travelers if category == "travelers" and travelers is not None else "provided"),
            hardness=ConstraintHardness.HARD,
            scope="meeting" if category.startswith("meeting_") else "trip",
            confidence=Decimal("0.95"),
        )
        for category in categories
    ]
    return InterpretationResult(
        mode_hint="plan",
        extracted_entities=(),
        constraint_candidates=tuple(candidates),
        explicit_questions=(),
        references_to_current_plan=(),
        field_confidence={},
        overall_confidence=Decimal("0.95"),
        safety_flags=(),
    )


def test_boundary_marks_explicit_multi_traveler_business_request_unsupported() -> None:
    result = BusinessTripBoundaryResolver().resolve(
        _interpretation("meeting_city", "travelers", travelers=3),
        "我和两位同事从杭州出发去上海开会，请规划差旅。",
    )

    assert result is BusinessTripBoundaryCode.MULTI_TRAVELER_UNSUPPORTED


def test_boundary_marks_group_language_without_count_unsupported() -> None:
    result = BusinessTripBoundaryResolver().resolve(
        _interpretation("meeting_city"),
        "我和同事们从杭州出发去上海开会，请规划差旅。",
    )

    assert result is BusinessTripBoundaryCode.MULTI_TRAVELER_UNSUPPORTED


def test_boundary_marks_explicit_tourism_unsupported_without_business_meeting() -> None:
    result = BusinessTripBoundaryResolver().resolve(
        _interpretation("destination", "place", "activity"),
        "我下周去上海旅游，想安排景点和活动。",
    )

    assert result is BusinessTripBoundaryCode.TOURISM_UNSUPPORTED


def test_boundary_does_not_misclassify_business_meeting_location_as_tourism() -> None:
    result = BusinessTripBoundaryResolver().resolve(
        _interpretation("destination", "meeting_city", "meeting_location"),
        "我去上海东方明珠塔参加会议，请规划会前到达。",
    )

    assert result is None


def test_boundary_gives_meeting_language_priority_over_tourism_language() -> None:
    result = BusinessTripBoundaryResolver().resolve(
        _interpretation(),
        "我要从厦门去广州开会后安排返程和景点游玩。",
    )

    assert result is None


def test_boundary_does_not_change_non_business_legacy_request_without_tourism_signal() -> None:
    result = BusinessTripBoundaryResolver().resolve(
        _interpretation("origin", "destination", "date_range", "travelers", travelers=2),
        "plan a trip from Shanghai to Hangzhou",
    )

    assert result is None
