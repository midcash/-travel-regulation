from __future__ import annotations

from evaluation.m2_live_interpreter import _build_live_settings
from src.config import Settings


def test_m2_live_settings_honor_configured_timeout_above_gate_floor() -> None:
    settings = _build_live_settings(
        Settings(deepseek_api_key="secret", llm_timeout_seconds=60.0)
    )

    assert settings.llm_timeout_seconds == 60.0
    assert settings.deepseek_model == "deepseek-v4-flash"
    assert settings.retry_count == 0


def test_m2_live_settings_keep_timeout_floor_for_short_configuration() -> None:
    settings = _build_live_settings(
        Settings(deepseek_api_key="secret", llm_timeout_seconds=10.0)
    )

    assert settings.llm_timeout_seconds == 60.0
