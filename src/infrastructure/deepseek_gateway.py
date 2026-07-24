import os
import time

try:
    from dotenv import load_dotenv; load_dotenv()
except ImportError:
    pass

from openai import OpenAI  # 同步客户端

from src.utils.logger import get_logger
from src.utils.tracing import trace_llm_call
from src.utils.metrics import (
    LLM_CALLS_TOTAL,
    LLM_DURATION_SECONDS,
    LLM_TOKENS_TOTAL,
)

logger = get_logger(__name__)

API_KEY = os.environ.get("DEEPSEEK_API_KEY")
MODEL = os.environ.get("DEEPSEEK_MODEL", "deepseek-chat")

# max_tokens 设为 None（不限制），让模型自行决定输出长度。
# DeepSeek V4 系列支持超长上下文（128k+），无需手动截断。
# 若需限制成本，可在 .env 中设置 DEEPSEEK_MAX_TOKENS。
_MAX_TOKENS = int(os.environ["DEEPSEEK_MAX_TOKENS"]) if "DEEPSEEK_MAX_TOKENS" in os.environ else None


def ask_llm(prompt: str) -> str:
    """调用 DeepSeek LLM，返回响应文本。

    Args:
        prompt: 用户 prompt（system prompt + 用户数据）。

    Returns:
        LLM 响应文本。若 finish_reason 为 "length" 则 JSON 可能不完整。

    Raises:
        RuntimeError: API_KEY 未设置时抛出。
    """
    if not API_KEY:
        raise RuntimeError("DEEPSEEK_API_KEY 未设置")

    client = OpenAI(api_key=API_KEY, base_url="https://api.deepseek.com")
    kwargs: dict = {
        "model": MODEL,
        "messages": [{"role": "user", "content": prompt}],
    }
    if _MAX_TOKENS is not None:
        kwargs["max_tokens"] = _MAX_TOKENS

    logger.info(
        "llm_call_started",
        model=MODEL,
        prompt_chars=len(prompt),
    )

    t_start = time.perf_counter()
    with trace_llm_call(MODEL) as span:
        try:
            resp = client.chat.completions.create(**kwargs)
        except Exception:
            LLM_CALLS_TOTAL.labels(model=MODEL, status="failure").inc()
            logger.error("llm_call_failed", model=MODEL)
            raise

        elapsed_ms = int((time.perf_counter() - t_start) * 1000)
        finish = resp.choices[0].finish_reason
        content = resp.choices[0].message.content or "{}"

        # Token 用量统计
        usage = resp.usage
        input_tokens = usage.prompt_tokens if usage else 0
        output_tokens = usage.completion_tokens if usage else 0

        span.set_attribute("gen_ai.usage.input_tokens", input_tokens)
        span.set_attribute("gen_ai.usage.output_tokens", output_tokens)
        span.set_attribute("gen_ai.response.finish_reasons", finish)

        LLM_CALLS_TOTAL.labels(model=MODEL, status="success").inc()
        LLM_TOKENS_TOTAL.labels(model=MODEL, type="input").inc(input_tokens)
        LLM_TOKENS_TOTAL.labels(model=MODEL, type="output").inc(output_tokens)
        LLM_DURATION_SECONDS.labels(model=MODEL).observe(elapsed_ms / 1000)

        logger.info(
            "llm_call_finished",
            model=MODEL,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            duration_ms=elapsed_ms,
            finish_reason=finish,
        )

        if finish == "length":
            current = _MAX_TOKENS if _MAX_TOKENS else "无限制"
            logger.warning(
                "llm_output_truncated",
                finish_reason="length",
                max_tokens=str(current),
            )

    return content
