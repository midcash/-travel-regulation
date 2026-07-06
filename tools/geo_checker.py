"""地理逻辑校验工具 — API 接入版。

v1.1.0: 双轨架构 — API 可用时调用 Nominatim 免费地理编码；不可用时降级到 Haversine + 贪心算法。
Nominatim 免费、无需 API key，仅需 User-Agent 标识。

来源: spec/executor_spec.md §2.4, handoff.md §5.2 §5.5
"""

from __future__ import annotations

import asyncio
import logging
import math
import time as _time
from typing import Any, Dict, List, Optional, Tuple

from core.config import API_TIMEOUT, MAX_RETRIES, RETRY_BACKOFF, get_config

logger = logging.getLogger(__name__)

# ============================================================
# 内置常量
# ============================================================

_DETOUR_RATIO_THRESHOLD = 1.5
_LONG_TRANSIT_MINUTES = 3 * 60
_MAX_SAME_DAY_DISTANCE_KM = 30

# Nominatim 速率限制
_NOMINATIM_MIN_INTERVAL = 1.0  # 1 req/s (free tier)


# ============================================================
# Nominatim 地理编码客户端
# ============================================================

class NominatimClient:
    """Nominatim 免费地理编码客户端。

    基于 OpenStreetMap 数据，免费使用，无需 API key。
    速率限制: 1 req/s。
    """

    def __init__(self):
        self._config = get_config()
        self._last_request_time: float = 0.0

    @property
    def available(self) -> bool:
        """Nominatim 无需 API key，始终可用（除非网络不可达）。"""
        return True

    async def _rate_limit(self) -> None:
        """确保请求间隔 ≥ 1s（Nominatim free tier 限制）。"""
        elapsed = _time.monotonic() - self._last_request_time
        if elapsed < _NOMINATIM_MIN_INTERVAL:
            await asyncio.sleep(_NOMINATIM_MIN_INTERVAL - elapsed)

    async def geocode(self, address: str) -> Optional[Dict[str, Any]]:
        """将地址解析为经纬度坐标。

        Args:
            address: 地址字符串（如 "东京塔"、"Eiffel Tower, Paris"）。

        Returns:
            {lat, lng, display_name, place_id} 或 None（查询失败）。
        """
        import urllib.request
        import urllib.parse
        import json as _json

        await self._rate_limit()

        try:
            params = urllib.parse.urlencode({
                "q": address,
                "format": "json",
                "limit": 1,
            })
            url = f"{self._config.nominatim_base_url}/search?{params}"

            async def _call():
                req = urllib.request.Request(
                    url,
                    headers={
                        "User-Agent": self._config.nominatim_user_agent,
                        "Accept": "application/json",
                    },
                )
                resp = urllib.request.urlopen(req, timeout=self._config.api_timeout)
                self._last_request_time = _time.monotonic()
                return _json.loads(resp.read())

            results = await asyncio.wait_for(_call(), timeout=self._config.api_timeout)

            if not results:
                logger.warning(f"Nominatim 未找到地址: {address}")
                return None

            best = results[0]
            return {
                "lat": float(best["lat"]),
                "lng": float(best["lon"]),
                "display_name": best.get("display_name", address),
                "place_id": best.get("place_id"),
                "source": "nominatim",
            }
        except asyncio.TimeoutError:
            logger.warning(f"Nominatim geocode 超时: {address}")
            return None
        except Exception as exc:
            logger.warning(f"Nominatim geocode 失败: {address} — {exc}")
            return None

    async def reverse_geocode(self, lat: float, lng: float) -> Optional[Dict[str, Any]]:
        """将经纬度反向解析为地址。

        Args:
            lat: 纬度
            lng: 经度

        Returns:
            {address, display_name} 或 None。
        """
        import urllib.request
        import urllib.parse
        import json as _json

        await self._rate_limit()

        try:
            params = urllib.parse.urlencode({
                "lat": lat,
                "lon": lng,
                "format": "json",
                "limit": 1,
            })
            url = f"{self._config.nominatim_base_url}/reverse?{params}"

            async def _call():
                req = urllib.request.Request(
                    url,
                    headers={"User-Agent": self._config.nominatim_user_agent},
                )
                resp = urllib.request.urlopen(req, timeout=self._config.api_timeout)
                self._last_request_time = _time.monotonic()
                return _json.loads(resp.read())

            result = await asyncio.wait_for(_call(), timeout=self._config.api_timeout)

            if not result:
                return None

            return {
                "lat": lat,
                "lng": lng,
                "display_name": result.get("display_name", ""),
                "source": "nominatim",
            }
        except asyncio.TimeoutError:
            logger.warning(f"Nominatim reverse geocode 超时: ({lat}, {lng})")
            return None
        except Exception as exc:
            logger.warning(f"Nominatim reverse geocode 失败: ({lat}, {lng}) — {exc}")
            return None


# ============================================================
# Haversine 距离计算 (降级算法)
# ============================================================

def _haversine_distance(lat1: float, lng1: float, lat2: float, lng2: float) -> float:
    """计算两点间的球面距离 (km)。"""
    R = 6371.0
    dlat = math.radians(lat2 - lat1)
    dlng = math.radians(lng2 - lng1)
    a = (
        math.sin(dlat / 2) ** 2
        + math.cos(math.radians(lat1))
        * math.cos(math.radians(lat2))
        * math.sin(dlng / 2) ** 2
    )
    c = 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))
    return R * c


def _optimal_path_length(points: List[Dict[str, float]]) -> float:
    """贪心最近邻算法估算最优路径长度 (km)。"""
    if len(points) <= 1:
        return 0.0
    visited = [False] * len(points)
    visited[0] = True
    current = 0
    total = 0.0
    for _ in range(len(points) - 1):
        nearest = -1
        nearest_dist = float("inf")
        for j in range(len(points)):
            if not visited[j]:
                d = _haversine_distance(
                    points[current]["lat"], points[current]["lng"],
                    points[j]["lat"], points[j]["lng"],
                )
                if d < nearest_dist:
                    nearest_dist = d
                    nearest = j
        visited[nearest] = True
        total += nearest_dist
        current = nearest
    return total


def _actual_path_length(points: List[Dict[str, float]]) -> float:
    """计算实际路径按顺序的距离 (km)。"""
    total = 0.0
    for i in range(len(points) - 1):
        total += _haversine_distance(
            points[i]["lat"], points[i]["lng"],
            points[i + 1]["lat"], points[i + 1]["lng"],
        )
    return total


# ============================================================
# 模块级客户端实例
# ============================================================

_nominatim_client: Optional[NominatimClient] = None


def _get_nominatim() -> NominatimClient:
    global _nominatim_client
    if _nominatim_client is None:
        _nominatim_client = NominatimClient()
    return _nominatim_client


# ============================================================
# 公共 API — 地理编码 (async)
# ============================================================

async def geocode_async(address: str) -> Dict[str, Any]:
    """将地址解析为经纬度 (async, API + 降级)。

    Returns:
        {lat, lng, source, degraded}
    """
    client = _get_nominatim()
    # 内置少量已知坐标作为快速降级
    known: Dict[str, Tuple[float, float]] = {
        "东京": (35.6762, 139.6503), "Tokyo": (35.6762, 139.6503),
        "浅草寺": (35.7148, 139.7967), "Sensoji": (35.7148, 139.7967),
        "东京塔": (35.6586, 139.7454), "Tokyo Tower": (35.6586, 139.7454),
        "新宿": (35.6895, 139.7006), "Shinjuku": (35.6895, 139.7006),
        "涩谷": (35.6580, 139.7016), "Shibuya": (35.6580, 139.7016),
        "上野": (35.7146, 139.7732), "Ueno": (35.7146, 139.7732),
        "秋叶原": (35.7023, 139.7745), "Akihabara": (35.7023, 139.7745),
        "银座": (35.6722, 139.7700), "Ginza": (35.6722, 139.7700),
        "北京": (39.9042, 116.4074), "Beijing": (39.9042, 116.4074),
        "上海": (31.2304, 121.4737), "Shanghai": (31.2304, 121.4737),
        "巴黎": (48.8566, 2.3522), "Paris": (48.8566, 2.3522),
        "埃菲尔铁塔": (48.8584, 2.2945), "Eiffel Tower": (48.8584, 2.2945),
        "卢浮宫": (48.8606, 2.3376), "Louvre": (48.8606, 2.3376),
        "曼谷": (13.7563, 100.5018), "Bangkok": (13.7563, 100.5018),
        "纽约": (40.7128, -74.0060), "New York": (40.7128, -74.0060),
        "首尔": (37.5665, 126.9780), "Seoul": (37.5665, 126.9780),
        "新加坡": (1.3521, 103.8198), "Singapore": (1.3521, 103.8198),
        "成都": (30.5728, 104.0668), "Chengdu": (30.5728, 104.0668),
        "三亚": (18.2528, 109.5120), "Sanya": (18.2528, 109.5120),
        "马尔代夫": (4.1755, 73.5093), "Maldives": (4.1755, 73.5093),
    }

    # 先查已知坐标
    if address in known:
        lat, lng = known[address]
        return {"lat": lat, "lng": lng, "source": "known_cache", "degraded": False}

    # 尝试 Nominatim API
    try:
        result = await client.geocode(address)
        if result:
            return {"lat": result["lat"], "lng": result["lng"], "source": "nominatim", "degraded": False}
    except Exception:
        pass

    # 降级: 模糊匹配已知坐标
    logger.warning(f"地理编码失败，降级到模糊匹配: {address}")
    for key, (lat, lng) in known.items():
        if key.lower() in address.lower() or address.lower() in key.lower():
            return {"lat": lat, "lng": lng, "source": "fuzzy_match", "degraded": True}

    # 彻底失败: 返回默认坐标（城市中心）
    logger.warning(f"地理编码完全失败，返回默认值: {address}")
    return {"lat": 0.0, "lng": 0.0, "source": "fallback_default", "degraded": True}


# ============================================================
# 公共 API — 地理校验
# ============================================================

def validate_geography(
    itinerary_day: Dict[str, Any],
) -> Dict[str, Any]:
    """验证单日地理逻辑。

    v1.1.0: 使用 Haversine 公式计算（不依赖 API 坐标获取，由调用方提供坐标）。
    绕路检测逻辑保持不变。

    Args:
        itinerary_day: 含 {activities: [{name, location: {lat, lng}}]}

    Returns:
        {detour_ratio, actual_distance_km, optimal_distance_km, warnings, optimized_route}
    """
    activities = itinerary_day.get("activities", [])
    points: List[Dict[str, float]] = []

    for act in activities:
        loc = act.get("location")
        if isinstance(loc, dict) and "lat" in loc and "lng" in loc:
            points.append({"lat": loc["lat"], "lng": loc["lng"]})

    if len(points) < 2:
        return {
            "detour_ratio": 1.0,
            "actual_distance_km": 0.0,
            "optimal_distance_km": 0.0,
            "warnings": [],
            "optimized_route": None,
        }

    optimal = _optimal_path_length(points)
    actual = _actual_path_length(points)
    detour_ratio = actual / optimal if optimal > 0 else 1.0

    warnings = []
    if detour_ratio > 1.0:
        warnings.append({
            "type": "detour",
            "ratio": round(detour_ratio, 2),
            "actual_km": round(actual, 1),
            "optimal_km": round(optimal, 1),
        })

    # 贪心优化路线建议
    optimized_route = None
    if detour_ratio > _DETOUR_RATIO_THRESHOLD and len(points) >= 3:
        visited = [False] * len(points)
        visited[0] = True
        order = [0]
        current = 0
        for _ in range(len(points) - 1):
            nearest = min(
                (j for j in range(len(points)) if not visited[j]),
                key=lambda j: _haversine_distance(
                    points[current]["lat"], points[current]["lng"],
                    points[j]["lat"], points[j]["lng"],
                ),
            )
            visited[nearest] = True
            order.append(nearest)
            current = nearest
        optimized_route = [activities[i].get("name", str(i)) for i in order]

    return {
        "detour_ratio": round(detour_ratio, 2),
        "actual_distance_km": round(actual, 1),
        "optimal_distance_km": round(optimal, 1),
        "warnings": warnings,
        "optimized_route": optimized_route,
    }


def check_geography(
    daily_itinerary: List[Dict[str, Any]],
) -> Dict[str, Any]:
    """地理逻辑校验。

    校验规则 (spec/executor_spec.md §2.4):
    - 实际路线 / 最优路径 > 1.5 → detour
    - 单程交通 > 3h → 需特别说明
    - 同天景点间距离 > 30km → warning

    Args:
        daily_itinerary: 每日行程列表

    Returns:
        {detours_found, detours, overall_geo_status, overall_geo_score, warnings, degraded}
    """
    detours: List[Dict[str, Any]] = []
    warnings: List[Dict[str, Any]] = []
    detours_found = 0
    degraded = False

    for day_entry in daily_itinerary:
        day_num = day_entry.get("day", 0)
        result = validate_geography(day_entry)

        if result["detour_ratio"] > _DETOUR_RATIO_THRESHOLD:
            detours_found += 1
            detours.append({
                "day": day_num,
                "description": f"第{day_num}天路线绕路比 {result['detour_ratio']} > {_DETOUR_RATIO_THRESHOLD}",
                "detour_ratio": result["detour_ratio"],
                "wasted_time_minutes": int(
                    (result["actual_distance_km"] - result["optimal_distance_km"]) / 25 * 60
                ),
                "optimized_route": result.get("optimized_route"),
            })

        # 检查同天景点间最大距离
        activities = day_entry.get("activities", [])
        for i, a1 in enumerate(activities):
            loc1 = a1.get("location", {})
            if not isinstance(loc1, dict):
                continue
            for a2 in activities[i + 1:]:
                loc2 = a2.get("location", {})
                if not isinstance(loc2, dict):
                    continue
                try:
                    dist = _haversine_distance(
                        loc1["lat"], loc1["lng"],
                        loc2["lat"], loc2["lng"],
                    )
                    if dist > _MAX_SAME_DAY_DISTANCE_KM:
                        warnings.append({
                            "day": day_num,
                            "issue": f"景点 '{a1.get('name')}' 与 '{a2.get('name')}' 相距 {dist:.0f}km > {_MAX_SAME_DAY_DISTANCE_KM}km",
                            "suggestion": "建议调整到不同天",
                        })
                except (KeyError, TypeError):
                    pass

        # 检查长途转移
        transit_notes = day_entry.get("transportation_notes", "")
        for activity in activities:
            duration = activity.get("transit_duration_minutes", 0)
            if duration > _LONG_TRANSIT_MINUTES and not transit_notes:
                warnings.append({
                    "day": day_num,
                    "issue": f"单程交通 {duration}min > 3h 但缺少特别说明",
                    "suggestion": "请标注该长途转移的交通方式和原因",
                })

    # 计算综合得分
    if detours_found > 1:
        overall_score = max(0, 100 - detours_found * 25 - len(warnings) * 5)
        overall_status = "failed"
    elif detours_found > 0:
        overall_score = max(60, 100 - detours_found * 20 - len(warnings) * 5)
        overall_status = "passed_with_warnings"
    elif warnings:
        overall_score = max(60, 100 - len(warnings) * 10)
        overall_status = "passed_with_warnings"
    else:
        overall_score = 100
        overall_status = "passed"

    result: Dict[str, Any] = {
        "detours_found": detours_found,
        "detours": detours,
        "overall_geo_status": overall_status,
        "overall_geo_score": overall_score,
        "warnings": warnings,
        "degraded": degraded,
    }

    if degraded:
        result["notes"] = "部分地理数据来自 Haversine 估算，非实时地图 API"

    return result
