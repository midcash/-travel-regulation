"""高德 Web Service 地理编码 Adapter。"""

from __future__ import annotations

import hashlib
import html
import json
import math
import re
from collections.abc import Mapping
from decimal import Decimal
from typing import cast

import httpx
from pydantic import ValidationError

from src.config import Settings
from src.domain.models.provider import GeoProviderResult, GeoQuery, GeoResultItem
from src.domain.models.value_objects import GeoPoint
from src.infrastructure.tools.assembly import ProviderBindings
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

AMAP_GEOCODE_URL = "https://restapi.amap.com/v3/geocode/geo"
MAX_RESPONSE_BYTES = 1_048_576

_CONTROL_CHARS = re.compile(r"[\x00-\x1F\x7F]")
_HTML_TAGS = re.compile(r"<[^>]*>")
_AUTHENTICATION_INFOCODES = frozenset(
    {"10001", "10002", "10005", "10006", "10007", "10008", "10009", "10012", "10013"}
)
_RATE_LIMIT_INFOCODES = frozenset({"10003", "10004", "10010", "10014", "10019", "10020"})
_CONFIDENCE_BY_LEVEL: dict[str, Decimal] = {
    "country": Decimal("0.40"),
    "province": Decimal("0.50"),
    "city": Decimal("0.60"),
    "district": Decimal("0.70"),
    "township": Decimal("0.75"),
    "street": Decimal("0.80"),
    "number": Decimal("0.95"),
    "poi": Decimal("0.95"),
    "国家": Decimal("0.40"),
    "省": Decimal("0.50"),
    "市": Decimal("0.60"),
    "区县": Decimal("0.70"),
    "区": Decimal("0.70"),
    "村庄": Decimal("0.70"),
    "乡镇": Decimal("0.75"),
    "街道": Decimal("0.80"),
    "商圈": Decimal("0.80"),
    "门牌号": Decimal("0.95"),
    "兴趣点": Decimal("0.95"),
}


class AmapGeoProvider:
    """将高德地理编码响应规范化为 ``GeoProviderResult``。"""

    def __init__(self, settings: Settings, client: httpx.AsyncClient, clock: Clock) -> None:
        """保存组合根提供的不可变依赖。

        Args:
            settings: 已校验的单次请求配置快照。
            client: 与其他 Adapter 共享的 HTTP 客户端。
            clock: 生成 ``observed_at`` 的时间端口。

        Raises:
            ToolConfigurationError: 高德 Key 缺失时抛出。
        """
        if not isinstance(settings, Settings):
            raise TypeError("settings must be a Settings instance")
        if not isinstance(client, httpx.AsyncClient):
            raise TypeError("client must be an httpx.AsyncClient")
        if not isinstance(clock, Clock):
            raise TypeError("clock must implement Clock")
        if not settings.amap_api_key:
            raise ToolConfigurationError(
                provider="amap",
                operation="geo_search",
                safe_message="provider credential is required for this adapter",
            )

        self._settings = settings
        self._client = client
        self._clock = clock
        self._api_key = settings.amap_api_key

    async def search(
        self, query: GeoQuery, *, timeout_seconds: Decimal
    ) -> GeoProviderResult:
        """执行一次高德地理编码请求。

        Args:
            query: 已完成 Schema 校验的地理查询。
            timeout_seconds: 本次调用明确的超时预算。

        Returns:
            GeoProviderResult: 不含原始供应商 payload 的标准化结果。

        Raises:
            ToolError: 高德调用或响应不能满足类型化契约时抛出。
        """
        timeout = _timeout_as_float(timeout_seconds)
        params = {"key": self._api_key, "address": query.text, "output": "JSON"}
        if query.region is not None:
            params["city"] = query.region

        try:
            async with self._client.stream(
                "GET",
                AMAP_GEOCODE_URL,
                params=params,
                headers={"Accept": "application/json"},
                timeout=timeout,
            ) as response:
                _raise_for_http_status(response.status_code, query)
                body = await _read_limited_body(response, query)
        except httpx.TimeoutException as exc:
            raise ToolTimeoutError(
                provider="amap",
                operation="geo_search",
                trace_id=query.trace_id,
                query_id=query.query_id,
                safe_message="provider request timed out",
            ) from exc
        except httpx.TransportError as exc:
            raise ToolTransportError(
                provider="amap",
                operation="geo_search",
                trace_id=query.trace_id,
                query_id=query.query_id,
                safe_message="provider transport failed",
            ) from exc

        payload = _decode_json_payload(body, query)
        _raise_for_amap_business_status(payload, query)
        return self._normalize_result(payload, query)

    def _normalize_result(
        self, payload: Mapping[str, object], query: GeoQuery
    ) -> GeoProviderResult:
        geocodes = payload.get("geocodes")
        if not isinstance(geocodes, list):
            raise _schema_error(query, "provider response has no geocode list")
        if not geocodes:
            raise ToolEmptyResultError(
                provider="amap",
                operation="geo_search",
                trace_id=query.trace_id,
                query_id=query.query_id,
                safe_message="provider returned no usable results",
            )

        try:
            items = tuple(_normalize_geocode_item(item) for item in geocodes)
            return GeoProviderResult(
                query_id=query.query_id,
                provider="amap",
                observed_at=self._clock.now(),
                source_ref=AMAP_GEOCODE_URL,
                items=items,
            )
        except (TypeError, ValueError, ValidationError) as exc:
            raise _schema_error(query, "provider response does not match geo schema") from exc


def create_amap_bindings(
    settings: Settings,
    client: httpx.AsyncClient,
    *,
    clock: Clock | None = None,
) -> ProviderBindings:
    """创建高德 Geo 能力绑定，供组合根显式注入。

    Args:
        settings: 组合根已加载的配置快照。
        client: 组合根共享的 HTTP 客户端。
        clock: 可选时间端口；生产默认使用 UTC 系统时钟。

    Returns:
        ProviderBindings: 仅提供 ``geo`` 能力的高德绑定。
    """
    return ProviderBindings(
        provider="amap",
        geo=AmapGeoProvider(settings, client, clock or SystemClock()),
    )


def _timeout_as_float(timeout_seconds: Decimal) -> float:
    """将显式超时预算安全地传递给 httpx。"""
    if isinstance(timeout_seconds, bool):
        raise TypeError("timeout_seconds must be a Decimal-compatible number")
    timeout = float(timeout_seconds)
    if not math.isfinite(timeout) or timeout <= 0:
        raise ValueError("timeout_seconds must be positive and finite")
    return timeout


async def _read_limited_body(response: httpx.Response, query: GeoQuery) -> bytes:
    """读取受大小限制的响应，避免原始 payload 无界进入进程。"""
    chunks: list[bytes] = []
    total_size = 0
    async for chunk in response.aiter_bytes():
        total_size += len(chunk)
        if total_size > MAX_RESPONSE_BYTES:
            raise _schema_error(query, "provider response exceeds the size limit")
        chunks.append(chunk)
    return b"".join(chunks)


def _raise_for_http_status(status_code: int, query: GeoQuery) -> None:
    """将 HTTP 状态映射到稳定且无敏感信息的 ToolError。"""
    error_kwargs = _error_kwargs(query)
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


def _decode_json_payload(body: bytes, query: GeoQuery) -> Mapping[str, object]:
    """解码 JSON object，拒绝非对象和非 UTF-8 响应。"""
    try:
        value: object = json.loads(body.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise _schema_error(query, "provider response is not valid JSON") from exc
    if not isinstance(value, dict) or any(not isinstance(key, str) for key in value):
        raise _schema_error(query, "provider response must be a JSON object")
    return cast(dict[str, object], value)


def _raise_for_amap_business_status(payload: Mapping[str, object], query: GeoQuery) -> None:
    """处理高德在 HTTP 200 内返回的业务失败。"""
    status = payload.get("status")
    if not isinstance(status, str):
        raise _schema_error(query, "provider response has an invalid status field")
    if status == "1":
        return
    if status != "0":
        raise _schema_error(query, "provider response has an unsupported status value")

    infocode = payload.get("infocode")
    if not isinstance(infocode, str):
        raise _schema_error(query, "provider error response has no infocode")
    error_kwargs = _error_kwargs(query)
    if infocode in _AUTHENTICATION_INFOCODES:
        raise ToolAuthenticationError(
            **error_kwargs,
            safe_message="provider rejected the request credentials",
        )
    if infocode in _RATE_LIMIT_INFOCODES:
        raise ToolRateLimitError(
            **error_kwargs,
            safe_message="provider rate limit rejected the request",
        )
    raise ToolBusinessError(
        **error_kwargs,
        safe_message="provider reported a business failure",
    )


def _normalize_geocode_item(value: object) -> GeoResultItem:
    """清理并转换一个高德 geocode item。"""
    if not isinstance(value, dict) or any(not isinstance(key, str) for key in value):
        raise TypeError("geocode item must be an object")
    item = cast(dict[str, object], value)
    name = _clean_external_text(item.get("formatted_address"))
    level = _clean_external_text(item.get("level")).casefold()
    confidence = _CONFIDENCE_BY_LEVEL.get(level)
    if confidence is None:
        raise ValueError("unrecognized geocode match level")
    location = _parse_location(item.get("location"))
    entity_id = _geocode_entity_id(name, location)
    return GeoResultItem(
        entity_id=entity_id,
        name=name,
        address=name,
        location=location,
        confidence=confidence,
    )


def _clean_external_text(value: object) -> str:
    """移除供应商文本中的 HTML 与控制字符，保留为不可信内容。"""
    if not isinstance(value, str):
        raise TypeError("provider text field must be a string")
    cleaned = _CONTROL_CHARS.sub("", _HTML_TAGS.sub("", html.unescape(value))).strip()
    if not cleaned:
        raise ValueError("provider text field must not be empty")
    return cleaned


def _parse_location(value: object) -> GeoPoint:
    """解析高德 ``longitude,latitude`` 坐标字符串。"""
    if not isinstance(value, str):
        raise TypeError("provider location must be a string")
    parts = value.split(",")
    if len(parts) != 2:
        raise ValueError("provider location must contain longitude and latitude")
    longitude, latitude = (float(part.strip()) for part in parts)
    if not math.isfinite(longitude) or not math.isfinite(latitude):
        raise ValueError("provider location must be finite")
    return GeoPoint(latitude=latitude, longitude=longitude)


def _geocode_entity_id(name: str, location: GeoPoint) -> str:
    """生成不含请求内容或凭证的稳定高德实体 ID。"""
    seed = f"{name}\x1f{location.longitude:.7f}\x1f{location.latitude:.7f}"
    digest = hashlib.sha256(seed.encode("utf-8")).hexdigest()[:32]
    return f"amap.geo:{digest}"


def _schema_error(query: GeoQuery, safe_message: str) -> ToolResponseSchemaError:
    """构造附带查询关联信息的响应 Schema 错误。"""
    return ToolResponseSchemaError(**_error_kwargs(query), safe_message=safe_message)


def _error_kwargs(query: GeoQuery) -> dict[str, str]:
    """返回不含用户文本和凭证的 ToolError 上下文。"""
    return {
        "provider": "amap",
        "operation": "geo_search",
        "trace_id": query.trace_id,
        "query_id": query.query_id,
    }


__all__ = [
    "AMAP_GEOCODE_URL",
    "MAX_RESPONSE_BYTES",
    "AmapGeoProvider",
    "create_amap_bindings",
]
