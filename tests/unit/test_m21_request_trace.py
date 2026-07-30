from __future__ import annotations

import json

from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import SimpleSpanProcessor
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter
from structlog.contextvars import clear_contextvars, get_contextvars

from src.obs import trace as trace_module
from src.obs.log import get_logger


def _test_tracer(monkeypatch):
    exporter = InMemorySpanExporter()
    provider = TracerProvider()
    provider.add_span_processor(SimpleSpanProcessor(exporter))
    monkeypatch.setattr(trace_module, "_tracer", provider.get_tracer("m21-test"))
    return exporter


def test_workflow_request_links_agent_and_llm_spans(monkeypatch) -> None:
    exporter = _test_tracer(monkeypatch)

    with trace_module.trace_workflow_request(
        trace_id="route:trip-1:req-1",
        request_id="req-1",
        trip_id="trip-1",
        session_id="session-1",
        workflow_status="COLLECTING",
        state_version=1,
    ) as context:
        with trace_module.trace_agent("request_interpreter", "session-1"):
            with trace_module.trace_llm_call("deepseek-chat"):
                pass

    spans = {span.name: span for span in exporter.get_finished_spans()}
    root = spans["workflow.request"]
    agent = spans["agent.request_interpreter"]
    llm = spans["gen_ai.chat"]

    assert context.trace_id == "route:trip-1:req-1"
    assert context.otel_trace_id == format(root.context.trace_id, "032x")
    assert root.parent is None
    assert agent.parent is not None
    assert agent.parent.span_id == root.context.span_id
    assert llm.parent is not None
    assert llm.parent.span_id == agent.context.span_id
    assert root.attributes["workflow.trace_id"] == context.trace_id
    assert llm.attributes["workflow.trace_id"] == context.trace_id


def test_request_logger_context_contains_both_trace_ids_and_is_restored(
    monkeypatch,
    capsys,
) -> None:
    _test_tracer(monkeypatch)
    clear_contextvars()
    logger = get_logger("m21-test")

    with trace_module.trace_workflow_request(
        trace_id="route:trip-2:req-2",
        request_id="req-2",
        trip_id="trip-2",
        session_id="session-2",
    ) as context:
        logger.info("request_context_probe")
        assert get_contextvars()["trace_id"] == context.trace_id
        assert get_contextvars()["otel_trace_id"] == context.otel_trace_id

    payload = json.loads(capsys.readouterr().err.strip().splitlines()[-1])
    assert payload["event"] == "request_context_probe"
    assert payload["trace_id"] == "route:trip-2:req-2"
    assert payload["otel_trace_id"] == context.otel_trace_id
    assert payload["request_id"] == "req-2"
    assert payload["trip_id"] == "trip-2"
    assert payload["session_id"] == "session-2"
    assert "request_id" not in get_contextvars()
    assert "trip_id" not in get_contextvars()
    assert "session_id" not in get_contextvars()
