"""LLM JSON 文本的清洗与严格解析。"""

from __future__ import annotations

import json
import re
from typing import TypeAlias

JsonScalar: TypeAlias = str | int | float | bool | None
JsonValue: TypeAlias = JsonScalar | list["JsonValue"] | dict[str, "JsonValue"]


class JsonResponseError(ValueError):
    """LLM JSON 响应为空、非法或顶层类型错误。"""


def sanitize_json(raw: str) -> str:
    """从 LLM 原始输出中提取 JSON 字符串。

    Args:
        raw: LLM 原始输出文本。

    Returns:
        str: 去除 Markdown 包装和前后说明的字符串；空输入返回空字符串。
    """
    cleaned = raw.strip()
    cleaned = re.sub(r"^```(?:json)?\s*", "", cleaned)
    cleaned = re.sub(r"\s*```$", "", cleaned)
    start = cleaned.find("{")
    end = cleaned.rfind("}")
    if start != -1 and end != -1 and end > start:
        cleaned = cleaned[start : end + 1]
    return cleaned


def parse_json_object(raw: str) -> dict[str, JsonValue]:
    """严格解析顶层 JSON object。

    Args:
        raw: 可能带 Markdown 包装的模型响应。

    Returns:
        dict[str, JsonValue]: 已解析的 JSON object。

    Raises:
        JsonResponseError: 响应为空、JSON 非法或顶层不是 object。
    """
    cleaned = sanitize_json(raw)
    if not cleaned:
        raise JsonResponseError("JSON 响应为空")
    try:
        value: JsonValue = json.loads(cleaned)
    except json.JSONDecodeError as exc:
        raise JsonResponseError("JSON 响应解析失败") from exc
    if not isinstance(value, dict):
        raise JsonResponseError("JSON 顶层必须是 object")
    return value