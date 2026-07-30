from __future__ import annotations

import json

import pytest
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import SimpleSpanProcessor
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter
from structlog.contextvars import clear_contextvars

from src.config import Settings
from src.engine import loop
from src.obs import trace as trace_module
from tests.support.fakes import FakeLLM


def _events(output: str) -> list[dict[str, object]]:
    return [json.loads(line) for line in output.splitlines() if line.strip()]


def _settings() -> Settings:
    return Settings(deepseek_api_key="fake-key")


def test_legacy_review_revision_events_keep_safe_refs_and_preserve_result(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    clear_contextvars()
    planner_llm = FakeLLM(
        [
            "\u9884\u7b97 2000 \u5143\uff0c\u603b\u8d39\u7528 2300 \u5143 SECRET_PLAN_TEXT",
            "\u9884\u7b97 2000 \u5143\uff0c\u603b\u8d39\u7528 1500 \u5143 FINAL_PLAN_TEXT",
        ]
    )
    review_results = [
        {"pass": False, "issues": ["l2-private-reason"]},
        {"pass": True, "issues": []},
    ]
    monkeypatch.setattr(loop, "ask_llm", planner_llm)
    monkeypatch.setattr(loop, "run_l2_review", lambda *args, **kwargs: review_results.pop(0))

    result = loop.plan("city-trip", settings=_settings())

    assert result["plan"].endswith("FINAL_PLAN_TEXT")
    assert result["rounds"] == 2
    events = _events(capsys.readouterr().out)
    reviews = [event for event in events if event["event"] == "legacy_review_completed"]
    assert len(reviews) == 2
    first_review = reviews[0]
    assert first_review["round"] == 1
    assert first_review["l1_passed"] is False
    assert first_review["l1_issue_count"] == 1
    assert first_review["l2_passed"] is False
    assert first_review["l2_issue_count"] == 1
    assert first_review["issue_refs"]
    assert first_review["l1_issue_refs"]
    assert first_review["l2_issue_refs"]

    requested = next(event for event in events if event["event"] == "legacy_revision_requested")
    assert requested["round"] == 1
    assert requested["trigger_sources"] == ["l1", "l2"]
    assert requested["issue_summary_ref"]
    assert requested["issue_refs"] == first_review["issue_refs"]

    completed = next(event for event in events if event["event"] == "legacy_revision_completed")
    assert completed["round"] == 1
    assert completed["output_chars"] == len(result["plan"])
    assert completed["duration_ms"] >= 0

    serialized = json.dumps(events, ensure_ascii=False)
    assert "SECRET_PLAN_TEXT" not in serialized
    assert "FINAL_PLAN_TEXT" not in serialized
    assert "l2-private-reason" not in serialized


def test_legacy_revision_exhausted_emits_unresolved_refs_and_keeps_failure(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    clear_contextvars()
    monkeypatch.setattr(
        loop,
        "ask_llm",
        FakeLLM(["\u9884\u7b97 2000 \u5143\uff0c\u603b\u8d39\u7528 2300 \u5143 SECRET_PLAN_TEXT"]),
    )
    monkeypatch.setattr(
        loop,
        "run_l2_review",
        lambda *args, **kwargs: {"pass": False, "issues": ["private-l2-reason"]},
    )

    with pytest.raises(loop.PlanningError) as raised:
        loop.plan("city-trip", max_rounds=0, settings=_settings())

    assert raised.value.stage == "revision"
    events = _events(capsys.readouterr().out)
    exhausted = [event for event in events if event["event"] == "legacy_revision_exhausted"]
    assert len(exhausted) == 1
    assert exhausted[0]["round"] == 1
    assert exhausted[0]["issue_refs"]
    assert exhausted[0]["issue_summary_ref"]
    assert not any(event["event"] == "legacy_revision_requested" for event in events)
    assert not any(event["event"] == "legacy_revision_completed" for event in events)
    serialized = json.dumps(events, ensure_ascii=False)
    assert "SECRET_PLAN_TEXT" not in serialized
    assert "private-l2-reason" not in serialized


def test_legacy_review_spans_are_nested_under_legacy_plan(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    exporter = InMemorySpanExporter()
    provider = TracerProvider()
    provider.add_span_processor(SimpleSpanProcessor(exporter))
    monkeypatch.setattr(trace_module, "_tracer", provider.get_tracer("m21-legacy-test"))
    monkeypatch.setattr(
        loop,
        "ask_llm",
        FakeLLM(
            [
                "\u9884\u7b97 2000 \u5143\uff0c\u603b\u8d39\u7528 2300 \u5143",
                "\u9884\u7b97 2000 \u5143\uff0c\u603b\u8d39\u7528 1500 \u5143",
            ]
        ),
    )
    review_results = [
        {"pass": False, "issues": ["review issue"]},
        {"pass": True, "issues": []},
    ]
    monkeypatch.setattr(loop, "run_l2_review", lambda *args, **kwargs: review_results.pop(0))

    loop.plan("city-trip", settings=_settings())

    spans = {span.name: span for span in exporter.get_finished_spans()}
    legacy_plan = spans["legacy.plan"]
    assert spans["gate.l1"].parent.span_id == legacy_plan.context.span_id
    assert spans["agent.legacy_critic"].parent.span_id == legacy_plan.context.span_id
    assert spans["legacy.revision"].parent.span_id == legacy_plan.context.span_id
    assert (
        spans["agent.planner_a_revision"].parent.span_id == spans["legacy.revision"].context.span_id
    )
