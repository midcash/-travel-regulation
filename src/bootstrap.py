"""M0 composition root.

The composition root loads and validates runtime configuration before the
request enters the planning workflow.
"""
from __future__ import annotations

from collections.abc import Mapping

import httpx

from src.config import Settings, load_settings
from src.infrastructure.tools.amap import create_amap_bindings
from src.infrastructure.tools.assembly import (
    AdapterFactory,
    ToolProviderAssembly,
    assemble_tool_providers,
)
from src.infrastructure.tools.tuniu import create_tuniu_bindings


def bootstrap_settings(environ: Mapping[str, str] | None = None) -> Settings:
    """Create and validate the single Settings instance for a request.

    Args:
        environ: Optional explicit environment mapping used by tests.

    Returns:
        Settings: Strict settings with the active workflow credentials checked.

    Raises:
        ConfigurationError: If settings are invalid or the LLM key is missing.
    """
    settings = load_settings(environ)
    settings.validate_runtime(require_llm=True)
    return settings


def bootstrap_tool_providers(
    environ: Mapping[str, str] | None = None,
    *,
    amap_factory: AdapterFactory | None = None,
    tuniu_factory: AdapterFactory | None = None,
    http_client: httpx.AsyncClient | None = None,
) -> ToolProviderAssembly:
    """Load one validated Settings snapshot and assemble configured providers.

    Args:
        environ: Optional explicit environment mapping used by tests or a caller.
        amap_factory: Explicit factory for the enabled Amap adapter.
        tuniu_factory: Explicit factory for the enabled Tuniu adapter.
        http_client: Optional shared client for the active adapters.

    Returns:
        ToolProviderAssembly: Shared settings/client and capability bindings.

    Raises:
        ConfigurationError: If the active workflow lacks the LLM credential.
        ToolConfigurationError: If an enabled tool cannot be assembled.
    """
    settings = bootstrap_settings(environ)
    resolved_amap_factory = amap_factory or create_amap_bindings
    resolved_tuniu_factory = tuniu_factory or create_tuniu_bindings
    return assemble_tool_providers(
        settings,
        amap_factory=resolved_amap_factory,
        tuniu_factory=resolved_tuniu_factory,
        http_client=http_client,
    )
