from __future__ import annotations

from datetime import UTC, date, datetime
from decimal import Decimal

import pytest

from src.application.interaction_facade import TripInteractionFacade
from src.application.use_cases.plan_trip import PlanTripResult
from src.config import Settings
from src.domain.errors import WorkflowError
from src.domain.models.enums import ConstraintHardness, InteractionMode, WorkflowStatus
from src.domain.models.interpretation import ConstraintCandidate, InterpretationResult
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


def test_facade_resolves_relative_date_with_one_reference_date() -> None:
    relative_date_interpretation = _interpretation(InteractionMode.PLAN, ready=True).replace(
        "2026-08-01/2026-08-03",
        "下周一",
    )
    facade, planner, repository = _facade(relative_date_interpretation)

    result = facade.execute(
        _request(),
        "请规划下周一从上海到杭州的旅行",
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
