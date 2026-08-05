from __future__ import annotations

import pytest

from src.config import Settings
from src.gateway import deepseek
from src.gateway.deepseek_adapter import DeepSeekLLMGateway
from src.ports.llm_gateway import LLMGateway, LLMOutputMode
from tests.support.llm_fakes import FakeLLMGateway, FakeNotConfiguredError


def test_fake_llm_gateway_implements_port_and_returns_explicit_responses() -> None:
    settings = Settings(deepseek_api_key="test-key")
    gateway = FakeLLMGateway(["first", "second"])

    assert isinstance(gateway, LLMGateway)
    assert gateway.complete("prompt-1", settings=settings) == "first"
    assert gateway.complete("prompt-2", settings=settings) == "second"
    assert gateway.calls == [
        ("prompt-1", settings, LLMOutputMode.TEXT),
        ("prompt-2", settings, LLMOutputMode.TEXT),
    ]


def test_fake_llm_gateway_fails_when_response_is_not_configured() -> None:
    gateway = FakeLLMGateway()
    settings = Settings(deepseek_api_key="test-key")

    with pytest.raises(FakeNotConfiguredError):
        gateway.complete("prompt", settings=settings)


def test_fake_llm_gateway_propagates_injected_failure() -> None:
    gateway = FakeLLMGateway([TimeoutError("upstream timeout")])
    settings = Settings(deepseek_api_key="test-key")

    with pytest.raises(TimeoutError, match="upstream timeout"):
        gateway.complete("prompt", settings=settings)


def test_deepseek_gateway_adapter_implements_port_and_delegates(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[tuple[str, Settings, LLMOutputMode]] = []

    def fake_ask_llm(
        prompt: str,
        settings: Settings,
        *,
        output_mode: LLMOutputMode,
    ) -> str:
        calls.append((prompt, settings, output_mode))
        return "response"

    monkeypatch.setattr(deepseek, "ask_llm", fake_ask_llm)
    settings = Settings(deepseek_api_key="test-key")
    gateway = DeepSeekLLMGateway()

    assert isinstance(gateway, LLMGateway)
    assert gateway.complete("prompt", settings=settings) == "response"
    assert calls == [("prompt", settings, LLMOutputMode.TEXT)]


def test_deepseek_gateway_adapter_delegates_structured_output_mode(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[LLMOutputMode] = []

    def fake_ask_llm(
        prompt: str,
        settings: Settings,
        *,
        output_mode: LLMOutputMode,
    ) -> str:
        calls.append(output_mode)
        return "{}"

    monkeypatch.setattr(deepseek, "ask_llm", fake_ask_llm)
    gateway = DeepSeekLLMGateway()

    assert gateway.complete(
        "prompt",
        settings=Settings(deepseek_api_key="test-key"),
        output_mode=LLMOutputMode.JSON_OBJECT,
    ) == "{}"
    assert calls == [LLMOutputMode.JSON_OBJECT]
