"""M2 ReadinessEvaluator：确定性计算 G1 是否阻断当前工作模式。"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Iterable
from datetime import date
from decimal import Decimal
from hashlib import sha256
from typing import Final

from pydantic import BaseModel, ConfigDict

from src.domain.models.constraint import Constraint, ConstraintSnapshot
from src.domain.models.enums import ConstraintHardness, InteractionMode
from src.domain.models.interpretation import InterpretationResult
from src.domain.models.readiness import (
    ActionPreconditions,
    ReadinessAssumption,
    ReadinessAssumptionCode,
    ReadinessBlocker,
    ReadinessBlockerCode,
    ReadinessResult,
)
from src.domain.models.value_objects import DateRange, Money, StableId, TraceId

_DATE_CATEGORIES: Final[frozenset[str]] = frozenset(
    {"date", "date_range", "travel_date", "travel_dates"}
)
_DURATION_CATEGORIES: Final[frozenset[str]] = frozenset(
    {"duration", "duration_days", "trip_duration", "days"}
)
_ORIGIN_CATEGORIES: Final[frozenset[str]] = frozenset(
    {"origin", "departure", "departure_city", "depart_from", "from"}
)
_DESTINATION_CATEGORIES: Final[frozenset[str]] = frozenset(
    {"destination", "destinations", "arrival", "arrival_city", "arrive_at", "to"}
)
_TRAVELER_CATEGORIES: Final[frozenset[str]] = frozenset(
    {"traveler", "travelers", "people", "person_count", "traveler_count"}
)
_SPECIAL_POPULATION_CATEGORIES: Final[frozenset[str]] = frozenset(
    {
        "child",
        "children",
        "senior",
        "seniors",
        "infant",
        "infants",
        "accessibility",
        "accessibility_need",
        "accessibility_needs",
        "special_population",
        "special_populations",
    }
)
_BUDGET_CATEGORIES: Final[frozenset[str]] = frozenset(
    {"budget", "budget_max", "budget_min", "budget_target", "budget_semantics", "price_limit"}
)
_PLANNING_MODES: Final[frozenset[InteractionMode]] = frozenset(
    {InteractionMode.PLAN, InteractionMode.COMPARE}
)
_UNKNOWN_TEXT: Final[frozenset[str]] = frozenset(
    {
        "",
        "unknown",
        "n/a",
        "na",
        "tbd",
        "unspecified",
        "not sure",
        "未确定",
        "未知",
        "不确定",
        "待定",
        "待补充",
        "不知道",
        "任意地点",
        "随便",
    }
)
_CATEGORY_ALIASES: Final[dict[str, str]] = {
    "depart_from": "origin",
    "departure_city": "origin",
    "from": "origin",
    "arrive_at": "destination",
    "arrival_city": "destination",
    "to": "destination",
    "destinations": "destination",
    "travel_dates": "date_range",
    "travel_date": "date_range",
    "dates": "date_range",
    "people": "travelers",
    "person_count": "travelers",
    "traveler_count": "travelers",
}


class ReadinessEvaluationContext(BaseModel):
    """ReadinessEvaluator 的非约束上下文，避免跨模块传递裸 dict。"""

    model_config = ConfigDict(extra="forbid", frozen=True)

    mode: InteractionMode = InteractionMode.PLAN
    current_plan_ref: StableId | None = None
    action_preconditions: ActionPreconditions | None = None


class ReadinessEvaluator:
    """只读取约束快照并确定性地产生 G1 就绪结果。"""

    def evaluate(
        self,
        snapshot: ConstraintSnapshot,
        *,
        trace_id: TraceId,
        interpretation: InterpretationResult | None = None,
        context: ReadinessEvaluationContext | None = None,
    ) -> ReadinessResult:
        """评估当前模式是否具备继续条件，不生成澄清问题或路由决策。"""
        if not isinstance(snapshot, ConstraintSnapshot):
            raise TypeError("snapshot must be a ConstraintSnapshot")
        if interpretation is not None and not isinstance(interpretation, InterpretationResult):
            raise TypeError("interpretation must be an InterpretationResult")

        evaluation_context = context or ReadinessEvaluationContext(
            mode=(
                interpretation.mode_hint
                if interpretation and interpretation.mode_hint
                else InteractionMode.PLAN
            )
        )
        grouped = _group_by_category(snapshot.constraints)
        blockers: list[ReadinessBlocker] = []
        assumptions: list[ReadinessAssumption] = []

        if evaluation_context.mode in _PLANNING_MODES:
            blockers.extend(_required_trip_fields(grouped))
            blockers.extend(_date_duration_conflicts(grouped))
            blockers.extend(_budget_conflicts(grouped))
        if evaluation_context.mode in {
            InteractionMode.PLAN,
            InteractionMode.REFINE,
            InteractionMode.REPLAN,
            InteractionMode.COMPARE,
        }:
            blockers.extend(_hard_conflicts(snapshot.constraints))
            assumptions.extend(_assumptions(snapshot.constraints, grouped))
        if evaluation_context.mode in {InteractionMode.REFINE, InteractionMode.REPLAN}:
            if evaluation_context.current_plan_ref is None:
                blockers.append(
                    _blocker(
                        ReadinessBlockerCode.CURRENT_PLAN_REQUIRED,
                        field="current_plan_ref",
                        message="a current plan reference is required for this mode",
                        priority=10,
                    )
                )
        if evaluation_context.mode is InteractionMode.ACTION:
            blockers.extend(_action_precondition_blockers(evaluation_context.action_preconditions))

        ordered_blockers = _sort_blockers(blockers)
        return ReadinessResult(
            trace_id=trace_id,
            request_id=snapshot.request_id,
            snapshot_version=snapshot.version,
            mode=evaluation_context.mode,
            ready=not ordered_blockers,
            confidence=_confidence(snapshot, interpretation, bool(ordered_blockers)),
            blockers=ordered_blockers,
            assumptions=_sort_assumptions(assumptions),
        )


def _required_trip_fields(
    grouped: dict[str, tuple[Constraint, ...]],
) -> list[ReadinessBlocker]:
    blockers: list[ReadinessBlocker] = []
    if not _has_resolved_value(grouped, _ORIGIN_CATEGORIES):
        blockers.append(
            _blocker(
                ReadinessBlockerCode.MISSING_ORIGIN,
                field="origin",
                message="origin cannot be determined from the current constraints",
                priority=20,
            )
        )
    if not _has_resolved_value(grouped, _DESTINATION_CATEGORIES):
        blockers.append(
            _blocker(
                ReadinessBlockerCode.MISSING_DESTINATION,
                field="destination",
                message="destination cannot be determined from the current constraints",
                priority=21,
            )
        )
    date_items = _items_for(grouped, _DATE_CATEGORIES)
    duration_items = _items_for(grouped, _DURATION_CATEGORIES)
    if not _has_known_date(date_items) and not _has_known_duration(duration_items):
        blockers.append(
            _blocker(
                ReadinessBlockerCode.DATE_OR_DURATION_UNDETERMINED,
                field="date_range_or_duration_days",
                message="a resolvable date range or duration is required",
                constraint_refs=_refs(date_items + duration_items),
                priority=22,
            )
        )

    travelers = _items_for(grouped, _TRAVELER_CATEGORIES)
    if not _has_known_traveler_count(travelers):
        blockers.append(
            _blocker(
                ReadinessBlockerCode.TRAVELER_COUNT_UNDETERMINED,
                field="travelers",
                message="traveler count cannot be determined safely",
                constraint_refs=_refs(travelers),
                priority=23,
            )
        )
    for category in sorted(_SPECIAL_POPULATION_CATEGORIES):
        items = grouped.get(category, ())
        if items and any(_is_undetermined(item) for item in items):
            blockers.append(
                _blocker(
                    ReadinessBlockerCode.SPECIAL_POPULATION_UNDETERMINED,
                    field=category,
                    message="special population details affect ticketing or safety",
                    constraint_refs=_refs(items),
                    priority=24,
                )
            )
    return blockers


def _date_duration_conflicts(
    grouped: dict[str, tuple[Constraint, ...]],
) -> list[ReadinessBlocker]:
    dates = _items_for(grouped, _DATE_CATEGORIES)
    durations = _items_for(grouped, _DURATION_CATEGORIES)
    ranges = [
        item.normalized_value for item in dates if isinstance(item.normalized_value, DateRange)
    ]
    days = [item.normalized_value for item in durations if type(item.normalized_value) is int]
    if ranges and days and any(item.days != duration for item in ranges for duration in days):
        return [
            _blocker(
                ReadinessBlockerCode.DATE_DURATION_CONFLICT,
                field="date_range_or_duration_days",
                message="date range and duration describe different trip lengths",
                constraint_refs=_refs(dates + durations),
                priority=22,
            )
        ]
    return []


def _budget_conflicts(
    grouped: dict[str, tuple[Constraint, ...]],
) -> list[ReadinessBlocker]:
    items = _items_for(grouped, _BUDGET_CATEGORIES)
    if not items:
        return []
    conflicts = _conflicting_groups(items)
    if conflicts:
        group_id, group_items = conflicts[0]
        return [
            _blocker(
                ReadinessBlockerCode.BUDGET_SEMANTIC_CONFLICT,
                field="budget",
                message="budget constraints have incompatible semantics",
                constraint_refs=_refs(group_items),
                conflict_group=group_id,
                priority=30,
            )
        ]
    minimums = _money_items(grouped, {"budget_min"})
    maximums = _money_items(grouped, {"budget_max"})
    if (
        minimums
        and maximums
        and (
            minimums[0].currency != maximums[0].currency or minimums[0].amount > maximums[0].amount
        )
    ):
        return [
            _blocker(
                ReadinessBlockerCode.BUDGET_SEMANTIC_CONFLICT,
                field="budget",
                message="budget minimum and maximum cannot form one valid range",
                constraint_refs=_refs(_items_for(grouped, {"budget_min", "budget_max"})),
                priority=30,
            )
        ]
    effective = _money_items(grouped, {"budget", "budget_max", "budget_target", "price_limit"})
    if len({item.currency for item in effective}) > 1 or (
        len(effective) > 1 and len({item.amount for item in effective}) > 1
    ):
        return [
            _blocker(
                ReadinessBlockerCode.BUDGET_SEMANTIC_CONFLICT,
                field="budget",
                message="budget constraints specify incompatible amounts or currencies",
                constraint_refs=_refs(items),
                priority=30,
            )
        ]
    semantics = grouped.get("budget_semantics", ())
    if len({_value_key(item.normalized_value) for item in semantics}) > 1:
        return [
            _blocker(
                ReadinessBlockerCode.BUDGET_SEMANTIC_CONFLICT,
                field="budget_semantics",
                message="budget constraints specify incompatible semantics",
                constraint_refs=_refs(semantics),
                priority=30,
            )
        ]
    return []


def _hard_conflicts(constraints: tuple[Constraint, ...]) -> list[ReadinessBlocker]:
    result: list[ReadinessBlocker] = []
    for group_id, items in _group_by_conflict(constraints).items():
        values = {_value_key(item.normalized_value) for item in items}
        hard_items = tuple(item for item in items if item.hardness is ConstraintHardness.HARD)
        if len(values) < 2 or len(hard_items) < 2:
            continue
        if all(item.category in _BUDGET_CATEGORIES for item in items):
            continue
        result.append(
            _blocker(
                ReadinessBlockerCode.CONSTRAINT_CONFLICT,
                field=hard_items[0].category,
                message="mutually exclusive hard constraints are present",
                constraint_refs=_refs(hard_items),
                conflict_group=group_id,
                priority=31,
            )
        )
    return result


def _action_precondition_blockers(
    preconditions: ActionPreconditions | None,
) -> list[ReadinessBlocker]:
    blockers: list[ReadinessBlocker] = []
    if preconditions is None or not preconditions.authenticated or not preconditions.authorized:
        blockers.append(
            _blocker(
                ReadinessBlockerCode.ACTION_AUTHORIZATION_REQUIRED,
                field="authorization",
                message="authenticated and authorized action context is required",
                priority=10,
            )
        )
    if preconditions is None or preconditions.identity_ref is None:
        blockers.append(
            _blocker(
                ReadinessBlockerCode.ACTION_IDENTITY_REQUIRED,
                field="identity_ref",
                message="a verified principal identity is required before an action",
                priority=11,
            )
        )
    return blockers


def _assumptions(
    constraints: tuple[Constraint, ...],
    grouped: dict[str, tuple[Constraint, ...]],
) -> list[ReadinessAssumption]:
    assumptions: list[ReadinessAssumption] = []
    if not _items_for(grouped, _BUDGET_CATEGORIES):
        assumptions.append(
            ReadinessAssumption(
                code=ReadinessAssumptionCode.BUDGET_NOT_SPECIFIED,
                field="budget",
                message="budget was not specified; no budget value is inferred",
            )
        )
    critical = (
        _ORIGIN_CATEGORIES
        | _DESTINATION_CATEGORIES
        | _DATE_CATEGORIES
        | _DURATION_CATEGORIES
        | _TRAVELER_CATEGORIES
        | _SPECIAL_POPULATION_CATEGORIES
    )
    for item in constraints:
        category = _canonical_category(item.category)
        if item.hardness is ConstraintHardness.ASSUMPTION:
            assumptions.append(
                ReadinessAssumption(
                    code=ReadinessAssumptionCode.EXPLICIT_ASSUMPTION,
                    field=category,
                    message="this constraint is an explicit assumption and may be replaced",
                    constraint_refs=(item.id,),
                )
            )
        elif item.hardness is ConstraintHardness.UNKNOWN and category not in critical:
            assumptions.append(
                ReadinessAssumption(
                    code=ReadinessAssumptionCode.NON_BLOCKING_UNKNOWN,
                    field=category,
                    message="this unresolved preference is non-blocking and remains explicit",
                    constraint_refs=(item.id,),
                )
            )
    return assumptions


def _canonical_category(category: str) -> str:
    normalized = category.strip().casefold().replace("-", "_").replace(" ", "_")
    return _CATEGORY_ALIASES.get(normalized, normalized)


def _group_by_category(constraints: tuple[Constraint, ...]) -> dict[str, tuple[Constraint, ...]]:
    grouped: dict[str, list[Constraint]] = defaultdict(list)
    for item in constraints:
        grouped[_canonical_category(item.category)].append(item)
    return {category: tuple(items) for category, items in grouped.items()}


def _items_for(
    grouped: dict[str, tuple[Constraint, ...]],
    categories: Iterable[str],
) -> tuple[Constraint, ...]:
    items: list[Constraint] = []
    for category in sorted(categories):
        items.extend(grouped.get(category, ()))
    return tuple(items)


def _has_resolved_value(
    grouped: dict[str, tuple[Constraint, ...]],
    categories: Iterable[str],
) -> bool:
    items = _items_for(grouped, categories)
    return bool(items) and any(not _is_undetermined(item) for item in items)


def _has_known_date(items: tuple[Constraint, ...]) -> bool:
    return any(
        isinstance(item.normalized_value, DateRange | date)
        for item in items
        if not _is_undetermined(item)
    )


def _has_known_duration(items: tuple[Constraint, ...]) -> bool:
    return any(
        type(item.normalized_value) is int and item.normalized_value > 0
        for item in items
        if not _is_undetermined(item)
    )


def _has_known_traveler_count(items: tuple[Constraint, ...]) -> bool:
    return any(
        type(item.normalized_value) is int and item.normalized_value > 0
        for item in items
        if not _is_undetermined(item)
    )


def _is_undetermined(item: Constraint) -> bool:
    if item.hardness in {ConstraintHardness.UNKNOWN, ConstraintHardness.ASSUMPTION}:
        return True
    value = item.normalized_value
    if isinstance(value, str):
        return value.strip().casefold() in _UNKNOWN_TEXT
    if isinstance(value, tuple):
        return not value or all(item.strip().casefold() in _UNKNOWN_TEXT for item in value)
    return False


def _conflicting_groups(
    items: tuple[Constraint, ...],
) -> list[tuple[str, tuple[Constraint, ...]]]:
    groups = _group_by_conflict(items)
    return [
        (group_id, groups[group_id])
        for group_id in sorted(groups)
        if len({_value_key(item.normalized_value) for item in groups[group_id]}) > 1
    ]


def _group_by_conflict(
    constraints: Iterable[Constraint],
) -> dict[str, tuple[Constraint, ...]]:
    grouped: dict[str, list[Constraint]] = defaultdict(list)
    for item in constraints:
        if item.conflict_group is not None:
            grouped[item.conflict_group].append(item)
    return {group_id: tuple(items) for group_id, items in grouped.items()}


def _money_items(
    grouped: dict[str, tuple[Constraint, ...]],
    categories: set[str],
) -> list[Money]:
    return [
        item.normalized_value
        for item in _items_for(grouped, categories)
        if isinstance(item.normalized_value, Money)
    ]


def _refs(items: Iterable[Constraint]) -> tuple[str, ...]:
    return tuple(sorted({item.id for item in items}))


def _value_key(value: object) -> str:
    if isinstance(value, BaseModel):
        return value.model_dump_json()
    return repr(value)


def _blocker(
    code: ReadinessBlockerCode,
    *,
    field: str,
    message: str,
    constraint_refs: tuple[str, ...] = (),
    conflict_group: str | None = None,
    priority: int,
) -> ReadinessBlocker:
    digest_input = "|".join((code.value, field, conflict_group or "", *constraint_refs))
    issue_id = f"g1-{sha256(digest_input.encode()).hexdigest()[:24]}"
    return ReadinessBlocker(
        issue_id=issue_id,
        code=code,
        field=field,
        message=message,
        constraint_refs=constraint_refs,
        conflict_group=conflict_group,
        priority=priority,
    )


def _sort_blockers(blockers: Iterable[ReadinessBlocker]) -> tuple[ReadinessBlocker, ...]:
    unique: dict[str, ReadinessBlocker] = {item.issue_id: item for item in blockers}
    return tuple(
        sorted(unique.values(), key=lambda item: (item.priority, item.code.value, item.field))
    )


def _sort_assumptions(
    assumptions: Iterable[ReadinessAssumption],
) -> tuple[ReadinessAssumption, ...]:
    unique: dict[tuple[ReadinessAssumptionCode, str, tuple[str, ...]], ReadinessAssumption] = {}
    for item in assumptions:
        unique[(item.code, item.field, item.constraint_refs)] = item
    return tuple(sorted(unique.values(), key=lambda item: (item.code.value, item.field)))


def _confidence(
    snapshot: ConstraintSnapshot,
    interpretation: InterpretationResult | None,
    has_blockers: bool,
) -> Decimal:
    values = [item.confidence for item in snapshot.constraints]
    if interpretation is not None:
        values.append(interpretation.overall_confidence)
    if not values:
        return Decimal("0") if has_blockers else Decimal("1")
    return min(values)
