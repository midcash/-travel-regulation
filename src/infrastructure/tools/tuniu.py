"""Tuniu legacy API-key MCP adapter for M3 travel-search ports."""

from __future__ import annotations

import hashlib
import html
import json
import math
import re
from collections.abc import Mapping
from datetime import datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation
from time import perf_counter
from typing import cast, overload

import httpx
from pydantic import ValidationError

from src.config import Settings
from src.domain.models.provider import (
    PlaceProviderResult,
    PlaceQuery,
    PlaceResultItem,
    ProviderQueryBase,
    StayProviderResult,
    StayQuery,
    StayResultItem,
    TransportProviderResult,
    TransportQuery,
    TransportResultItem,
)
from src.domain.models.value_objects import Money
from src.infrastructure.tools.assembly import ProviderBindings
from src.obs.metric import record_tool_call
from src.ports.clock import Clock, SystemClock
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

TUNIU_HOTEL_URL = "https://openapi.tuniu.cn/mcp/hotel"
TUNIU_FLIGHT_URL = "https://openapi.tuniu.cn/mcp/flight"
TUNIU_TICKET_URL = "https://openapi.tuniu.cn/mcp/ticket"
MAX_RESPONSE_BYTES = 1_048_576

_CHINA_TIMEZONE = timezone(timedelta(hours=8))
_CONTROL_CHARS = re.compile(r"[\x00-\x1F\x7F]")
_HTML_TAGS = re.compile(r"<[^>]*>")


class TuniuTravelProvider:
    """Expose Tuniu flight, hotel, and ticket search through typed M3 ports."""

    def __init__(self, settings: Settings, client: httpx.AsyncClient, clock: Clock) -> None:
        """Keep the immutable composition-root dependencies for one request."""
        if not isinstance(settings, Settings):
            raise TypeError("settings must be a Settings instance")
        if not isinstance(client, httpx.AsyncClient):
            raise TypeError("client must be an httpx.AsyncClient")
        if not isinstance(clock, Clock):
            raise TypeError("clock must implement Clock")
        if not settings.tuniu_api_key:
            raise ToolConfigurationError(
                provider="tuniu",
                operation="travel_search",
                safe_message="provider credential is required for this adapter",
            )

        self._client = client
        self._clock = clock
        self._api_key = settings.tuniu_api_key

    @overload
    async def search(
        self, query: TransportQuery, *, timeout_seconds: Decimal
    ) -> TransportProviderResult: ...

    @overload
    async def search(self, query: StayQuery, *, timeout_seconds: Decimal) -> StayProviderResult: ...

    @overload
    async def search(
        self, query: PlaceQuery, *, timeout_seconds: Decimal
    ) -> PlaceProviderResult: ...

    async def search(
        self,
        query: TransportQuery | StayQuery | PlaceQuery,
        *,
        timeout_seconds: Decimal,
    ) -> TransportProviderResult | StayProviderResult | PlaceProviderResult:
        """Dispatch one capability-specific query without retry or fallback."""
        operation: str
        if isinstance(query, TransportQuery):
            operation = "transport_search"
        elif isinstance(query, StayQuery):
            operation = "stay_search"
        elif isinstance(query, PlaceQuery):
            operation = "place_search"
        else:
            raise TypeError("query must be a Tuniu-supported provider query")

        started = perf_counter()
        result: TransportProviderResult | StayProviderResult | PlaceProviderResult
        try:
            if operation == "transport_search":
                result = await self._search_transport(
                    cast(TransportQuery, query), timeout_seconds=timeout_seconds
                )
            elif operation == "stay_search":
                result = await self._search_stay(
                    cast(StayQuery, query), timeout_seconds=timeout_seconds
                )
            else:
                result = await self._search_place(
                    cast(PlaceQuery, query), timeout_seconds=timeout_seconds
                )
        except Exception:
            record_tool_call(
                provider="tuniu",
                operation=operation,
                status="failure",
                duration_ms=_elapsed_ms(started),
            )
            raise

        record_tool_call(
            provider="tuniu",
            operation=operation,
            status="success",
            duration_ms=_elapsed_ms(started),
        )
        return result

    async def _search_transport(
        self, query: TransportQuery, *, timeout_seconds: Decimal
    ) -> TransportProviderResult:
        """Search the documented low-price domestic-flight tool once."""
        if query.departure_after is None:
            raise ToolBusinessError(
                **_error_kwargs(query, "transport_search"),
                safe_message="provider requires a departure date",
            )
        payload = await self._call_tool(
            endpoint=TUNIU_FLIGHT_URL,
            tool_name="searchLowestPriceFlight",
            operation="transport_search",
            query=query,
            timeout_seconds=timeout_seconds,
            arguments={
                "departureCityName": query.origin,
                "arrivalCityName": query.destination,
                "departureDate": query.departure_after.date().isoformat(),
            },
        )
        _require_success(payload, "successCode", query, "transport_search")
        records = _required_list(payload, "data", query, "transport_search")
        if not records:
            raise _empty_error(query, "transport_search")

        try:
            items = tuple(
                _normalize_flight_item(record, query) for record in records[: query.max_results]
            )
            return TransportProviderResult(
                query_id=query.query_id,
                provider="tuniu",
                observed_at=self._clock.now(),
                source_ref=TUNIU_FLIGHT_URL,
                items=items,
            )
        except (TypeError, ValueError, ValidationError, InvalidOperation) as exc:
            raise _schema_error(
                query,
                "transport_search",
                "response does not match flight schema",
            ) from exc

    async def _search_stay(
        self, query: StayQuery, *, timeout_seconds: Decimal
    ) -> StayProviderResult:
        """Search the documented hotel tool once."""
        arguments: dict[str, object] = {
            "cityName": query.destination,
            "checkIn": query.date_range.start.isoformat(),
            "checkOut": query.date_range.end.isoformat(),
            "adultNum": query.travelers,
        }
        if query.area is not None:
            arguments["keyword"] = query.area
        if query.max_total_price is not None:
            arguments["prices"] = f"0-{query.max_total_price.amount}"

        payload = await self._call_tool(
            endpoint=TUNIU_HOTEL_URL,
            tool_name="tuniuHotelSearch",
            operation="stay_search",
            query=query,
            timeout_seconds=timeout_seconds,
            arguments=arguments,
        )
        _require_success(payload, "success", query, "stay_search")
        records = _required_list(payload, "hotels", query, "stay_search")
        if not records:
            raise _empty_error(query, "stay_search")

        try:
            items = tuple(
                _normalize_hotel_item(record) for record in records[: query.max_results]
            )
            return StayProviderResult(
                query_id=query.query_id,
                provider="tuniu",
                observed_at=self._clock.now(),
                source_ref=TUNIU_HOTEL_URL,
                items=items,
            )
        except (TypeError, ValueError, ValidationError, InvalidOperation) as exc:
            raise _schema_error(
                query,
                "stay_search",
                "response does not match hotel schema",
            ) from exc

    async def _search_place(
        self, query: PlaceQuery, *, timeout_seconds: Decimal
    ) -> PlaceProviderResult:
        """Search the documented ticket tool once."""
        if query.category != "ticket":
            raise ToolBusinessError(
                **_error_kwargs(query, "place_search"),
                safe_message="provider supports only ticket place searches",
            )
        payload = await self._call_tool(
            endpoint=TUNIU_TICKET_URL,
            tool_name="query_cheapest_tickets",
            operation="place_search",
            query=query,
            timeout_seconds=timeout_seconds,
            arguments={"scenic_name": query.destination},
        )
        records = _required_list(payload, "tickets", query, "place_search")
        if not records:
            raise _empty_error(query, "place_search")

        try:
            scenic_name = _clean_external_text(payload.get("scenic_name"))
            items = tuple(
                _normalize_ticket_item(record, scenic_name, query.category)
                for record in records[: query.max_results]
            )
            return PlaceProviderResult(
                query_id=query.query_id,
                provider="tuniu",
                observed_at=self._clock.now(),
                source_ref=TUNIU_TICKET_URL,
                items=items,
            )
        except (TypeError, ValueError, ValidationError, InvalidOperation) as exc:
            raise _schema_error(
                query,
                "place_search",
                "response does not match ticket schema",
            ) from exc

    async def _call_tool(
        self,
        *,
        endpoint: str,
        tool_name: str,
        operation: str,
        query: ProviderQueryBase,
        timeout_seconds: Decimal,
        arguments: Mapping[str, object],
    ) -> Mapping[str, object]:
        """Issue exactly one legacy API-key JSON-RPC request and unwrap its result."""
        request_payload = {
            "jsonrpc": "2.0",
            "id": query.query_id,
            "method": "tools/call",
            "params": {"name": tool_name, "arguments": dict(arguments)},
        }
        try:
            async with self._client.stream(
                "POST",
                endpoint,
                json=request_payload,
                headers={
                    "Accept": "application/json, text/event-stream",
                    "apiKey": self._api_key,
                },
                timeout=_timeout_as_float(timeout_seconds),
            ) as response:
                _raise_for_http_status(response.status_code, query, operation)
                body = await _read_limited_body(response, query, operation)
        except httpx.TimeoutException as exc:
            raise ToolTimeoutError(
                **_error_kwargs(query, operation),
                safe_message="provider request timed out",
            ) from exc
        except httpx.TransportError as exc:
            raise ToolTransportError(
                **_error_kwargs(query, operation),
                safe_message="provider transport failed",
            ) from exc
        return _decode_mcp_result(body, query, operation)


def create_tuniu_bindings(
    settings: Settings,
    client: httpx.AsyncClient,
    *,
    clock: Clock | None = None,
) -> ProviderBindings:
    """Create all currently supported Tuniu capability bindings."""
    provider = TuniuTravelProvider(settings, client, clock or SystemClock())
    return ProviderBindings(
        provider="tuniu",
        transport=provider,
        stay=provider,
        place=provider,
    )


def _timeout_as_float(timeout_seconds: Decimal) -> float:
    """Convert the explicit Decimal timeout budget for httpx."""
    if isinstance(timeout_seconds, bool):
        raise TypeError("timeout_seconds must be a Decimal-compatible number")
    timeout = float(timeout_seconds)
    if not math.isfinite(timeout) or timeout <= 0:
        raise ValueError("timeout_seconds must be positive and finite")
    return timeout


def _elapsed_ms(started: float) -> int:
    """将单次调用的单调时钟差转换为非负毫秒。"""
    return max(0, int((perf_counter() - started) * 1000))


async def _read_limited_body(
    response: httpx.Response,
    query: ProviderQueryBase,
    operation: str,
) -> bytes:
    """Read an external response with a bounded in-memory payload size."""
    chunks: list[bytes] = []
    total_size = 0
    async for chunk in response.aiter_bytes():
        total_size += len(chunk)
        if total_size > MAX_RESPONSE_BYTES:
            raise _schema_error(query, operation, "provider response exceeds the size limit")
        chunks.append(chunk)
    return b"".join(chunks)


def _raise_for_http_status(
    status_code: int,
    query: ProviderQueryBase,
    operation: str,
) -> None:
    """Map HTTP failures to safe, typed M3 errors."""
    error_kwargs = _error_kwargs(query, operation)
    if status_code in {401, 403}:
        raise ToolAuthenticationError(
            **error_kwargs,
            safe_message="provider rejected the request credentials",
        )
    if status_code == 429:
        raise ToolRateLimitError(
            **error_kwargs,
            safe_message="provider rate limit rejected the request",
        )
    if 500 <= status_code <= 599:
        raise ToolTransportError(
            **error_kwargs,
            safe_message="provider service is unavailable",
        )
    if 400 <= status_code <= 499:
        raise ToolBusinessError(
            **error_kwargs,
            safe_message="provider rejected the request",
        )
    if 300 <= status_code <= 399:
        raise ToolTransportError(
            **error_kwargs,
            safe_message="provider returned an unsupported redirect response",
        )


def _decode_mcp_result(
    body: bytes,
    query: ProviderQueryBase,
    operation: str,
) -> Mapping[str, object]:
    """Decode JSON or one SSE data event and validate the JSON-RPC envelope."""
    envelope = _decode_json_or_sse(body, query, operation)
    if envelope.get("jsonrpc") != "2.0":
        raise _schema_error(query, operation, "provider response has an invalid JSON-RPC version")
    if "error" in envelope:
        _raise_for_mcp_error(envelope["error"], query, operation)
    if "result" not in envelope:
        raise _schema_error(query, operation, "provider response has no JSON-RPC result")
    return _unwrap_mcp_result(envelope["result"], query, operation)


def _decode_json_or_sse(
    body: bytes,
    query: ProviderQueryBase,
    operation: str,
) -> Mapping[str, object]:
    """Decode either a JSON object or exactly one server-sent JSON event."""
    try:
        decoded = body.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise _schema_error(query, operation, "provider response is not UTF-8") from exc

    if "data:" in decoded:
        events: list[Mapping[str, object]] = []
        for line in decoded.splitlines():
            if not line.startswith("data:"):
                continue
            event_data = line.removeprefix("data:").strip()
            if not event_data or event_data == "[DONE]":
                continue
            events.append(_decode_json_object(event_data, query, operation))
        if len(events) != 1:
            raise _schema_error(query, operation, "provider SSE response is not a single result")
        return events[0]
    return _decode_json_object(decoded, query, operation)


def _decode_json_object(
    value: str,
    query: ProviderQueryBase,
    operation: str,
) -> Mapping[str, object]:
    """Decode a provider JSON object without retaining raw payload data."""
    try:
        parsed: object = json.loads(value)
    except json.JSONDecodeError as exc:
        raise _schema_error(query, operation, "provider response is not valid JSON") from exc
    if not isinstance(parsed, dict) or any(not isinstance(key, str) for key in parsed):
        raise _schema_error(query, operation, "provider response must be a JSON object")
    return cast(dict[str, object], parsed)


def _raise_for_mcp_error(
    value: object,
    query: ProviderQueryBase,
    operation: str,
) -> None:
    """Translate a JSON-RPC error object without exposing its message."""
    if not isinstance(value, dict) or any(not isinstance(key, str) for key in value):
        raise _schema_error(query, operation, "provider JSON-RPC error is malformed")
    error = cast(dict[str, object], value)
    code = error.get("code")
    error_kwargs = _error_kwargs(query, operation)
    if code in {401, 403, "401", "403", "UNAUTHORIZED", "FORBIDDEN"}:
        raise ToolAuthenticationError(
            **error_kwargs,
            safe_message="provider rejected the request credentials",
        )
    if code in {429, "429", "RATE_LIMITED"}:
        raise ToolRateLimitError(
            **error_kwargs,
            safe_message="provider rate limit rejected the request",
        )
    raise ToolBusinessError(
        **error_kwargs,
        safe_message="provider reported a business failure",
    )


def _unwrap_mcp_result(
    value: object,
    query: ProviderQueryBase,
    operation: str,
) -> Mapping[str, object]:
    """Extract the typed tool payload from a direct or text-content result."""
    result = _as_mapping(value, query, operation, "provider JSON-RPC result")
    if result.get("isError") is True:
        raise ToolBusinessError(
            **_error_kwargs(query, operation),
            safe_message="provider reported a tool failure",
        )
    if "content" not in result:
        return result

    content = _required_list(result, "content", query, operation)
    if len(content) != 1:
        raise _schema_error(query, operation, "provider content must contain one text block")
    block = _as_mapping(content[0], query, operation, "provider content block")
    if block.get("type") != "text" or not isinstance(block.get("text"), str):
        raise _schema_error(query, operation, "provider content must be one JSON text block")
    return _decode_json_object(cast(str, block["text"]), query, operation)


def _require_success(
    payload: Mapping[str, object],
    field_name: str,
    query: ProviderQueryBase,
    operation: str,
) -> None:
    """Require a documented provider success flag before normalization."""
    success = payload.get(field_name)
    if success is True:
        return
    if success is False:
        raise ToolBusinessError(
            **_error_kwargs(query, operation),
            safe_message="provider reported a business failure",
        )
    raise _schema_error(query, operation, "provider response has an invalid success field")


def _required_list(
    payload: Mapping[str, object],
    field_name: str,
    query: ProviderQueryBase,
    operation: str,
) -> list[object]:
    """Return one required provider list or raise a response-schema error."""
    value = payload.get(field_name)
    if not isinstance(value, list):
        raise _schema_error(query, operation, f"provider response has no {field_name} list")
    return value


def _normalize_flight_item(value: object, query: TransportQuery) -> TransportResultItem:
    """Normalize one documented flight record to the transport DTO."""
    item = _plain_mapping(value)
    flight_number = _clean_external_text(item.get("flightNumber"))
    airline = _clean_external_text(item.get("airlineCompany"))
    departure_at = _parse_tuniu_datetime(item.get("departureTime"))
    arrival_at = _parse_tuniu_datetime(item.get("arrivalTime"))
    total_price = _flight_total_price(item)
    return TransportResultItem(
        entity_id=_stable_id("flight", flight_number, item.get("departureTime")),
        mode="flight",
        name=f"{airline} {flight_number}",
        origin=query.origin,
        destination=query.destination,
        departure_at=departure_at,
        arrival_at=arrival_at,
        total_price=total_price,
        source_ref=TUNIU_FLIGHT_URL,
    )


def _normalize_hotel_item(value: object) -> StayResultItem:
    """Normalize one documented hotel record to the stay DTO."""
    item = _plain_mapping(value)
    hotel_id = item.get("hotelId")
    if isinstance(hotel_id, bool) or not isinstance(hotel_id, str | int):
        raise TypeError("hotelId must be a string or integer")
    return StayResultItem(
        entity_id=_stable_id("hotel", hotel_id),
        name=_clean_external_text(item.get("hotelName")),
        area=_clean_external_text(item.get("cityName")),
        total_price=_money(item.get("lowestPrice")),
        source_ref=TUNIU_HOTEL_URL,
    )


def _normalize_ticket_item(
    value: object,
    scenic_name: str,
    category: str,
) -> PlaceResultItem:
    """Normalize one documented ticket record to the place DTO."""
    item = _plain_mapping(value)
    product_id = item.get("productId")
    if isinstance(product_id, bool) or not isinstance(product_id, str | int):
        raise TypeError("productId must be a string or integer")
    resource_id = _clean_external_text(item.get("resId"))
    ticket_type = _clean_external_text(item.get("ticketType"))
    return PlaceResultItem(
        entity_id=_stable_id("ticket", product_id, resource_id),
        name=f"{scenic_name} {ticket_type}",
        category=category,
        tags=(ticket_type,),
        total_price=_money(item.get("price")),
        source_ref=TUNIU_TICKET_URL,
    )


def _flight_total_price(item: Mapping[str, object]) -> Money:
    """Add the documented base fare and taxes without binary floating-point math."""
    base_price = _decimal(item.get("basePrice"))
    total_tax = _decimal(item.get("totalTax"))
    return Money(amount=base_price + total_tax, currency="CNY")


def _money(value: object) -> Money:
    """Convert a documented CNY quote to the shared Money value object."""
    return Money(amount=_decimal(value), currency="CNY")


def _decimal(value: object) -> Decimal:
    """Parse an exact provider number and reject floats and booleans."""
    if isinstance(value, bool) or not isinstance(value, str | int | Decimal):
        raise TypeError("provider price must be an integer, decimal string, or Decimal")
    try:
        return Decimal(value)
    except InvalidOperation as exc:
        raise ValueError("provider price must be a valid decimal") from exc


def _parse_tuniu_datetime(value: object) -> datetime:
    """Interpret documented domestic-flight local timestamps in China Standard Time."""
    text = _clean_external_text(value)
    for format_string in ("%Y-%m-%d %H:%M", "%Y-%m-%d %H:%M:%S"):
        try:
            return datetime.strptime(text, format_string).replace(tzinfo=_CHINA_TIMEZONE)
        except ValueError:
            continue
    raise ValueError("provider flight time has an unsupported format")


def _clean_external_text(value: object) -> str:
    """Strip HTML and control characters from untrusted provider text."""
    if not isinstance(value, str):
        raise TypeError("provider text field must be a string")
    cleaned = _CONTROL_CHARS.sub("", _HTML_TAGS.sub("", html.unescape(value))).strip()
    if not cleaned:
        raise ValueError("provider text field must not be empty")
    return cleaned


def _as_mapping(
    value: object,
    query: ProviderQueryBase,
    operation: str,
    description: str,
) -> Mapping[str, object]:
    """Validate an external JSON object while retaining no raw payload."""
    if not isinstance(value, dict) or any(not isinstance(key, str) for key in value):
        raise _schema_error(query, operation, f"{description} must be an object")
    return cast(dict[str, object], value)


def _plain_mapping(value: object) -> Mapping[str, object]:
    """Validate one collection item before its field-level normalization."""
    if not isinstance(value, dict) or any(not isinstance(key, str) for key in value):
        raise TypeError("provider collection item must be an object")
    return cast(dict[str, object], value)


def _stable_id(kind: str, *parts: object) -> str:
    """Create a stable provider entity identifier without query data or credentials."""
    seed = "\x1f".join(str(part) for part in parts)
    digest = hashlib.sha256(seed.encode("utf-8")).hexdigest()[:32]
    return f"tuniu.{kind}:{digest}"


def _empty_error(query: ProviderQueryBase, operation: str) -> ToolEmptyResultError:
    """Create a typed empty-result error with only safe query identifiers."""
    return ToolEmptyResultError(
        **_error_kwargs(query, operation),
        safe_message="provider returned no usable results",
    )


def _schema_error(
    query: ProviderQueryBase,
    operation: str,
    safe_message: str,
) -> ToolResponseSchemaError:
    """Create a typed response-schema error with only safe identifiers."""
    return ToolResponseSchemaError(
        **_error_kwargs(query, operation),
        safe_message=safe_message,
    )


def _error_kwargs(query: ProviderQueryBase, operation: str) -> dict[str, str]:
    """Return non-sensitive ToolError context for one Tuniu request."""
    return {
        "provider": "tuniu",
        "operation": operation,
        "trace_id": query.trace_id,
        "query_id": query.query_id,
    }


__all__ = [
    "MAX_RESPONSE_BYTES",
    "TUNIU_FLIGHT_URL",
    "TUNIU_HOTEL_URL",
    "TUNIU_TICKET_URL",
    "TuniuTravelProvider",
    "create_tuniu_bindings",
]
