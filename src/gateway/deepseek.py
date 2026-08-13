"""DeepSeek synchronous LLM gateway."""

from __future__ import annotations

import time
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from openai import OpenAI

from src.config import Settings
from src.obs.log import get_logger
from src.obs.metric import record_llm_call
from src.obs.trace import trace_llm_call
from src.ports.llm_gateway import LLMOutputMode, LLMResponseError

logger = get_logger(__name__)

_V4_THINKING_MODELS = frozenset({"deepseek-v4-flash", "deepseek-v4-pro"})


@dataclass(frozen=True, slots=True)
class LLMCallRecord:
    """Safe summary of one LLM call without prompts or credentials."""

    model: str
    status: str
    duration_ms: int
    input_tokens: int
    output_tokens: int
    failure_type: str | None = None
    cause_code: str | None = None
    finish_reason: str | None = None
    max_tokens: int | None = None


def ask_llm(
    prompt: str,
    settings: Settings | None = None,
    *,
    output_mode: LLMOutputMode = LLMOutputMode.TEXT,
    observer: Callable[[LLMCallRecord], None] | None = None,
) -> str:
    """Call DeepSeek and return a non-empty, non-truncated text response.

    The public return type remains ``str``. Provider response-contract failures
    use ``LLMResponseError`` so callers can distinguish them without receiving
    the raw provider payload.
    """
    if settings is None:
        raise RuntimeError("Settings must be provided by the composition root")
    current = settings
    if not current.deepseek_api_key:
        raise RuntimeError("DEEPSEEK_API_KEY is not configured")

    client = OpenAI(
        api_key=current.deepseek_api_key,
        base_url="https://api.deepseek.com",
        timeout=current.llm_timeout_seconds,
        max_retries=current.retry_count,
    )
    kwargs: dict[str, Any] = {
        "model": current.deepseek_model,
        "messages": [{"role": "user", "content": prompt}],
    }
    if current.deepseek_max_tokens is not None:
        kwargs["max_tokens"] = current.deepseek_max_tokens
    if output_mode is LLMOutputMode.JSON_OBJECT:
        kwargs["response_format"] = {"type": "json_object"}
        kwargs["extra_body"] = {"thinking": {"type": "disabled"}}
    if current.deepseek_model.casefold() in _V4_THINKING_MODELS:
        kwargs["extra_body"] = {"thinking": {"type": "disabled"}}
        kwargs["temperature"] = 0

    logger.info(
        "llm_call_started",
        model=current.deepseek_model,
        output_mode=output_mode.value,
        prompt_chars=len(prompt),
    )

    started_at = time.perf_counter()
    input_tokens = 0
    output_tokens = 0
    finish_reason: str | None = None
    with trace_llm_call(current.deepseek_model) as span:
        try:
            response = client.chat.completions.create(**kwargs)
            if not response.choices:
                raise LLMResponseError(
                    "LLM response is missing choices",
                    cause_code="LLM_NO_CHOICES",
                    model=current.deepseek_model,
                    max_tokens=current.deepseek_max_tokens,
                )

            choice = response.choices[0]
            finish_reason = choice.finish_reason
            usage = response.usage
            input_tokens = usage.prompt_tokens if usage else 0
            output_tokens = usage.completion_tokens if usage else 0
            content = choice.message.content
            if not isinstance(content, str) or not content.strip():
                raise LLMResponseError(
                    "LLM response is empty",
                    cause_code="LLM_EMPTY_RESPONSE",
                    finish_reason=finish_reason,
                    model=current.deepseek_model,
                    max_tokens=current.deepseek_max_tokens,
                    input_tokens=input_tokens,
                    output_tokens=output_tokens,
                )
            if finish_reason == "length":
                raise LLMResponseError(
                    "LLM output was truncated by the token limit",
                    cause_code="LLM_OUTPUT_TRUNCATED",
                    finish_reason=finish_reason,
                    model=current.deepseek_model,
                    max_tokens=current.deepseek_max_tokens,
                    input_tokens=input_tokens,
                    output_tokens=output_tokens,
                )
        except Exception as exc:
            elapsed_ms = int((time.perf_counter() - started_at) * 1000)
            record_llm_call(
                model=current.deepseek_model,
                status="failure",
                duration_ms=elapsed_ms,
                input_tokens=input_tokens,
                output_tokens=output_tokens,
                finish_reason=finish_reason,
            )
            logger.error(
                "llm_call_failed",
                model=current.deepseek_model,
                cause_code=_cause_code(exc),
                finish_reason=finish_reason,
            )
            _notify(
                observer,
                LLMCallRecord(
                    model=current.deepseek_model,
                    status="failure",
                    duration_ms=elapsed_ms,
                    input_tokens=input_tokens,
                    output_tokens=output_tokens,
                    failure_type=type(exc).__name__,
                    cause_code=_cause_code(exc),
                    finish_reason=finish_reason,
                    max_tokens=current.deepseek_max_tokens,
                ),
            )
            raise

        elapsed_ms = int((time.perf_counter() - started_at) * 1000)
        span.set_attribute("gen_ai.usage.input_tokens", input_tokens)
        span.set_attribute("gen_ai.usage.output_tokens", output_tokens)
        span.set_attribute("gen_ai.response.finish_reasons", finish_reason or "unknown")

        record_llm_call(
            model=current.deepseek_model,
            status="success",
            duration_ms=elapsed_ms,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            finish_reason=finish_reason,
        )
        logger.info(
            "llm_call_finished",
            model=current.deepseek_model,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            duration_ms=elapsed_ms,
            finish_reason=finish_reason,
        )
        _notify(
            observer,
            LLMCallRecord(
                model=current.deepseek_model,
                status="success",
                duration_ms=elapsed_ms,
                input_tokens=input_tokens,
                output_tokens=output_tokens,
                finish_reason=finish_reason,
                max_tokens=current.deepseek_max_tokens,
            ),
        )

    return content


def _cause_code(exc: BaseException) -> str:
    if isinstance(exc, LLMResponseError):
        return exc.cause_code
    if isinstance(exc, TimeoutError):
        return "LLM_TIMEOUT"
    if isinstance(exc, RuntimeError | ValueError):
        return "LLM_CONFIGURATION_OR_PROVIDER_ERROR"
    return "LLM_PROVIDER_ERROR"


def _notify(
    observer: Callable[[LLMCallRecord], None] | None,
    record: LLMCallRecord,
) -> None:
    """Notify an optional observer without changing the call result."""
    if observer is None:
        return
    try:
        observer(record)
    except Exception as exc:
        logger.warning("llm_observer_failed", error_type=type(exc).__name__)
