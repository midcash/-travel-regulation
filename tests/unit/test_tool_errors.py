from __future__ import annotations

import pytest

from src.ports import (
    ToolAuthenticationError,
    ToolBusinessError,
    ToolConfigurationError,
    ToolEmptyResultError,
    ToolError,
    ToolRateLimitError,
    ToolResponseSchemaError,
    ToolTimeoutError,
    ToolTransportError,
)


@pytest.mark.parametrize(
    ("error_type", "code", "retryable"),
    [
        (ToolConfigurationError, "TOOL_CONFIGURATION_ERROR", False),
        (ToolTimeoutError, "TOOL_TIMEOUT_ERROR", True),
        (ToolTransportError, "TOOL_TRANSPORT_ERROR", True),
        (ToolAuthenticationError, "TOOL_AUTHENTICATION_ERROR", False),
        (ToolRateLimitError, "TOOL_RATE_LIMIT_ERROR", True),
        (ToolResponseSchemaError, "TOOL_RESPONSE_SCHEMA_ERROR", False),
        (ToolEmptyResultError, "TOOL_EMPTY_RESULT_ERROR", False),
        (ToolBusinessError, "TOOL_BUSINESS_ERROR", False),
    ],
)
def test_tool_error_subclasses_expose_typed_safe_diagnostics(
    error_type: type[ToolError], code: str, retryable: bool
) -> None:
    error = error_type(
        provider="amap",
        operation="geo_search",
        trace_id="trace-1",
        query_id="query-1",
        safe_message="provider request failed",
    )

    assert isinstance(error, ToolError)
    assert error.code == code
    assert error.retryable is retryable
    assert error.provider == "amap"
    assert error.operation == "geo_search"
    assert error.trace_id == "trace-1"
    assert error.query_id == "query-1"
    assert str(error) == "provider request failed"
    assert "amap" not in error.safe_message


def test_tool_error_context_is_immutable() -> None:
    error = ToolConfigurationError(
        provider="tuniu",
        operation="stay_search",
        safe_message="provider configuration is incomplete",
    )

    with pytest.raises(AttributeError):
        error.context.provider = "other"  # type: ignore[misc]


def test_tool_error_preserves_cause_when_adapter_wraps_failure() -> None:
    cause = TimeoutError("secret provider endpoint")

    def call_provider() -> None:
        try:
            raise cause
        except TimeoutError as original:
            raise ToolTimeoutError(
                provider="amap",
                operation="geo_search",
                trace_id="trace-1",
                query_id="query-1",
                safe_message="provider request timed out",
            ) from original

    with pytest.raises(ToolTimeoutError) as raised:
        call_provider()

    assert raised.value.__cause__ is cause
    assert str(raised.value) == "provider request timed out"
    assert "secret provider endpoint" not in str(raised.value)


def test_tool_error_does_not_offer_implicit_fallback_or_empty_success() -> None:
    error = ToolEmptyResultError(
        provider="amap",
        operation="place_search",
        safe_message="provider returned no usable results",
    )

    assert error.retryable is False
    assert not hasattr(error, "fallback")
    assert not hasattr(error, "result")
