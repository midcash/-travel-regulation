"""Fail-fast assembly of configured M3 tool adapters."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import cast

import httpx

from src.config import Settings
from src.ports.tool_errors import ToolConfigurationError
from src.ports.tool_provider import (
    ContextProvider,
    GeoProvider,
    PlaceProvider,
    StayProvider,
    TransportProvider,
)

_PROVIDER_NAMES = ("amap", "tuniu")
_CAPABILITY_NAMES = ("geo", "transport", "stay", "place", "context")


@dataclass(frozen=True, slots=True)
class ProviderBindings:
    """Typed capabilities exposed by one provider adapter."""

    provider: str
    geo: GeoProvider | None = None
    transport: TransportProvider | None = None
    stay: StayProvider | None = None
    place: PlaceProvider | None = None
    context: ContextProvider | None = None

    def __post_init__(self) -> None:
        if self.provider not in _PROVIDER_NAMES:
            raise ValueError(f"unsupported provider: {self.provider}")
        if not self.capabilities:
            raise ValueError("provider adapter must expose at least one capability")

    @property
    def capabilities(self) -> tuple[str, ...]:
        """Return the non-empty capability names in stable order."""
        return tuple(name for name in _CAPABILITY_NAMES if getattr(self, name) is not None)


AdapterFactory = Callable[[Settings, httpx.AsyncClient], ProviderBindings]


@dataclass(frozen=True, slots=True)
class ToolProviderAssembly:
    """Immutable provider bindings created for one Settings/client snapshot."""

    settings: Settings
    http_client: httpx.AsyncClient | None
    amap: ProviderBindings | None = None
    tuniu: ProviderBindings | None = None
    owns_http_client: bool = False

    @property
    def providers(self) -> tuple[ProviderBindings, ...]:
        """Return configured providers without creating a fallback."""
        return tuple(provider for provider in (self.amap, self.tuniu) if provider is not None)

    def capability(self, name: str) -> object | None:
        """Return a uniquely bound capability, or ``None`` when unavailable."""
        if name not in _CAPABILITY_NAMES:
            raise ValueError(f"unsupported capability: {name}")
        for binding in self.providers:
            value = cast(object | None, getattr(binding, name))
            if value is not None:
                return value
        return None

    @property
    def geo(self) -> GeoProvider | None:
        """Return the assembled geographic provider, if configured."""
        return self.capability("geo")  # type: ignore[return-value]

    @property
    def transport(self) -> TransportProvider | None:
        """Return the assembled transport provider, if configured."""
        return self.capability("transport")  # type: ignore[return-value]

    @property
    def stay(self) -> StayProvider | None:
        """Return the assembled stay provider, if configured."""
        return self.capability("stay")  # type: ignore[return-value]

    @property
    def place(self) -> PlaceProvider | None:
        """Return the assembled place provider, if configured."""
        return self.capability("place")  # type: ignore[return-value]

    @property
    def context(self) -> ContextProvider | None:
        """Return the assembled context provider, if configured."""
        return self.capability("context")  # type: ignore[return-value]

    async def aclose(self) -> None:
        """Close a client created by this assembly."""
        if self.owns_http_client and self.http_client is not None:
            await self.http_client.aclose()


def assemble_tool_providers(
    settings: Settings,
    *,
    amap_factory: AdapterFactory | None = None,
    tuniu_factory: AdapterFactory | None = None,
    http_client: httpx.AsyncClient | None = None,
) -> ToolProviderAssembly:
    """Assemble enabled adapters from one validated Settings snapshot.

    The factories are intentionally explicit. This function never creates a Fake,
    reads the process environment, retries, or performs a provider request.

    Args:
        settings: Immutable configuration snapshot supplied by the composition root.
        amap_factory: Factory for the enabled Amap adapter.
        tuniu_factory: Factory for the enabled Tuniu adapter.
        http_client: Optional shared client. A client is created only when a provider
            is enabled and a caller did not inject one.

    Returns:
        ToolProviderAssembly: Configured provider bindings and shared dependencies.

    Raises:
        ToolConfigurationError: If an enabled provider lacks a key/factory or if
            multiple providers bind the same capability.
    """
    if not isinstance(settings, Settings):
        raise TypeError("settings must be a Settings instance")

    active = _active_provider_names(settings)
    _validate_active_configuration(settings, active, amap_factory, tuniu_factory)
    if not active:
        return ToolProviderAssembly(settings=settings, http_client=http_client)

    owns_http_client = http_client is None
    shared_client = http_client or httpx.AsyncClient(
        timeout=settings.external_api_timeout_seconds,
    )
    bindings: dict[str, ProviderBindings] = {}
    for provider_name, factory in (("amap", amap_factory), ("tuniu", tuniu_factory)):
        if provider_name not in active:
            continue
        assert factory is not None
        binding = factory(settings, shared_client)
        if not isinstance(binding, ProviderBindings):
            raise TypeError(f"{provider_name} adapter factory must return ProviderBindings")
        if binding.provider != provider_name:
            raise ToolConfigurationError(
                provider=provider_name,
                operation="assembly",
                safe_message="provider adapter identity does not match its configuration",
            )
        bindings[provider_name] = binding

    _reject_duplicate_capabilities(bindings)
    return ToolProviderAssembly(
        settings=settings,
        http_client=shared_client,
        amap=bindings.get("amap"),
        tuniu=bindings.get("tuniu"),
        owns_http_client=owns_http_client,
    )


def _active_provider_names(settings: Settings) -> tuple[str, ...]:
    return tuple(
        name
        for name, enabled in (
            ("amap", settings.amap_enabled),
            ("tuniu", settings.tuniu_enabled),
        )
        if enabled
    )


def _validate_active_configuration(
    settings: Settings,
    active: tuple[str, ...],
    amap_factory: AdapterFactory | None,
    tuniu_factory: AdapterFactory | None,
) -> None:
    factories = {"amap": amap_factory, "tuniu": tuniu_factory}
    keys = {"amap": settings.amap_api_key, "tuniu": settings.tuniu_api_key}
    for provider_name in active:
        if not keys[provider_name]:
            raise ToolConfigurationError(
                provider=provider_name,
                operation="assembly",
                safe_message="enabled provider is missing its required credential",
            )
        if factories[provider_name] is None:
            raise ToolConfigurationError(
                provider=provider_name,
                operation="assembly",
                safe_message="enabled provider has no explicit adapter factory",
            )


def _reject_duplicate_capabilities(bindings: dict[str, ProviderBindings]) -> None:
    owners: dict[str, str] = {}
    for binding in bindings.values():
        for capability in binding.capabilities:
            previous = owners.get(capability)
            if previous is not None:
                raise ToolConfigurationError(
                    provider="assembly",
                    operation="bind",
                    safe_message=(
                        f"capability {capability} is configured by multiple providers"
                    ),
                )
            owners[capability] = binding.provider
