from __future__ import annotations

import pytest

from src.config import Settings
from src.review import l2


def _settings() -> Settings:
    return Settings(deepseek_api_key='fake-key')


def test_run_l2_review_parses_pass_response_and_injects_settings(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    seen: list[Settings] = []

    def fake_ask(prompt: str, settings: Settings) -> str:
        seen.append(settings)
        return 'PASS'

    monkeypatch.setattr(l2, 'ask_llm', fake_ask)
    settings = _settings()

    result = l2.run_l2_review('去杭州', '预算 2000 元', [], settings=settings)

    assert result == {'pass': True, 'issues': []}
    assert seen == [settings]


@pytest.mark.parametrize(
    'response,expected',
    [
        ('1. 缺少返程交通\n2. 行程过密', ['缺少返程交通', '行程过密']),
        ('- 缺少酒店证据\n- 缺少备选', ['缺少酒店证据', '缺少备选']),
        (
            '方案需要补充当地交通说明，并且需要检查返程时间与酒店位置。',
            ['方案需要补充当地交通说明，并且需要检查返程时间与酒店位置。'],
        ),
    ],
)
def test_run_l2_review_parses_issue_formats(
    response: str,
    expected: list[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(l2, 'ask_llm', lambda prompt, settings: response)

    result = l2.run_l2_review('去杭州', '预算 2000 元', [], settings=_settings())

    assert result == {'pass': False, 'issues': expected}


def test_run_l2_review_propagates_timeout(monkeypatch: pytest.MonkeyPatch) -> None:
    def fail(prompt: str, settings: Settings) -> str:
        raise TimeoutError('upstream timeout')

    monkeypatch.setattr(l2, 'ask_llm', fail)

    with pytest.raises(TimeoutError):
        l2.run_l2_review('去杭州', '预算 2000 元', [], settings=_settings())
