from __future__ import annotations

import pytest

import main
from src.config import Settings


@pytest.fixture(autouse=True)
def fake_bootstrap_settings(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(main, 'bootstrap_settings', lambda: Settings(deepseek_api_key='fake-key'))


def test_cli_without_arguments_uses_default_input(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    seen: list[str] = []

    def fake_plan(user_input: str, *, settings: Settings) -> dict[str, object]:
        seen.append(user_input)
        return {'plan': 'fake plan', 'rounds': 1, 'issues_found': []}

    monkeypatch.setattr(main, 'plan', fake_plan)
    monkeypatch.setattr(main, '_print_result', lambda result: None)

    assert main.main([]) == 0
    assert len(seen) == 1
    assert '深圳' in seen[0]


def test_cli_with_arguments_joins_user_input(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    seen: list[str] = []

    def fake_plan(user_input: str, *, settings: Settings) -> dict[str, object]:
        seen.append(user_input)
        return {'plan': 'fake plan', 'rounds': 1, 'issues_found': []}

    monkeypatch.setattr(main, 'plan', fake_plan)
    monkeypatch.setattr(main, '_print_result', lambda result: None)

    assert main.main(['去', '广州', '两天']) == 0
    assert seen == ['去 广州 两天']


def test_cli_internal_exception_returns_failure_without_traceback(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    def fail(user_input: str, *, settings: Settings) -> dict[str, object]:
        raise RuntimeError('secret-key must not be logged')

    monkeypatch.setattr(main, 'plan', fail)

    assert main.main(['去深圳']) == 1
    output = capsys.readouterr().out
    assert 'plan_failed' in output
    assert 'secret-key' not in output
