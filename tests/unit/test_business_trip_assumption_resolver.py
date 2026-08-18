from __future__ import annotations

from decimal import Decimal

from src.domain.models.constraint import ConstraintSource
from src.domain.models.enums import ConstraintHardness
from src.domain.models.interpretation import ConstraintCandidate, InterpretationResult
from src.domain.services.business_trip_assumption_resolver import (
    BusinessTripAssumptionResolver,
)


def _interpretation(
    *,
    city: str = "上海",
    include_timezone: bool = False,
    include_travelers: bool = False,
) -> InterpretationResult:
    candidates = [
        ConstraintCandidate(
            category="meeting_city",
            value=city,
            hardness=ConstraintHardness.HARD,
            scope="meeting",
            confidence=Decimal("0.95"),
        ),
        ConstraintCandidate(
            category="meeting_location",
            value=f"{city}会议中心",
            hardness=ConstraintHardness.HARD,
            scope="meeting",
            confidence=Decimal("0.95"),
        ),
    ]
    if include_timezone:
        candidates.append(
            ConstraintCandidate(
                category="meeting_timezone",
                value="Asia/Shanghai",
                hardness=ConstraintHardness.HARD,
                scope="meeting",
                confidence=Decimal("0.95"),
            )
        )
    if include_travelers:
        candidates.append(
            ConstraintCandidate(
                category="travelers",
                value=2,
                hardness=ConstraintHardness.HARD,
                scope="trip",
                confidence=Decimal("0.95"),
            )
        )
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


def test_resolver_adds_timezone_and_single_traveler_assumptions_for_known_city() -> None:
    observations = BusinessTripAssumptionResolver().resolve(
        _interpretation(),
        "下周六在上海开会，请规划差旅。",
    )

    by_category = {item.candidate.category: item for item in observations}
    assert by_category["meeting_timezone"].candidate.value == "Asia/Shanghai"
    assert by_category["meeting_timezone"].candidate.hardness is ConstraintHardness.ASSUMPTION
    assert by_category["meeting_timezone"].source is ConstraintSource.ASSUMPTION
    assert by_category["travelers"].candidate.value == 1
    assert by_category["travelers"].candidate.hardness is ConstraintHardness.ASSUMPTION
    assert by_category["travelers"].source is ConstraintSource.ASSUMPTION


def test_resolver_keeps_explicit_values_without_generating_defaults() -> None:
    observations = BusinessTripAssumptionResolver().resolve(
        _interpretation(include_timezone=True, include_travelers=True),
        "我两个人在上海开会，时区是 Asia/Shanghai。",
    )

    assert observations == ()


def test_resolver_treats_explicit_alone_as_user_fact() -> None:
    observations = BusinessTripAssumptionResolver().resolve(
        _interpretation(),
        "我一个人在上海开会，请规划差旅。",
    )

    traveler = next(item for item in observations if item.candidate.category == "travelers")
    assert traveler.candidate.value == 1
    assert traveler.candidate.hardness is ConstraintHardness.HARD
    assert traveler.source is ConstraintSource.USER
    assert traveler.user_confirmed is True


def test_resolver_does_not_default_travelers_for_group_request() -> None:
    observations = BusinessTripAssumptionResolver().resolve(
        _interpretation(),
        "我和两位同事在上海开会，请规划差旅。",
    )

    assert {item.candidate.category for item in observations} == {"meeting_timezone"}


def test_resolver_does_not_apply_business_defaults_to_tourism_request() -> None:
    interpretation = _interpretation().model_copy(
        update={
            "constraint_candidates": (
                ConstraintCandidate(
                    category="destination",
                    value="上海",
                    hardness=ConstraintHardness.HARD,
                    scope="trip",
                    confidence=Decimal("0.95"),
                ),
            )
        }
    )

    assert BusinessTripAssumptionResolver().resolve(interpretation, "去上海旅游。") == ()


def test_resolver_keeps_timezone_unknown_when_city_is_not_mapped() -> None:
    observations = BusinessTripAssumptionResolver().resolve(
        _interpretation(city="Springfield"),
        "下周六在 Springfield 开会，请规划差旅。",
    )

    assert "meeting_timezone" not in {
        item.candidate.category for item in observations
    }
    assert {item.candidate.category for item in observations} == {"travelers"}
