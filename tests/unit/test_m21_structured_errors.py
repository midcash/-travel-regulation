from __future__ import annotations

import json
from decimal import Decimal

import pytest
from structlog.contextvars import clear_contextvars

from src.application.interaction_facade import TripInteractionFacade
from src.config import Settings
from src.domain.models.enums import ConstraintHardness
from src.domain.models.interpretation import ConstraintCandidate, InterpretationResult
from src.domain.models.state import TripState
from src.domain.models.trip_request import TravelerProfile, TripRequest
from src.infrastructure.persistence.in_memory import InMemoryStateRepository
from src.obs.stage import observe_stage
from tests.support.llm_fakes import FakeLLMGateway


class _UnexpectedPlanner:
    def execute(self, request: TripRequest) -> None:
        raise RuntimeError("secret-key must not be exposed")


class _FailureOnGetRepository(InMemoryStateRepository):
    def get(self, trip_id: str) -> TripState:
        raise RuntimeError("state secret must not be exposed")


class _FailureOnFailedSaveRepository(InMemoryStateRepository):
    def save(self, state: TripState, expected_version: int) -> TripState:
        if state.status.value == "failed":
            raise RuntimeError("database password must not be exposed")
        return super().save(state, expected_version)


def _request() -> TripRequest:
    return TripRequest(
        request_id="m21-error-request",
        trip_id="m21-error-trip",
        session_id="m21-error-session",
        origin="上海",
        destinations=("杭州",),
        duration_days=1,
        travelers=TravelerProfile(adults=1),
    )


def _interpretation_response() -> str:
    candidates = (
        ConstraintCandidate(
            category="origin",
            value="上海",
            hardness=ConstraintHardness.HARD,
            scope="trip",
            confidence=Decimal("0.95"),
        ),
        ConstraintCandidate(
            category="destination",
            value="杭州",
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
            value=1,
            hardness=ConstraintHardness.HARD,
            scope="trip",
            confidence=Decimal("0.95"),
        ),
    )
    return InterpretationResult(
        mode_hint="plan",
        extracted_entities=(),
        constraint_candidates=candidates,
        explicit_questions=(),
        references_to_current_plan=(),
        field_confidence={},
        overall_confidence=Decimal("0.95"),
        safety_flags=(),
    ).model_dump_json()


def _events(output: str) -> list[dict[str, object]]:
    return [json.loads(line) for line in output.splitlines() if line.strip()]


def _facade(repository: InMemoryStateRepository) -> TripInteractionFacade:
    return TripInteractionFacade(
        Settings(),
        planner=_UnexpectedPlanner(),
        gateway=FakeLLMGateway([_interpretation_response()]),
        state_repository=repository,
    )


def test_unknown_planner_error_is_safe_and_persisted(
    capsys: pytest.CaptureFixture[str],
) -> None:
    clear_contextvars()
    repository = InMemoryStateRepository()

    with pytest.raises(RuntimeError, match="secret-key"):
        _facade(repository).execute(_request(), "请安排一次旅行")

    events = _events(capsys.readouterr().out)
    failure = next(event for event in events if event["event"] == "workflow_failed")
    assert failure["code"] == "UNEXPECTED_INTERNAL_ERROR"
    assert failure["category"] == "internal"
    assert failure["cause_type"] == "RuntimeError"
    assert failure["safe_message"] != "secret-key must not be exposed"
    state = repository.get("m21-error-trip")
    assert state.last_error is not None
    assert state.last_error.code == "UNEXPECTED_INTERNAL_ERROR"
    assert state.last_error.safe_message != "secret-key must not be exposed"


def test_state_persistence_failure_does_not_replace_root_error(
    capsys: pytest.CaptureFixture[str],
) -> None:
    clear_contextvars()

    with pytest.raises(RuntimeError, match="secret-key"):
        _facade(_FailureOnFailedSaveRepository()).execute(
            _request(), "请安排一次旅行"
        )

    events = _events(capsys.readouterr().out)
    persistence = next(
        event for event in events if event["event"] == "state_persistence_failed"
    )
    assert persistence["code"] == "UNEXPECTED_INTERNAL_ERROR"
    assert persistence["stage"] == "state_persistence"
    assert persistence["cause_type"] == "RuntimeError"
    assert persistence["safe_message"] != "database password must not be exposed"


def test_unknown_stage_failure_has_safe_classification(
    capsys: pytest.CaptureFixture[str],
) -> None:
    clear_contextvars()

    with pytest.raises(RuntimeError, match="private-token"):
        with observe_stage("router"):
            raise RuntimeError("private-token must not be logged")

    failure = next(
        event
        for event in _events(capsys.readouterr().out)
        if event["event"] == "stage_failed"
    )
    assert failure["code"] == "UNEXPECTED_INTERNAL_ERROR"
    assert failure["safe_message"] == (
        "workflow failed due to an unexpected internal error"
    )
    assert failure["cause_type"] == "RuntimeError"
    assert "private-token" not in json.dumps(failure)


def test_state_load_error_is_logged_without_changing_exception(
    capsys: pytest.CaptureFixture[str],
) -> None:
    clear_contextvars()

    with pytest.raises(RuntimeError, match="state secret"):
        _facade(_FailureOnGetRepository()).execute(_request(), "请安排一次旅行")

    failure = next(
        event
        for event in _events(capsys.readouterr().out)
        if event["event"] == "workflow_failed"
    )
    assert failure["stage"] == "unknown"
    assert failure["code"] == "UNEXPECTED_INTERNAL_ERROR"
    assert "state secret" not in json.dumps(failure)
