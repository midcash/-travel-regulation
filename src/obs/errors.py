"""Workflow failure diagnostics at the application and CLI boundaries."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from src.domain.errors import WorkflowError, WorkflowErrorPayload
from src.domain.models.enums import ErrorCategory

UNEXPECTED_INTERNAL_ERROR_CODE = "UNEXPECTED_INTERNAL_ERROR"
UNEXPECTED_INTERNAL_SAFE_MESSAGE = "workflow failed due to an unexpected internal error"
_SAFE_EXCEPTION_STAGES = frozenset(
    {
        "bootstrap",
        "configuration",
        "constraint_service",
        "g0",
        "generation",
        "interpreter",
        "mapping",
        "readiness_evaluator",
        "request_interpreter",
        "review",
        "revision",
        "router",
        "state",
        "state_persistence",
        "state_repository",
        "unknown",
    }
)


@dataclass(frozen=True, slots=True)
class WorkflowFailure:
    """Safe failure data shared by state persistence, logs, and the CLI."""

    payload: WorkflowErrorPayload
    cause_type: str

    def event_fields(self, *, duration_ms: int = 0) -> dict[str, Any]:
        """Return an explicit, low-sensitivity event field allowlist."""
        return {
            "trace_id": str(self.payload.trace_id),
            "stage": self.payload.stage,
            "status": "failed",
            "duration_ms": duration_ms,
            "category": self.payload.category.value,
            "code": self.payload.code,
            "safe_message": self.payload.safe_message,
            "upstream_refs": [str(ref) for ref in self.payload.upstream_refs],
            "retryable": self.payload.retryable,
            "cause_type": self.cause_type,
        }


def from_exception(
    exc: BaseException,
    *,
    trace_id: str,
    stage: str | None = None,
) -> WorkflowFailure:
    """Convert an exception to a safe, structured workflow failure."""
    if isinstance(exc, WorkflowError):
        cause = exc.cause or exc
        return WorkflowFailure(
            payload=exc.public_payload(),
            cause_type=type(cause).__name__,
        )

    resolved_stage = stage or _exception_stage(exc) or "unknown"
    payload = WorkflowErrorPayload(
        trace_id=trace_id,
        stage=resolved_stage,
        category=ErrorCategory.INTERNAL,
        code=UNEXPECTED_INTERNAL_ERROR_CODE,
        safe_message=UNEXPECTED_INTERNAL_SAFE_MESSAGE,
        retryable=False,
    )
    return WorkflowFailure(payload=payload, cause_type=type(exc).__name__)


def _exception_stage(exc: BaseException) -> str | None:
    """Read an optional stage attribute without exposing arbitrary exception text."""
    value = getattr(exc, "stage", None)
    return value if isinstance(value, str) and value in _SAFE_EXCEPTION_STAGES else None
