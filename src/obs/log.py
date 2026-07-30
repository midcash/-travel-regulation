"""Structured logging and request correlation context."""

from __future__ import annotations

import sys
from collections.abc import Iterator, MutableMapping
from contextlib import contextmanager
from typing import Any, TextIO, cast

import structlog
from structlog.contextvars import bound_contextvars

_LOG_LEVELS = {
    "DEBUG": 10,
    "INFO": 20,
    "WARNING": 30,
    "ERROR": 40,
    "CRITICAL": 50,
}
_current_log_level = "INFO"
_log_stream: TextIO | None = None

if sys.stderr.encoding != "utf-8":
    reconfigure = getattr(sys.stderr, "reconfigure", None)
    if callable(reconfigure):
        reconfigure(encoding="utf-8")


def _add_otel_context(
    logger: structlog.types.BindableLogger,
    method_name: str,
    event_dict: MutableMapping[str, Any],
) -> MutableMapping[str, Any]:
    """Add OTel Trace and Span IDs without overwriting the business trace_id."""
    try:
        from opentelemetry import trace
    except ImportError:
        return event_dict

    span = trace.get_current_span()
    if span.is_recording():
        context = span.get_span_context()
        otel_trace_id = format(context.trace_id, "032x")
        otel_span_id = format(context.span_id, "016x")
        event_dict.setdefault("trace_id", otel_trace_id)
        event_dict.setdefault("span_id", otel_span_id)
        event_dict.setdefault("otel_trace_id", otel_trace_id)
        event_dict.setdefault("otel_span_id", otel_span_id)
    return event_dict


class _DynamicPrintLoggerFactory:
    """Resolve stderr at emit time so CLI/test stream redirection remains valid."""

    def __call__(self, *args: Any, **kwargs: Any) -> structlog.PrintLogger:
        return structlog.PrintLogger(file=_log_stream or sys.stderr)


def _normalize_level(level: str) -> str:
    normalized = level.strip().upper()
    if normalized not in _LOG_LEVELS:
        allowed = ", ".join(_LOG_LEVELS)
        raise ValueError(f"LOG_LEVEL must be one of {allowed}")
    return normalized


def configure_logging(level: str = "INFO", *, stream: TextIO | None = None) -> None:
    """Configure the local JSONL channel and its minimum level.

    Human-readable CLI output stays on stdout. Application events are emitted
    as JSONL to stderr so they can be redirected independently.
    """
    global _current_log_level, _log_stream
    _current_log_level = _normalize_level(level)
    _log_stream = stream
    structlog.configure(
        processors=[
            structlog.contextvars.merge_contextvars,
            structlog.stdlib.add_log_level,
            _add_otel_context,
            structlog.processors.TimeStamper(fmt="iso"),
            structlog.processors.JSONRenderer(ensure_ascii=False),
        ],
        wrapper_class=structlog.make_filtering_bound_logger(_LOG_LEVELS[_current_log_level]),
        logger_factory=_DynamicPrintLoggerFactory(),
        cache_logger_on_first_use=False,
    )


def current_log_level() -> str:
    """Return the configured local logging level."""
    return _current_log_level


def get_logger(name: str = __name__) -> structlog.stdlib.BoundLogger:
    """Return a configured structured logger."""
    return cast(structlog.stdlib.BoundLogger, structlog.get_logger(name))


@contextmanager
def bind_request_context(
    *,
    trace_id: str,
    request_id: str,
    trip_id: str,
    session_id: str,
    otel_trace_id: str,
    workflow_status: str | None = None,
    state_version: int | None = None,
) -> Iterator[None]:
    """Bind safe request identifiers for the current context scope."""
    values: dict[str, Any] = {
        "trace_id": trace_id,
        "otel_trace_id": otel_trace_id,
        "request_id": request_id,
        "trip_id": trip_id,
        "session_id": session_id,
    }
    if workflow_status is not None:
        values["workflow_status"] = workflow_status
    if state_version is not None:
        values["state_version"] = state_version
    with bound_contextvars(**values):
        yield


configure_logging()
