"""M2.1 application-boundary stage events and trace spans."""

from __future__ import annotations

from time import perf_counter
from typing import Any, Literal

from opentelemetry.trace import Span

from src.domain.errors import WorkflowError
from src.obs.errors import UNEXPECTED_INTERNAL_ERROR_CODE, UNEXPECTED_INTERNAL_SAFE_MESSAGE
from src.obs.log import get_logger
from src.obs.metric import record_stage
from src.obs.trace import trace_stage

logger = get_logger(__name__)

_ALLOWED_STAGES = frozenset(
    {
        "g0",
        "interpreter",
        "constraint_service",
        "readiness_evaluator",
        "router",
        "state",
    }
)


class StageObservation:
    """Emit one stage lifecycle event and manage its child Span."""

    def __init__(self, stage: str) -> None:
        if stage not in _ALLOWED_STAGES:
            raise ValueError(f"unsupported M2.1 stage: {stage}")
        self.stage = stage
        self._started_at = 0.0
        self._span_scope: Any = None
        self._span: Span | None = None
        self._summary: dict[str, Any] = {}

    def __enter__(self) -> StageObservation:
        self._started_at = perf_counter()
        self._span_scope = trace_stage(self.stage)
        self._span = self._span_scope.__enter__()
        _emit(
            "stage_started",
            stage=self.stage,
            status="started",
            duration_ms=0,
        )
        return self

    def add_summary(self, **fields: Any) -> None:
        """Add explicitly selected, low-sensitivity output fields."""
        self._summary.update(fields)

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: Any,
    ) -> Literal[False]:
        duration_ms = max(0, int((perf_counter() - self._started_at) * 1000))
        try:
            if exc is None:
                _set_span_summary(self._span, self._summary, duration_ms, "completed")
                record_stage(self.stage, "completed", duration_ms)
                _emit(
                    "stage_completed",
                    stage=self.stage,
                    status="completed",
                    duration_ms=duration_ms,
                    **self._summary,
                )
            else:
                failure = _failure_summary(exc)
                _set_span_summary(self._span, failure, duration_ms, "failed")
                record_stage(self.stage, "failed", duration_ms)
                _emit(
                    "stage_failed",
                    stage=self.stage,
                    status="failed",
                    duration_ms=duration_ms,
                    **self._summary,
                    **failure,
                )
        finally:
            if self._span_scope is not None:
                self._span_scope.__exit__(exc_type, exc, traceback)
        return False


def observe_stage(stage: str) -> StageObservation:
    """Create an observation scope for one M2.1 application stage."""
    return StageObservation(stage)


def _emit(event: str, **fields: Any) -> None:
    """Write one structured event without user-provided free text."""
    logger.info(event, **fields)


def _failure_summary(exc: BaseException) -> dict[str, Any]:
    payload = exc.public_payload() if isinstance(exc, WorkflowError) else None
    if payload is None:
        return {
            "category": "internal",
            "code": UNEXPECTED_INTERNAL_ERROR_CODE,
            "safe_message": UNEXPECTED_INTERNAL_SAFE_MESSAGE,
            "retryable": False,
            "cause_type": type(exc).__name__,
        }

    category = getattr(payload.category, "value", str(payload.category))
    cause = getattr(exc, "cause", None)
    return {
        "category": category,
        "code": payload.code,
        "safe_message": payload.safe_message,
        "upstream_refs": tuple(str(ref) for ref in payload.upstream_refs),
        "retryable": payload.retryable,
        "cause_type": type(cause).__name__ if cause is not None else type(exc).__name__,
    }


def _set_span_summary(
    span: Span | None,
    fields: dict[str, Any],
    duration_ms: int,
    status: str,
) -> None:
    if span is None:
        return
    span.set_attribute("workflow.stage_status", status)
    span.set_attribute("workflow.duration_ms", duration_ms)
    for key, value in fields.items():
        if value is None:
            continue
        if isinstance(value, str | bool | int | float):
            span.set_attribute(f"workflow.{key}", value)
        elif isinstance(value, tuple) and all(
            isinstance(item, str | bool | int | float) for item in value
        ):
            span.set_attribute(f"workflow.{key}", value)
