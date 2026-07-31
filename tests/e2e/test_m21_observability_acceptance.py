"""M2.1 step eight: end-to-end observability acceptance."""

from __future__ import annotations

import json
import re
from datetime import date
from decimal import Decimal

import pytest

from src.application.interaction_facade import PlanExecutor, TripInteractionFacade
from src.application.use_cases.plan_trip import PlanTripResult, PlanTripUseCase
from src.config import Settings
from src.domain.errors import WorkflowError
from src.domain.models.enums import ConstraintHardness, InteractionMode
from src.domain.models.interpretation import ConstraintCandidate, InterpretationResult
from src.domain.models.trip_request import TravelerProfile, TripRequest
from src.domain.models.value_objects import DateRange
from src.engine import loop
from src.infrastructure.persistence.in_memory import InMemoryStateRepository
from tests.support.fakes import FakeLLM
from tests.support.llm_fakes import FakeLLMGateway

_TRACE_ID_PATTERN = re.compile(r"^route:[^:]+:[^:]+$")
_OTEL_TRACE_ID_PATTERN = re.compile(r"^[0-9a-f]{32}$")


class _RecordingPlanner:
    """Return a fixed plan and record calls for offline acceptance tests."""

    def __init__(self) -> None:
        self.calls: list[TripRequest] = []

    def execute(self, request: TripRequest) -> PlanTripResult:
        self.calls.append(request)
        return PlanTripResult(
            request_id=request.request_id,
            trip_id=request.trip_id,
            session_id=request.session_id,
            plan="safe plan",
            rounds=1,
            issues_found=(),
        )


def _request(case_id: str) -> TripRequest:
    return TripRequest(
        request_id=f"{case_id}-request",
        trip_id=f"{case_id}-trip",
        session_id=f"{case_id}-session",
        origin="\u4e0a\u6d77",
        destinations=("\u676d\u5dde",),
        date_range=DateRange(start=date(2026, 8, 1), end=date(2026, 8, 3)),
        travelers=TravelerProfile(adults=2),
    )


def _candidate(
    category: str,
    value: str | int | float | bool | tuple[str, ...],
) -> ConstraintCandidate:
    return ConstraintCandidate(
        category=category,
        value=value,
        hardness=ConstraintHardness.HARD,
        scope="trip",
        confidence=Decimal("0.95"),
    )


def _interpretation_response(*candidates: ConstraintCandidate) -> str:
    return InterpretationResult(
        mode_hint=InteractionMode.PLAN,
        extracted_entities=(),
        constraint_candidates=candidates,
        explicit_questions=(),
        references_to_current_plan=(),
        field_confidence={},
        overall_confidence=Decimal("0.95"),
        safety_flags=(),
    ).model_dump_json()


_READY_CANDIDATES = (
    _candidate("origin", "\u4e0a\u6d77"),
    _candidate("destination", "\u676d\u5dde"),
    _candidate("date_range", "2026-08-01/2026-08-03"),
    _candidate("travelers", 2),
)


def _facade(response: str, planner: PlanExecutor) -> TripInteractionFacade:
    return TripInteractionFacade(
        Settings(deepseek_api_key="fake-key"),
        planner=planner,
        gateway=FakeLLMGateway([response]),
        state_repository=InMemoryStateRepository(),
    )


def _events(stderr: str) -> list[dict[str, object]]:
    return [json.loads(line) for line in stderr.splitlines() if line.strip()]


_OBSERVATION_EVENTS = {
    "workflow_started",
    "workflow_completed",
    "workflow_failed",
    "stage_started",
    "stage_completed",
    "stage_failed",
    "legacy_review_completed",
    "legacy_revision_requested",
    "legacy_revision_completed",
    "legacy_revision_exhausted",
}


def _assert_event_envelope(events: list[dict[str, object]], trace_id: str) -> None:
    observed = [event for event in events if event["event"] in _OBSERVATION_EVENTS]
    assert observed
    assert {event["trace_id"] for event in observed} == {trace_id}
    assert all(_TRACE_ID_PATTERN.fullmatch(str(event["trace_id"])) for event in observed)
    assert all(_OTEL_TRACE_ID_PATTERN.fullmatch(str(event["otel_trace_id"])) for event in observed)
    assert all(isinstance(event["timestamp"], str) for event in observed)
    assert all(
        isinstance(event["duration_ms"], int) and event["duration_ms"] >= 0
        for event in observed
    )


def test_success_trace_links_stages_and_workflow_completion(
    capsys: pytest.CaptureFixture[str],
) -> None:
    planner = _RecordingPlanner()
    request = _request("m21-e2e-success")
    facade = _facade(_interpretation_response(*_READY_CANDIDATES), planner)

    result = facade.execute(request, "plan a three-day trip")
    events = _events(capsys.readouterr().err)

    trace_id = f"route:{request.trip_id}:{request.request_id}"
    _assert_event_envelope(events, trace_id)
    event_names = [str(event["event"]) for event in events]
    assert event_names[0] == "workflow_started"
    assert event_names[-1] == "workflow_completed"
    assert "stage_completed" in event_names
    assert "workflow_failed" not in event_names
    assert result.route_decision.mode == InteractionMode.PLAN.value
    assert len(planner.calls) == 1


def test_clarify_trace_contains_blockers_and_success_completion(
    capsys: pytest.CaptureFixture[str],
) -> None:
    planner = _RecordingPlanner()
    request = _request("m21-e2e-clarify")
    facade = _facade(_interpretation_response(), planner)

    result = facade.execute(request, "I want to arrange a trip")
    events = _events(capsys.readouterr().err)

    trace_id = f"route:{request.trip_id}:{request.request_id}"
    _assert_event_envelope(events, trace_id)
    route_event = next(
        event
        for event in events
        if event["event"] == "stage_completed" and event["stage"] == "router"
    )
    assert route_event["mode"] == "clarify"
    assert route_event["reason_codes"] == ["CLARIFICATION_REQUIRED"]
    readiness_event = next(
        event
        for event in events
        if event["event"] == "stage_completed"
        and event["stage"] == "readiness_evaluator"
    )
    assert readiness_event["blocker_codes"]
    assert events[-1]["event"] == "workflow_completed"
    assert len(planner.calls) == 0
    assert result.route_decision.mode == InteractionMode.CLARIFY.value


def test_failure_trace_keeps_safe_error_and_no_raw_input(
    capsys: pytest.CaptureFixture[str],
) -> None:
    request = _request("m21-e2e-failure")
    facade = _facade("not-json", _RecordingPlanner())
    raw_input = "plan a trip SECRET_USER_INPUT"

    with pytest.raises(WorkflowError):
        facade.execute(request, raw_input)
    events = _events(capsys.readouterr().err)

    trace_id = f"route:{request.trip_id}:{request.request_id}"
    _assert_event_envelope(events, trace_id)
    failure = next(event for event in events if event["event"] == "workflow_failed")
    assert failure["stage"] == "request_interpreter"
    assert failure["code"] == "INTERPRETATION_INVALID"
    assert failure["safe_message"] != raw_input
    assert "SECRET_USER_INPUT" not in json.dumps(events, ensure_ascii=False)
    assert events[-1]["event"] == "workflow_failed"


def test_legacy_revision_trace_keeps_review_sources_and_redacts_plan(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    planner_llm = FakeLLM(
        [
            "\u9884\u7b97 2000 \u5143\uff0c\u603b\u8d39\u7528 2300 \u5143 SECRET_PLAN_TEXT",
            "\u9884\u7b97 2000 \u5143\uff0c\u603b\u8d39\u7528 1500 \u5143 FINAL_PLAN_TEXT",
        ]
    )
    review_results = [
        {"pass": False, "issues": ["private-review-reason"]},
        {"pass": True, "issues": []},
    ]
    monkeypatch.setattr(loop, "ask_llm", planner_llm)
    monkeypatch.setattr(loop, "run_l2_review", lambda *args, **kwargs: review_results.pop(0))

    settings = Settings(deepseek_api_key="fake-key")
    legacy_planner = PlanTripUseCase(
        settings,
        planner=lambda user_input, *, settings: loop.plan(user_input, settings=settings),
    )
    request = _request("m21-e2e-revision")
    facade = TripInteractionFacade(
        settings,
        planner=legacy_planner,
        gateway=FakeLLMGateway([_interpretation_response(*_READY_CANDIDATES)]),
        state_repository=InMemoryStateRepository(),
    )

    result = facade.execute(request, "plan a city trip with budget 2000")
    events = _events(capsys.readouterr().err)

    trace_id = f"route:{request.trip_id}:{request.request_id}"
    _assert_event_envelope(events, trace_id)
    review = next(event for event in events if event["event"] == "legacy_review_completed")
    requested = next(event for event in events if event["event"] == "legacy_revision_requested")
    completed = next(event for event in events if event["event"] == "legacy_revision_completed")
    assert review["l1_issue_count"] == 1
    assert review["l2_issue_count"] == 1
    assert requested["trigger_sources"] == ["l1", "l2"]
    assert requested["issue_refs"] == review["issue_refs"]
    assert completed["round"] == 1
    serialized = json.dumps(events, ensure_ascii=False)
    assert "SECRET_PLAN_TEXT" not in serialized
    assert "FINAL_PLAN_TEXT" not in serialized
    assert "private-review-reason" not in serialized
    assert result.plan_result is not None
    assert result.plan_result.rounds == 2
    assert events[-1]["event"] == "workflow_completed"
