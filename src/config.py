# M0 strict settings.
from __future__ import annotations

# 配置值
import os
from collections.abc import Mapping
from dataclasses import dataclass, field
from math import isfinite

_LOG_LEVELS = frozenset({'DEBUG', 'INFO', 'WARNING', 'ERROR', 'CRITICAL'})


class ConfigurationError(ValueError):
    # 配置值非法或违反 strict 约束。
    pass


@dataclass(frozen=True, slots=True)
class Settings:
    # M0～M8 使用的 fail-fast 配置。
    strict_mode: bool = True
    retry_count: int = 0
    cache_reads: bool = False
    fallbacks: bool = False
    partial_success: bool = False
    llm_timeout_seconds: float = 30.0
    external_api_timeout_seconds: float = 15.0
    max_revision_rounds: int = 2
    deepseek_api_key: str | None = field(default=None, repr=False)
    deepseek_model: str = 'deepseek-chat'
    deepseek_max_tokens: int | None = None
    amap_api_key: str | None = field(default=None, repr=False)
    tuniu_api_key: str | None = field(default=None, repr=False)
    amap_enabled: bool | None = None
    tuniu_enabled: bool | None = None
    log_level: str = 'INFO'
    console_span_exporter: bool = False

    # M0～M8 strict。
    def __post_init__(self) -> None:
        if not self.strict_mode:
            raise ConfigurationError('STRICT_MODE required')
        if self.retry_count != 0:
            raise ConfigurationError('strict mode requires RETRY_COUNT=0')
        if self.cache_reads:
            raise ConfigurationError('strict mode forbids CACHE_READS')
        if self.fallbacks:
            raise ConfigurationError('strict mode forbids FALLBACKS')
        if self.partial_success:
            raise ConfigurationError('strict mode forbids PARTIAL_SUCCESS')
        if self.retry_count < 0:
            raise ConfigurationError('RETRY_COUNT must not be negative')
        if not isfinite(self.llm_timeout_seconds) or self.llm_timeout_seconds <= 0:
            raise ConfigurationError('LLM_TIMEOUT_SECONDS must be positive')
        if (
            not isfinite(self.external_api_timeout_seconds)
            or self.external_api_timeout_seconds <= 0
        ):
            raise ConfigurationError('EXTERNAL_API_TIMEOUT_SECONDS must be positive')
        if self.max_revision_rounds < 0:
            raise ConfigurationError('MAX_REVISION_ROUNDS must not be negative')
        if self.deepseek_max_tokens is not None and self.deepseek_max_tokens <= 0:
            raise ConfigurationError('DEEPSEEK_MAX_TOKENS must be positive')
        if not self.deepseek_model.strip():
            raise ConfigurationError('DEEPSEEK_MODEL must not be empty')
        if self.amap_enabled is None:
            object.__setattr__(self, 'amap_enabled', _has_value(self.amap_api_key))
        if self.tuniu_enabled is None:
            object.__setattr__(self, 'tuniu_enabled', _has_value(self.tuniu_api_key))
        normalized_log_level = self.log_level.strip().upper()
        object.__setattr__(self, 'log_level', normalized_log_level)
        if normalized_log_level not in _LOG_LEVELS:
            raise ConfigurationError(
                f'LOG_LEVEL must be one of {", ".join(sorted(_LOG_LEVELS))}'
            )

    def validate_runtime(self, *, require_llm: bool = True) -> None:
        "Validate runtime credentials for the active workflow."
        if require_llm and not self.deepseek_api_key:
            raise ConfigurationError('DEEPSEEK_API_KEY is required for the active workflow')


def load_settings(environ: Mapping[str, str] | None = None) -> Settings:
    # 从显式映射或进程环境加载，不读取 .env。
    values = os.environ if environ is None else environ
    return Settings(
        strict_mode=_parse_bool(values.get('STRICT_MODE', 'true'), 'STRICT_MODE'),
        retry_count=_parse_int(values.get('RETRY_COUNT', '0'), 'RETRY_COUNT'),
        cache_reads=_parse_bool(values.get('CACHE_READS', 'false'), 'CACHE_READS'),
        fallbacks=_parse_bool(values.get('FALLBACKS', 'false'), 'FALLBACKS'),
        partial_success=_parse_bool(
            values.get('PARTIAL_SUCCESS', 'false'), 'PARTIAL_SUCCESS'
        ),
        llm_timeout_seconds=_parse_float(
            values.get('LLM_TIMEOUT_SECONDS', '30'), 'LLM_TIMEOUT_SECONDS'
        ),
        external_api_timeout_seconds=_parse_float(
            values.get('EXTERNAL_API_TIMEOUT_SECONDS', '15'),
            'EXTERNAL_API_TIMEOUT_SECONDS',
        ),
        max_revision_rounds=_parse_int(
            values.get('MAX_REVISION_ROUNDS', '2'), 'MAX_REVISION_ROUNDS'
        ),
        deepseek_api_key=_optional(values.get('DEEPSEEK_API_KEY')),
        deepseek_model=values.get('DEEPSEEK_MODEL', 'deepseek-chat').strip(),
        deepseek_max_tokens=_parse_optional_int(
            values.get('DEEPSEEK_MAX_TOKENS'), 'DEEPSEEK_MAX_TOKENS'
        ),
        amap_api_key=_optional(values.get('AMAP_API_KEY')),
        tuniu_api_key=_optional(values.get('TUNIU_API_KEY')),
        amap_enabled=_parse_optional_bool(values.get('AMAP_ENABLED'), 'AMAP_ENABLED'),
        tuniu_enabled=_parse_optional_bool(values.get('TUNIU_ENABLED'), 'TUNIU_ENABLED'),
        log_level=values.get('LOG_LEVEL', 'INFO').strip().upper(),
        console_span_exporter=_parse_bool(
            values.get('CONSOLE_SPAN_EXPORTER', 'false'),
            'CONSOLE_SPAN_EXPORTER',
        ),
    )


def _parse_bool(raw: str, name: str) -> bool:
    normalized = raw.strip().lower()
    if normalized == 'true':
        return True
    if normalized == 'false':
        return False
    raise ConfigurationError(f'{name} must be true or false')


def _parse_int(raw: str, name: str) -> int:
    try:
        return int(raw.strip())
    except ValueError as exc:
        raise ConfigurationError(f'{name} must be an integer') from exc


def _parse_optional_int(raw: str | None, name: str) -> int | None:
    return None if raw is None or not raw.strip() else _parse_int(raw, name)


def _parse_optional_bool(raw: str | None, name: str) -> bool | None:
    return None if raw is None or not raw.strip() else _parse_bool(raw, name)


def _parse_float(raw: str, name: str) -> float:
    try:
        return float(raw.strip())
    except ValueError as exc:
        raise ConfigurationError(f'{name} must be a number') from exc


def _optional(raw: str | None) -> str | None:
    if raw is None:
        return None
    normalized = raw.strip()
    return normalized or None


def _has_value(value: str | None) -> bool:
    return value is not None and bool(value.strip())
