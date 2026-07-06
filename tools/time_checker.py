"""时间可行性校验工具 — 高德地图版。

v1.1.0: 双轨架构 — API 可用时调用高德地图路径规划 API 获取真实交通时间；
不可用时降级到 Haversine 估算 + 规则引擎。

来源: spec/executor_spec.md §2.3, handoff.md §5.3 §5.5
"""

from __future__ import annotations

import asyncio
import logging
import math
from datetime import datetime as dt, timedelta
from typing import Any, Dict, List, Optional

from core.config import API_TIMEOUT, get_config

logger = logging.getLogger(__name__)

# ============================================================
# 内置常量
# ============================================================

_DEFAULT_TRANSIT_SAME_AREA = 30
_DEFAULT_TRANSIT_CROSS_AREA = 60
_MAX_DAILY_TOTAL_MINUTES = 12 * 60
_WARNING_THRESHOLD_MINUTES = 10 * 60
_DEFAULT_OPENING_HOURS = {"open": "09:00", "close": "17:00"}
_LUNCH_WINDOW = ("11:30", "13:30")
_DINNER_WINDOW = ("17:30", "20:00")

# 高德路径规划模式映射
_AMAP_STRATEGY_MAP = {
    "driving": "0",          # 驾车最快
    "walking": None,         # 步行用独立 API
}


# ============================================================
# 高德地图路径规划客户端
# ============================================================

class AmapDirectionsClient:
    """高德地图路径规划 API 客户端。

    免费层: 5,000 次/天。
    认证方式: key 查询参数。
    """

    def __init__(self):
        self._config = get_config()

    @property
    def available(self) -> bool:
        """客户端是否可用（高德 API key 已配置）。"""
        return self._config.is_configured("amap")

    async def get_travel_time(
        self,
        origin: Dict[str, float],
        destination: Dict[str, float],
        mode: str = "driving",
    ) -> Optional[Dict[str, Any]]:
        """查询两点间的交通时间（高德路径规划 API）。

        Args:
            origin: {"lat": float, "lng": float}
            destination: {"lat": float, "lng": float}
            mode: "driving" | "walking"

        Returns:
            {duration_minutes, distance_km, mode, source_type} 或 None。
        """
        if not self.available:
            return None

        import urllib.request
        import json as _json

        lat1 = origin.get("lat", 0)
        lng1 = origin.get("lng", 0)
        lat2 = destination.get("lat", 0)
        lng2 = destination.get("lng", 0)

        key = self._config.amap_api_key

        if mode == "walking":
            url = (
                f"{self._config.amap_base_url}/v3/direction/walking"
                f"?key={key}&origin={lng1},{lat1}&destination={lng2},{lat2}"
                f"&output=JSON"
            )
        else:
            strategy = _AMAP_STRATEGY_MAP.get(mode, "0")
            url = (
                f"{self._config.amap_base_url}/v3/direction/driving"
                f"?key={key}&origin={lng1},{lat1}&destination={lng2},{lat2}"
                f"&strategy={strategy}&output=JSON"
            )

        try:
            async def _call():
                req = urllib.request.Request(url, headers={"Accept": "application/json"})
                resp = urllib.request.urlopen(req, timeout=self._config.api_timeout)
                return _json.loads(resp.read())

            data = await asyncio.wait_for(_call(), timeout=self._config.api_timeout)

            if data.get("status") != "1":
                logger.warning(f"高德路径规划失败: status={data.get('status')}, info={data.get('info')}")
                return None

            route_key = "route"
            route = data.get(route_key, {})
            paths = route.get("paths", [])
            if not paths:
                logger.warning(f"高德未找到路线: ({lat1},{lng1}) → ({lat2},{lng2})")
                return None

            path = paths[0]
            distance_meters = int(path.get("distance", 0))
            duration_seconds = int(path.get("duration", 0))

            return {
                "origin": origin,
                "destination": destination,
                "distance_km": round(distance_meters / 1000, 1),
                "duration_minutes": max(1, round(duration_seconds / 60)),
                "mode": mode,
                "is_cross_area": (distance_meters / 1000) > 15,
                "source_type": "api",
            }
        except asyncio.TimeoutError:
            logger.warning(f"高德路径规划超时: ({lat1},{lng1}) → ({lat2},{lng2})")
            return None
        except Exception as exc:
            logger.warning(f"高德路径规划失败: {exc}")
            return None


# ============================================================
# 模块级客户端实例
# ============================================================

_directions_client: Optional[AmapDirectionsClient] = None


def _get_directions() -> AmapDirectionsClient:
    global _directions_client
    if _directions_client is None:
        _directions_client = AmapDirectionsClient()
    return _directions_client


# ============================================================
# 降级: Haversine 距离估算
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


def _estimate_transit_time(
    lat1: float, lng1: float, lat2: float, lng2: float, mode: str
) -> Dict[str, Any]:
    """降级: Haversine 距离 + 估算速度 → 时间。"""
    distance_km = _haversine_distance(lat1, lng1, lat2, lng2)

    if mode == "walking":
        speed_kmh = 5.0
    elif mode == "driving":
        speed_kmh = 40.0
    else:
        speed_kmh = 25.0

    duration_minutes = int(distance_km / speed_kmh * 60)
    duration_minutes = max(duration_minutes, _DEFAULT_TRANSIT_SAME_AREA)
    is_cross_area = distance_km > 15

    return {
        "origin": {"lat": lat1, "lng": lng1},
        "destination": {"lat": lat2, "lng": lng2},
        "distance_km": round(distance_km, 1),
        "duration_minutes": duration_minutes,
        "mode": mode,
        "is_cross_area": is_cross_area,
        "source_type": "estimated",
    }


# ============================================================
# 公共 API — 开放时间查询
# ============================================================

def check_opening_hours(
    place_name: str,
    date: Optional[str] = None,
) -> Dict[str, Any]:
    """查询景点开放时间。

    v1.1.0: 使用内置规则（周一闭馆等）。API 接入留待后续版本。

    Args:
        place_name: 景点名称
        date: 日期 YYYY-MM-DD

    Returns:
        {place_name, open, close, is_closed, notes, source_type}
    """
    is_monday = False
    if date:
        try:
            d = dt.fromisoformat(date)
            is_monday = d.weekday() == 0
        except (ValueError, TypeError):
            pass

    # 博物馆/美术馆类周一闭馆
    museum_keywords = ["museum", "博物馆", "美术馆", "gallery", "展览"]
    is_museum = any(kw in place_name.lower() for kw in museum_keywords)

    return {
        "place_name": place_name,
        "open": _DEFAULT_OPENING_HOURS["open"],
        "close": _DEFAULT_OPENING_HOURS["close"],
        "is_closed": is_monday and is_museum,
        "notes": (
            "博物馆/美术馆类周一闭馆" if is_museum
            else "使用默认营业时间 9:00-17:00"
        ),
        "source_type": "estimated",
    }


# ============================================================
# 公共 API — 交通时间计算 (async)
# ============================================================

async def calculate_transit_time_async(
    origin: Dict[str, float],
    destination: Dict[str, float],
    mode: str = "public_transit",
) -> Dict[str, Any]:
    """计算两地之间的交通时间 (async, API + 降级)。

    Args:
        origin: {"lat": float, "lng": float}
        destination: {"lat": float, "lng": float}
        mode: "public_transit" | "walking" | "driving"

    Returns:
        {origin, destination, distance_km, duration_minutes, mode, is_cross_area, source_type, degraded}
    """
    lat1 = origin.get("lat", 0)
    lng1 = origin.get("lng", 0)
    lat2 = destination.get("lat", 0)
    lng2 = destination.get("lng", 0)

    # 高德支持 driving/walking，public_transit 降级为 driving
    amap_mode = mode if mode in ("driving", "walking") else "driving"

    # 尝试高德 API
    client = _get_directions()
    if client.available:
        try:
            result = await client.get_travel_time(origin, destination, amap_mode)
            if result:
                return {**result, "degraded": False}
        except Exception:
            pass

        logger.warning(
            f"高德路径规划不可用，降级到 Haversine 估算: "
            f"({lat1},{lng1}) → ({lat2},{lng2})"
        )

    # 降级到 Haversine
    estimated = _estimate_transit_time(lat1, lng1, lat2, lng2, mode)
    return {**estimated, "degraded": True}


def calculate_transit_time(
    origin: Dict[str, float],
    destination: Dict[str, float],
    mode: str = "public_transit",
) -> Dict[str, Any]:
    """计算两地之间的交通时间 (同步包装器)。

    保持 v1.0.0 签名完全兼容。
    """
    import asyncio as _asyncio
    lat1 = origin.get("lat", 0)
    lng1 = origin.get("lng", 0)
    lat2 = destination.get("lat", 0)
    lng2 = destination.get("lng", 0)
    try:
        loop = _asyncio.get_running_loop()
        estimated = _estimate_transit_time(lat1, lng1, lat2, lng2, mode)
        return {**estimated, "degraded": True}
    except RuntimeError:
        return _asyncio.run(calculate_transit_time_async(origin, destination, mode))


# ============================================================
# 公共 API — 时间校验
# ============================================================

def check_time(
    daily_itinerary: List[Dict[str, Any]],
) -> Dict[str, Any]:
    """时间可行性校验。

    校验规则 (spec/executor_spec.md §2.3):
    - 总时间 > 12h → conflict (severity: high)
    - 总时间 10-12h → warning (severity: low)
    - 用餐时间被活动占用 → warning (severity: medium)

    Args:
        daily_itinerary: 每日行程 [{day, activities, meals, transit_minutes}]

    Returns:
        {days_checked, conflicts, overall_time_status, overall_time_score, warnings, degraded}
    """
    conflicts: List[Dict[str, Any]] = []
    warnings_list: List[Dict[str, Any]] = []
    days_checked = 0
    degraded = False

    for day_entry in daily_itinerary:
        day_num = day_entry.get("day", days_checked + 1)
        activities = day_entry.get("activities", [])
        transit_minutes = day_entry.get("transit_minutes", 0)

        total_activity_minutes = sum(
            a.get("duration_minutes", 60) for a in activities
        )
        total_minutes = total_activity_minutes + transit_minutes

        if total_minutes > _MAX_DAILY_TOTAL_MINUTES:
            conflicts.append({
                "day": day_num,
                "issue": f"第{day_num}天总时长 {total_minutes // 60}h{total_minutes % 60}min 超过上限 12h",
                "severity": "high",
                "suggestion": f"建议减少活动或缩短交通时间 (当前超出 {total_minutes - _MAX_DAILY_TOTAL_MINUTES}min)",
                "affected_activities": [a.get("name", "") for a in activities],
            })
        elif total_minutes > _WARNING_THRESHOLD_MINUTES:
            warnings_list.append({
                "day": day_num,
                "issue": f"第{day_num}天总时长接近上限 ({total_minutes // 60}h{total_minutes % 60}min / 12h)",
                "severity": "low",
                "suggestion": "关注疲劳度，避免安排过密",
            })

        # 检查午餐/晚餐时段冲突
        for activity in activities:
            start = activity.get("start_time", "")
            duration = activity.get("duration_minutes", 0)
            if not start or not duration:
                continue
            try:
                act_start = dt.strptime(start, "%H:%M")
                act_end = act_start + timedelta(minutes=duration)
                lunch_start = dt.strptime(_LUNCH_WINDOW[0], "%H:%M")
                lunch_end = dt.strptime(_LUNCH_WINDOW[1], "%H:%M")
                dinner_start = dt.strptime(_DINNER_WINDOW[0], "%H:%M")
                dinner_end = dt.strptime(_DINNER_WINDOW[1], "%H:%M")

                if act_start < lunch_end and act_end > lunch_start:
                    warnings_list.append({
                        "day": day_num,
                        "issue": f"活动 '{activity.get('name')}' 占用午餐时段",
                        "severity": "medium",
                        "suggestion": "建议预留午餐时间",
                    })
                elif act_start < dinner_end and act_end > dinner_start:
                    warnings_list.append({
                        "day": day_num,
                        "issue": f"活动 '{activity.get('name')}' 占用晚餐时段",
                        "severity": "medium",
                        "suggestion": "建议预留晚餐时间",
                    })
            except (ValueError, TypeError):
                pass

        days_checked += 1

    conflict_count = len(conflicts)
    warning_count = len(warnings_list)
    if conflict_count > 0:
        overall_score = max(0, 100 - conflict_count * 30 - warning_count * 5)
        overall_status = "failed"
    elif warning_count > 0:
        overall_score = max(60, 100 - warning_count * 10)
        overall_status = "passed_with_warnings"
    else:
        overall_score = 100
        overall_status = "passed"

    result: Dict[str, Any] = {
        "days_checked": days_checked,
        "conflicts": conflicts,
        "overall_time_status": overall_status,
        "overall_time_score": overall_score,
        "warnings": warnings_list,
        "degraded": degraded,
    }

    if degraded:
        result["notes"] = "交通时间来自 Haversine 估算，非实时地图数据"

    return result
