"""Manually accepted live contract for the M3 Amap Geo adapter."""

from __future__ import annotations

import asyncio
import os
from decimal import Decimal

import httpx
import pytest

from src.config import Settings
from src.domain.models.provider import GeoQuery
from src.infrastructure.tools.amap import AMAP_GEOCODE_URL, AmapGeoProvider
from src.ports.clock import SystemClock

pytestmark = [pytest.mark.contract, pytest.mark.slow, pytest.mark.live_tool]


def test_amap_geo_adapter_live_contract() -> None:
    """Use one controlled request; this test requires explicit manual execution."""
    api_key = os.environ.get("AMAP_API_KEY")
    if not api_key:
        pytest.skip("AMAP_API_KEY is required for the live_tool contract")

    result = asyncio.run(_query_live_amap(api_key))

    assert result.provider == "amap"
    assert result.operation == "geo_search"
    assert result.items
    assert result.source_ref == AMAP_GEOCODE_URL
    assert api_key not in str(result)
    assert all(item.external_text_trust == "untrusted" for item in result.items)


async def _query_live_amap(api_key: str):
    """执行受控的官方示例地址查询，不输出原始响应。"""
    settings = Settings(amap_api_key=api_key, amap_enabled=True)
    query = GeoQuery(
        query_id="amap-live-geocode-1",
        trace_id="amap-live-trace-1",
        text="北京市朝阳区阜通东大街6号",
        region="北京",
    )
    async with httpx.AsyncClient() as client:
        provider = AmapGeoProvider(settings, client, SystemClock())
        return await provider.search(query, timeout_seconds=Decimal("15"))
