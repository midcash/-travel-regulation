"""M0 composition root.

The composition root loads and validates runtime configuration before the
request enters the planning workflow.
"""
from __future__ import annotations

from collections.abc import Mapping

from src.config import Settings, load_settings


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
