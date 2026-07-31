"""Composition-root wiring for external travel tool adapters."""

from __future__ import annotations

from src.infrastructure.tools.assembly import (
    AdapterFactory,
    ProviderBindings,
    ToolProviderAssembly,
    assemble_tool_providers,
)

__all__ = [
    "AdapterFactory",
    "ProviderBindings",
    "ToolProviderAssembly",
    "assemble_tool_providers",
]
