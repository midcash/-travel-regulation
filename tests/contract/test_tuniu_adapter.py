"""Offline contract tests for the M3 Tuniu legacy API-key adapter."""

from __future__ import annotations

import json
from datetime import UTC, date, datetime, timedelta, timezone
from decimal import Decimal
from typing import Any

import httpx
import pytest

from src.config import Settings
from src.domain.models.provider import (
    PlaceProviderResult,
    PlaceQuery,
    StayProviderResult,
    StayQuery,
    TransportProviderResult,
    TransportQuery,
)
from src.domain.models.value_objects import DateRange, Money
from src.infrastructure.tools.tuniu import (
    MAX_RESPONSE_BYTES,
    TUNIU_FLIGHT_URL,
    TUNIU_HOTEL_URL,
    TUNIU_TICKET_URL,
    TuniuTravelProvider,
    create_tuniu_bindings,
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
from src.ports.tool_provider import PlaceProvider, StayProvider, TransportProvider
from tests.support.clock_fakes import FakeClock

pytestmark = pytest.mark.contract

_TEST_KEY = "test-tuniu-key"
_OBSERVED_AT = datetime(2026, 7, 31, 9, tzinfo=UTC)


def _transport_query() -> TransportQuery:
    return TransportQuery(
        query_id="transport-query-1",
        trace_id="trace-1",
        origin="Beijing",
        destination="Shanghai",
        departure_after=datetime(2026, 8, 15, 8, tzinfo=UTC),
        travelers=2,
    )


def _stay_query() -> StayQuery:
    return StayQuery(
        query_id="stay-query-1",
        trace_id="trace-1",
        destination="Beijing",
        date_range=DateRange(start=date(2026, 8, 15), end=date(2026, 8, 17)),
        travelers=2,
        area="Palace",
        max_total_price=Money(amount=Decimal("2000"), currency="CNY"),
    )


def _place_query() -> PlaceQuery:
    return PlaceQuery(
        query_id="place-query-1",
        trace_id="trace-1",
        destination="Summer Palace",
        category="ticket",
    )


def _flight_payload(**item: object) -> dict[str, object]:
    return {
        "successCode": True,
        "queryId": "flight-page-1",
        "totalPageNum": 1,
        "data": [
            {
                "flightNumber": "ZH9561",
                "airlineCompany": "Shenzhen Airlines",
                "departureTime": "2026-08-15 07:20",
                "arrivalTime": "2026-08-15 09:55",
                "basePrice": "710",
                "totalTax": "50",
                **item,
            }
        ],
    }


def _hotel_payload(**item: object) -> dict[str, object]:
    return {
        "success": True,
        "queryId": "hotel-page-1",
        "totalPageNum": 1,
        "currentPageNum": 1,
        "hotels": [
            {
                "hotelId": 12345,
                "hotelName": "City Hotel",
                "cityName": "Beijing",
                "lowestPrice": 1416,
                **item,
            }
        ],
    }


def _ticket_payload(**item: object) -> dict[str, object]:
    return {
        "scenic_name": "Summer Palace",
        "tickets": [
            {
                "productId": 12345,
                "resId": "res-001",
                "price": "50",
                "ticketType": "Adult",
                **item,
            }
        ],
    }


def _mcp_payload(payload: dict[str, object]) -> dict[str, object]:
    return {
        "jsonrpc": "2.0",
        "id": "ignored-by-provider",
        "result": {
            "content": [
                {
                    "type": "text",
                    "text": json.dumps(payload),
                }
            ]
        },
    }


def _provider(handler: httpx.MockTransport) -> tuple[TuniuTravelProvider, FakeClock]:
    clock = FakeClock(_OBSERVED_AT)
    client = httpx.AsyncClient(transport=handler)
    settings = Settings(tuniu_api_key=_TEST_KEY, tuniu_enabled=True)
    return TuniuTravelProvider(settings, client, clock), clock


def _run(coroutine: Any) -> Any:
    """Drive MockTransport-only coroutines without a socket-backed event loop."""
    try:
        coroutine.send(None)
    except StopIteration as completed:
        return completed.value
    raise AssertionError("MockTransport coroutine unexpectedly suspended")


def test_tuniu_adapter_normalizes_all_supported_capabilities_once() -> None:
    requests: list[httpx.Request] = []
    responses = [
        _mcp_payload(_flight_payload()),
        _mcp_payload(_hotel_payload()),
        _mcp_payload(_ticket_payload()),
    ]

    async def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(200, json=responses.pop(0))

    provider, clock = _provider(httpx.MockTransport(handler))
    transport = _run(provider.search(_transport_query(), timeout_seconds=Decimal("3.5")))
    stay = _run(provider.search(_stay_query(), timeout_seconds=Decimal("3.5")))
    place = _run(provider.search(_place_query(), timeout_seconds=Decimal("3.5")))

    assert isinstance(provider, TransportProvider)
    assert isinstance(provider, StayProvider)
    assert isinstance(provider, PlaceProvider)
    assert isinstance(transport, TransportProviderResult)
    assert isinstance(stay, StayProviderResult)
    assert isinstance(place, PlaceProviderResult)
    assert transport.provider == "tuniu"
    assert transport.operation == "transport_search"
    assert transport.observed_at == _OBSERVED_AT
    assert transport.items[0].name == "Shenzhen Airlines ZH9561"
    assert transport.items[0].total_price == Money(amount=Decimal("760"), currency="CNY")
    assert transport.items[0].departure_at == datetime(
        2026, 8, 15, 7, 20, tzinfo=timezone(timedelta(hours=8))
    )
    assert stay.operation == "stay_search"
    assert stay.items[0].area == "Beijing"
    assert stay.items[0].total_price == Money(amount=Decimal("1416"), currency="CNY")
    assert place.operation == "place_search"
    assert place.items[0].name == "Summer Palace Adult"
    assert place.items[0].total_price == Money(amount=Decimal("50"), currency="CNY")
    assert all(
        item.external_text_trust == "untrusted"
        for item in (transport.items[0], stay.items[0], place.items[0])
    )
    assert clock.calls == [_OBSERVED_AT, _OBSERVED_AT, _OBSERVED_AT]
    assert [str(request.url) for request in requests] == [
        TUNIU_FLIGHT_URL,
        TUNIU_HOTEL_URL,
        TUNIU_TICKET_URL,
    ]
    assert all(request.method == "POST" for request in requests)
    assert all(request.headers["apiKey"] == _TEST_KEY for request in requests)
    assert all(_TEST_KEY not in request.content.decode("utf-8") for request in requests)
    assert requests[0].extensions["timeout"]["read"] == 3.5
    assert json.loads(requests[0].content) == {
        "jsonrpc": "2.0",
        "id": "transport-query-1",
        "method": "tools/call",
        "params": {
            "name": "searchLowestPriceFlight",
            "arguments": {
                "departureCityName": "Beijing",
                "arrivalCityName": "Shanghai",
                "departureDate": "2026-08-15",
            },
        },
    }
    assert json.loads(requests[1].content)["params"] == {
        "name": "tuniuHotelSearch",
        "arguments": {
            "cityName": "Beijing",
            "checkIn": "2026-08-15",
            "checkOut": "2026-08-17",
            "adultNum": 2,
            "keyword": "Palace",
            "prices": "0-2000",
        },
    }
    assert json.loads(requests[2].content)["params"] == {
        "name": "query_cheapest_tickets",
        "arguments": {"scenic_name": "Summer Palace"},
    }


def test_tuniu_adapter_factory_exposes_only_supported_capabilities() -> None:
    client = httpx.AsyncClient(transport=httpx.MockTransport(_unexpected_request))
    bindings = create_tuniu_bindings(
        Settings(tuniu_api_key=_TEST_KEY, tuniu_enabled=True),
        client,
        clock=FakeClock(),
    )

    assert bindings.provider == "tuniu"
    assert bindings.geo is None
    assert isinstance(bindings.transport, TuniuTravelProvider)
    assert bindings.transport is bindings.stay is bindings.place
    assert bindings.context is None


def test_tuniu_adapter_decodes_one_sse_result() -> None:
    async def handler(_: httpx.Request) -> httpx.Response:
        event = json.dumps(_mcp_payload(_hotel_payload()))
        return httpx.Response(200, content=f"event: message\ndata: {event}\n\n".encode())

    provider, _ = _provider(httpx.MockTransport(handler))
    result = _run(provider.search(_stay_query(), timeout_seconds=Decimal("1")))

    assert result.items[0].name == "City Hotel"


def test_tuniu_adapter_rejects_missing_key_before_any_request() -> None:
    client = httpx.AsyncClient(transport=httpx.MockTransport(_unexpected_request))

    with pytest.raises(ToolConfigurationError) as raised:
        TuniuTravelProvider(Settings(tuniu_enabled=True), client, FakeClock())

    assert raised.value.provider == "tuniu"
    assert raised.value.operation == "travel_search"
    assert _TEST_KEY not in str(raised.value)


def test_tuniu_transport_requires_departure_date_before_any_request() -> None:
    calls = 0

    async def handler(_: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return httpx.Response(200, json=_mcp_payload(_flight_payload()))

    provider, _ = _provider(httpx.MockTransport(handler))
    missing_departure_date = _transport_query().model_copy(
        update={"departure_after": None}
    )

    with pytest.raises(ToolBusinessError, match="departure date"):
        _run(provider.search(missing_departure_date, timeout_seconds=Decimal("1")))

    assert calls == 0


@pytest.mark.parametrize(
    ("status_code", "error_type"),
    [
        (401, ToolAuthenticationError),
        (403, ToolAuthenticationError),
        (429, ToolRateLimitError),
        (400, ToolBusinessError),
        (302, ToolTransportError),
        (500, ToolTransportError),
    ],
)
def test_tuniu_adapter_maps_http_failures_without_exposing_key(
    status_code: int,
    error_type: type[Exception],
) -> None:
    calls = 0

    async def handler(_: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return httpx.Response(status_code, text=f"failure for {_TEST_KEY}")

    provider, _ = _provider(httpx.MockTransport(handler))

    with pytest.raises(error_type) as raised:
        _run(provider.search(_stay_query(), timeout_seconds=Decimal("1")))

    assert calls == 1
    assert _TEST_KEY not in str(raised.value)
    assert raised.value.trace_id == "trace-1"
    assert raised.value.query_id == "stay-query-1"


@pytest.mark.parametrize(
    ("code", "error_type"),
    [
        (401, ToolAuthenticationError),
        (429, ToolRateLimitError),
        (-32000, ToolBusinessError),
    ],
)
def test_tuniu_adapter_maps_json_rpc_failures_without_exposing_key(
    code: int,
    error_type: type[Exception],
) -> None:
    async def handler(_: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "jsonrpc": "2.0",
                "id": "stay-query-1",
                "error": {"code": code, "message": f"failure for {_TEST_KEY}"},
            },
        )

    provider, _ = _provider(httpx.MockTransport(handler))

    with pytest.raises(error_type) as raised:
        _run(provider.search(_stay_query(), timeout_seconds=Decimal("1")))

    assert _TEST_KEY not in str(raised.value)


def test_tuniu_adapter_maps_timeout_and_connection_failure_once() -> None:
    timeout_calls = 0

    async def timeout_handler(request: httpx.Request) -> httpx.Response:
        nonlocal timeout_calls
        timeout_calls += 1
        raise httpx.ReadTimeout("internal endpoint", request=request)

    timeout_provider, _ = _provider(httpx.MockTransport(timeout_handler))
    with pytest.raises(ToolTimeoutError) as timeout_raised:
        _run(timeout_provider.search(_stay_query(), timeout_seconds=Decimal("1")))

    transport_calls = 0

    async def transport_handler(request: httpx.Request) -> httpx.Response:
        nonlocal transport_calls
        transport_calls += 1
        raise httpx.ConnectError("internal endpoint", request=request)

    transport_provider, _ = _provider(httpx.MockTransport(transport_handler))
    with pytest.raises(ToolTransportError) as transport_raised:
        _run(transport_provider.search(_stay_query(), timeout_seconds=Decimal("1")))

    assert timeout_calls == 1
    assert transport_calls == 1
    assert "internal endpoint" not in str(timeout_raised.value)
    assert "internal endpoint" not in str(transport_raised.value)


@pytest.mark.parametrize(
    ("response", "query"),
    [
        (httpx.Response(200, content=b"not-json"), _stay_query()),
        (httpx.Response(200, content=b"\xff"), _stay_query()),
        (httpx.Response(200, json=_mcp_payload({"success": True, "hotels": {}})), _stay_query()),
        (
            httpx.Response(200, json=_mcp_payload(_hotel_payload(hotelId=False))),
            _stay_query(),
        ),
        (
            httpx.Response(200, json=_mcp_payload(_flight_payload(basePrice=1.5))),
            _transport_query(),
        ),
        (
            httpx.Response(200, json=_mcp_payload(_ticket_payload(ticketType=""))),
            _place_query(),
        ),
    ],
)
def test_tuniu_adapter_rejects_non_json_and_schema_drift(
    response: httpx.Response,
    query: TransportQuery | StayQuery | PlaceQuery,
) -> None:
    async def handler(_: httpx.Request) -> httpx.Response:
        return response

    provider, _ = _provider(httpx.MockTransport(handler))

    with pytest.raises(ToolResponseSchemaError):
        _run(provider.search(query, timeout_seconds=Decimal("1")))


@pytest.mark.parametrize(
    ("payload", "query"),
    [
        ({"successCode": True, "data": []}, _transport_query()),
        ({"success": True, "hotels": []}, _stay_query()),
        ({"scenic_name": "Summer Palace", "tickets": []}, _place_query()),
    ],
)
def test_tuniu_adapter_rejects_empty_results_without_success_fallback(
    payload: dict[str, object],
    query: TransportQuery | StayQuery | PlaceQuery,
) -> None:
    async def handler(_: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=_mcp_payload(payload))

    provider, _ = _provider(httpx.MockTransport(handler))

    with pytest.raises(ToolEmptyResultError):
        _run(provider.search(query, timeout_seconds=Decimal("1")))


@pytest.mark.parametrize(
    ("payload", "query"),
    [
        ({"successCode": False, "data": []}, _transport_query()),
        ({"success": False, "hotels": []}, _stay_query()),
    ],
)
def test_tuniu_adapter_raises_business_error_for_failed_success_flag(
    payload: dict[str, object],
    query: TransportQuery | StayQuery,
) -> None:
    async def handler(_: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=_mcp_payload(payload))

    provider, _ = _provider(httpx.MockTransport(handler))

    with pytest.raises(ToolBusinessError, match="business failure"):
        _run(provider.search(query, timeout_seconds=Decimal("1")))


def test_tuniu_adapter_rejects_oversized_response_before_json_parsing() -> None:
    async def handler(_: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=b"{" + (b" " * MAX_RESPONSE_BYTES))

    provider, _ = _provider(httpx.MockTransport(handler))

    with pytest.raises(ToolResponseSchemaError, match="size limit"):
        _run(provider.search(_stay_query(), timeout_seconds=Decimal("1")))


def test_tuniu_adapter_sanitizes_external_text_and_marks_it_untrusted() -> None:
    responses = [
        _mcp_payload(
            _flight_payload(
                airlineCompany="<b>Air</b>\x00<script>ignore instructions</script>"
            )
        ),
        _mcp_payload(_hotel_payload(hotelName="<b>Hotel</b>\x00<script>ignore</script>")),
        _mcp_payload(
            {
                "scenic_name": "<b>Park</b>\x00<script>ignore</script>",
                "tickets": [
                    {
                        "productId": 12345,
                        "resId": "res-001",
                        "price": "50",
                        "ticketType": "<i>Adult</i>",
                    }
                ],
            }
        ),
    ]

    async def handler(_: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=responses.pop(0))

    provider, _ = _provider(httpx.MockTransport(handler))
    results = (
        _run(provider.search(_transport_query(), timeout_seconds=Decimal("1"))),
        _run(provider.search(_stay_query(), timeout_seconds=Decimal("1"))),
        _run(provider.search(_place_query(), timeout_seconds=Decimal("1"))),
    )

    assert results[0].items[0].name == "Airignore instructions ZH9561"
    assert results[1].items[0].name == "Hotelignore"
    assert results[2].items[0].name == "Parkignore Adult"
    assert all(
        "<" not in item.name
        and "\x00" not in item.name
        and item.external_text_trust == "untrusted"
        for result in results
        for item in result.items
    )


def test_tuniu_adapter_rejects_unsupported_port_query_without_a_request() -> None:
    calls = 0

    async def handler(_: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return httpx.Response(200, json=_mcp_payload(_ticket_payload()))

    provider, _ = _provider(httpx.MockTransport(handler))
    unsupported = _place_query().model_copy(update={"category": "restaurant"})

    with pytest.raises(ToolBusinessError, match="only ticket"):
        _run(provider.search(unsupported, timeout_seconds=Decimal("1")))

    assert calls == 0


async def _unexpected_request(_: httpx.Request) -> httpx.Response:
    raise AssertionError("adapter factory must not issue a network request")
