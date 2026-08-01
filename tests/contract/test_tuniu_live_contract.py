"""Manually accepted live contract for the M3 Tuniu hotel adapter."""

from __future__ import annotations

import asyncio
import os
from datetime import UTC, datetime, timedelta
from decimal import Decimal

import httpx
import pytest

from src.config import Settings, load_settings
from src.domain.models.provider import StayProviderResult, StayQuery
from src.domain.models.value_objects import DateRange
from src.infrastructure.tools.tuniu import TuniuTravelProvider
from src.ports.clock import SystemClock
from src.ports.tool_errors import ToolEmptyResultError
from tests.support.live_tool_contract import (
    assert_provider_result_contract,
    execute_live_call,
)

pytestmark = [pytest.mark.contract, pytest.mark.slow, pytest.mark.live_tool]


def test_tuniu_hotel_adapter_live_contract() -> None:
    """Use one controlled search; this test requires explicit manual execution."""
    api_key = os.environ.get("TUNIU_API_KEY")
    if not api_key:
        pytest.skip("TUNIU_API_KEY is required for the live_tool contract")

    requests: list[httpx.Request] = []
    settings = load_settings()
    result = execute_live_call(
        provider="tuniu",
        operation="stay_search",
        scenario="normal",
        call=lambda: asyncio.run(_query_live_tuniu(settings, requests)),
        request_count=lambda: len(requests),
    )

    assert isinstance(result, StayProviderResult)
    assert_provider_result_contract(
        result,
        provider="tuniu",
        operation="stay_search",
        source_ref=settings.tuniu_hotel_url,
        api_key=api_key,
    )
    assert len(requests) == 1


def test_tuniu_hotel_adapter_live_empty_result_contract() -> None:
    """Verify a real no-inventory query stays an explicit typed failure."""
    api_key = os.environ.get("TUNIU_API_KEY")
    if not api_key:
        pytest.skip("TUNIU_API_KEY is required for the live_tool contract")

    requests: list[httpx.Request] = []
    settings = load_settings()
    result = execute_live_call(
        provider="tuniu",
        operation="stay_search",
        scenario="empty",
        call=lambda: asyncio.run(
            _query_live_tuniu(
                settings,
                requests,
                destination=os.environ.get(
                    "TUNIU_LIVE_EMPTY_DESTINATION",
                    "__M3_NO_MATCH_DESTINATION__",
                ),
            )
        ),
        request_count=lambda: len(requests),
        expected_exception=ToolEmptyResultError,
    )

    assert result is None, "configured empty query returned usable results"
    assert len(requests) == 1


async def _query_live_tuniu(
    settings: Settings,
    requests: list[httpx.Request],
    *,
    destination: str = "Beijing",
) -> StayProviderResult:
    """Run one bounded read-only hotel search without printing provider payloads."""
    check_in = datetime.now(UTC).date() + timedelta(days=30)
    query = StayQuery(
        query_id="tuniu-live-hotel-1",
        trace_id="tuniu-live-trace-1",
        destination=destination,
        date_range=DateRange(start=check_in, end=check_in + timedelta(days=1)),
        travelers=1,
        max_results=1,
    )
    async def track_request(request: httpx.Request) -> None:
        requests.append(request)

    async with httpx.AsyncClient(event_hooks={"request": [track_request]}) as client:
        provider = TuniuTravelProvider(settings, client, SystemClock())
        return await provider.search(query, timeout_seconds=Decimal("15"))
