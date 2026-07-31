"""Composition-root wiring for external travel tool adapters."""

from __future__ import annotations

from src.infrastructure.tools.amap import AmapGeoProvider, create_amap_bindings
from src.infrastructure.tools.assembly import (
    AdapterFactory,
    ProviderBindings,
    ToolProviderAssembly,
    assemble_tool_providers,
)
from src.infrastructure.tools.tuniu import TuniuTravelProvider, create_tuniu_bindings

__all__ = [
    "AdapterFactory",
    "AmapGeoProvider",
    "ProviderBindings",
    "ToolProviderAssembly",
    "TuniuTravelProvider",
    "assemble_tool_providers",
    "create_amap_bindings",
    "create_tuniu_bindings",
]
