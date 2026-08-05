"""Manually accepted live contract for the M3 Amap Geo adapter."""

from __future__ import annotations

import asyncio
import os
from decimal import Decimal

import httpx
import pytest

from src.config import Settings, load_settings
from src.domain.models.provider import GeoProviderResult, GeoQuery
from src.infrastructure.tools.amap import AmapGeoProvider
from src.ports.clock import SystemClock
from src.ports.tool_errors import ToolBusinessError
from tests.support.live_tool_contract import (
    assert_provider_result_contract,
    execute_live_call,
)

pytestmark = [pytest.mark.contract, pytest.mark.slow, pytest.mark.live_tool]

_DEFAULT_AMAP_LIVE_EMPTY_TEXT = "M3NORESULTX9Q7V5K3J1"
_DEFAULT_AMAP_LIVE_EMPTY_REGION = "北京"


def test_amap_geo_adapter_live_contract() -> None:
    """Use one controlled request; this test requires explicit manual execution."""
    api_key = os.environ.get("AMAP_API_KEY")
    if not api_key:
        pytest.skip("AMAP_API_KEY is required for the live_tool contract")

    requests: list[httpx.Request] = []
    settings = load_settings()
    result = execute_live_call(
        provider="amap",
        operation="geo_search",
        scenario="normal",
        call=lambda: asyncio.run(_query_live_amap(settings, requests)),
        request_count=lambda: len(requests),
    )

    assert result is not None
    assert_provider_result_contract(
        result,
        provider="amap",
        operation="geo_search",
        source_ref=settings.amap_geocode_url,
        api_key=api_key,
    )
    assert len(requests) == 1


def test_amap_geo_adapter_live_empty_result_contract() -> None:
    """Verify a real no-match probe stays an explicit typed provider failure.

    The Amap geocoder currently reports synthetic no-match probes as
    ``ENGINE_RESPONSE_DATA_ERROR`` (30001) instead of returning an empty
    ``geocodes`` list.  The adapter must preserve that provider-level failure;
    the offline contract separately verifies ``ToolEmptyResultError`` for a
    successful empty response.
    """
    api_key = os.environ.get("AMAP_API_KEY")
    if not api_key:
        pytest.skip("AMAP_API_KEY is required for the live_tool contract")

    requests: list[httpx.Request] = []
    settings = load_settings()
    empty_text = os.environ.get("AMAP_LIVE_EMPTY_TEXT", _DEFAULT_AMAP_LIVE_EMPTY_TEXT)
    empty_region = os.environ.get("AMAP_LIVE_EMPTY_REGION", _DEFAULT_AMAP_LIVE_EMPTY_REGION)
    result = execute_live_call(
        provider="amap",
        operation="geo_search",
        scenario="empty",
        call=lambda: asyncio.run(
            _query_live_amap(
                settings,
                requests,
                text=empty_text,
                region=empty_region,
            )
        ),
        request_count=lambda: len(requests),
        expected_exception=ToolBusinessError,
    )

    assert result is None, "configured empty query returned usable results"
    assert len(requests) == 1


async def _query_live_amap(
    settings: Settings,
    requests: list[httpx.Request],
    *,
    text: str = "北京市朝阳区阜通东大街6号",
    region: str | None = "北京",
) -> GeoProviderResult:
    """执行受控的官方示例地址查询，不输出原始响应。"""
    query = GeoQuery(
        query_id="amap-live-geocode-1",
        trace_id="amap-live-trace-1",
        text=text,
        region=region,
    )
    async def track_request(request: httpx.Request) -> None:
        requests.append(request)

    async with httpx.AsyncClient(event_hooks={"request": [track_request]}) as client:
        provider = AmapGeoProvider(settings, client, SystemClock())
        return await provider.search(query, timeout_seconds=Decimal("15"))
