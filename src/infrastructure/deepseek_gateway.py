import os, json, asyncio
try:
    from dotenv import load_dotenv; load_dotenv()
except ImportError:
    pass

from openai import OpenAI  # 同步客户端

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

    resp = client.chat.completions.create(**kwargs)
    finish = resp.choices[0].finish_reason

    if finish == "length":
        current = _MAX_TOKENS if _MAX_TOKENS else "无限制"
        print(
            f"[LLM] WARNING: finish_reason=length — 输出可能被截断。"
            f" 当前 max_tokens={current}。"
            f" 若需更大输出，在 .env 设置 DEEPSEEK_MAX_TOKENS=65536 或更高。"
        )

    return resp.choices[0].message.content or "{}"
