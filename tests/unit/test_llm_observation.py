from __future__ import annotations

from types import SimpleNamespace

import pytest

from src.config import Settings
from src.gateway import deepseek
from tests.support.fakes import FakeOpenAIClient


def _patch_client(monkeypatch: pytest.MonkeyPatch, response_factory):
    client = FakeOpenAIClient(response_factory)

    def fake_openai(**kwargs: object) -> FakeOpenAIClient:
        client.configure(**kwargs)
        return client

    monkeypatch.setattr(deepseek, 'OpenAI', fake_openai)
    return client


def test_ask_llm_observer_receives_tokens_and_latency(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    response = SimpleNamespace(
        choices=[SimpleNamespace(message=SimpleNamespace(content='ok'), finish_reason='stop')],
        usage=SimpleNamespace(prompt_tokens=4, completion_tokens=2),
    )
    _patch_client(monkeypatch, lambda: response)
    records = []

    assert deepseek.ask_llm(
        'prompt',
        Settings(deepseek_api_key='secret'),
        observer=records.append,
    ) == 'ok'

    assert len(records) == 1
    assert records[0].status == 'success'
    assert records[0].input_tokens == 4
    assert records[0].output_tokens == 2
    assert records[0].duration_ms >= 0


def test_ask_llm_observer_receives_failure_classification(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_client(monkeypatch, lambda: (_ for _ in ()).throw(TimeoutError('timeout')))
    records = []

    with pytest.raises(TimeoutError):
        deepseek.ask_llm(
            'prompt',
            Settings(deepseek_api_key='secret'),
            observer=records.append,
        )

    assert len(records) == 1
    assert records[0].status == 'failure'
    assert records[0].failure_type == 'TimeoutError'
