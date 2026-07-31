"""M3 兼容 Facade：将旧 Tool Calling 入口转发到类型化 Provider Port。"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Callable, Coroutine, Mapping
from datetime import UTC, date, datetime
from decimal import Decimal
from typing import Any, cast

from pydantic import TypeAdapter

from src.domain.models.provider import (
    GeoProviderResult,
    GeoQuery,
    PlaceProviderResult,
    PlaceQuery,
    ProviderQueryBase,
    StayProviderResult,
    StayQuery,
    TransportProviderResult,
    TransportQuery,
)
from src.domain.models.value_objects import DateRange, StableId, TraceId
from src.ports.clock import Clock
from src.ports.tool_errors import ToolConfigurationError
from src.ports.tool_provider import GeoProvider, PlaceProvider, StayProvider, TransportProvider

LegacyToolResult = dict[str, object]
LegacySynchronousRunner = Callable[[Coroutine[Any, Any, LegacyToolResult]], LegacyToolResult]
LegacyToolExecutor = Callable[..., LegacyToolResult]
_ProviderResult = (
    GeoProviderResult | PlaceProviderResult | StayProviderResult | TransportProviderResult
)

# 此集合和 TOOLS 是遗留调用方仍会读取的公开入口；新代码不得依赖本模块。
ALLOWED_TOOLS = {
    "amap_geocode",
    "tuniu_hotel_search",
    "tuniu_flight_search",
    "tuniu_ticket_search",
}

TOOLS: list[dict[str, object]] = [
    {
        "type": "function",
        "function": {
            "name": "amap_geocode",
            "description": "Convert an address into geographic coordinates.",
            "parameters": {
                "type": "object",
                "properties": {"address": {"type": "string"}},
                "required": ["address"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "tuniu_hotel_search",
            "description": "Search hotel availability and prices.",
            "parameters": {
                "type": "object",
                "properties": {
                    "city": {"type": "string"},
                    "checkIn": {"type": "string"},
                    "checkOut": {"type": "string"},
                },
                "required": ["city", "checkIn", "checkOut"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "tuniu_flight_search",
            "description": "Search transport options between two cities.",
            "parameters": {
                "type": "object",
                "properties": {
                    "from_city": {"type": "string"},
                    "to_city": {"type": "string"},
                    "date": {"type": "string"},
                },
                "required": ["from_city", "to_city", "date"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "tuniu_ticket_search",
            "description": "Search ticket options for a scenic destination.",
            "parameters": {
                "type": "object",
                "properties": {
                    "scenic": {"type": "string"},
                    "city": {"type": "string"},
                },
                "required": ["scenic", "city"],
            },
        },
    },
]


class KnowledgeFacade:
    """保留旧工具入口，并通过显式注入的 M3 Port 执行一次查询。"""

    def __init__(
        self,
        *,
        clock: Clock,
        trace_id: TraceId,
        timeout_seconds: Decimal,
        geo_provider: GeoProvider | None = None,
        transport_provider: TransportProvider | None = None,
        stay_provider: StayProvider | None = None,
        place_provider: PlaceProvider | None = None,
        synchronous_runner: LegacySynchronousRunner | None = None,
    ) -> None:
        """保存组合根提供的依赖，不创建 Adapter、Settings 或 Fake。

        Args:
            clock: 为旧入口生成查询标识的显式时钟。
            trace_id: 当前调用链的稳定追踪标识。
            timeout_seconds: 每次 Provider 调用的显式超时预算。
            geo_provider: 已装配的地理 Provider。
            transport_provider: 已装配的交通 Provider。
            stay_provider: 已装配的住宿 Provider。
            place_provider: 已装配的地点 Provider。
            synchronous_runner: 旧同步入口使用的组合根注入执行器。

        Raises:
            TypeError: 依赖不满足对应 Port 或超时不是 Decimal。
            ValueError: 超时预算不为正数。
        """
        if not isinstance(clock, Clock):
            raise TypeError("clock must implement Clock")
        if isinstance(timeout_seconds, bool) or not isinstance(timeout_seconds, Decimal):
            raise TypeError("timeout_seconds must be a Decimal")
        if timeout_seconds <= Decimal("0"):
            raise ValueError("timeout_seconds must be positive")
        _validate_provider("geo_provider", geo_provider, GeoProvider)
        _validate_provider("transport_provider", transport_provider, TransportProvider)
        _validate_provider("stay_provider", stay_provider, StayProvider)
        _validate_provider("place_provider", place_provider, PlaceProvider)
        if synchronous_runner is not None and not callable(synchronous_runner):
            raise TypeError("synchronous_runner must be callable")

        self._clock = clock
        self._trace_id = TypeAdapter(TraceId).validate_python(trace_id)
        self._timeout_seconds = timeout_seconds
        self._geo_provider = geo_provider
        self._transport_provider = transport_provider
        self._stay_provider = stay_provider
        self._place_provider = place_provider
        self._synchronous_runner = synchronous_runner

    async def amap_geocode(self, address: str) -> LegacyToolResult:
        """通过 GeoProvider 执行旧版高德地理编码入口。"""
        query = GeoQuery(
            query_id=self._query_id("amap_geocode", {"address": address}),
            trace_id=self._trace_id,
            text=address,
            timeout_seconds=self._timeout_seconds,
        )
        provider = self._geo_provider
        if provider is None:
            raise _missing_provider(query, provider="amap", capability="geo", operation="geo_search")
        result = await provider.search(query, timeout_seconds=self._timeout_seconds)
        item = result.items[0]
        return {
            "lat": item.location.latitude,
            "lng": item.location.longitude,
            "display_name": item.address or item.name,
            "source_ref": result.source_ref,
        }

    async def tuniu_hotel_search(
        self,
        city: str,
        check_in: str,
        check_out: str,
    ) -> LegacyToolResult:
        """通过 StayProvider 执行旧版途牛酒店查询入口。"""
        start = _parse_legacy_date(check_in, field_name="checkIn")
        end = _parse_legacy_date(check_out, field_name="checkOut")
        if end <= start:
            raise ValueError("checkOut must be later than checkIn")
        query = StayQuery(
            query_id=self._query_id(
                "tuniu_hotel_search",
                {"city": city, "checkIn": check_in, "checkOut": check_out},
            ),
            trace_id=self._trace_id,
            destination=city,
            date_range=DateRange(start=start, end=end),
            timeout_seconds=self._timeout_seconds,
        )
        provider = self._stay_provider
        if provider is None:
            raise _missing_provider(query, provider="tuniu", capability="stay", operation="stay_search")
        result = await provider.search(query, timeout_seconds=self._timeout_seconds)
        return _serialize_result(result)

    async def tuniu_flight_search(
        self,
        from_city: str,
        to_city: str,
        departure_date: str,
    ) -> LegacyToolResult:
        """通过 TransportProvider 执行旧版途牛交通查询入口。"""
        departure_day = _parse_legacy_date(departure_date, field_name="date")
        departure_after = datetime(
            departure_day.year,
            departure_day.month,
            departure_day.day,
            tzinfo=UTC,
        )
        query = TransportQuery(
            query_id=self._query_id(
                "tuniu_flight_search",
                {"from_city": from_city, "to_city": to_city, "date": departure_date},
            ),
            trace_id=self._trace_id,
            origin=from_city,
            destination=to_city,
            departure_after=departure_after,
            timeout_seconds=self._timeout_seconds,
        )
        provider = self._transport_provider
        if provider is None:
            raise _missing_provider(
                query,
                provider="tuniu",
                capability="transport",
                operation="transport_search",
            )
        result = await provider.search(query, timeout_seconds=self._timeout_seconds)
        return _serialize_result(result)

    async def tuniu_ticket_search(self, scenic: str, city: str) -> LegacyToolResult:
        """通过 PlaceProvider 执行旧版途牛景区门票查询入口。"""
        _require_non_empty_text(city, field_name="city")
        query = PlaceQuery(
            query_id=self._query_id(
                "tuniu_ticket_search",
                {"scenic": scenic, "city": city},
            ),
            trace_id=self._trace_id,
            destination=scenic,
            category="ticket",
            timeout_seconds=self._timeout_seconds,
        )
        provider = self._place_provider
        if provider is None:
            raise _missing_provider(query, provider="tuniu", capability="place", operation="place_search")
        result = await provider.search(query, timeout_seconds=self._timeout_seconds)
        return _serialize_result(result)

    def execute_synchronously(
        self,
        operation: Callable[[], Coroutine[Any, Any, LegacyToolResult]],
    ) -> LegacyToolResult:
        """通过组合根注入的执行器保留旧同步入口，不在 Facade 内创建事件循环。"""
        runner = self._synchronous_runner
        if runner is None:
            raise ToolConfigurationError(
                provider="knowledge_facade",
                operation="legacy_entrypoint",
                trace_id=self._trace_id,
                safe_message="legacy facade requires an explicitly injected synchronous runner",
            )
        return runner(operation())

    def _query_id(self, operation: str, arguments: Mapping[str, str]) -> StableId:
        """用注入 Clock 生成可审计的旧入口查询标识，避免硬编码当前日期。"""
        seed = json.dumps(
            {
                "trace_id": self._trace_id,
                "operation": operation,
                "arguments": dict(arguments),
                "observed_at": self._clock.now().isoformat(),
            },
            ensure_ascii=True,
            separators=(",", ":"),
            sort_keys=True,
        )
        digest = hashlib.sha256(seed.encode("utf-8")).hexdigest()[:24]
        return f"legacy-knowledge.{operation}:{digest}"


_legacy_facade: KnowledgeFacade | None = None


def configure_legacy_facade(facade: KnowledgeFacade) -> None:
    """由组合根显式安装临时 Facade，供旧 TOOL_EXECUTORS 入口使用。"""
    if not isinstance(facade, KnowledgeFacade):
        raise TypeError("facade must be a KnowledgeFacade")
    global _legacy_facade
    _legacy_facade = facade


def _exec_amap_geocode(address: str) -> LegacyToolResult:
    """保留同步高德入口，并转发到显式安装的 Facade。"""
    facade = _require_legacy_facade()
    return facade.execute_synchronously(lambda: facade.amap_geocode(address))


def _exec_tuniu_hotel_search(
    city: str,
    checkIn: str,
    checkOut: str,
) -> LegacyToolResult:
    """保留同步酒店入口，并转发到显式安装的 Facade。"""
    facade = _require_legacy_facade()
    return facade.execute_synchronously(
        lambda: facade.tuniu_hotel_search(city, checkIn, checkOut)
    )


def _exec_tuniu_flight_search(
    from_city: str,
    to_city: str,
    date: str,
) -> LegacyToolResult:
    """保留同步交通入口，并转发到显式安装的 Facade。"""
    facade = _require_legacy_facade()
    return facade.execute_synchronously(
        lambda: facade.tuniu_flight_search(from_city, to_city, date)
    )


def _exec_tuniu_ticket_search(scenic: str, city: str) -> LegacyToolResult:
    """保留同步门票入口，并转发到显式安装的 Facade。"""
    facade = _require_legacy_facade()
    return facade.execute_synchronously(lambda: facade.tuniu_ticket_search(scenic, city))


TOOL_EXECUTORS: dict[str, LegacyToolExecutor] = {
    "amap_geocode": _exec_amap_geocode,
    "tuniu_hotel_search": _exec_tuniu_hotel_search,
    "tuniu_flight_search": _exec_tuniu_flight_search,
    "tuniu_ticket_search": _exec_tuniu_ticket_search,
}


def _validate_provider(
    name: str,
    provider: object | None,
    port: type[GeoProvider] | type[PlaceProvider] | type[StayProvider] | type[TransportProvider],
) -> None:
    """拒绝不满足 Port 的显式依赖，避免延迟到网络调用后失败。"""
    if provider is not None and not isinstance(provider, port):
        raise TypeError(f"{name} must implement its provider port")


def _missing_provider(
    query: ProviderQueryBase,
    *,
    provider: str,
    capability: str,
    operation: str,
) -> ToolConfigurationError:
    """构造缺失显式 Provider 时的 M3 失败。"""
    return ToolConfigurationError(
        provider=provider,
        operation=operation,
        trace_id=query.trace_id,
        query_id=query.query_id,
        safe_message=f"legacy facade requires an explicitly assembled {capability} provider",
    )


def _parse_legacy_date(value: str, *, field_name: str) -> date:
    """解析遗留入口使用的 ISO 日期字符串。"""
    if not isinstance(value, str):
        raise TypeError(f"{field_name} must be an ISO date string")
    try:
        return date.fromisoformat(value)
    except ValueError as exc:
        raise ValueError(f"{field_name} must be an ISO date in YYYY-MM-DD format") from exc


def _require_non_empty_text(value: str, *, field_name: str) -> None:
    """校验遗留参数不会在 Port 边界前被静默丢弃。"""
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field_name} must not be blank")


def _serialize_result(result: _ProviderResult) -> LegacyToolResult:
    """仅在遗留边界序列化标准化 DTO，不暴露供应商原始响应。"""
    return cast(LegacyToolResult, result.model_dump(mode="json"))


def _require_legacy_facade() -> KnowledgeFacade:
    """在未由组合根安装 Facade 时显式失败。"""
    if _legacy_facade is None:
        raise ToolConfigurationError(
            provider="knowledge_facade",
            operation="legacy_entrypoint",
            safe_message="legacy knowledge facade has not been configured",
        )
    return _legacy_facade


__all__ = [
    "ALLOWED_TOOLS",
    "KnowledgeFacade",
    "TOOLS",
    "TOOL_EXECUTORS",
    "configure_legacy_facade",
]
