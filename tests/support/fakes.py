from __future__ import annotations

from collections.abc import Callable


class FakeNotConfiguredError(RuntimeError):
    pass


class FakeLLM:
    def __init__(self, responses: list[str | BaseException] | None = None) -> None:
        self._responses = list(responses or [])
        self.calls: list[tuple[str, object | None]] = []

    def __call__(self, prompt: str, settings: object | None = None) -> str:
        self.calls.append((prompt, settings))
        if not self._responses:
            raise FakeNotConfiguredError('Fake LLM 未配置响应')
        response = self._responses.pop(0)
        if isinstance(response, BaseException):
            raise response
        return response


class FakeHTTPResponse:
    def __init__(self, body: bytes) -> None:
        self.body = body

    def read(self) -> bytes:
        return self.body


class FakeOpenAIClient:
    def __init__(self, response_factory: Callable[[], object]) -> None:
        self.response_factory = response_factory
        self.constructor_kwargs: dict[str, object] | None = None
        self.create_kwargs: dict[str, object] | None = None
        self.chat = self
        self.completions = self

    def configure(self, **kwargs: object) -> None:
        self.constructor_kwargs = kwargs

    def create(self, **kwargs: object) -> object:
        self.create_kwargs = kwargs
        return self.response_factory()
