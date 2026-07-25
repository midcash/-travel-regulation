"""
JSON 工具 — LLM 输出的 JSON 清洗。

消除 planner/reviewer/knowledge/orchestrator 中的重复 _sanitize_json 定义。

依赖: 无（纯标准库）
"""
from __future__ import annotations

import re


def sanitize_json(raw: str) -> str:
    """从 LLM 原始输出中提取纯 JSON 字符串。

    处理常见的 LLM 输出包装格式：
    - ```json ... ``` 代码块
    - ``` ... ``` 无语言标记的代码块
    - 前后多余文本

    Args:
        raw: LLM 原始输出文本。

    Returns:
        提取后的纯 JSON 字符串。
    """
    raw = raw.strip()
    raw = re.sub(r"^```(?:json)?\s*", "", raw)
    raw = re.sub(r"\s*```$", "", raw)
    start = raw.find("{")
    end = raw.rfind("}")
    if start != -1 and end != -1 and end > start:
        raw = raw[start:end + 1]
    return raw
