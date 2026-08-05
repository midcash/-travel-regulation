"""DeepSeek 网关到应用层 LLMGateway Port 的适配器。"""

from __future__ import annotations

from src.config import Settings
from src.gateway import deepseek
from src.ports.llm_gateway import LLMOutputMode


class DeepSeekLLMGateway:
    """将现有 DeepSeek 函数式网关适配到应用层 Port。"""

    def complete(
        self,
        prompt: str,
        *,
        settings: Settings,
        output_mode: LLMOutputMode = LLMOutputMode.TEXT,
    ) -> str:
        """调用 DeepSeek 网关，不改变现有错误传播和可观测行为。"""
        return deepseek.ask_llm(prompt, settings, output_mode=output_mode)
