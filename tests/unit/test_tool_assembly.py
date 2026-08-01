from __future__ import annotations

from collections.abc import Callable

import httpx
import pytest

from src.bootstrap import bootstrap_tool_providers
from src.config import ConfigurationError, Settings, load_settings
from src.infrastructure.tools.amap import AmapGeoProvider
from src.infrastructure.tools.assembly import (
    ProviderBindings,
    ToolProviderAssembly,
    assemble_tool_providers,
)
from src.ports.tool_errors import ToolConfigurationError
from src.ports.tool_provider import GeoProvider
from tests.support.provider_fakes import FakeGeoProvider


def _geo_factory(
    seen: list[tuple[Settings, httpx.AsyncClient]],
) -> Callable[[Settings, httpx.AsyncClient], ProviderBindings]:
    def factory(settings: Settings, client: httpx.AsyncClient) -> ProviderBindings:
        seen.append((settings, client))
        return ProviderBindings(provider="amap", geo=FakeGeoProvider())

    return factory


def test_assembly_injects_one_settings_snapshot_and_shared_client() -> None:
    settings = Settings(
        deepseek_api_key="llm-key",
        amap_api_key="amap-key",
        amap_enabled=True,
    )
    seen: list[tuple[Settings, httpx.AsyncClient]] = []
    client = httpx.AsyncClient()

    assembly = assemble_tool_providers(
        settings,
        amap_factory=_geo_factory(seen),
        http_client=client,
    )

    assert isinstance(assembly, ToolProviderAssembly)
    assert assembly.settings is settings
    assert assembly.http_client is client
    assert assembly.amap is not None
    assert assembly.geo is assembly.amap.geo
    assert isinstance(assembly.geo, GeoProvider)
    assert seen == [(settings, client)]


def test_disabled_provider_is_not_created_or_requires_a_key() -> None:
    settings = Settings(deepseek_api_key="llm-key", amap_enabled=False)
    called = False

    def factory(_: Settings, __: httpx.AsyncClient) -> ProviderBindings:
        nonlocal called
        called = True
        raise AssertionError("disabled provider factory must not be called")

    assembly = assemble_tool_providers(settings, amap_factory=factory)

    assert assembly.amap is None
    assert assembly.http_client is None
    assert called is False


def test_enabled_provider_without_key_fails_during_assembly() -> None:
    settings = Settings(
        deepseek_api_key="llm-key",
        amap_enabled=True,
    )

    with pytest.raises(ToolConfigurationError) as raised:
        assemble_tool_providers(settings, amap_factory=_geo_factory([]))

    assert raised.value.code == "TOOL_CONFIGURATION_ERROR"
    assert raised.value.provider == "amap"
    assert "key" not in str(raised.value).lower()


def test_enabled_provider_without_explicit_factory_fails_without_network() -> None:
    settings = Settings(
        deepseek_api_key="llm-key",
        amap_api_key="amap-key",
        amap_enabled=True,
    )

    with pytest.raises(ToolConfigurationError, match="factory"):
        assemble_tool_providers(settings)


def test_assembly_rejects_two_providers_for_the_same_capability() -> None:
    settings = Settings(
        deepseek_api_key="llm-key",
        amap_api_key="amap-key",
        tuniu_api_key="tuniu-key",
        amap_enabled=True,
        tuniu_enabled=True,
    )
    client = httpx.AsyncClient()

    def tuniu_factory(_: Settings, __: httpx.AsyncClient) -> ProviderBindings:
        return ProviderBindings(provider="tuniu", geo=FakeGeoProvider())

    with pytest.raises(ToolConfigurationError, match="multiple providers"):
        assemble_tool_providers(
            settings,
            amap_factory=_geo_factory([]),
            tuniu_factory=tuniu_factory,
            http_client=client,
        )


def test_bootstrap_tool_providers_loads_settings_before_assembly() -> None:
    seen: list[tuple[Settings, httpx.AsyncClient]] = []
    client = httpx.AsyncClient()

    assembly = bootstrap_tool_providers(
        {
            "DEEPSEEK_API_KEY": "llm-key",
            "AMAP_API_KEY": "amap-key",
            "AMAP_ENABLED": "true",
        },
        amap_factory=_geo_factory(seen),
        http_client=client,
    )

    assert assembly.settings.deepseek_api_key == "llm-key"
    assert assembly.settings.amap_api_key == "amap-key"
    assert assembly.settings.amap_enabled is True
    assert seen[0][0] is assembly.settings
    assert seen[0][1] is client


def test_bootstrap_tool_providers_defaults_to_real_enabled_adapter_factory() -> None:
    client = httpx.AsyncClient(transport=httpx.MockTransport(_unexpected_request))
    assembly = bootstrap_tool_providers(
        {
            "DEEPSEEK_API_KEY": "llm-key",
            "AMAP_API_KEY": "amap-key",
            "AMAP_ENABLED": "true",
        },
        http_client=client,
    )

    assert isinstance(assembly.geo, AmapGeoProvider)
    assert assembly.settings.amap_geocode_url.startswith("https://")


async def _unexpected_request(_: httpx.Request) -> httpx.Response:
    raise AssertionError("default adapter factory test must not issue a network request")


def test_settings_infers_provider_enablement_from_key_unless_explicitly_disabled() -> None:
    inferred = Settings(amap_api_key="amap-key")
    disabled = Settings(amap_api_key="amap-key", amap_enabled=False)

    assert inferred.amap_enabled is True
    assert disabled.amap_enabled is False


@pytest.mark.parametrize("name", ["AMAP_ENABLED", "TUNIU_ENABLED"])
def test_settings_rejects_invalid_provider_enablement(name: str) -> None:
    with pytest.raises(ConfigurationError):
        load_settings({name: "sometimes"})
