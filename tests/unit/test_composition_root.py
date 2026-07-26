from __future__ import annotations

import pytest

from src.bootstrap import bootstrap_settings
from src.config import ConfigurationError


def test_bootstrap_settings_rejects_missing_llm_key_before_workflow() -> None:
    with pytest.raises(ConfigurationError, match='DEEPSEEK_API_KEY'):
        bootstrap_settings({})


def test_bootstrap_settings_returns_validated_single_instance() -> None:
    settings = bootstrap_settings(
        {
            'DEEPSEEK_API_KEY': 'test-key',
            'DEEPSEEK_MODEL': 'test-model',
        }
    )

    assert settings.deepseek_api_key == 'test-key'
    assert settings.deepseek_model == 'test-model'
    assert settings.strict_mode is True
