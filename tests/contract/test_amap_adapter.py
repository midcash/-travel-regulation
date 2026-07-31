"""Offline contract tests for the M3 Amap Geo adapter."""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

import httpx
import pytest

from src.config import Settings
from src.domain.models.provider import GeoProviderResult, GeoQuery
from src.infrastructure.tools.amap import (
    AMAP_GEOCODE_URL,
    MAX_RESPONSE_BYTES,
    AmapGeoProvider,
    create_amap_bindings,
)
from src.ports.tool_errors import (
    ToolAuthenticationError,
    ToolBusinessError,
    ToolConfigurationError,
    ToolEmptyResultError,
    ToolRateLimitError,
    ToolResponseSchemaError,
    ToolTimeoutError,
    ToolTransportError,
)
from src.ports.tool_provider import GeoProvider
from tests.support.clock_fakes import FakeClock

pytestmark = pytest.mark.contract

_TEST_KEY = "test-amap-key"


def _query() -> GeoQuery:
    return GeoQuery(
        query_id="geo-query-1",
        trace_id="trace-1",
        text="深圳市南山区科技园",
        region="深圳",
    )


def _success_payload(**geocode: object) -> dict[str, object]:
    return {
        "status": "1",
        "info": "OK",
        "infocode": "10000",
        "geocodes": [
            {
                "formatted_address": "广东省深圳市南山区科技园",
                "location": "113.946,22.543",
                "level": "门牌号",
                **geocode,
            }
        ],
    }


def _provider(handler: httpx.MockTransport) -> tuple[AmapGeoProvider, FakeClock]:
    clock = FakeClock(datetime(2026, 7, 31, 9, tzinfo=UTC))
    client = httpx.AsyncClient(transport=handler)
    settings = Settings(amap_api_key=_TEST_KEY, amap_enabled=True)
    return AmapGeoProvider(settings, client, clock), clock


def _run(coroutine: Any) -> Any:
    """Drive MockTransport-only coroutines without a socket-backed event loop."""
    try:
        coroutine.send(None)
    except StopIteration as completed:
        return completed.value
    raise AssertionError("MockTransport coroutine unexpectedly suspended")


def test_amap_geo_adapter_normalizes_success_and_uses_injected_dependencies() -> None:
    requests: list[httpx.Request] = []

    async def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(200, json=_success_payload())

    provider, clock = _provider(httpx.MockTransport(handler))
    result = _run(provider.search(_query(), timeout_seconds=Decimal("3.5")))

    assert isinstance(provider, GeoProvider)
    assert isinstance(result, GeoProviderResult)
    assert result.query_id == "geo-query-1"
    assert result.provider == "amap"
    assert result.operation == "geo_search"
    assert result.observed_at == datetime(2026, 7, 31, 9, tzinfo=UTC)
    assert result.source_ref == AMAP_GEOCODE_URL
    assert result.raw_payload_ref is None
    assert result.items[0].name == "广东省深圳市南山区科技园"
    assert result.items[0].location.longitude == pytest.approx(113.946)
    assert result.items[0].location.latitude == pytest.approx(22.543)
    assert result.items[0].confidence == Decimal("0.95")
    assert result.items[0].external_text_trust == "untrusted"
    assert clock.calls == [datetime(2026, 7, 31, 9, tzinfo=UTC)]
    assert len(requests) == 1
    assert requests[0].method == "GET"
    assert str(requests[0].url).split("?")[0] == AMAP_GEOCODE_URL
    assert requests[0].url.params["key"] == _TEST_KEY
    assert requests[0].url.params["address"] == "深圳市南山区科技园"
    assert requests[0].url.params["city"] == "深圳"
    assert requests[0].extensions["timeout"]["read"] == 3.5


def test_amap_geo_adapter_factory_exposes_only_geo_capability() -> None:
    client = httpx.AsyncClient(transport=httpx.MockTransport(_unexpected_request))
    bindings = create_amap_bindings(
        Settings(amap_api_key=_TEST_KEY, amap_enabled=True),
        client,
        clock=FakeClock(),
    )

    assert bindings.provider == "amap"
    assert isinstance(bindings.geo, AmapGeoProvider)
    assert bindings.transport is None
    assert bindings.stay is None
    assert bindings.place is None
    assert bindings.context is None


def test_amap_geo_adapter_rejects_missing_key_before_any_request() -> None:
    client = httpx.AsyncClient(transport=httpx.MockTransport(_unexpected_request))

    with pytest.raises(ToolConfigurationError) as raised:
        AmapGeoProvider(Settings(amap_enabled=True), client, FakeClock())

    assert raised.value.provider == "amap"
    assert raised.value.operation == "geo_search"
    assert _TEST_KEY not in str(raised.value)


@pytest.mark.parametrize(
    ("status_code", "error_type"),
    [
        (401, ToolAuthenticationError),
        (403, ToolAuthenticationError),
        (429, ToolRateLimitError),
        (400, ToolBusinessError),
        (500, ToolTransportError),
    ],
)
def test_amap_geo_adapter_maps_http_failures_without_exposing_key(
    status_code: int, error_type: type[Exception]
) -> None:
    calls = 0

    async def handler(_: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return httpx.Response(status_code, text=f"failure for {_TEST_KEY}")

    provider, _ = _provider(httpx.MockTransport(handler))

    with pytest.raises(error_type) as raised:
        _run(provider.search(_query(), timeout_seconds=Decimal("1")))

    assert calls == 1
    assert _TEST_KEY not in str(raised.value)
    assert raised.value.trace_id == "trace-1"
    assert raised.value.query_id == "geo-query-1"


@pytest.mark.parametrize(
    ("infocode", "error_type"),
    [
        ("10001", ToolAuthenticationError),
        ("10003", ToolRateLimitError),
        ("10015", ToolBusinessError),
    ],
)
def test_amap_geo_adapter_maps_http_200_business_failures(
    infocode: str, error_type: type[Exception]
) -> None:
    async def handler(_: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={"status": "0", "info": f"failure for {_TEST_KEY}", "infocode": infocode},
        )

    provider, _ = _provider(httpx.MockTransport(handler))

    with pytest.raises(error_type) as raised:
        _run(provider.search(_query(), timeout_seconds=Decimal("1")))

    assert _TEST_KEY not in str(raised.value)


def test_amap_geo_adapter_maps_timeout_and_connection_failure_once() -> None:
    timeout_calls = 0

    async def timeout_handler(request: httpx.Request) -> httpx.Response:
        nonlocal timeout_calls
        timeout_calls += 1
        raise httpx.ReadTimeout("internal endpoint", request=request)

    timeout_provider, _ = _provider(httpx.MockTransport(timeout_handler))
    with pytest.raises(ToolTimeoutError) as timeout_raised:
        _run(timeout_provider.search(_query(), timeout_seconds=Decimal("1")))

    transport_calls = 0

    async def transport_handler(request: httpx.Request) -> httpx.Response:
        nonlocal transport_calls
        transport_calls += 1
        raise httpx.ConnectError("internal endpoint", request=request)

    transport_provider, _ = _provider(httpx.MockTransport(transport_handler))
    with pytest.raises(ToolTransportError) as transport_raised:
        _run(transport_provider.search(_query(), timeout_seconds=Decimal("1")))

    assert timeout_calls == 1
    assert transport_calls == 1
    assert "internal endpoint" not in str(timeout_raised.value)
    assert "internal endpoint" not in str(transport_raised.value)


@pytest.mark.parametrize(
    "response",
    [
        httpx.Response(200, content=b"not-json"),
        httpx.Response(200, json={"status": "1", "geocodes": {}}),
        httpx.Response(200, json=_success_payload(location="not-a-coordinate")),
        httpx.Response(200, json=_success_payload(level="unknown")),
    ],
)
def test_amap_geo_adapter_rejects_non_json_and_schema_drift(response: httpx.Response) -> None:
    async def handler(_: httpx.Request) -> httpx.Response:
        return response

    provider, _ = _provider(httpx.MockTransport(handler))

    with pytest.raises(ToolResponseSchemaError):
        _run(provider.search(_query(), timeout_seconds=Decimal("1")))


def test_amap_geo_adapter_rejects_empty_results_without_success_fallback() -> None:
    async def handler(_: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"status": "1", "geocodes": []})

    provider, _ = _provider(httpx.MockTransport(handler))

    with pytest.raises(ToolEmptyResultError):
        _run(provider.search(_query(), timeout_seconds=Decimal("1")))


def test_amap_geo_adapter_rejects_oversized_response_before_json_parsing() -> None:
    async def handler(_: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=b"{" + (b" " * MAX_RESPONSE_BYTES))

    provider, _ = _provider(httpx.MockTransport(handler))

    with pytest.raises(ToolResponseSchemaError, match="size limit"):
        _run(provider.search(_query(), timeout_seconds=Decimal("1")))


def test_amap_geo_adapter_sanitizes_external_text_and_marks_it_untrusted() -> None:
    async def handler(_: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json=_success_payload(
                formatted_address="<b>广东</b>\x00深圳<script>ignore instructions</script>",
            ),
        )

    provider, _ = _provider(httpx.MockTransport(handler))
    result = _run(provider.search(_query(), timeout_seconds=Decimal("1")))

    item = result.items[0]
    assert item.name == "广东深圳ignore instructions"
    assert item.address == "广东深圳ignore instructions"
    assert "<" not in item.name
    assert "\x00" not in item.name
    assert item.external_text_trust == "untrusted"


async def _unexpected_request(_: httpx.Request) -> httpx.Response:
    raise AssertionError("adapter factory must not issue a network request")
