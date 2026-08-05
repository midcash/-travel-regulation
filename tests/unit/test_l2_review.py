from __future__ import annotations

import json

import pytest

from src.config import Settings
from src.ports.llm_gateway import LLMOutputMode
from src.review import l2


def _settings() -> Settings:
    return Settings(deepseek_api_key="fake-key")


def test_run_l2_review_parses_pass_response_and_injects_settings(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    seen: list[tuple[Settings, LLMOutputMode]] = []

    def fake_ask(
        prompt: str,
        *,
        settings: Settings,
        output_mode: LLMOutputMode,
    ) -> str:
        seen.append((settings, output_mode))
        return json.dumps({"pass": True, "issues": []})

    monkeypatch.setattr(l2, "ask_llm", fake_ask)
    settings = _settings()

    result = l2.run_l2_review("go to Hangzhou", "budget 2000", [], settings=settings)

    assert result == {"pass": True, "issues": []}
    assert seen == [(settings, LLMOutputMode.JSON_OBJECT)]


@pytest.mark.parametrize(
    ("response", "expected"),
    [
        (
            {"pass": False, "issues": ["missing return transport", "schedule is too dense"]},
            ["missing return transport", "schedule is too dense"],
        ),
        (
            {"pass": False, "issues": ["budget exceeds the stated limit"]},
            ["budget exceeds the stated limit"],
        ),
    ],
)
def test_run_l2_review_parses_structured_issues(
    response: dict[str, object],
    expected: list[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        l2,
        "ask_llm",
        lambda prompt, *, settings, output_mode: json.dumps(response),
    )

    result = l2.run_l2_review("go to Hangzhou", "budget 2000", [], settings=_settings())

    assert result == {"pass": False, "issues": expected}


def test_run_l2_review_rejects_incoherent_pass_payload(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        l2,
        "ask_llm",
        lambda prompt, *, settings, output_mode: json.dumps(
            {"pass": True, "issues": ["unexpected issue"]}
        ),
    )

    with pytest.raises(l2.L2ReviewError, match="JSON contract"):
        l2.run_l2_review("go to Hangzhou", "plan", [], settings=_settings())


def test_run_l2_review_propagates_timeout(monkeypatch: pytest.MonkeyPatch) -> None:
    def fail(
        prompt: str,
        *,
        settings: Settings,
        output_mode: LLMOutputMode,
    ) -> str:
        raise TimeoutError("upstream timeout")

    monkeypatch.setattr(l2, "ask_llm", fail)

    with pytest.raises(TimeoutError):
        l2.run_l2_review("go to Hangzhou", "budget 2000", [], settings=_settings())
