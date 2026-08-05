from __future__ import annotations

import pytest

from src.config import ConfigurationError, Settings, load_settings


def test_load_settings_defaults_to_strict_fail_fast() -> None:
    settings = load_settings({})

    assert settings.strict_mode is True
    assert settings.retry_count == 0
    assert settings.cache_reads is False
    assert settings.fallbacks is False
    assert settings.partial_success is False
    assert settings.max_revision_rounds == 2
    assert settings.deepseek_max_tokens == 2048
    assert settings.amap_geocode_url.startswith('https://')
    assert settings.tuniu_hotel_url.startswith('https://')


@pytest.mark.parametrize(
    'name,value',
    [
        ('STRICT_MODE', 'maybe'),
        ('CACHE_READS', 'yes'),
        ('FALLBACKS', '1'),
        ('PARTIAL_SUCCESS', 'enabled'),
    ],
)
def test_load_settings_rejects_invalid_boolean(name: str, value: str) -> None:
    with pytest.raises(ConfigurationError):
        load_settings({name: value})


@pytest.mark.parametrize(
    'field',
    ['retry_count', 'cache_reads', 'fallbacks', 'partial_success'],
)
def test_settings_rejects_non_strict_features(field: str) -> None:
    with pytest.raises(ConfigurationError):
        Settings(**{field: 1 if field == 'retry_count' else True})


@pytest.mark.parametrize(
    'environ',
    [
        {'LLM_TIMEOUT_SECONDS': '0'},
        {'LLM_TIMEOUT_SECONDS': 'nan'},
        {'EXTERNAL_API_TIMEOUT_SECONDS': '-1'},
        {'MAX_REVISION_ROUNDS': '-1'},
        {'DEEPSEEK_MAX_TOKENS': '0'},
        {'DEEPSEEK_MODEL': '   '},
        {'AMAP_GEOCODE_URL': 'not-an-url'},
        {'TUNIU_HOTEL_URL': 'ftp://provider.example/hotel'},
    ],
)
def test_load_settings_rejects_invalid_numeric_or_model_values(
    environ: dict[str, str],
) -> None:
    with pytest.raises(ConfigurationError):
        load_settings(environ)


def test_load_settings_strips_optional_secrets_without_logging_them() -> None:
    settings = load_settings(
        {
            'DEEPSEEK_API_KEY': '  secret-value  ',
            'AMAP_API_KEY': ' ',
            'DEEPSEEK_MODEL': 'deepseek-test',
        }
    )

    assert settings.deepseek_api_key == 'secret-value'
    assert settings.amap_api_key is None
    assert settings.deepseek_model == 'deepseek-test'


def test_load_settings_injects_tool_endpoints_from_one_snapshot() -> None:
    settings = load_settings(
        {
            'AMAP_GEOCODE_URL': 'https://mock.example/amap',
            'TUNIU_HOTEL_URL': 'https://mock.example/hotel',
            'TUNIU_FLIGHT_URL': 'https://mock.example/flight',
            'TUNIU_TICKET_URL': 'https://mock.example/ticket',
        }
    )

    assert settings.amap_geocode_url == 'https://mock.example/amap'
    assert settings.tuniu_hotel_url == 'https://mock.example/hotel'
    assert settings.tuniu_flight_url == 'https://mock.example/flight'
    assert settings.tuniu_ticket_url == 'https://mock.example/ticket'
