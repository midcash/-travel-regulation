"""DeepSeek 同步 LLM 网关。"""

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
from src.ports.llm_gateway import LLMOutputMode

logger = get_logger(__name__)


@dataclass(frozen=True, slots=True)
class LLMCallRecord:
    "Summary of one LLM call without prompts, responses, or credentials."

    model: str
    status: str
    duration_ms: int
    input_tokens: int
    output_tokens: int
    failure_type: str | None = None


class LLMResponseError(RuntimeError):
    """LLM 返回了无法作为文本使用的响应。"""


def ask_llm(
    prompt: str,
    settings: Settings | None = None,
    *,
    output_mode: LLMOutputMode = LLMOutputMode.TEXT,
    observer: Callable[[LLMCallRecord], None] | None = None,
) -> str:
    """调用 DeepSeek LLM 并返回非空文本。

    Args:
        prompt: 发给模型的 Prompt。
        settings: 由组合根创建并校验的配置。
        output_mode: 文本或结构化 JSON 输出契约。
        observer: 可选的脱敏调用摘要观察器。

    Returns:
        str: 非空响应文本。

    Raises:
        RuntimeError: API Key 未配置。
        LLMResponseError: 模型响应为空或缺少 choice。
        Exception: SDK 的超时、网络和服务端异常原样传播。
    """
    if settings is None:
        raise RuntimeError('Settings must be provided by the composition root')
    current = settings
    if not current.deepseek_api_key:
        raise RuntimeError("DEEPSEEK_API_KEY 未设置")

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

    logger.info(
        "llm_call_started",
        model=current.deepseek_model,
        output_mode=output_mode.value,
        prompt_chars=len(prompt),
    )

    started_at = time.perf_counter()
    with trace_llm_call(current.deepseek_model) as span:
        try:
            response = client.chat.completions.create(**kwargs)
            if not response.choices:
                raise LLMResponseError("LLM 响应缺少 choices")
            content = response.choices[0].message.content
            if not isinstance(content, str) or not content.strip():
                raise LLMResponseError("LLM 返回空响应")
        except Exception as exc:
            elapsed_ms = int((time.perf_counter() - started_at) * 1000)
            record_llm_call(
                model=current.deepseek_model,
                status="failure",
                duration_ms=elapsed_ms,
            )
            logger.error("llm_call_failed", model=current.deepseek_model)
            _notify(
                observer,
                LLMCallRecord(
                    model=current.deepseek_model,
                    status='failure',
                    duration_ms=elapsed_ms,
                    input_tokens=0,
                    output_tokens=0,
                    failure_type=type(exc).__name__,
                ),
            )
            raise

        elapsed_ms = int((time.perf_counter() - started_at) * 1000)
        finish_reason = response.choices[0].finish_reason
        usage = response.usage
        input_tokens = usage.prompt_tokens if usage else 0
        output_tokens = usage.completion_tokens if usage else 0

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
                status='success',
                duration_ms=elapsed_ms,
                input_tokens=input_tokens,
                output_tokens=output_tokens,
            ),
        )

        if finish_reason == 'length':
            logger.warning(
                "llm_output_truncated",
                finish_reason="length",
                max_tokens=str(current.deepseek_max_tokens or "无限制"),
            )

    return content


def _notify(
    observer: Callable[[LLMCallRecord], None] | None,
    record: LLMCallRecord,
) -> None:
    "Notify an optional observer without changing the call result."
    if observer is None:
        return
    try:
        observer(record)
    except Exception as exc:
        logger.warning('llm_observer_failed', error_type=type(exc).__name__)
