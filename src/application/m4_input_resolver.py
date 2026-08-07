"""Deterministic M2-to-M4 planning input resolution."""

from __future__ import annotations

from datetime import date

from src.domain.errors import WorkflowError
from src.domain.models.constraint import ConstraintSnapshot
from src.domain.models.enums import ConstraintHardness, ErrorCategory
from src.domain.models.trip_request import BudgetSemantics, BudgetSpec, TravelerProfile, TripRequest
from src.domain.models.value_objects import DateRange, Money, TraceId

_ORIGIN_CATEGORIES = frozenset({"origin", "departure", "departure_city", "depart_from", "from"})
_DESTINATION_CATEGORIES = frozenset(
    {"destination", "destinations", "arrival", "arrival_city", "arrive_at", "to"}
)
_DATE_CATEGORIES = frozenset({"date", "date_range", "travel_date", "travel_dates"})
_TRAVELER_CATEGORIES = frozenset(
    {"traveler", "travelers", "people", "person_count", "traveler_count"}
)
_BUDGET_MAX_CATEGORIES = frozenset({"budget_max", "price_limit"})
_BUDGET_MIN_CATEGORIES = frozenset({"budget_min",})
_BUDGET_TARGET_CATEGORIES = frozenset({"budget_target",})
_PREFERENCE_CATEGORIES = frozenset({"preference", "preferences"})
_EXCLUSION_CATEGORIES = frozenset({"exclude", "exclusion", "explicit_exclusion"})


class M4InputResolver:
    """Bind the authoritative ConstraintSnapshot to the M4 request contract."""

    def resolve(
        self,
        request: TripRequest,
        snapshot: ConstraintSnapshot,
        *,
        trace_id: TraceId,
    ) -> TripRequest:
        """Return a request enriched only by resolved snapshot values."""
        if not isinstance(request, TripRequest):
            raise TypeError("request must be a TripRequest")
        if not isinstance(snapshot, ConstraintSnapshot):
            raise TypeError("snapshot must be a ConstraintSnapshot")
        if request.request_id != snapshot.request_id:
            raise WorkflowError(
                trace_id=trace_id,
                stage="m4_input",
                category=ErrorCategory.STATE_CONFLICT,
                code="M4_INPUT_SNAPSHOT_MISMATCH",
                safe_message="M4 request and constraint snapshot belong to different requests",
                upstream_refs=(request.request_id, snapshot.request_id),
            )

        updates: dict[str, object] = {}
        origin = self._single_value(snapshot, _ORIGIN_CATEGORIES, "origin", trace_id)
        if origin is not None:
            if not isinstance(origin, str):
                self._invalid(trace_id, "origin constraint is not text")
            updates["origin"] = origin

        destinations = self._single_value(
            snapshot,
            _DESTINATION_CATEGORIES,
            "destination",
            trace_id,
        )
        if destinations is not None:
            if isinstance(destinations, str):
                updates["destinations"] = (destinations,)
            elif isinstance(destinations, tuple) and all(
                isinstance(item, str) for item in destinations
            ):
                updates["destinations"] = tuple(dict.fromkeys(destinations))
            else:
                self._invalid(trace_id, "destination constraint has an invalid value")

        date_value = self._single_value(snapshot, _DATE_CATEGORIES, "date_range", trace_id)
        if date_value is not None:
            date_range = _as_date_range(date_value, trace_id)
            updates["date_range"] = date_range
            updates["duration_days"] = date_range.days

        traveler_value = self._single_value(snapshot, _TRAVELER_CATEGORIES, "travelers", trace_id)
        if traveler_value is not None:
            if type(traveler_value) is not int or traveler_value <= 0:
                self._invalid(trace_id, "traveler constraint has an invalid value")
            current = request.travelers
            if current.total_count != traveler_value:
                if current.children or current.seniors or current.accessibility_needs:
                    self._invalid(
                        trace_id,
                        "traveler constraint conflicts with the structured traveler profile",
                    )
                updates["travelers"] = TravelerProfile(adults=traveler_value)

        budget = _budget_from_snapshot(snapshot, request.budget, trace_id)
        if budget is not None:
            updates["budget"] = budget

        preferences = _append_text_values(
            request.preferences,
            _values(snapshot, _PREFERENCE_CATEGORIES),
        )
        exclusions = _append_text_values(
            request.explicit_exclusions,
            _values(snapshot, _EXCLUSION_CATEGORIES),
        )
        if preferences != request.preferences:
            updates["preferences"] = preferences
        if exclusions != request.explicit_exclusions:
            updates["explicit_exclusions"] = exclusions

        return request.model_copy(update=updates)

    @staticmethod
    def _single_value(
        snapshot: ConstraintSnapshot,
        categories: frozenset[str],
        field: str,
        trace_id: TraceId,
    ) -> object | None:
        values = tuple(
            constraint.normalized_value
            for constraint in snapshot.constraints
            if (
                constraint.category in categories
                and constraint.hardness
                not in {
                    ConstraintHardness.UNKNOWN,
                    ConstraintHardness.ASSUMPTION,
                }
            )
        )
        unique = tuple(dict.fromkeys(values))
        if len(unique) > 1:
            raise WorkflowError(
                trace_id=trace_id,
                stage="m4_input",
                category=ErrorCategory.VALIDATION,
                code="M4_INPUT_AMBIGUOUS",
                safe_message=f"M4 input has multiple unresolved values for {field}",
                upstream_refs=tuple(
                    constraint.id
                    for constraint in snapshot.constraints
                    if (
                        constraint.category in categories
                        and constraint.hardness
                        not in {
                            ConstraintHardness.UNKNOWN,
                            ConstraintHardness.ASSUMPTION,
                        }
                    )
                ),
            )
        return unique[0] if unique else None

    @staticmethod
    def _invalid(trace_id: TraceId, message: str) -> None:
        raise WorkflowError(
            trace_id=trace_id,
            stage="m4_input",
            category=ErrorCategory.VALIDATION,
            code="M4_INPUT_INVALID",
            safe_message=message,
        )


def _as_date_range(value: object, trace_id: TraceId) -> DateRange:
    if isinstance(value, DateRange):
        return value
    if isinstance(value, date):
        return DateRange(start=value, end=value)
    raise WorkflowError(
        trace_id=trace_id,
        stage="m4_input",
        category=ErrorCategory.VALIDATION,
        code="M4_INPUT_INVALID",
        safe_message="date constraint has an invalid value",
    )


def _values(snapshot: ConstraintSnapshot, categories: frozenset[str]) -> tuple[str, ...]:
    result: list[str] = []
    for constraint in snapshot.constraints:
        if (
            constraint.category not in categories
            or constraint.hardness in {ConstraintHardness.UNKNOWN, ConstraintHardness.ASSUMPTION}
        ):
            continue
        value = constraint.normalized_value
        if isinstance(value, str):
            result.append(value)
        elif isinstance(value, tuple) and all(isinstance(item, str) for item in value):
            result.extend(value)
    return tuple(dict.fromkeys(result))


def _append_text_values(existing: tuple[str, ...], additions: tuple[str, ...]) -> tuple[str, ...]:
    return tuple(dict.fromkeys((*existing, *additions)))


def _budget_from_snapshot(
    snapshot: ConstraintSnapshot,
    existing: BudgetSpec | None,
    trace_id: TraceId,
) -> BudgetSpec | None:
    if existing is not None:
        return existing
    maximum = _money_value(snapshot, _BUDGET_MAX_CATEGORIES)
    minimum = _money_value(snapshot, _BUDGET_MIN_CATEGORIES)
    target = _money_value(snapshot, _BUDGET_TARGET_CATEGORIES)
    if target is not None and maximum is not None:
        raise WorkflowError(
            trace_id=trace_id,
            stage="m4_input",
            category=ErrorCategory.VALIDATION,
            code="M4_INPUT_AMBIGUOUS",
            safe_message="budget constraints have incompatible semantics",
        )
    if target is not None:
        return BudgetSpec(semantics=BudgetSemantics.TARGET, target=target)
    if minimum is not None and maximum is not None:
        return BudgetSpec(
            semantics=BudgetSemantics.RANGE,
            minimum=minimum,
            maximum=maximum,
        )
    if maximum is not None:
        return BudgetSpec(semantics=BudgetSemantics.MAXIMUM, maximum=maximum)
    return None


def _money_value(snapshot: ConstraintSnapshot, categories: frozenset[str]) -> Money | None:
    values = tuple(
        constraint.normalized_value
        for constraint in snapshot.constraints
        if (
            constraint.category in categories
            and constraint.hardness not in {
                ConstraintHardness.UNKNOWN,
                ConstraintHardness.ASSUMPTION,
            }
        )
    )
    if not values:
        return None
    if len(values) != 1 or not isinstance(values[0], Money):
        return None
    return values[0]


__all__ = ["M4InputResolver"]
