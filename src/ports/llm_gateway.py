"""LLM 网关的应用层 Port。"""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from src.config import Settings


@runtime_checkable
class LLMGateway(Protocol):
    """为约束解释等应用服务提供同步 LLM 调用能力。"""

    def complete(self, prompt: str, *, settings: Settings) -> str:
        """提交一个 Prompt 并返回非空文本响应。"""

