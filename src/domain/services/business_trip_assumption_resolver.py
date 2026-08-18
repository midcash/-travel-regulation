"""M4.2-S1：为商务会议请求生成受控的默认假设。"""

from __future__ import annotations

from decimal import Decimal
from typing import Final

from src.domain.models.constraint import ConstraintSource
from src.domain.models.enums import ConstraintHardness
from src.domain.models.interpretation import ConstraintCandidate, InterpretationResult
from src.domain.services.constraint_service import ConstraintObservation

_MEETING_CONTEXT_CATEGORIES: Final[frozenset[str]] = frozenset(
    {
        "meeting_city",
        "meeting_location",
        "meeting_starts_at",
        "meeting_timezone",
        "planning_horizon",
    }
)
_CITY_TIMEZONES: Final[dict[str, str]] = {
    "上海": "Asia/Shanghai",
    "上海市": "Asia/Shanghai",
    "杭州": "Asia/Shanghai",
    "杭州市": "Asia/Shanghai",
}
_GROUP_MARKERS: Final[tuple[str, ...]] = (
    "我们",
    "团队",
    "同事",
    "家人",
    "多人",
    "两人",
    "三人",
    "四人",
    "朋友",
    "夫妻",
    "父母",
    "带孩子",
)
_SINGLE_TRAVELER_MARKERS: Final[tuple[str, ...]] = (
    "我一个人",
    "一个人去",
    "独自",
    "单独出行",
    "本人出行",
)
_ASSUMPTION_CONFIDENCE: Final[Decimal] = Decimal("0.90")
_EXPLICIT_SINGLE_CONFIDENCE: Final[Decimal] = Decimal("0.98")


class BusinessTripAssumptionResolver:
    """只根据已提取的会议字段和受控文本标记生成商务默认值。"""

    def resolve(
        self,
        interpretation: InterpretationResult,
        raw_input: str,
    ) -> tuple[ConstraintObservation, ...]:
        """返回需要交给 ConstraintService 的系统假设观察。"""
        if not isinstance(interpretation, InterpretationResult):
            raise TypeError("interpretation must be an InterpretationResult")
        if not isinstance(raw_input, str) or not raw_input.strip():
            raise ValueError("raw_input must be non-empty text")

        candidates = interpretation.constraint_candidates
        categories = {candidate.category.strip().casefold() for candidate in candidates}
        if not categories.intersection(_MEETING_CONTEXT_CATEGORIES):
            return ()

        observations: list[ConstraintObservation] = []
        if "meeting_timezone" not in categories:
            timezone_name = _timezone_for_city(candidates)
            if timezone_name is not None:
                observations.append(
                    _observation(
                        category="meeting_timezone",
                        value=timezone_name,
                        scope="meeting",
                        hardness=ConstraintHardness.ASSUMPTION,
                        source=ConstraintSource.ASSUMPTION,
                        confidence=_ASSUMPTION_CONFIDENCE,
                    )
                )

        if not _has_candidate(candidates, "travelers"):
            if _contains_any(raw_input, _SINGLE_TRAVELER_MARKERS):
                observations.append(
                    _observation(
                        category="travelers",
                        value=1,
                        scope="trip",
                        hardness=ConstraintHardness.HARD,
                        source=ConstraintSource.USER,
                        confidence=_EXPLICIT_SINGLE_CONFIDENCE,
                        user_confirmed=True,
                    )
                )
            elif not _contains_any(raw_input, _GROUP_MARKERS):
                observations.append(
                    _observation(
                        category="travelers",
                        value=1,
                        scope="trip",
                        hardness=ConstraintHardness.ASSUMPTION,
                        source=ConstraintSource.ASSUMPTION,
                        confidence=_ASSUMPTION_CONFIDENCE,
                    )
                )

        return tuple(observations)


def _observation(
    *,
    category: str,
    value: str | int,
    scope: str,
    hardness: ConstraintHardness,
    source: ConstraintSource,
    confidence: Decimal,
    user_confirmed: bool = False,
) -> ConstraintObservation:
    return ConstraintObservation(
        candidate=ConstraintCandidate(
            category=category,
            value=value,
            hardness=hardness,
            scope=scope,
            confidence=confidence,
        ),
        source=source,
        user_confirmed=user_confirmed,
    )


def _timezone_for_city(candidates: tuple[ConstraintCandidate, ...]) -> str | None:
    city = next(
        (
            candidate.value.strip()
            for candidate in candidates
            if candidate.category.strip().casefold() == "meeting_city"
            and isinstance(candidate.value, str)
        ),
        None,
    )
    return _CITY_TIMEZONES.get(city) if city is not None else None


def _has_candidate(candidates: tuple[ConstraintCandidate, ...], category: str) -> bool:
    return any(item.category.strip().casefold() == category for item in candidates)


def _contains_any(value: str, markers: tuple[str, ...]) -> bool:
    return any(marker in value for marker in markers)
