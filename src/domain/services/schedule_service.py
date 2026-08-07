"""M4 step eight: deterministic date and time scheduling."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, date, datetime, time, timedelta, timezone
from hashlib import sha256
from typing import Final, NoReturn, Self
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from pydantic import BaseModel, ConfigDict, Field, StrictInt, field_validator, model_validator

from src.agents.itinerary_composer import PlanCandidate
from src.domain.errors import WorkflowError
from src.domain.models.candidates import (
    Candidate,
    CandidatePoolResult,
    ContextCandidate,
    PlaceCandidate,
    StayCandidate,
    TransportCandidate,
)
from src.domain.models.enums import ErrorCategory, EvidenceStatus, WorkflowStatus
from src.domain.models.evidence import EvidenceSnapshot
from src.domain.models.itinerary import ItineraryDay, ItineraryPlan, PlanBuffer, PlanItem
from src.domain.models.trip_request import TripRequest
from src.domain.models.value_objects import CandidateId, EvidenceId, PlanId, StableId, TraceId

SCHEDULE_SCHEMA_VERSION: Final[str] = "m4-schedule-v1"
SCHEDULE_STAGE: Final[str] = "schedule_service"


class OpeningWindow(BaseModel):
    """One verified local opening interval for a candidate and trip day."""

    model_config = ConfigDict(extra="forbid", frozen=True, str_strip_whitespace=True)

    candidate_id: CandidateId
    day_number: int = Field(ge=1)
    opens_at: datetime
    closes_at: datetime
    evidence_refs: tuple[EvidenceId, ...] = Field(min_length=1)

    @field_validator("opens_at", "closes_at")
    @classmethod
    def validate_timezone(cls, value: datetime) -> datetime:
        """Require timezone-aware opening timestamps."""
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("opening window timestamps must be timezone-aware")
        return value

    @field_validator("evidence_refs")
    @classmethod
    def validate_unique_evidence_refs(
        cls, values: tuple[EvidenceId, ...]
    ) -> tuple[EvidenceId, ...]:
        """Reject duplicate evidence references."""
        if len(values) != len(set(values)):
            raise ValueError("opening window evidence_refs must be unique")
        return values

    @model_validator(mode="after")
    def validate_interval(self) -> Self:
        """Reject zero or negative business intervals."""
        if self.closes_at <= self.opens_at:
            raise ValueError("opening window must have positive duration")
        return self


class ActivitySpec(BaseModel):
    """Deterministic duration and flex buffer supplied by the scheduling boundary."""

    model_config = ConfigDict(extra="forbid", frozen=True, str_strip_whitespace=True)

    candidate_id: CandidateId
    duration_minutes: StrictInt = Field(gt=0)
    flex_buffer_minutes: StrictInt = Field(default=0, ge=0)
    evidence_refs: tuple[EvidenceId, ...] = Field(min_length=1)

    @field_validator("evidence_refs")
    @classmethod
    def validate_unique_evidence_refs(
        cls, values: tuple[EvidenceId, ...]
    ) -> tuple[EvidenceId, ...]:
        """Reject duplicate evidence references."""
        if len(values) != len(set(values)):
            raise ValueError("activity spec evidence_refs must be unique")
        return values


class RouteLeg(BaseModel):
    """Verified deterministic travel and transfer cost between two candidates."""

    model_config = ConfigDict(extra="forbid", frozen=True, str_strip_whitespace=True)

    from_candidate_id: CandidateId
    to_candidate_id: CandidateId
    duration_minutes: StrictInt = Field(ge=0)
    transfer_buffer_minutes: StrictInt = Field(default=0, ge=0)
    transfer_count: StrictInt = Field(default=0, ge=0)
    evidence_refs: tuple[EvidenceId, ...] = Field(min_length=1)

    @field_validator("evidence_refs")
    @classmethod
    def validate_unique_evidence_refs(
        cls, values: tuple[EvidenceId, ...]
    ) -> tuple[EvidenceId, ...]:
        """Reject duplicate evidence references."""
        if len(values) != len(set(values)):
            raise ValueError("route leg evidence_refs must be unique")
        return values

    @model_validator(mode="after")
    def validate_endpoints(self) -> Self:
        """Reject self routes that cannot represent movement."""
        if self.from_candidate_id == self.to_candidate_id:
            raise ValueError("route leg endpoints must be different")
        return self

    @property
    def total_minutes(self) -> int:
        """Return travel plus deterministic transfer buffer."""
        return self.duration_minutes + self.transfer_buffer_minutes


class SchedulePolicy(BaseModel):
    """Local-day bounds used by deterministic scheduling."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    day_start_local: time = time(hour=8)
    day_end_local: time = time(hour=22)

    @field_validator("day_start_local", "day_end_local")
    @classmethod
    def validate_local_time(cls, value: time) -> time:
        """Require wall-clock times without a second timezone."""
        if value.tzinfo is not None:
            raise ValueError("schedule policy times must be naive local times")
        return value.replace(microsecond=0)

    @model_validator(mode="after")
    def validate_day_bounds(self) -> Self:
        """Require a positive daily scheduling interval."""
        if self.day_end_local <= self.day_start_local:
            raise ValueError("day_end_local must be later than day_start_local")
        return self


class ScheduleContext(BaseModel):
    """Immutable inputs shared by Composer output and ScheduleService."""

    model_config = ConfigDict(extra="forbid", frozen=True, str_strip_whitespace=True)

    trace_id: TraceId
    as_of: datetime
    request: TripRequest
    constraint_snapshot_version: int = Field(ge=1)
    evidence_snapshot_id: StableId
    candidate_pool: CandidatePoolResult
    evidence_snapshot: EvidenceSnapshot
    plan_candidate: PlanCandidate
    opening_windows: tuple[OpeningWindow, ...] = ()
    activity_specs: tuple[ActivitySpec, ...] = ()
    route_legs: tuple[RouteLeg, ...] = ()
    policy: SchedulePolicy = Field(default_factory=SchedulePolicy)

    @field_validator("as_of")
    @classmethod
    def validate_as_of_timezone(cls, value: datetime) -> datetime:
        """Require a timezone for evidence freshness decisions."""
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("as_of must be timezone-aware")
        return value

    @model_validator(mode="after")
    def validate_snapshot_and_references(self) -> Self:
        """Ensure every schedule input belongs to one verified snapshot."""
        if self.candidate_pool.constraint_snapshot_version != self.constraint_snapshot_version:
            raise ValueError("candidate pool and constraint snapshot versions differ")
        if self.candidate_pool.evidence_snapshot_id != self.evidence_snapshot_id:
            raise ValueError("candidate pool and evidence snapshot differ")
        candidate_by_id = {
            candidate.candidate_id: candidate for candidate in self.candidate_pool.candidates
        }
        selected_refs = set(self.plan_candidate.selected_candidate_refs)
        if selected_refs.difference(candidate_by_id):
            raise ValueError("plan candidate references candidates outside the pool")
        if any(isinstance(candidate_by_id[ref], ContextCandidate) for ref in selected_refs):
            raise ValueError("plan candidate must not select ContextCandidate")
        spec_ids = tuple(spec.candidate_id for spec in self.activity_specs)
        if len(spec_ids) != len(set(spec_ids)):
            raise ValueError("activity specs must be unique by candidate")
        window_keys = tuple(
            (w.candidate_id, w.day_number, w.opens_at, w.closes_at) for w in self.opening_windows
        )
        if len(window_keys) != len(set(window_keys)):
            raise ValueError("opening windows must be unique")
        route_keys = tuple((leg.from_candidate_id, leg.to_candidate_id) for leg in self.route_legs)
        if len(route_keys) != len(set(route_keys)):
            raise ValueError("route legs must be unique by direction")
        if any(w.candidate_id not in selected_refs for w in self.opening_windows):
            raise ValueError("opening window references an unselected candidate")
        if any(spec.candidate_id not in selected_refs for spec in self.activity_specs):
            raise ValueError("activity spec references an unselected candidate")
        if any(
            leg.from_candidate_id not in selected_refs or leg.to_candidate_id not in selected_refs
            for leg in self.route_legs
        ):
            raise ValueError("route leg references an unselected candidate")
        evidence_by_id = {item.evidence_id: item for item in self.evidence_snapshot.evidence_items}
        required_refs = {
            ref
            for candidate_id in selected_refs
            for ref in candidate_by_id[candidate_id].evidence_refs
        }
        required_refs.update(ref for window in self.opening_windows for ref in window.evidence_refs)
        required_refs.update(ref for spec in self.activity_specs for ref in spec.evidence_refs)
        required_refs.update(ref for leg in self.route_legs for ref in leg.evidence_refs)
        _validate_verified_evidence(
            evidence_by_id, required_refs, self.evidence_snapshot.conflict_refs, self.as_of
        )
        return self

    @property
    def day_count(self) -> int:
        """Return the exact number of calendar days available to scheduling."""
        if self.request.date_range is not None:
            return self.request.date_range.days
        if self.request.duration_days is not None:
            return self.request.duration_days
        raise ValueError("request does not contain a duration")


class ScheduleResult(BaseModel):
    """Stable scheduling result for later budget and validation services."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    trace_id: TraceId
    plan_candidate_id: PlanId
    variant: str = Field(min_length=1, max_length=32)
    schema_version: str = SCHEDULE_SCHEMA_VERSION
    itinerary_plan: ItineraryPlan
    route_legs: tuple[RouteLeg, ...] = ()
    total_flex_buffer_minutes: StrictInt = Field(ge=0)

    @model_validator(mode="after")
    def validate_plan_identity(self) -> Self:
        """Keep the materialized itinerary tied to the Composer candidate."""
        if self.itinerary_plan.plan_id != self.plan_candidate_id:
            raise ValueError("itinerary plan must use the PlanCandidate ID")
        return self

    @property
    def plan(self) -> ItineraryPlan:
        """Expose the scheduled domain plan for downstream deterministic services."""
        return self.itinerary_plan


class ScheduleError(WorkflowError):
    """Fail-fast error raised by deterministic ScheduleService."""

    def __init__(
        self,
        trace_id: TraceId,
        code: str,
        safe_message: str,
        *,
        category: ErrorCategory = ErrorCategory.VALIDATION,
        upstream_refs: tuple[StableId, ...] = (),
        cause: BaseException | None = None,
    ) -> None:
        super().__init__(
            trace_id=trace_id,
            stage=SCHEDULE_STAGE,
            category=category,
            code=code,
            safe_message=safe_message,
            upstream_refs=upstream_refs,
            retryable=False,
            cause=cause,
        )


@dataclass(frozen=True)
class _ScheduledEvent:
    """Internal immutable event used before materializing ItineraryPlan."""

    candidate_id: CandidateId
    title: str
    kind: str
    start_at: datetime
    end_at: datetime
    evidence_refs: tuple[EvidenceId, ...]


class ScheduleService:
    """Assign exact dates and deterministic time windows to a PlanCandidate."""

    def schedule(self, context: ScheduleContext) -> ScheduleResult:
        """Materialize one plan candidate into a non-overlapping itinerary.

        Args:
            context: Verified candidates, timing inputs, and an exact date range.

        Returns:
            ScheduleResult: A versioned ItineraryPlan with explicit day and time data.

        Raises:
            ScheduleError: If any required timing, route, evidence, or slot is invalid.
        """
        if not isinstance(context, ScheduleContext):
            raise TypeError("context must be a ScheduleContext")
        if context.request.date_range is None:
            _raise_schedule_error(
                context,
                "SCHEDULE_DATE_RANGE_REQUIRED",
                "ScheduleService requires an exact date_range; duration alone is insufficient",
            )
        timezone = _load_timezone(context)
        candidate_by_id = {
            candidate.candidate_id: candidate for candidate in context.candidate_pool.candidates
        }
        day_refs = _day_refs(context.plan_candidate)
        fixed_by_day = self._build_fixed_events(context, candidate_by_id, timezone)
        route_by_pair = {
            (leg.from_candidate_id, leg.to_candidate_id): leg for leg in context.route_legs
        }
        activity_by_id = {spec.candidate_id: spec for spec in context.activity_specs}
        windows_by_key: dict[tuple[CandidateId, int], tuple[OpeningWindow, ...]] = {}
        for window in sorted(
            context.opening_windows,
            key=lambda item: (item.candidate_id, item.day_number, item.opens_at, item.closes_at),
        ):
            key = (window.candidate_id, window.day_number)
            windows_by_key[key] = (*windows_by_key.get(key, ()), window)

        events_by_day: dict[int, list[_ScheduledEvent]] = {
            day: [] for day in range(1, context.day_count + 1)
        }
        used_fixed_events: set[_ScheduledEvent] = set()
        flex_minutes_by_day: dict[int, int] = {}
        for day_number in range(1, context.day_count + 1):
            day_start, day_end = _day_bounds(context, timezone, day_number)
            cursor = day_start
            previous_candidate_id: CandidateId | None = None
            for candidate_id in day_refs.get(day_number, ()):
                candidate = candidate_by_id[candidate_id]
                if previous_candidate_id is not None:
                    cursor = self._apply_route(
                        context, route_by_pair, previous_candidate_id, candidate_id, cursor, day_end
                    )
                if isinstance(candidate, TransportCandidate | StayCandidate):
                    candidate_events = tuple(
                        event
                        for event in fixed_by_day[day_number]
                        if event.candidate_id == candidate_id
                    )
                    if not candidate_events:
                        _raise_schedule_error(
                            context,
                            "SCHEDULE_FIXED_EVENT_MISSING",
                            "a fixed-time candidate has no event on its assigned day",
                            upstream_refs=(candidate_id,),
                        )
                    for event in candidate_events:
                        cursor = self._place_fixed_event(
                            context, event, cursor, day_start, day_end, events_by_day[day_number]
                        )
                        events_by_day[day_number].append(event)
                        used_fixed_events.add(event)
                    previous_candidate_id = candidate_id
                    continue
                if not isinstance(candidate, PlaceCandidate):
                    _raise_schedule_error(
                        context,
                        "SCHEDULE_CANDIDATE_UNSUPPORTED",
                        "only transport, stay, and place candidates can be scheduled",
                        upstream_refs=(candidate_id,),
                    )
                event, cursor, flex_minutes = self._schedule_place(
                    context,
                    candidate,
                    cursor,
                    day_start,
                    day_end,
                    windows_by_key.get((candidate_id, day_number), ()),
                    activity_by_id.get(candidate_id),
                    fixed_by_day[day_number],
                    events_by_day[day_number],
                )
                events_by_day[day_number].append(event)
                flex_minutes_by_day[day_number] = (
                    flex_minutes_by_day.get(day_number, 0) + flex_minutes
                )
                previous_candidate_id = candidate_id
            for event in fixed_by_day[day_number]:
                if event not in used_fixed_events:
                    events_by_day[day_number].append(event)
            self._validate_day_events(context, day_number, events_by_day[day_number])

        items: list[PlanItem] = []
        days: list[ItineraryDay] = []
        all_evidence_refs: list[EvidenceId] = list(context.plan_candidate.evidence_refs)
        all_evidence_refs.extend(ref for leg in context.route_legs for ref in leg.evidence_refs)
        ordinal = 0
        for day_number in range(1, context.day_count + 1):
            day_events = sorted(
                events_by_day[day_number],
                key=lambda event: (event.start_at, event.end_at, event.candidate_id, event.kind),
            )
            item_refs: list[str] = []
            for event in day_events:
                item_id = _stable_item_id(context.plan_candidate.plan_candidate_id, ordinal)
                ordinal += 1
                items.append(
                    PlanItem(
                        plan_item_id=item_id,
                        candidate_id=event.candidate_id,
                        day_number=day_number,
                        title=event.title,
                        start_at=event.start_at,
                        end_at=event.end_at,
                        evidence_refs=event.evidence_refs,
                    )
                )
                item_refs.append(item_id)
                all_evidence_refs.extend(event.evidence_refs)
            days.append(
                ItineraryDay(
                    day_number=day_number,
                    date=context.request.date_range.start + timedelta(days=day_number - 1),
                    item_refs=tuple(item_refs),
                )
            )

        unique_evidence_refs = tuple(dict.fromkeys(all_evidence_refs))
        total_flex = sum(flex_minutes_by_day.values())
        buffers = tuple(
            PlanBuffer(buffer_type=f"flex-day-{day}", minutes=minutes)
            for day, minutes in sorted(flex_minutes_by_day.items())
            if minutes > 0
        )
        itinerary_plan = ItineraryPlan(
            plan_id=context.plan_candidate.plan_candidate_id,
            version=1,
            status=WorkflowStatus.DRAFTING,
            date_range=context.request.date_range,
            days=tuple(days),
            items=tuple(items),
            buffers=buffers,
            assumptions=context.plan_candidate.assumptions,
            warnings=context.plan_candidate.warnings,
            evidence_refs=unique_evidence_refs,
        )
        return ScheduleResult(
            trace_id=context.trace_id,
            plan_candidate_id=context.plan_candidate.plan_candidate_id,
            variant=context.plan_candidate.variant,
            itinerary_plan=itinerary_plan,
            route_legs=context.route_legs,
            total_flex_buffer_minutes=total_flex,
        )

    def _build_fixed_events(
        self,
        context: ScheduleContext,
        candidate_by_id: dict[CandidateId, Candidate],
        timezone: ZoneInfo,
    ) -> dict[int, tuple[_ScheduledEvent, ...]]:
        """Convert provider candidate timestamps into request-local fixed events."""
        fixed: dict[int, list[_ScheduledEvent]] = {
            day: [] for day in range(1, context.day_count + 1)
        }
        date_range = context.request.date_range
        if date_range is None:
            _raise_schedule_error(
                context, "SCHEDULE_DATE_RANGE_REQUIRED", "exact date_range is required"
            )
        for candidate_id in sorted(context.plan_candidate.selected_candidate_refs):
            candidate = candidate_by_id[candidate_id]
            if isinstance(candidate, TransportCandidate):
                if candidate.departure_at is None or candidate.arrival_at is None:
                    _raise_schedule_error(
                        context,
                        "SCHEDULE_FIXED_TIME_MISSING",
                        "transport candidate must provide departure_at and arrival_at",
                        upstream_refs=(candidate_id,),
                    )
                start_at = candidate.departure_at.astimezone(timezone)
                end_at = candidate.arrival_at.astimezone(timezone)
                if end_at <= start_at:
                    _raise_schedule_error(
                        context,
                        "SCHEDULE_NEGATIVE_DURATION",
                        "transport candidate has a non-positive duration",
                        upstream_refs=(candidate_id,),
                    )
                if start_at.date() != end_at.date():
                    _raise_schedule_error(
                        context,
                        "SCHEDULE_CROSS_DAY_FIXED_EVENT",
                        "transport event crosses a local calendar day",
                        upstream_refs=(candidate_id,),
                    )
                day = _day_number(date_range.start, start_at.date())
                if not 1 <= day <= context.day_count:
                    _raise_schedule_error(
                        context,
                        "SCHEDULE_FIXED_EVENT_OUTSIDE_RANGE",
                        "transport event is outside the requested date range",
                        upstream_refs=(candidate_id,),
                    )
                fixed[day].append(
                    _ScheduledEvent(
                        candidate_id=candidate_id,
                        title=candidate.name,
                        kind="transport",
                        start_at=start_at,
                        end_at=end_at,
                        evidence_refs=candidate.evidence_refs,
                    )
                )
            elif isinstance(candidate, StayCandidate):
                if candidate.check_in is None or candidate.check_out is None:
                    _raise_schedule_error(
                        context,
                        "SCHEDULE_FIXED_TIME_MISSING",
                        "stay candidate must provide check_in and check_out",
                        upstream_refs=(candidate_id,),
                    )
                check_in = candidate.check_in.astimezone(timezone)
                check_out = candidate.check_out.astimezone(timezone)
                if check_out <= check_in:
                    _raise_schedule_error(
                        context,
                        "SCHEDULE_NEGATIVE_DURATION",
                        "stay candidate has a non-positive stay window",
                        upstream_refs=(candidate_id,),
                    )
                check_in_day = _day_number(date_range.start, check_in.date())
                check_out_day = _day_number(date_range.start, check_out.date())
                if (
                    not 1 <= check_in_day <= context.day_count
                    or not 1 <= check_out_day <= context.day_count
                ):
                    _raise_schedule_error(
                        context,
                        "SCHEDULE_FIXED_EVENT_OUTSIDE_RANGE",
                        "stay check-in or check-out is outside the requested date range",
                        upstream_refs=(candidate_id,),
                    )
                fixed[check_in_day].append(
                    _ScheduledEvent(
                        candidate_id=candidate_id,
                        title=f"{candidate.name} check-in",
                        kind="stay_check_in",
                        start_at=check_in,
                        end_at=check_in,
                        evidence_refs=candidate.evidence_refs,
                    )
                )
                fixed[check_out_day].append(
                    _ScheduledEvent(
                        candidate_id=candidate_id,
                        title=f"{candidate.name} check-out",
                        kind="stay_check_out",
                        start_at=check_out,
                        end_at=check_out,
                        evidence_refs=candidate.evidence_refs,
                    )
                )
        return {
            day: tuple(sorted(events, key=lambda event: (event.start_at, event.kind)))
            for day, events in fixed.items()
        }

    def _apply_route(
        self,
        context: ScheduleContext,
        route_by_pair: dict[tuple[CandidateId, CandidateId], RouteLeg],
        from_candidate_id: CandidateId,
        to_candidate_id: CandidateId,
        cursor: datetime,
        day_end: datetime,
    ) -> datetime:
        """Consume a verified route leg before the next scheduled candidate."""
        leg = route_by_pair.get((from_candidate_id, to_candidate_id))
        if leg is None:
            _raise_schedule_error(
                context,
                "SCHEDULE_ROUTE_MISSING",
                "a route leg is required between consecutive candidates",
                upstream_refs=(from_candidate_id, to_candidate_id),
            )
        if leg.duration_minutes < 0 or leg.transfer_buffer_minutes < 0:
            _raise_schedule_error(
                context,
                "SCHEDULE_NEGATIVE_DURATION",
                "route duration and transfer buffer must not be negative",
                upstream_refs=leg.evidence_refs,
            )
        ready_at = cursor + timedelta(minutes=leg.total_minutes)
        if ready_at > day_end:
            _raise_schedule_error(
                context,
                "SCHEDULE_ROUTE_OVERFLOW",
                "route and transfer buffer exceed the daily scheduling window",
                upstream_refs=leg.evidence_refs,
            )
        return ready_at

    def _place_fixed_event(
        self,
        context: ScheduleContext,
        event: _ScheduledEvent,
        cursor: datetime,
        day_start: datetime,
        day_end: datetime,
        existing_events: list[_ScheduledEvent],
    ) -> datetime:
        """Place one exact-time event while honoring its event semantics."""
        if event.end_at < event.start_at:
            _raise_schedule_error(
                context,
                "SCHEDULE_NEGATIVE_DURATION",
                "fixed event has a negative duration",
                upstream_refs=(event.candidate_id,),
            )
        is_stay_boundary = event.kind in {"stay_check_in", "stay_check_out"}
        if not is_stay_boundary and (event.start_at < day_start or event.end_at > day_end):
            _raise_schedule_error(
                context,
                "SCHEDULE_FIXED_EVENT_OUTSIDE_DAY",
                "fixed event is outside the configured daily window",
                upstream_refs=(event.candidate_id,),
            )
        if (not is_stay_boundary and event.start_at < cursor) or any(
            _events_overlap(event, other) for other in existing_events
        ):
            _raise_schedule_error(
                context,
                "SCHEDULE_OVERLAP",
                "fixed event overlaps an earlier scheduled event",
                upstream_refs=(event.candidate_id,),
            )
        return max(cursor, event.end_at)

    def _schedule_place(
        self,
        context: ScheduleContext,
        candidate: PlaceCandidate,
        cursor: datetime,
        day_start: datetime,
        day_end: datetime,
        windows: tuple[OpeningWindow, ...],
        spec: ActivitySpec | None,
        fixed_events: tuple[_ScheduledEvent, ...],
        existing_events: list[_ScheduledEvent],
    ) -> tuple[_ScheduledEvent, datetime, int]:
        """Find the first deterministic slot satisfying opening and route bounds."""
        if spec is None:
            _raise_schedule_error(
                context,
                "SCHEDULE_ACTIVITY_SPEC_MISSING",
                "a place candidate requires an explicit activity duration",
                upstream_refs=(candidate.candidate_id,),
            )
        if spec.duration_minutes <= 0 or spec.flex_buffer_minutes < 0:
            _raise_schedule_error(
                context,
                "SCHEDULE_NEGATIVE_DURATION",
                "activity duration and flex buffer must be non-negative as configured",
                upstream_refs=spec.evidence_refs,
            )
        if not windows:
            _raise_schedule_error(
                context,
                "SCHEDULE_OPENING_WINDOW_MISSING",
                "a place candidate requires at least one opening window per scheduled day",
                upstream_refs=(candidate.candidate_id,),
            )
        blockers = (*fixed_events, *existing_events)
        for window in windows:
            opens_at = window.opens_at.astimezone(day_start.tzinfo)
            closes_at = window.closes_at.astimezone(day_start.tzinfo)
            if opens_at.date() != day_start.date() or closes_at.date() != day_start.date():
                _raise_schedule_error(
                    context,
                    "SCHEDULE_OPENING_WINDOW_DATE_MISMATCH",
                    "opening window date does not match its assigned trip day",
                    upstream_refs=window.evidence_refs,
                )
            if closes_at <= opens_at:
                _raise_schedule_error(
                    context,
                    "SCHEDULE_NEGATIVE_DURATION",
                    "opening window has a non-positive duration",
                    upstream_refs=window.evidence_refs,
                )
            candidate_start = max(cursor, opens_at, day_start)
            duration = timedelta(minutes=spec.duration_minutes)
            while True:
                candidate_end = candidate_start + duration
                conflict = next(
                    (
                        blocker
                        for blocker in sorted(
                            blockers,
                            key=lambda event: (event.start_at, event.end_at, event.candidate_id),
                        )
                        if _interval_conflicts(candidate_start, candidate_end, blocker)
                    ),
                    None,
                )
                if conflict is None:
                    break
                candidate_start = max(conflict.end_at, opens_at)
            if candidate_end > closes_at or candidate_end > day_end:
                continue
            after_buffer = candidate_end + timedelta(minutes=spec.flex_buffer_minutes)
            if after_buffer > day_end:
                continue
            event = _ScheduledEvent(
                candidate_id=candidate.candidate_id,
                title=candidate.name,
                kind="place_activity",
                start_at=candidate_start,
                end_at=candidate_end,
                evidence_refs=tuple(
                    dict.fromkeys(
                        (*candidate.evidence_refs, *window.evidence_refs, *spec.evidence_refs)
                    )
                ),
            )
            return event, after_buffer, spec.flex_buffer_minutes
        _raise_schedule_error(
            context,
            "SCHEDULE_NO_FEASIBLE_SLOT",
            "no opening window can fit the activity duration and buffers",
            upstream_refs=(candidate.candidate_id,),
        )

    def _validate_day_events(
        self, context: ScheduleContext, day_number: int, events: list[_ScheduledEvent]
    ) -> None:
        """Apply the final deterministic overlap check for one day."""
        ordered = sorted(
            events, key=lambda event: (event.start_at, event.end_at, event.candidate_id)
        )
        for event in ordered:
            if event.end_at < event.start_at:
                _raise_schedule_error(
                    context,
                    "SCHEDULE_NEGATIVE_DURATION",
                    "scheduled event has a negative duration",
                    upstream_refs=(event.candidate_id,),
                )
        if any(
            _events_overlap(left, right) for left, right in zip(ordered, ordered[1:], strict=False)
        ):
            _raise_schedule_error(
                context,
                "SCHEDULE_OVERLAP",
                f"scheduled events overlap on day {day_number}",
                upstream_refs=tuple(event.candidate_id for event in ordered),
            )


def _day_refs(plan_candidate: PlanCandidate) -> dict[int, tuple[CandidateId, ...]]:
    """Normalize the Composer skeleton into a stable day-to-candidate mapping."""
    return {
        day.day_number: tuple(day.candidate_refs)
        for day in sorted(plan_candidate.day_skeleton, key=lambda item: item.day_number)
    }


def _day_number(start_date: date, target_date: date) -> int:
    """Return one-based day number for an exact date."""
    return (target_date - start_date).days + 1


def _day_bounds(
    context: ScheduleContext, timezone: ZoneInfo, day_number: int
) -> tuple[datetime, datetime]:
    """Create timezone-aware local boundaries for one itinerary day."""
    date_range = context.request.date_range
    if date_range is None:
        _raise_schedule_error(
            context, "SCHEDULE_DATE_RANGE_REQUIRED", "exact date_range is required"
        )
    target_date = date_range.start + timedelta(days=day_number - 1)
    start_at = datetime.combine(target_date, context.policy.day_start_local, timezone)
    end_at = datetime.combine(target_date, context.policy.day_end_local, timezone)
    if end_at <= start_at:
        _raise_schedule_error(
            context,
            "SCHEDULE_POLICY_INVALID",
            "daily scheduling window must have positive duration",
        )
    return start_at, end_at


def _load_timezone(context: ScheduleContext) -> timezone | ZoneInfo:
    """Resolve an IANA timezone with the project's explicit fixed-zone contract."""
    try:
        return ZoneInfo(context.request.timezone)
    except ZoneInfoNotFoundError:
        fixed_offsets = {
            "UTC": UTC,
            "Asia/Shanghai": timezone(timedelta(hours=8), "Asia/Shanghai"),
        }
        fixed = fixed_offsets.get(context.request.timezone)
        if fixed is None:
            _raise_schedule_error(
                context,
                "SCHEDULE_TIMEZONE_INVALID",
                "request timezone data is unavailable",
            )
        return fixed
    except ValueError as exc:
        _raise_schedule_error(
            context,
            "SCHEDULE_TIMEZONE_INVALID",
            "request timezone is not a valid IANA timezone",
            cause=exc,
        )


def _validate_verified_evidence(
    evidence_by_id: dict[EvidenceId, object],
    required_refs: set[EvidenceId],
    conflict_refs: tuple[EvidenceId, ...],
    as_of: datetime,
) -> None:
    """Validate evidence references without accepting stale or conflicting facts."""
    missing = required_refs.difference(evidence_by_id)
    if missing:
        raise ValueError("schedule input references missing evidence")
    for evidence_ref in sorted(required_refs):
        evidence = evidence_by_id[evidence_ref]
        if not hasattr(evidence, "status"):
            raise ValueError("schedule input evidence has an invalid shape")
        if evidence.status is not EvidenceStatus.VERIFIED:
            raise ValueError("schedule input evidence is not verified")
        if evidence_ref in conflict_refs:
            raise ValueError("schedule input evidence is conflicting")
        if evidence.valid_until is not None and evidence.valid_until <= as_of:
            raise ValueError("schedule input evidence is expired")


def _events_overlap(left: _ScheduledEvent, right: _ScheduledEvent) -> bool:
    """Return whether two event intervals overlap, including a point inside an interval."""
    return _interval_conflicts(left.start_at, left.end_at, right) or _interval_conflicts(
        right.start_at, right.end_at, left
    )


def _interval_conflicts(start_at: datetime, end_at: datetime, event: _ScheduledEvent) -> bool:
    """Check an interval against an event; touching boundaries are allowed."""
    if start_at == end_at:
        return event.start_at < start_at < event.end_at
    if event.start_at == event.end_at:
        return start_at < event.start_at < end_at
    return start_at < event.end_at and event.start_at < end_at


def _stable_item_id(plan_candidate_id: PlanId, ordinal: int) -> str:
    """Generate a bounded deterministic PlanItem ID."""
    digest = sha256(f"{plan_candidate_id}:{ordinal}".encode()).hexdigest()[:24]
    return f"plan-item:{digest}"


def _raise_schedule_error(
    context: ScheduleContext,
    code: str,
    safe_message: str,
    *,
    category: ErrorCategory = ErrorCategory.VALIDATION,
    upstream_refs: tuple[StableId, ...] = (),
    cause: BaseException | None = None,
) -> NoReturn:
    """Raise one structured fail-fast error for the current scheduling trace."""
    raise ScheduleError(
        trace_id=context.trace_id,
        code=code,
        safe_message=safe_message,
        category=category,
        upstream_refs=upstream_refs,
        cause=cause,
    )


__all__ = [
    "ActivitySpec",
    "OpeningWindow",
    "RouteLeg",
    "SCHEDULE_SCHEMA_VERSION",
    "SCHEDULE_STAGE",
    "ScheduleContext",
    "ScheduleError",
    "SchedulePolicy",
    "ScheduleResult",
    "ScheduleService",
]
