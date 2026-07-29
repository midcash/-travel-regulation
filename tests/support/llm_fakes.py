"""M2 LLMGateway 的离线测试 Fake。"""

from __future__ import annotations

from src.config import Settings


class FakeNotConfiguredError(RuntimeError):
    """Fake 未提供足够的显式响应。"""


class FakeLLMGateway:
    """显式注入响应的 LLM Fake；未配置响应时 fail-fast。"""

    def __init__(self, responses: list[str | BaseException] | None = None) -> None:
        self._responses = list(responses or [])
        self.calls: list[tuple[str, Settings]] = []

    def complete(self, prompt: str, *, settings: Settings) -> str:
        """返回下一个显式响应，或传播显式注入的异常。"""
        self.calls.append((prompt, settings))
        if not self._responses:
            raise FakeNotConfiguredError("Fake LLM 未配置响应")
        response = self._responses.pop(0)
        if isinstance(response, BaseException):
            raise response
        return response
