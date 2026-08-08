"""Workflow failure diagnostics at the application and CLI boundaries."""

from __future__ import annotations

import re
import ssl
from dataclasses import dataclass
from typing import Any

from pydantic import ValidationError

from src.domain.errors import WorkflowError, WorkflowErrorPayload
from src.domain.models.enums import ErrorCategory

UNEXPECTED_INTERNAL_ERROR_CODE = "UNEXPECTED_INTERNAL_ERROR"
UNEXPECTED_INTERNAL_SAFE_MESSAGE = "workflow failed due to an unexpected internal error"
_SAFE_CAUSE_CODE = re.compile(r"^[A-Z][A-Z0-9_]{0,63}$")
_SAFE_VALIDATION_PART = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
_SAFE_VALIDATION_TYPE = re.compile(r"^[a-z][a-z0-9_.-]{0,63}$")
_SAFE_VALIDATION_MODEL = re.compile(r"^[A-Za-z_][A-Za-z0-9_]{0,127}$")
_SAFE_VALIDATION_CODE = re.compile(r"^[a-z][a-z0-9_.-]{0,127}$")
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
    root_cause_type: str
    root_cause_code: str | None
    root_cause_model: str | None
    root_cause_validation: tuple[str, ...]

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
            "root_cause_type": self.root_cause_type,
            "root_cause_code": self.root_cause_code,
            "root_cause_model": self.root_cause_model,
            "root_cause_validation": list(self.root_cause_validation),
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
            root_cause_type=type(_root_cause(cause)).__name__,
            root_cause_code=_root_cause_code(cause),
            root_cause_model=_root_cause_model(cause),
            root_cause_validation=_root_cause_validation(cause),
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
    return WorkflowFailure(
        payload=payload,
        cause_type=type(exc).__name__,
        root_cause_type=type(_root_cause(exc)).__name__,
        root_cause_code=_root_cause_code(exc),
        root_cause_model=_root_cause_model(exc),
        root_cause_validation=_root_cause_validation(exc),
    )


def _root_cause(exc: BaseException) -> BaseException:
    """Follow the explicit cause chain while exposing only exception types."""
    current = exc
    visited = {id(current)}
    while True:
        nested = current.__cause__
        if nested is None or id(nested) in visited:
            return current
        current = nested
        visited.add(id(current))


def _root_cause_code(exc: BaseException) -> str | None:
    """Return only a bounded OpenSSL reason identifier, never exception text."""
    root = _root_cause(exc)
    if not isinstance(root, ssl.SSLError):
        return None
    reason = getattr(root, "reason", None)
    return reason if isinstance(reason, str) and _SAFE_CAUSE_CODE.fullmatch(reason) else None


def _root_cause_validation(exc: BaseException) -> tuple[str, ...]:
    """Return only safe Pydantic field paths and error types."""
    root = _root_cause(exc)
    if not isinstance(root, ValidationError):
        return ()

    signatures: list[str] = []
    for detail in root.errors():
        location = detail.get("loc", ())
        error_type = detail.get("type")
        if not isinstance(location, tuple) or not isinstance(error_type, str):
            continue
        if not _SAFE_VALIDATION_TYPE.fullmatch(error_type):
            continue
        if not location:
            context = detail.get("ctx")
            error = context.get("error") if isinstance(context, dict) else None
            code = getattr(error, "code", None)
            if isinstance(code, str) and _SAFE_VALIDATION_CODE.fullmatch(code):
                signatures.append(f"__model__:{code}")
            else:
                signatures.append(f"__model__:{error_type}")
            continue
        parts: list[str] = []
        safe_location = True
        for part in location:
            if isinstance(part, int) and not isinstance(part, bool):
                parts.append(f"[{part}]")
            elif isinstance(part, str) and _SAFE_VALIDATION_PART.fullmatch(part):
                parts.append(part)
            else:
                safe_location = False
                break
        if not safe_location or not parts:
            continue
        signature = f"{'.'.join(parts)}:{error_type}"
        if signature not in signatures:
            signatures.append(signature)
    return tuple(signatures)


def _root_cause_model(exc: BaseException) -> str | None:
    """Return a bounded Pydantic model title without validation details."""
    root = _root_cause(exc)
    if not isinstance(root, ValidationError):
        return None
    title = getattr(root, "title", None)
    return title if isinstance(title, str) and _SAFE_VALIDATION_MODEL.fullmatch(title) else None


def _exception_stage(exc: BaseException) -> str | None:
    """Read an optional stage attribute without exposing arbitrary exception text."""
    value = getattr(exc, "stage", None)
    return value if isinstance(value, str) and value in _SAFE_EXCEPTION_STAGES else None
