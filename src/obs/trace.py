"""Local OpenTelemetry tracing helpers."""

from __future__ import annotations

import sys
from collections.abc import Iterator, Sequence
from contextlib import contextmanager
from dataclasses import dataclass

from opentelemetry import trace
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import ConsoleSpanExporter, SimpleSpanProcessor
from opentelemetry.trace import Span, Status, StatusCode

from src.obs.log import bind_request_context

_AttributeValue = (
    str
    | bool
    | int
    | float
    | Sequence[str]
    | Sequence[bool]
    | Sequence[int]
    | Sequence[float]
)

_resource = Resource.create({"service.name": "travel-planner-agent"})
_provider = TracerProvider(resource=_resource)
_provider.add_span_processor(SimpleSpanProcessor(ConsoleSpanExporter(out=sys.stderr)))
trace.set_tracer_provider(_provider)

_tracer = trace.get_tracer(__name__)


@dataclass(frozen=True, slots=True)
class WorkflowTraceContext:
    """Correlation identifiers for one workflow request."""

    trace_id: str
    otel_trace_id: str
    request_id: str
    trip_id: str
    session_id: str


def _otel_ids(span: Span) -> tuple[str, str]:
    context = span.get_span_context()
    return format(context.trace_id, "032x"), format(context.span_id, "016x")


def _current_business_trace_id() -> str | None:
    from structlog.contextvars import get_contextvars

    value = get_contextvars().get("trace_id")
    return value if isinstance(value, str) else None


@contextmanager
def trace_workflow_request(
    *,
    trace_id: str,
    request_id: str,
    trip_id: str,
    session_id: str,
    workflow_status: str | None = None,
    state_version: int | None = None,
) -> Iterator[WorkflowTraceContext]:
    """Create the workflow.request root span and bind request context."""
    attributes: dict[str, _AttributeValue] = {
        "workflow.trace_id": trace_id,
        "workflow.request_id": request_id,
        "workflow.trip_id": trip_id,
        "workflow.session_id": session_id,
    }
    if workflow_status is not None:
        attributes["workflow.status"] = workflow_status
    if state_version is not None:
        attributes["workflow.state_version"] = state_version

    with _tracer.start_as_current_span(
        "workflow.request",
        attributes=attributes,
        record_exception=False,
    ) as span:
        otel_trace_id, _ = _otel_ids(span)
        span.set_attribute("workflow.otel_trace_id", otel_trace_id)
        span.set_attribute("otel_trace_id", otel_trace_id)
        context = WorkflowTraceContext(
            trace_id=trace_id,
            otel_trace_id=otel_trace_id,
            request_id=request_id,
            trip_id=trip_id,
            session_id=session_id,
        )
        try:
            with bind_request_context(
                trace_id=trace_id,
                otel_trace_id=otel_trace_id,
                request_id=request_id,
                trip_id=trip_id,
                session_id=session_id,
                workflow_status=workflow_status,
                state_version=state_version,
            ):
                yield context
        except BaseException as exc:
            span.set_status(Status(StatusCode.ERROR, type(exc).__name__))
            span.set_attribute("error.type", type(exc).__name__)
            raise


@contextmanager
def trace_session(session_id: str) -> Iterator[trace.Span]:
    """Keep legacy planner compatible and reuse an existing request root."""
    current = trace.get_current_span()
    if current.get_span_context().is_valid:
        yield current
        return
    with _tracer.start_as_current_span(
        "session",
        attributes={"session_id": session_id},
        record_exception=False,
    ) as span:
        yield span


@contextmanager
def trace_phase(phase: int, session_id: str) -> Iterator[trace.Span]:
    """Create a child span for a workflow phase."""
    attributes: dict[str, _AttributeValue] = {"session_id": session_id, "phase": phase}
    business_trace_id = _current_business_trace_id()
    if business_trace_id is not None:
        attributes["workflow.trace_id"] = business_trace_id
    with _tracer.start_as_current_span(
        f"phase_{phase}",
        attributes=attributes,
        record_exception=False,
    ) as span:
        yield span


@contextmanager
def trace_agent(
    agent_name: str,
    session_id: str,
    *,
    trace_id: str | None = None,
) -> Iterator[trace.Span]:
    """Create an agent child span for automatic OTel parent propagation."""
    attributes: dict[str, _AttributeValue] = {"agent": agent_name, "session_id": session_id}
    business_trace_id = trace_id or _current_business_trace_id()
    if business_trace_id is not None:
        attributes["workflow.trace_id"] = business_trace_id
    with _tracer.start_as_current_span(
        f"agent.{agent_name}",
        attributes=attributes,
        record_exception=False,
    ) as span:
        yield span


@contextmanager
def trace_llm_call(model: str, provider: str = "deepseek") -> Iterator[trace.Span]:
    """Create a gen_ai.chat child span."""
    attributes: dict[str, _AttributeValue] = {
        "gen_ai.system": provider,
        "gen_ai.operation.name": "chat",
        "gen_ai.request.model": model,
    }
    business_trace_id = _current_business_trace_id()
    if business_trace_id is not None:
        attributes["workflow.trace_id"] = business_trace_id
    with _tracer.start_as_current_span(
        "gen_ai.chat",
        attributes=attributes,
        record_exception=False,
    ) as span:
        yield span

_STAGE_SPAN_NAMES: dict[str, str] = {
    "g0": "stage.g0",
    "interpreter": "stage.interpreter",
    "constraint_service": "stage.constraint_snapshot",
    "readiness_evaluator": "stage.readiness",
    "router": "stage.route",
    "state": "stage.state_persistence",
}


@contextmanager
def trace_stage(
    stage: str,
    *,
    attributes: dict[str, _AttributeValue] | None = None,
) -> Iterator[trace.Span]:
    """Create an application-boundary child Span for one M2.1 stage."""
    if not stage.strip():
        raise ValueError("stage must not be empty")
    span_attributes: dict[str, _AttributeValue] = {"workflow.stage": stage}
    if attributes:
        span_attributes.update(attributes)
    with _tracer.start_as_current_span(
        _STAGE_SPAN_NAMES.get(stage, f"stage.{stage}"),
        attributes=span_attributes,
        record_exception=False,
    ) as span:
        try:
            yield span
        except BaseException as exc:
            span.set_status(Status(StatusCode.ERROR, type(exc).__name__))
            span.set_attribute("error.type", type(exc).__name__)
            payload = getattr(exc, "payload", None)
            if payload is not None:
                span.set_attribute("workflow.stage", str(payload.stage))
                span.set_attribute("workflow.code", str(payload.code))
            else:
                span.set_attribute("workflow.code", "UNEXPECTED_INTERNAL_ERROR")
            raise
