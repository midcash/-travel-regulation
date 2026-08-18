from __future__ import annotations

import json
from datetime import UTC, date, datetime
from decimal import Decimal

import pytest

from src.application.interaction_facade import TripInteractionFacade
from src.application.use_cases.plan_trip import PlanTripResult
from src.config import Settings
from src.domain.errors import WorkflowError
from src.domain.models.enums import ConstraintHardness, InteractionMode, WorkflowStatus
from src.domain.models.interpretation import ConstraintCandidate, InterpretationResult
from src.domain.models.readiness import ReadinessBlockerCode
from src.domain.models.routing import RouteReasonCode
from src.domain.models.trip_request import TravelerProfile, TripRequest
from src.domain.models.value_objects import DateRange
from src.infrastructure.persistence.in_memory import InMemoryStateRepository
from tests.support.clock_fakes import FakeClock
from tests.support.llm_fakes import FakeLLMGateway


class RecordingPlanner:
    """Compatibility planner that only records PLAN calls."""

    def __init__(self) -> None:
        self.calls: list[TripRequest] = []

    def execute(self, request: TripRequest) -> PlanTripResult:
        self.calls.append(request)
        return PlanTripResult(
            request_id=request.request_id,
            trip_id=request.trip_id,
            session_id=request.session_id,
            plan="legacy plan",
            rounds=1,
            issues_found=(),
        )


def _request() -> TripRequest:
    return TripRequest(
        request_id="request-facade",
        trip_id="trip-facade",
        session_id="session-facade",
        origin="Shanghai",
        destinations=("Hangzhou",),
        date_range=DateRange(start=date(2026, 8, 1), end=date(2026, 8, 3)),
        travelers=TravelerProfile(adults=2),
    )


def _interpretation(mode: InteractionMode, *, ready: bool) -> str:
    candidates = (
        ConstraintCandidate(
            category="origin",
            value="Shanghai",
            hardness=ConstraintHardness.HARD,
            scope="trip",
            confidence=Decimal("0.95"),
        ),
        ConstraintCandidate(
            category="destination",
            value="Hangzhou",
            hardness=ConstraintHardness.HARD,
            scope="trip",
            confidence=Decimal("0.95"),
        ),
        ConstraintCandidate(
            category="date_range",
            value="2026-08-01/2026-08-03",
            hardness=ConstraintHardness.HARD,
            scope="trip",
            confidence=Decimal("0.95"),
        ),
        ConstraintCandidate(
            category="travelers",
            value=2,
            hardness=ConstraintHardness.HARD,
            scope="trip",
            confidence=Decimal("0.95"),
        ),
    ) if ready else ()
    return InterpretationResult(
        mode_hint=mode,
        extracted_entities=(),
        constraint_candidates=candidates,
        explicit_questions=(),
        references_to_current_plan=(),
        field_confidence={},
        overall_confidence=Decimal("0.95"),
        safety_flags=(),
    ).model_dump_json()


def _business_interpretation(*, with_timezone: bool, traveler_count: int | None = 1) -> str:
    candidates = [
        {
            "category": "origin",
            "value": "杭州",
            "hardness": "hard",
            "scope": "trip",
            "confidence": 0.95,
        },
        {
            "category": "destination",
            "value": "上海",
            "hardness": "hard",
            "scope": "trip",
            "confidence": 0.95,
        },
        {
            "category": "date_range",
            "value": "2026-08-22",
            "hardness": "hard",
            "scope": "trip",
            "confidence": 0.95,
        },
        {
            "category": "meeting_city",
            "value": "上海",
            "hardness": "hard",
            "scope": "meeting",
            "confidence": 0.95,
        },
        {
            "category": "meeting_location",
            "value": "上海东方明珠塔",
            "hardness": "hard",
            "scope": "meeting",
            "confidence": 0.95,
        },
        {
            "category": "meeting_starts_at",
            "value": "2026-08-22T08:00:00",
            "hardness": "hard",
            "scope": "meeting",
            "confidence": 0.95,
        },
    ]
    if traveler_count is not None:
        candidates.insert(
            3,
            {
                "category": "travelers",
                "value": traveler_count,
                "hardness": "hard",
                "scope": "trip",
                "confidence": 0.95,
            },
        )
    if with_timezone:
        candidates.append(
            {
                "category": "meeting_timezone",
                "value": "Asia/Shanghai",
                "hardness": "hard",
                "scope": "meeting",
                "confidence": 0.95,
            }
        )
    return InterpretationResult.model_validate(
        {
            "mode_hint": "plan",
            "extracted_entities": [],
            "constraint_candidates": candidates,
            "explicit_questions": [],
            "references_to_current_plan": [],
            "field_confidence": {},
            "overall_confidence": 0.95,
            "safety_flags": [],
        }
    ).model_dump_json()


def _facade(
    response: str | BaseException,
    *,
    planner: RecordingPlanner | None = None,
    repository: InMemoryStateRepository | None = None,
) -> tuple[TripInteractionFacade, RecordingPlanner, InMemoryStateRepository]:
    actual_planner = planner or RecordingPlanner()
    actual_repository = repository or InMemoryStateRepository()
    facade = TripInteractionFacade(
        Settings(),
        planner=actual_planner,
        gateway=FakeLLMGateway([response]),
        state_repository=actual_repository,
        clock=FakeClock(datetime(2026, 7, 30, 12, tzinfo=UTC)),
    )
    return facade, actual_planner, actual_repository


def test_facade_routes_ready_plan_and_preserves_legacy_plan_call() -> None:
    facade, planner, repository = _facade(_interpretation(InteractionMode.PLAN, ready=True))

    result = facade.execute(_request(), "plan a trip from Shanghai to Hangzhou")

    assert result.route_decision.mode == InteractionMode.PLAN.value
    assert result.state.status is WorkflowStatus.RESEARCHING
    assert result.constraint_snapshot.version == 1
    assert len(planner.calls) == 1
    assert repository.get("trip-facade").status is WorkflowStatus.RESEARCHING


def test_facade_exposes_business_scope_without_starting_legacy_planner() -> None:
    facade, planner, repository = _facade(_business_interpretation(with_timezone=True))

    result = facade.execute(
        _request(),
        "我一个人从杭州到上海参加中国标准时间的会议，请规划会前到达。",
        reference_date=date(2026, 7, 30),
    )

    assert result.business_scope is not None
    assert result.business_scope.planning_horizon == "meeting_arrival_ready"
    assert result.route_decision.required_capabilities == (
        "geo",
        "policy",
        "intercity_transport",
    )
    assert result.route_decision.continue_to_planner is False
    assert result.plan_result is None
    assert planner.calls == []
    assert result.state.status is WorkflowStatus.COLLECTING
    assert repository.get("trip-facade").status is WorkflowStatus.COLLECTING


def test_facade_defaults_missing_business_timezone_without_planner_call() -> None:
    facade, planner, repository = _facade(_business_interpretation(with_timezone=False))

    result = facade.execute(
        _request(),
        "我从杭州到上海参加早上八点的会议，请规划差旅。",
        reference_date=date(2026, 7, 30),
    )

    assert result.route_decision.mode == InteractionMode.PLAN.value
    assert result.readiness.ready is True
    assert result.business_scope is not None
    assert result.business_scope.meeting.timezone == "Asia/Shanghai"
    assert any(
        assumption.field == "meeting_timezone"
        for assumption in result.readiness.assumptions
    )
    assert planner.calls == []
    assert repository.get("trip-facade").status is WorkflowStatus.COLLECTING


def test_facade_uses_business_defaults_for_missing_timezone_and_travelers() -> None:
    payload = json.loads(_business_interpretation(with_timezone=False))
    payload["constraint_candidates"] = [
        item
        for item in payload["constraint_candidates"]
        if item["category"] != "travelers"
    ]
    facade, planner, repository = _facade(json.dumps(payload, ensure_ascii=False))

    result = facade.execute(
        _request(),
        "我下周六早上八点在上海东方明珠塔开会，请规划从杭州出发的差旅。",
        reference_date=date(2026, 7, 30),
    )

    assert result.readiness.ready is True
    assert result.readiness.blockers == ()
    assert result.business_scope is not None
    assert result.business_scope.meeting.timezone == "Asia/Shanghai"
    assert result.business_scope.meeting.traveler_count == 1
    assert {
        "meeting_timezone",
        "travelers",
    }.issubset({item.field for item in result.readiness.assumptions})
    assert result.route_decision.required_capabilities == (
        "geo",
        "policy",
        "intercity_transport",
    )
    assert result.route_decision.continue_to_planner is False
    assert planner.calls == []
    assert repository.get("trip-facade").status is WorkflowStatus.COLLECTING


def test_facade_rejects_explicit_multi_traveler_business_request() -> None:
    payload = json.loads(_business_interpretation(with_timezone=False, traveler_count=3))
    facade, planner, repository = _facade(json.dumps(payload, ensure_ascii=False))

    result = facade.execute(
        _request(),
        "我和两位同事从杭州出发，下周六早上八点在上海东方明珠塔开会，请规划差旅。",
        reference_date=date(2026, 7, 30),
    )

    assert result.readiness.ready is True
    assert result.business_scope is not None
    assert result.business_scope.meeting.traveler_count == 3
    assert result.route_decision.mode == InteractionMode.UNSUPPORTED.value
    assert result.route_decision.reason_codes == (
        RouteReasonCode.MULTI_TRAVELER_UNSUPPORTED,
    )
    assert result.route_decision.required_capabilities == ()
    assert result.route_decision.continue_to_planner is False
    assert planner.calls == []
    assert repository.get("trip-facade").status is WorkflowStatus.COLLECTING


def test_facade_rejects_group_language_without_defaulting_one_traveler() -> None:
    payload = json.loads(_business_interpretation(with_timezone=False, traveler_count=None))
    facade, planner, repository = _facade(json.dumps(payload, ensure_ascii=False))

    result = facade.execute(
        _request(),
        "我和同事们从杭州出发，下周六早上八点在上海东方明珠塔开会，请规划差旅。",
        reference_date=date(2026, 7, 30),
    )

    assert result.readiness.ready is False
    assert result.route_decision.mode == InteractionMode.UNSUPPORTED.value
    assert result.route_decision.reason_codes == (
        RouteReasonCode.MULTI_TRAVELER_UNSUPPORTED,
    )
    assert result.business_scope is None
    assert planner.calls == []
    assert repository.get("trip-facade").status is WorkflowStatus.COLLECTING


def test_facade_rejects_explicit_tourism_without_business_assumptions() -> None:
    payload = json.loads(_interpretation(InteractionMode.PLAN, ready=True))
    payload["constraint_candidates"] += [
        {
            "category": "place",
            "value": "景点",
            "hardness": "soft",
            "scope": "trip",
            "confidence": 0.95,
        },
        {
            "category": "activity",
            "value": "游玩",
            "hardness": "soft",
            "scope": "trip",
            "confidence": 0.95,
        },
    ]
    facade, planner, repository = _facade(json.dumps(payload, ensure_ascii=False))

    result = facade.execute(
        _request(),
        "我下周去上海旅游，想安排景点和活动。",
        reference_date=date(2026, 7, 30),
    )

    assert result.readiness.ready is True
    assert result.route_decision.mode == InteractionMode.UNSUPPORTED.value
    assert result.route_decision.reason_codes == (
        RouteReasonCode.TOURISM_UNSUPPORTED,
    )
    assert result.constraint_snapshot.constraints
    assert result.business_scope is None
    assert planner.calls == []
    assert repository.get("trip-facade").status is WorkflowStatus.COLLECTING


def test_facade_keeps_timezone_blocker_for_unmapped_meeting_city() -> None:
    payload = json.loads(_business_interpretation(with_timezone=False))
    payload["constraint_candidates"] = [
        {
            **item,
            "value": "Springfield",
        }
        if item["category"] == "meeting_city"
        else item
        for item in payload["constraint_candidates"]
        if item["category"] != "travelers"
    ]
    facade, planner, repository = _facade(json.dumps(payload, ensure_ascii=False))

    result = facade.execute(
        _request(),
        "我下周六早上八点在 Springfield 开会，请规划差旅。",
        reference_date=date(2026, 7, 30),
    )

    assert result.readiness.ready is False
    assert {blocker.field for blocker in result.readiness.blockers} == {
        "meeting_timezone"
    }
    assert result.business_scope is None
    assert result.route_decision.mode == InteractionMode.CLARIFY.value
    assert planner.calls == []
    assert repository.get("trip-facade").status is WorkflowStatus.CLARIFYING


def test_facade_does_not_derive_generic_fields_from_business_meeting_fields() -> None:
    payload = json.loads(_business_interpretation(with_timezone=True))
    payload["constraint_candidates"] = [
        item
        for item in payload["constraint_candidates"]
        if item["category"] not in {"destination", "date_range"}
    ]
    facade, planner, repository = _facade(json.dumps(payload, ensure_ascii=False))

    result = facade.execute(
        _request(),
        "我一个人从杭州到上海参加中国标准时间的会议，请规划会前到达。",
        reference_date=date(2026, 7, 30),
    )

    blocker_fields = {blocker.field for blocker in result.readiness.blockers}
    assert result.route_decision.mode == InteractionMode.CLARIFY.value
    assert {"destination", "date_range_or_duration_days"}.issubset(blocker_fields)
    assert result.business_scope is None
    assert planner.calls == []
    assert repository.get("trip-facade").status is WorkflowStatus.CLARIFYING


def test_facade_resolves_relative_date_with_one_reference_date() -> None:
    relative_date_interpretation = _interpretation(InteractionMode.PLAN, ready=True).replace(
        "2026-08-01/2026-08-03",
        "\u4e0b\u5468\u4e00",
    )
    facade, planner, repository = _facade(relative_date_interpretation)

    result = facade.execute(
        _request(),
        "\u8bf7\u89c4\u5212\u4e0b\u5468\u4e00\u4ece\u4e0a\u6d77\u5230\u676d\u5dde\u7684\u51fa\u884c",
        reference_date=date(2026, 7, 30),
    )

    assert result.route_decision.mode == InteractionMode.PLAN.value
    assert result.constraint_snapshot.version == 1
    assert planner.calls
    date_constraint = next(
        item for item in result.constraint_snapshot.constraints if item.category == "date_range"
    )
    assert date_constraint.normalized_value.start == date(2026, 8, 3)  # type: ignore[union-attr]
    assert date_constraint.normalized_value.end == date(2026, 8, 3)  # type: ignore[union-attr]
    assert repository.get("trip-facade").status is WorkflowStatus.RESEARCHING


def test_facade_blocks_past_date_as_structured_clarification_without_planner_call() -> None:
    facade, planner, repository = _facade(_interpretation(InteractionMode.PLAN, ready=True))

    result = facade.execute(
        _request(),
        "plan a trip from Shanghai to Hangzhou",
        reference_date=date(2026, 8, 7),
    )

    assert result.route_decision.mode == InteractionMode.CLARIFY.value
    assert result.clarification is not None
    assert any(
        question.code is ReadinessBlockerCode.DATE_RANGE_IN_PAST
        for question in result.clarification.questions
    )
    assert planner.calls == []
    assert repository.get("trip-facade").status is WorkflowStatus.CLARIFYING
def test_facade_routes_missing_plan_fields_to_clarification_without_plan_call() -> None:
    facade, planner, repository = _facade(_interpretation(InteractionMode.PLAN, ready=False))

    result = facade.execute(_request(), "I want to arrange a trip")

    assert result.route_decision.mode == InteractionMode.CLARIFY.value
    assert result.state.status is WorkflowStatus.CLARIFYING
    assert result.clarification is not None
    assert 1 <= len(result.clarification.questions) <= 3
    assert planner.calls == []
    assert repository.get("trip-facade").status is WorkflowStatus.CLARIFYING


def test_facade_marks_state_failed_when_interpretation_is_invalid() -> None:
    facade, planner, repository = _facade("not-json")

    with pytest.raises(WorkflowError):
        facade.execute(_request(), "plan a trip from Shanghai to Hangzhou")

    assert repository.get("trip-facade").status is WorkflowStatus.FAILED
    assert planner.calls == []
