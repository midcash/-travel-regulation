from __future__ import annotations

import json
from datetime import date
from decimal import Decimal

import pytest
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import SimpleSpanProcessor
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter
from structlog.contextvars import clear_contextvars

from src.application.interaction_facade import TripInteractionFacade
from src.config import Settings
from src.domain.errors import WorkflowError
from src.domain.models.enums import ConstraintHardness, ErrorCategory, InteractionMode
from src.domain.models.interpretation import ConstraintCandidate, InterpretationResult
from src.domain.models.trip_request import TravelerProfile, TripRequest
from src.domain.models.value_objects import DateRange
from src.infrastructure.persistence.in_memory import InMemoryStateRepository
from src.obs import trace as trace_module
from src.obs.stage import observe_stage
from tests.support.clock_fakes import FakeClock
from tests.support.llm_fakes import FakeLLMGateway


class _Planner:
    def execute(self, request: TripRequest) -> None:
        return None


def _tracer(monkeypatch: pytest.MonkeyPatch) -> InMemorySpanExporter:
    exporter = InMemorySpanExporter()
    provider = TracerProvider()
    provider.add_span_processor(SimpleSpanProcessor(exporter))
    monkeypatch.setattr(trace_module, "_tracer", provider.get_tracer("m21-stage-test"))
    return exporter


def _request() -> TripRequest:
    return TripRequest(
        request_id="m21-stage-request",
        trip_id="m21-stage-trip",
        session_id="m21-stage-session",
        origin="上海",
        destinations=("杭州",),
        date_range=DateRange(start=date(2026, 8, 1), end=date(2026, 8, 3)),
        travelers=TravelerProfile(adults=2),
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
            value="2026年8月1日至2026年8月3日",
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
    )
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


def _events(output: str) -> list[dict[str, object]]:
    return [json.loads(line) for line in output.splitlines() if line.strip()]


def test_facade_emits_ordered_stage_summaries_and_spans(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    exporter = _tracer(monkeypatch)
    clear_contextvars()

    facade = TripInteractionFacade(
        Settings(),
        planner=_Planner(),
        gateway=FakeLLMGateway([_interpretation_response()]),
        state_repository=InMemoryStateRepository(),
        clock=FakeClock(),
    )
    result = facade.execute(_request(), "请安排上海到杭州的三日行程。")

    completed = [
        event for event in _events(capsys.readouterr().err) if event["event"] == "stage_completed"
    ]
    assert [event["stage"] for event in completed] == [
        "g0",
        "interpreter",
        "constraint_service",
        "readiness_evaluator",
        "router",
        "state",
    ]
    assert completed[0]["passed"] is True
    assert completed[1]["candidate_count"] == 4
    assert completed[2]["snapshot_version"] == result.constraint_snapshot.version
    assert completed[3]["blocker_codes"] == []
    assert completed[4]["mode"] == "plan"
    assert completed[4]["reason_codes"] == ["PLAN_REQUEST"]
    assert completed[5]["state_after"] == result.state.status.value
    assert all(isinstance(event["duration_ms"], int) for event in completed)

    spans = {span.name: span for span in exporter.get_finished_spans()}
    root = spans["workflow.request"]
    for name in (
        "stage.g0",
        "stage.interpreter",
        "stage.constraint_snapshot",
        "stage.readiness",
        "stage.route",
        "stage.state_persistence",
    ):
        span = spans[name]
        assert span.parent is not None
        assert span.parent.span_id == root.context.span_id
        assert span.attributes["workflow.stage_status"] == "completed"
        assert span.attributes["workflow.duration_ms"] >= 0


def test_stage_failure_event_contains_safe_workflow_error_fields(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    exporter = _tracer(monkeypatch)
    clear_contextvars()

    with pytest.raises(WorkflowError):
        with observe_stage("constraint_service") as stage:
            stage.add_summary(snapshot_version=1)
            raise WorkflowError(
                "trace:m21-stage",
                "constraint_service",
                ErrorCategory.VALIDATION,
                "INTERPRETATION_INVALID",
                "constraints violate snapshot contract",
                retryable=False,
            )

    failed = [
        event for event in _events(capsys.readouterr().err) if event["event"] == "stage_failed"
    ]
    assert len(failed) == 1
    assert failed[0]["stage"] == "constraint_service"
    assert failed[0]["code"] == "INTERPRETATION_INVALID"
    assert failed[0]["category"] == "validation"
    assert failed[0]["safe_message"] == "constraints violate snapshot contract"
    assert failed[0]["retryable"] is False
    assert failed[0]["snapshot_version"] == 1

    span = exporter.get_finished_spans()[0]
    assert span.name == "stage.constraint_snapshot"
    assert span.status.is_ok is False
    assert span.attributes["workflow.code"] == "INTERPRETATION_INVALID"
