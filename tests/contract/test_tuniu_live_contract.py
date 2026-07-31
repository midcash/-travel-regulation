"""Manually accepted live contract for the M3 Tuniu hotel adapter."""

from __future__ import annotations

import asyncio
import os
from datetime import UTC, datetime, timedelta
from decimal import Decimal

import httpx
import pytest

from src.config import Settings
from src.domain.models.provider import StayProviderResult, StayQuery
from src.domain.models.value_objects import DateRange
from src.infrastructure.tools.tuniu import TUNIU_HOTEL_URL, TuniuTravelProvider
from src.ports.clock import SystemClock

pytestmark = [pytest.mark.contract, pytest.mark.slow, pytest.mark.live_tool]


def test_tuniu_hotel_adapter_live_contract() -> None:
    """Use one controlled search; this test requires explicit manual execution."""
    api_key = os.environ.get("TUNIU_API_KEY")
    if not api_key:
        pytest.skip("TUNIU_API_KEY is required for the live_tool contract")

    result = asyncio.run(_query_live_tuniu(api_key))

    assert isinstance(result, StayProviderResult)
    assert result.provider == "tuniu"
    assert result.operation == "stay_search"
    assert result.items
    assert result.source_ref == TUNIU_HOTEL_URL
    assert api_key not in str(result)
    assert all(item.external_text_trust == "untrusted" for item in result.items)


async def _query_live_tuniu(api_key: str) -> StayProviderResult:
    """Run one bounded read-only hotel search without printing provider payloads."""
    check_in = datetime.now(UTC).date() + timedelta(days=30)
    query = StayQuery(
        query_id="tuniu-live-hotel-1",
        trace_id="tuniu-live-trace-1",
        destination="Beijing",
        date_range=DateRange(start=check_in, end=check_in + timedelta(days=1)),
        travelers=1,
        max_results=1,
    )
    settings = Settings(tuniu_api_key=api_key, tuniu_enabled=True)
    async with httpx.AsyncClient() as client:
        provider = TuniuTravelProvider(settings, client, SystemClock())
        return await provider.search(query, timeout_seconds=Decimal("15"))
