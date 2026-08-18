"""M4.2-S1：从类型化会议约束确定商务差旅范围。"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone, tzinfo
from typing import Final
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from src.domain.models.business_trip import (
    BusinessTripScope,
    CapabilityReason,
    MeetingRequirement,
    ScopeRequirementState,
)
from src.domain.models.constraint import Constraint, ConstraintSnapshot

_MEETING_CATEGORIES: Final[frozenset[str]] = frozenset(
    {
        "meeting_city",
        "meeting_location",
        "meeting_starts_at",
        "meeting_timezone",
        "planning_horizon",
    }
)
_REQUIRED_MEETING_FIELDS: Final[tuple[str, ...]] = (
    "meeting_city",
    "meeting_location",
    "meeting_starts_at",
    "meeting_timezone",
)
_FIXED_TIMEZONES: Final[dict[str, tzinfo]] = {
    "Asia/Shanghai": timezone(timedelta(hours=8), "Asia/Shanghai"),
}


class BusinessTripScopeResolver:
    """只消费 ConstraintSnapshot，不调用 LLM、Agent 或外部工具。"""

    def resolve(self, snapshot: ConstraintSnapshot) -> BusinessTripScope | None:
        """根据会议约束生成冻结的初始差旅范围。"""
        if not isinstance(snapshot, ConstraintSnapshot):
            raise TypeError("snapshot must be a ConstraintSnapshot")
        grouped = _group_current_constraints(snapshot)
        if not set(grouped).intersection(_MEETING_CATEGORIES):
            return None

        missing = tuple(
            category
            for category in _REQUIRED_MEETING_FIELDS
            if not _single_text(grouped.get(category, ()))
        )
        if missing:
            raise ValueError(f"meeting scope is incomplete: {', '.join(missing)}")

        timezone_name = _single_text(grouped["meeting_timezone"])
        starts_at_text = _single_text(grouped["meeting_starts_at"])
        city = _single_text(grouped["meeting_city"])
        location = _single_text(grouped["meeting_location"])
        if timezone_name is None or starts_at_text is None or city is None or location is None:
            raise ValueError("meeting scope contains an empty required value")
        timezone = _load_timezone(timezone_name)
        starts_at = _parse_meeting_start(starts_at_text, timezone)
        travelers = _traveler_count(grouped.get("travelers", ()))
        if travelers is None:
            raise ValueError("traveler count is required for business trip scope")

        required = ("geo", "policy", "intercity_transport", "local_transport")
        conditional = ("stay",)
        excluded = ("place", "activity", "return_transport")
        reasons = (
            CapabilityReason(
                capability="geo",
                state=ScopeRequirementState.REQUIRED,
                reason="会议地点需要先完成地理解析，才能形成可执行的到会位置。",
            ),
            CapabilityReason(
                capability="policy",
                state=ScopeRequirementState.REQUIRED,
                reason="商务差旅必须先取得适用的公司政策依据。",
            ),
            CapabilityReason(
                capability="intercity_transport",
                state=ScopeRequirementState.REQUIRED,
                reason="需要查找从出发地到会议城市的去程交通候选。",
            ),
            CapabilityReason(
                capability="stay",
                state=ScopeRequirementState.CONDITIONAL,
                reason="是否需要会前住宿取决于具体去程候选的本地到达日期和时间。",
            ),
            CapabilityReason(
                capability="local_transport",
                state=ScopeRequirementState.REQUIRED,
                reason="机场或车站到会场的具体路线需等待到达点和候选住宿事实。",
            ),
            CapabilityReason(
                capability="place",
                state=ScopeRequirementState.EXCLUDED,
                reason="景点不是会前到达目标的一部分。",
            ),
            CapabilityReason(
                capability="activity",
                state=ScopeRequirementState.EXCLUDED,
                reason="活动不是商务差旅主链路的一部分。",
            ),
            CapabilityReason(
                capability="return_transport",
                state=ScopeRequirementState.EXCLUDED,
                reason="当前范围只规划到首场会议，不规划返程。",
            ),
        )
        return BusinessTripScope(
            scope_version="m4.2-s1.v2",
            planning_horizon="meeting_arrival_ready",
            meeting=MeetingRequirement(
                meeting_id=f"meeting-{snapshot.request_id}",
                city=city,
                location=location,
                timezone=timezone_name,
                starts_at=starts_at,
                traveler_count=travelers,
            ),
            initial_required_capabilities=("geo", "policy", "intercity_transport"),
            required_capabilities=required,
            conditional_capabilities=conditional,
            excluded_capabilities=excluded,
            capability_reasons=reasons,
            return_scope="not_planned",
        )


def _group_current_constraints(snapshot: ConstraintSnapshot) -> dict[str, tuple[Constraint, ...]]:
    grouped: dict[str, list[Constraint]] = {}
    for constraint in snapshot.constraints:
        grouped.setdefault(constraint.category, []).append(constraint)
    return {category: tuple(items) for category, items in grouped.items()}


def _single_text(items: tuple[Constraint, ...]) -> str | None:
    if len(items) != 1 or not isinstance(items[0].normalized_value, str):
        return None
    value = items[0].normalized_value.strip()
    return value or None


def _traveler_count(items: tuple[Constraint, ...]) -> int | None:
    if len(items) != 1 or type(items[0].normalized_value) is not int:
        return None
    value = items[0].normalized_value
    return value if value > 0 else None


def _load_timezone(value: str) -> tzinfo:
    fixed = _FIXED_TIMEZONES.get(value)
    if fixed is not None:
        return fixed
    try:
        return ZoneInfo(value)
    except ZoneInfoNotFoundError as exc:
        raise ValueError("meeting timezone must be a valid IANA timezone") from exc


def _parse_meeting_start(value: str, timezone: tzinfo) -> datetime:
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError as exc:
        raise ValueError("meeting_starts_at must be an ISO datetime") from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        return parsed.replace(tzinfo=timezone)
    return parsed.astimezone(timezone)
