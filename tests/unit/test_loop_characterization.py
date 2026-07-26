from __future__ import annotations

import pytest

from src.config import Settings
from src.engine import loop
from tests.support.fakes import FakeLLM


def _settings() -> Settings:
    return Settings(deepseek_api_key='fake-key')


def test_plan_initial_generation_and_review_success(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake = FakeLLM(['预算 2000 元，总费用 1200 元'])
    monkeypatch.setattr(loop, 'ask_llm', fake)
    monkeypatch.setattr(loop, 'run_l2_review', lambda *args, **kwargs: {'pass': True, 'issues': []})

    result = loop.plan('去深圳，预算2000元', settings=_settings())

    assert result['plan'] == '预算 2000 元，总费用 1200 元'
    assert result['rounds'] == 1
    assert result['issues_found'] == []
    assert len(fake.calls) == 1
    assert fake.calls[0][1] == _settings()


def test_plan_revises_after_l1_budget_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake = FakeLLM(['预算 2000 元，总费用 2300 元', '预算 2000 元，总费用 1500 元'])
    monkeypatch.setattr(loop, 'ask_llm', fake)
    monkeypatch.setattr(loop, 'run_l2_review', lambda *args, **kwargs: {'pass': True, 'issues': []})

    result = loop.plan('去深圳，预算2000元', settings=_settings())

    assert result['plan'] == '预算 2000 元，总费用 1500 元'
    assert result['rounds'] == 2
    assert any('预算超支' in issue for issue in result['issues_found'])
    assert len(fake.calls) == 2


def test_plan_exhaustion_is_explicit_failure_not_partial_success(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake = FakeLLM(['预算 2000 元，总费用 2300 元'])
    monkeypatch.setattr(loop, 'ask_llm', fake)
    monkeypatch.setattr(loop, 'run_l2_review', lambda *args, **kwargs: {'pass': True, 'issues': []})

    with pytest.raises(loop.PlanningError) as caught:
        loop.plan('去深圳，预算2000元', max_rounds=0, settings=_settings())

    assert caught.value.stage == 'revision'
    assert caught.value.retryable is False
    assert len(fake.calls) == 1


def test_plan_wraps_llm_exception_with_generation_stage(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake = FakeLLM([TimeoutError('upstream timeout')])
    monkeypatch.setattr(loop, 'ask_llm', fake)

    with pytest.raises(loop.PlanningError) as caught:
        loop.plan('去深圳', settings=_settings())

    assert caught.value.stage == 'generation'
    assert isinstance(caught.value.__cause__, TimeoutError)


def test_plan_rejects_invalid_review_shape(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(loop, 'ask_llm', FakeLLM(['预算 2000 元，总费用 1200 元']))
    monkeypatch.setattr(loop, 'run_l2_review', lambda *args, **kwargs: {'issues': []})

    with pytest.raises(loop.PlanningError) as caught:
        loop.plan('去深圳', settings=_settings())

    assert caught.value.stage == 'review'
