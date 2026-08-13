"""LLM 网关的应用层 Port。"""

from __future__ import annotations

from enum import StrEnum
from typing import Protocol, runtime_checkable

from src.config import Settings


class LLMOutputMode(StrEnum):
    """LLM 调用期望的输出契约。"""

    TEXT = "text"
    JSON_OBJECT = "json_object"


class LLMResponseError(RuntimeError):
    """LLM 响应违反输出契约时携带的安全元数据。"""

    def __init__(
        self,
        message: str,
        *,
        cause_code: str = "LLM_RESPONSE_INVALID",
        finish_reason: str | None = None,
        model: str | None = None,
        max_tokens: int | None = None,
        input_tokens: int = 0,
        output_tokens: int = 0,
    ) -> None:
        self.cause_code = cause_code
        self.finish_reason = finish_reason
        self.model = model
        self.max_tokens = max_tokens
        self.input_tokens = input_tokens
        self.output_tokens = output_tokens
        super().__init__(message)


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
