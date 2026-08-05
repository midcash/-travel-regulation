"""LLM 网关的应用层 Port。"""

from __future__ import annotations

from enum import StrEnum
from typing import Protocol, runtime_checkable

from src.config import Settings


class LLMOutputMode(StrEnum):
    """LLM 调用期望的输出契约。"""

    TEXT = "text"
    JSON_OBJECT = "json_object"


@runtime_checkable
class LLMGateway(Protocol):
    """为约束解释等应用服务提供同步 LLM 调用能力。"""

    def complete(
        self,
        prompt: str,
        *,
        settings: Settings,
        output_mode: LLMOutputMode = LLMOutputMode.TEXT,
    ) -> str:
        """提交一个 Prompt 并返回非空文本响应。"""
