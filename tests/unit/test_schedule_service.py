"""M4 step eight: deterministic ScheduleService tests."""

from __future__ import annotations

from datetime import UTC, datetime, time, timedelta, timezone
from decimal import Decimal

import pytest
from pydantic import ValidationError

from src.agents.itinerary_composer import PlanCandidate, PlanDaySkeleton
from src.domain.models.candidates import (
    CandidatePoolResult,
    CandidatePrice,
    CandidateProvenance,
    PlaceCandidate,
    StayCandidate,
    TransportCandidate,
)
from src.domain.models.enums import EvidenceStatus, EvidenceTtlCategory, WorkflowStatus
from src.domain.models.evidence import EvidenceItem, EvidenceSnapshot
from src.domain.models.trip_request import TravelerProfile, TripRequest
from src.domain.models.value_objects import DateRange, GeoPoint, Money
from src.domain.services.schedule_service import (
    ActivitySpec,
    OpeningWindow,
    RouteLeg,
    ScheduleContext,
    ScheduleError,
    SchedulePolicy,
    ScheduleResult,
    ScheduleService,
)

AS_OF = datetime(2026, 8, 6, 9, tzinfo=UTC)
LOCAL = timezone(timedelta(hours=8))


def _evidence(evidence_id: str, *, valid_until: datetime | None = None) -> EvidenceItem:
    return EvidenceItem(
        evidence_id=evidence_id,
        entity_id=f"entity:{evidence_id}",
        fact_type="schedule.fact",
        value="verified",
        provider="fake-provider",
        source="fixture",
        source_ref=f"source:{evidence_id}",
        observed_at=(valid_until - timedelta(minutes=1) if valid_until is not None else AS_OF),
        valid_until=valid_until or datetime(2026, 8, 20, tzinfo=UTC),
        ttl_category=EvidenceTtlCategory.STATIC_GEOGRAPHY,
        status=EvidenceStatus.VERIFIED,
        confidence=Decimal("1"),
        query_fingerprint=f"query:{evidence_id}",
    )


def _place(candidate_id: str, evidence_id: str) -> PlaceCandidate:
    return PlaceCandidate(
        candidate_id=candidate_id,
        name=candidate_id.replace(":", " "),
        evidence_refs=(evidence_id,),
        provenance=(
            CandidateProvenance(
                provider="fake-provider",
                entity_id=f"entity:{candidate_id}",
                source_ref=f"source:{candidate_id}",
            ),
        ),
        timezone="Asia/Shanghai",
        location=GeoPoint(latitude=30.25, longitude=120.16),
        category="scenic",
    )


def _transport(
    candidate_id: str = "candidate:train",
    *,
    departure_at: datetime | None = datetime(2026, 8, 10, 8, tzinfo=LOCAL),
    arrival_at: datetime | None = datetime(2026, 8, 10, 9, tzinfo=LOCAL),
) -> TransportCandidate:
    return TransportCandidate(
        candidate_id=candidate_id,
        name="verified rail",
        evidence_refs=("evidence:train",),
        provenance=(
            CandidateProvenance(
                provider="fake-provider", entity_id="entity:train", source_ref="source:train"
            ),
        ),
        timezone="Asia/Shanghai",
        mode="rail",
        origin="origin",
        destination="destination",
        departure_at=departure_at,
        arrival_at=arrival_at,
        price=CandidatePrice(
            total=Money(amount=Decimal("100"), currency="CNY"), evidence_refs=("evidence:train",)
        ),
    )


def _stay() -> StayCandidate:
    return StayCandidate(
        candidate_id="candidate:stay",
        name="verified hotel",
        evidence_refs=("evidence:stay",),
        provenance=(
            CandidateProvenance(
                provider="fake-provider", entity_id="entity:stay", source_ref="source:stay"
            ),
        ),
        timezone="Asia/Shanghai",
        area="destination",
        check_in=datetime(2026, 8, 10, 15, tzinfo=LOCAL),
        check_out=datetime(2026, 8, 12, 12, tzinfo=LOCAL),
    )


def _plan(*refs: str, days: tuple[int, ...] | None = None) -> PlanCandidate:
    day_numbers = days or tuple(range(1, len(refs) + 1))
    grouped: dict[int, list[str]] = {}
    for day_number, candidate_id in zip(day_numbers, refs, strict=True):
        grouped.setdefault(day_number, []).append(candidate_id)
    return PlanCandidate(
        plan_candidate_id="plan-candidate:trip-schedule:balanced",
        variant="balanced",
        title="balanced schedule",
        rationale="typed candidate skeleton",
        day_skeleton=tuple(
            PlanDaySkeleton(
                day_number=day_number,
                candidate_refs=tuple(candidate_ids),
                focus=f"day {day_number}",
            )
            for day_number, candidate_ids in sorted(grouped.items())
        ),
        selected_candidate_refs=refs,
        constraint_refs=(),
        evidence_refs=tuple(
            dict.fromkeys(
                "evidence:train"
                if candidate_id == "candidate:train"
                else f"evidence:{candidate_id.split(':')[-1]}"
                for candidate_id in refs
            )
        ),
        tradeoffs=("explicit timing",),
    )


def _context(
    *candidates: PlaceCandidate | TransportCandidate | StayCandidate,
    plan: PlanCandidate | None = None,
    opening_windows: tuple[OpeningWindow, ...] = (),
    activity_specs: tuple[ActivitySpec, ...] = (),
    route_legs: tuple[RouteLeg, ...] = (),
    policy: SchedulePolicy | None = None,
    date_range: DateRange | None = None,
    evidence_items: tuple[EvidenceItem, ...] | None = None,
) -> ScheduleContext:
    date_range = date_range or DateRange(start="2026-08-10", end="2026-08-12")
    selected = plan or _plan(
        *(candidate.candidate_id for candidate in candidates), days=(1,) * len(candidates)
    )
    if evidence_items is None:
        refs = {
            evidence_ref for candidate in candidates for evidence_ref in candidate.evidence_refs
        }
        refs.update(
            evidence_ref for window in opening_windows for evidence_ref in window.evidence_refs
        )
        refs.update(evidence_ref for spec in activity_specs for evidence_ref in spec.evidence_refs)
        refs.update(evidence_ref for leg in route_legs for evidence_ref in leg.evidence_refs)
        evidence_items = tuple(_evidence(ref) for ref in sorted(refs))
    request = TripRequest(
        request_id="request:schedule",
        trip_id="trip:schedule",
        session_id="session:schedule",
        origin="origin",
        destinations=("destination",),
        date_range=date_range,
        travelers=TravelerProfile(adults=2),
        timezone="Asia/Shanghai",
    )
    return ScheduleContext(
        trace_id="trace:schedule",
        as_of=AS_OF,
        request=request,
        constraint_snapshot_version=2,
        evidence_snapshot_id="evidence-snapshot:schedule",
        candidate_pool=CandidatePoolResult(
            evidence_snapshot_id="evidence-snapshot:schedule",
            constraint_snapshot_version=2,
            candidates=tuple(candidates),
        ),
        evidence_snapshot=EvidenceSnapshot(
            snapshot_id="evidence-snapshot:schedule",
            created_at=AS_OF,
            evidence_items=evidence_items,
            coverage=Decimal("1"),
            freshness=Decimal("1"),
        ),
        plan_candidate=selected,
        opening_windows=opening_windows,
        activity_specs=activity_specs,
        route_legs=route_legs,
        policy=policy or SchedulePolicy(),
    )


def _window(
    candidate_id: str, day_number: int, start_hour: int = 9, end_hour: int = 18
) -> OpeningWindow:
    return OpeningWindow(
        candidate_id=candidate_id,
        day_number=day_number,
        opens_at=datetime(2026, 8, 9 + day_number, start_hour, tzinfo=LOCAL),
        closes_at=datetime(2026, 8, 9 + day_number, end_hour, tzinfo=LOCAL),
        evidence_refs=(f"evidence:window:{candidate_id}:{day_number}",),
    )


def _activity(candidate_id: str, *, minutes: int = 120, flex: int = 15) -> ActivitySpec:
    return ActivitySpec(
        candidate_id=candidate_id,
        duration_minutes=minutes,
        flex_buffer_minutes=flex,
        evidence_refs=(f"evidence:activity:{candidate_id}",),
    )


def _route(from_id: str, to_id: str, *, minutes: int = 30, buffer: int = 10) -> RouteLeg:
    return RouteLeg(
        from_candidate_id=from_id,
        to_candidate_id=to_id,
        duration_minutes=minutes,
        transfer_buffer_minutes=buffer,
        transfer_count=1,
        evidence_refs=(f"evidence:route:{from_id}:{to_id}",),
    )


def test_schedule_assigns_exact_dates_windows_and_flex_buffers() -> None:
    place = _place("candidate:place", "evidence:place")
    result = ScheduleService().schedule(
        _context(
            place,
            opening_windows=(_window(place.candidate_id, 1),),
            activity_specs=(_activity(place.candidate_id),),
        )
    )

    plan = result.itinerary_plan
    assert plan.status is WorkflowStatus.DRAFTING
    assert [day.date.isoformat() for day in plan.days] == ["2026-08-10", "2026-08-11", "2026-08-12"]
    item = plan.items[0]
    assert item.start_at == datetime(2026, 8, 10, 9, tzinfo=LOCAL)
    assert item.end_at == datetime(2026, 8, 10, 11, tzinfo=LOCAL)
    assert result.total_flex_buffer_minutes == 15
    assert plan.buffers[0].minutes == 15
    assert item.evidence_refs == (
        "evidence:place",
        "evidence:window:candidate:place:1",
        "evidence:activity:candidate:place",
    )


def test_schedule_is_deterministic_and_keeps_empty_days() -> None:
    first = _place("candidate:first", "evidence:first")
    second = _place("candidate:second", "evidence:second")
    plan = _plan(first.candidate_id, second.candidate_id, days=(1, 1))
    context = _context(
        first,
        second,
        plan=plan,
        opening_windows=(_window(first.candidate_id, 1), _window(second.candidate_id, 1, 13, 20)),
        activity_specs=(
            _activity(first.candidate_id),
            _activity(second.candidate_id, minutes=60, flex=0),
        ),
        route_legs=(_route(first.candidate_id, second.candidate_id),),
    )

    first_result = ScheduleService().schedule(context)
    second_result = ScheduleService().schedule(context)

    assert first_result == second_result
    assert [item.candidate_id for item in first_result.plan.items] == [
        first.candidate_id,
        second.candidate_id,
    ]
    assert first_result.plan.days[1].item_refs == ()


def test_schedule_uses_fixed_transport_time_and_route_to_following_activity() -> None:
    train = _transport()
    place = _place("candidate:place", "evidence:place")
    plan = _plan(train.candidate_id, place.candidate_id, days=(1, 1))
    result = ScheduleService().schedule(
        _context(
            train,
            place,
            plan=plan,
            opening_windows=(_window(place.candidate_id, 1, 10, 18),),
            activity_specs=(_activity(place.candidate_id, minutes=60, flex=0),),
            route_legs=(_route(train.candidate_id, place.candidate_id, minutes=30, buffer=15),),
        )
    )

    assert result.plan.items[0].start_at == datetime(2026, 8, 10, 8, tzinfo=LOCAL)
    assert result.plan.items[0].end_at == datetime(2026, 8, 10, 9, tzinfo=LOCAL)
    assert result.plan.items[1].start_at == datetime(2026, 8, 10, 10, tzinfo=LOCAL)
    assert result.plan.items[1].end_at == datetime(2026, 8, 10, 11, tzinfo=LOCAL)
    assert "evidence:route:candidate:train:candidate:place" in result.plan.evidence_refs


def test_schedule_creates_check_in_and_check_out_events_for_stay() -> None:
    stay = _stay()
    result = ScheduleService().schedule(_context(stay, plan=_plan(stay.candidate_id, days=(1,))))

    assert [(item.title, item.day_number, item.start_at) for item in result.plan.items] == [
        ("verified hotel check-in", 1, datetime(2026, 8, 10, 15, tzinfo=LOCAL)),
        ("verified hotel check-out", 3, datetime(2026, 8, 12, 12, tzinfo=LOCAL)),
    ]


@pytest.mark.parametrize(
    ("code", "context_factory"),
    [
        (
            "SCHEDULE_ACTIVITY_SPEC_MISSING",
            lambda: _context(
                _place("candidate:place", "evidence:place"),
                opening_windows=(_window("candidate:place", 1),),
            ),
        ),
        (
            "SCHEDULE_OPENING_WINDOW_MISSING",
            lambda: _context(
                _place("candidate:place", "evidence:place"),
                activity_specs=(_activity("candidate:place"),),
            ),
        ),
        (
            "SCHEDULE_ROUTE_MISSING",
            lambda: _context(
                _place("candidate:first", "evidence:first"),
                _place("candidate:second", "evidence:second"),
                plan=_plan("candidate:first", "candidate:second", days=(1, 1)),
                opening_windows=(
                    _window("candidate:first", 1),
                    _window("candidate:second", 1, 13, 20),
                ),
                activity_specs=(
                    _activity("candidate:first"),
                    _activity("candidate:second", minutes=60, flex=0),
                ),
            ),
        ),
    ],
)
def test_schedule_requires_all_structured_timing_inputs(code: str, context_factory: object) -> None:
    with pytest.raises(ScheduleError) as raised:
        ScheduleService().schedule(context_factory())  # type: ignore[operator]

    assert raised.value.payload.code == code
    assert raised.value.payload.stage == "schedule_service"
    assert raised.value.retryable is False


def test_schedule_rejects_transport_without_exact_times() -> None:
    train = _transport(departure_at=None)
    with pytest.raises(ScheduleError) as raised:
        ScheduleService().schedule(_context(train, plan=_plan(train.candidate_id, days=(1,))))

    assert raised.value.payload.code == "SCHEDULE_FIXED_TIME_MISSING"


def test_schedule_allows_stay_boundaries_outside_daily_window() -> None:
    stay = _stay().model_copy(
        update={
            "check_in": datetime(2026, 8, 10, 0, tzinfo=LOCAL),
            "check_out": datetime(2026, 8, 12, 0, tzinfo=LOCAL),
        }
    )
    result = ScheduleService().schedule(_context(stay, plan=_plan(stay.candidate_id, days=(1,))))

    assert result.plan.items[0].title == "verified hotel check-in"
    assert result.plan.items[0].start_at == datetime(2026, 8, 10, 0, tzinfo=LOCAL)
    assert result.plan.items[1].title == "verified hotel check-out"
    assert result.plan.items[1].start_at == datetime(2026, 8, 12, 0, tzinfo=LOCAL)


def test_schedule_rejects_fixed_event_outside_daily_window() -> None:
    train = _transport(
        departure_at=datetime(2026, 8, 10, 7, tzinfo=LOCAL),
        arrival_at=datetime(2026, 8, 10, 9, tzinfo=LOCAL),
    )
    with pytest.raises(ScheduleError) as raised:
        ScheduleService().schedule(_context(train, plan=_plan(train.candidate_id, days=(1,))))

    assert raised.value.payload.code == "SCHEDULE_FIXED_EVENT_OUTSIDE_DAY"


def test_schedule_rejects_activity_that_cannot_fit_opening_window() -> None:
    place = _place("candidate:place", "evidence:place")
    context = _context(
        place,
        opening_windows=(_window(place.candidate_id, 1, 9, 10),),
        activity_specs=(_activity(place.candidate_id, minutes=120, flex=0),),
    )

    with pytest.raises(ScheduleError) as raised:
        ScheduleService().schedule(context)

    assert raised.value.payload.code == "SCHEDULE_NO_FEASIBLE_SLOT"


def test_schedule_fails_when_activity_overlaps_fixed_transport() -> None:
    train = _transport(
        departure_at=datetime(2026, 8, 10, 10, tzinfo=LOCAL),
        arrival_at=datetime(2026, 8, 10, 12, tzinfo=LOCAL),
    )
    place = _place("candidate:place", "evidence:place")
    plan = _plan(place.candidate_id, train.candidate_id, days=(1, 1))
    context = _context(
        place,
        train,
        plan=plan,
        opening_windows=(_window(place.candidate_id, 1, 9, 12),),
        activity_specs=(_activity(place.candidate_id, minutes=120, flex=0),),
        route_legs=(_route(place.candidate_id, train.candidate_id, minutes=0, buffer=0),),
    )

    with pytest.raises(ScheduleError) as raised:
        ScheduleService().schedule(context)

    assert raised.value.payload.code == "SCHEDULE_NO_FEASIBLE_SLOT"


def test_schedule_rejects_invalid_timezone_and_duration_only_request() -> None:
    place = _place("candidate:place", "evidence:place")
    context = _context(
        place,
        opening_windows=(_window(place.candidate_id, 1),),
        activity_specs=(_activity(place.candidate_id),),
    )
    invalid_timezone = context.model_copy(
        update={"request": context.request.model_copy(update={"timezone": "Not/An/InstalledZone"})}
    )
    with pytest.raises(ScheduleError) as raised:
        ScheduleService().schedule(invalid_timezone)
    assert raised.value.payload.code == "SCHEDULE_TIMEZONE_INVALID"

    no_exact_dates = context.model_copy(
        update={
            "request": context.request.model_copy(update={"date_range": None, "duration_days": 3})
        }
    )
    with pytest.raises(ScheduleError) as raised:
        ScheduleService().schedule(no_exact_dates)
    assert raised.value.payload.code == "SCHEDULE_DATE_RANGE_REQUIRED"


def test_schedule_rejects_expired_or_conflicting_schedule_evidence() -> None:
    place = _place("candidate:place", "evidence:place")
    expired = _evidence("evidence:place", valid_until=datetime(2026, 8, 6, 8, tzinfo=UTC))
    with pytest.raises(ValidationError, match="expired"):
        _context(
            place,
            opening_windows=(_window(place.candidate_id, 1),),
            activity_specs=(_activity(place.candidate_id),),
            evidence_items=(
                expired,
                _evidence("evidence:window:candidate:place:1"),
                _evidence("evidence:activity:candidate:place"),
            ),
        )

    conflict_context = _context(
        place,
        opening_windows=(_window(place.candidate_id, 1),),
        activity_specs=(_activity(place.candidate_id),),
    )
    with pytest.raises(ValidationError, match="conflicting"):
        ScheduleContext.model_validate(
            {
                **conflict_context.model_dump(mode="python"),
                "evidence_snapshot": {
                    **conflict_context.evidence_snapshot.model_dump(mode="python"),
                    "conflict_refs": ("evidence:place",),
                },
            }
        )


def test_schedule_rejects_window_date_mismatch_and_bad_policy() -> None:
    place = _place("candidate:place", "evidence:place")
    mismatched = OpeningWindow(
        candidate_id=place.candidate_id,
        day_number=1,
        opens_at=datetime(2026, 8, 11, 9, tzinfo=LOCAL),
        closes_at=datetime(2026, 8, 11, 18, tzinfo=LOCAL),
        evidence_refs=("evidence:window:bad",),
    )
    context = _context(
        place, opening_windows=(mismatched,), activity_specs=(_activity(place.candidate_id),)
    )
    with pytest.raises(ScheduleError) as raised:
        ScheduleService().schedule(context)
    assert raised.value.payload.code == "SCHEDULE_OPENING_WINDOW_DATE_MISMATCH"

    with pytest.raises(ValidationError, match="day_end_local"):
        SchedulePolicy(day_start_local=time(18), day_end_local=time(8))


def test_schedule_rejects_route_overflow_and_preserves_trace_refs() -> None:
    first = _place("candidate:first", "evidence:first")
    second = _place("candidate:second", "evidence:second")
    context = _context(
        first,
        second,
        plan=_plan(first.candidate_id, second.candidate_id, days=(1, 1)),
        opening_windows=(_window(first.candidate_id, 1), _window(second.candidate_id, 1)),
        activity_specs=(_activity(first.candidate_id), _activity(second.candidate_id)),
        route_legs=(_route(first.candidate_id, second.candidate_id, minutes=900, buffer=0),),
    )

    with pytest.raises(ScheduleError) as raised:
        ScheduleService().schedule(context)

    assert raised.value.payload.code == "SCHEDULE_ROUTE_OVERFLOW"
    assert raised.value.trace_id == "trace:schedule"
    assert "evidence:route:candidate:first:candidate:second" in raised.value.payload.upstream_refs


def test_schedule_rejects_non_strict_values_and_context_mismatches() -> None:
    with pytest.raises(ValidationError):
        ActivitySpec(
            candidate_id="candidate:place",
            duration_minutes=-1,
            evidence_refs=("evidence:activity",),
        )
    with pytest.raises(ValidationError):
        ActivitySpec(
            candidate_id="candidate:place",
            duration_minutes=30.5,
            evidence_refs=("evidence:activity",),
        )
    with pytest.raises(ValidationError):
        RouteLeg(
            from_candidate_id="candidate:a",
            to_candidate_id="candidate:b",
            duration_minutes=-1,
            evidence_refs=("evidence:route",),
        )

    place = _place("candidate:place", "evidence:place")
    base = _context(
        place,
        opening_windows=(_window(place.candidate_id, 1),),
        activity_specs=(_activity(place.candidate_id),),
    )
    for update in (
        {"constraint_snapshot_version": 1},
        {"evidence_snapshot_id": "evidence-snapshot:other"},
        {"plan_candidate": _plan("candidate:missing", days=(1,))},
    ):
        with pytest.raises(ValidationError):
            ScheduleContext.model_validate({**base.model_dump(mode="python"), **update})


def test_schedule_input_dtos_reject_naive_duplicates_and_self_routes() -> None:
    with pytest.raises(ValidationError):
        OpeningWindow(
            candidate_id="candidate:place",
            day_number=1,
            opens_at=datetime(2026, 8, 10, 9),
            closes_at=datetime(2026, 8, 10, 10, tzinfo=UTC),
            evidence_refs=("evidence:window",),
        )
    with pytest.raises(ValidationError):
        ActivitySpec(
            candidate_id="candidate:place",
            duration_minutes=30,
            evidence_refs=("evidence:activity", "evidence:activity"),
        )
    with pytest.raises(ValidationError):
        RouteLeg(
            from_candidate_id="candidate:place",
            to_candidate_id="candidate:place",
            duration_minutes=0,
            evidence_refs=("evidence:route",),
        )


def test_schedule_rejects_cross_day_transport_and_out_of_range_stay() -> None:
    cross_day = _transport(
        departure_at=datetime(2026, 8, 10, 21, tzinfo=LOCAL),
        arrival_at=datetime(2026, 8, 11, 1, tzinfo=LOCAL),
    )
    with pytest.raises(ScheduleError) as raised:
        ScheduleService().schedule(
            _context(cross_day, plan=_plan(cross_day.candidate_id, days=(1,)))
        )
    assert raised.value.payload.code == "SCHEDULE_CROSS_DAY_FIXED_EVENT"

    outside = _stay().model_copy(
        update={
            "check_in": datetime(2026, 8, 9, 15, tzinfo=LOCAL),
            "check_out": datetime(2026, 8, 12, 12, tzinfo=LOCAL),
        }
    )
    with pytest.raises(ScheduleError) as raised:
        ScheduleService().schedule(_context(outside, plan=_plan(outside.candidate_id, days=(1,))))
    assert raised.value.payload.code == "SCHEDULE_FIXED_EVENT_OUTSIDE_RANGE"


def test_schedule_result_rejects_plan_identity_mismatch() -> None:
    place = _place("candidate:place", "evidence:place")
    result = ScheduleService().schedule(
        _context(
            place,
            opening_windows=(_window(place.candidate_id, 1),),
            activity_specs=(_activity(place.candidate_id),),
        )
    )
    with pytest.raises(ValidationError, match="PlanCandidate ID"):
        ScheduleResult.model_validate(
            {**result.model_dump(mode="python"), "plan_candidate_id": "plan-candidate:other"}
        )
