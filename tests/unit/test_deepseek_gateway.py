from __future__ import annotations

from types import SimpleNamespace

import pytest

from src.config import Settings
from src.gateway import deepseek
from tests.support.fakes import FakeOpenAIClient


def _response(content: str | None, *, choices: bool = True) -> object:
    choice_items = []
    if choices:
        choice_items = [
            SimpleNamespace(
                message=SimpleNamespace(content=content),
                finish_reason='stop',
            )
        ]
    return SimpleNamespace(
        choices=choice_items,
        usage=SimpleNamespace(prompt_tokens=7, completion_tokens=3),
    )


def _patch_client(monkeypatch: pytest.MonkeyPatch, response: object) -> FakeOpenAIClient:
    client = FakeOpenAIClient(lambda: response)

    def fake_openai(**kwargs: object) -> FakeOpenAIClient:
        client.configure(**kwargs)
        return client

    monkeypatch.setattr(deepseek, 'OpenAI', fake_openai)
    return client


def test_ask_llm_passes_timeout_and_zero_retries_to_sdk(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = _patch_client(monkeypatch, _response('ok'))
    settings = Settings(
        deepseek_api_key='secret-key',
        deepseek_model='fake-model',
        llm_timeout_seconds=4.5,
        deepseek_max_tokens=128,
    )

    assert deepseek.ask_llm('prompt', settings) == 'ok'
    assert client.constructor_kwargs == {
        'api_key': 'secret-key',
        'base_url': 'https://api.deepseek.com',
        'timeout': 4.5,
        'max_retries': 0,
    }
    assert client.create_kwargs is not None
    assert client.create_kwargs['model'] == 'fake-model'
    assert client.create_kwargs['max_tokens'] == 128


def test_ask_llm_fails_before_sdk_when_key_is_missing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    called = False

    def unexpected_openai(**kwargs: object) -> object:
        nonlocal called
        called = True
        return object()

    monkeypatch.setattr(deepseek, 'OpenAI', unexpected_openai)
    with pytest.raises(RuntimeError, match='DEEPSEEK_API_KEY'):
        deepseek.ask_llm('prompt', Settings())
    assert called is False


@pytest.mark.parametrize(
    'response',
    [_response(None), _response('', choices=True), _response(None, choices=False)],
)
def test_ask_llm_rejects_empty_or_missing_choice(
    response: object,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_client(monkeypatch, response)
    with pytest.raises(deepseek.LLMResponseError):
        deepseek.ask_llm('prompt', Settings(deepseek_api_key='secret'))


def test_ask_llm_propagates_sdk_timeout_without_retry(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = FakeOpenAIClient(lambda: (_ for _ in ()).throw(TimeoutError('timeout')))

    def fake_openai(**kwargs: object) -> FakeOpenAIClient:
        client.configure(**kwargs)
        return client

    monkeypatch.setattr(deepseek, 'OpenAI', fake_openai)
    with pytest.raises(TimeoutError):
        deepseek.ask_llm('prompt', Settings(deepseek_api_key='secret'))
