"""M4.2-S1：识别当前商务差旅产品不支持的请求边界。"""

from __future__ import annotations

from typing import Final

from src.domain.models.business_trip import BusinessTripBoundaryCode
from src.domain.models.interpretation import ConstraintCandidate, InterpretationResult

_MEETING_CONTEXT_CATEGORIES: Final[frozenset[str]] = frozenset(
    {
        "meeting_city",
        "meeting_location",
        "meeting_starts_at",
        "meeting_timezone",
        "planning_horizon",
    }
)
_TRAVELER_CATEGORIES: Final[frozenset[str]] = frozenset(
    {"traveler", "travelers", "people", "person_count", "traveler_count"}
)
_TOURISM_CATEGORIES: Final[frozenset[str]] = frozenset(
    {
        "place",
        "place_category",
        "scenic",
        "sightseeing",
        "attraction",
        "restaurant",
        "food",
        "activity",
        "avoid_activity",
    }
)
_MEETING_MARKERS: Final[tuple[str, ...]] = (
    "开会",
    "会议",
    "会场",
    "参会",
    "参加会议",
    "商务差旅",
)
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
_TOURISM_MARKERS: Final[tuple[str, ...]] = (
    "旅游",
    "游玩",
    "观光",
    "度假",
    "景点",
    "活动",
    "打卡",
)


class BusinessTripBoundaryResolver:
    """只根据结构化语义和受控文本标记判断产品边界。"""

    def resolve(
        self,
        interpretation: InterpretationResult,
        raw_input: str,
    ) -> BusinessTripBoundaryCode | None:
        """返回当前产品需要拒答的边界，普通兼容请求返回 ``None``。"""
        if not isinstance(interpretation, InterpretationResult):
            raise TypeError("interpretation must be an InterpretationResult")
        if not isinstance(raw_input, str) or not raw_input.strip():
            raise ValueError("raw_input must be non-empty text")

        candidates = interpretation.constraint_candidates
        categories = {candidate.category.strip().casefold() for candidate in candidates}
        meeting_context = categories.intersection(_MEETING_CONTEXT_CATEGORIES) or _contains_any(
            raw_input,
            _MEETING_MARKERS,
        )
        if meeting_context:
            if _has_multiple_travelers(candidates) or _contains_any(raw_input, _GROUP_MARKERS):
                return BusinessTripBoundaryCode.MULTI_TRAVELER_UNSUPPORTED
            return None

        if categories.intersection(_TOURISM_CATEGORIES) or _contains_any(
            raw_input,
            _TOURISM_MARKERS,
        ):
            return BusinessTripBoundaryCode.TOURISM_UNSUPPORTED
        return None


def _has_multiple_travelers(candidates: tuple[ConstraintCandidate, ...]) -> bool:
    return any(
        candidate.category.strip().casefold() in _TRAVELER_CATEGORIES
        and type(candidate.value) is int
        and candidate.value > 1
        for candidate in candidates
    )


def _contains_any(value: str, markers: tuple[str, ...]) -> bool:
    return any(marker in value for marker in markers)
