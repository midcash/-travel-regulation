"""地理逻辑校验工具 — stub 实现。

v1.0.0: 使用 Haversine 公式 + 贪心算法，不接真实地图 API。
后续版本: 接入高德/Google Maps API。

来源: spec/executor_spec.md §2.4
"""

from __future__ import annotations

import math
from typing import Any, Dict, List, Optional

# ============================================================
# 内置常量
# ============================================================

_DETOUR_RATIO_THRESHOLD = 1.5   # 绕路比阈值
_LONG_TRANSIT_MINUTES = 3 * 60  # 单程 > 3h 需特别说明
_MAX_SAME_DAY_DISTANCE_KM = 30  # 同天景点间最大距离


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
    """贪心最近邻算法估算最优路径长度 (km)。

    以第一个点为起点，每次取最近的未访问点。
    """
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


def validate_geography(
    itinerary_day: Dict[str, Any],
) -> Dict[str, Any]:
    """验证单日地理逻辑 (stub)。

    Args:
        itinerary_day: 包含 {activities: [{name, location: {lat, lng}}]}

    Returns:
        含 detour_ratio, warnings 的字典
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
            "warnings": [],
            "optimized_route": None,
        }

    optimal = _optimal_path_length(points)
    actual = _actual_path_length(points)

    if optimal > 0:
        detour_ratio = actual / optimal
    else:
        detour_ratio = 1.0

    warnings = []
    if detour_ratio > 1.0:
        warnings.append({
            "type": "detour",
            "ratio": round(detour_ratio, 2),
            "actual_km": round(actual, 1),
            "optimal_km": round(optimal, 1),
        })

    return {
        "detour_ratio": round(detour_ratio, 2),
        "actual_distance_km": round(actual, 1),
        "optimal_distance_km": round(optimal, 1),
        "warnings": warnings,
        "optimized_route": None,  # stub 不计算优化路线
    }


def check_geography(
    daily_itinerary: List[Dict[str, Any]],
) -> Dict[str, Any]:
    """地理逻辑校验 (stub)。

    校验规则 (spec/executor_spec.md §2.4):
    - 实际路线 / 最优路径 > 1.5 → detour
    - 单程交通 > 3h → 需特别说明
    - 同天景点间距离 > 30km → warning

    Args:
        daily_itinerary: 每日行程列表

    Returns:
        GeographyCheckResult 字典
    """
    detours: List[Dict[str, Any]] = []
    warnings: List[Dict[str, Any]] = []
    detours_found = 0

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
    if detours_found > 0:
        overall_score = max(0, 100 - detours_found * 25 - len(warnings) * 5)
        overall_status = "failed" if detours_found > 1 else "passed_with_warnings"
    elif warnings:
        overall_score = max(60, 100 - len(warnings) * 10)
        overall_status = "passed_with_warnings"
    else:
        overall_score = 100
        overall_status = "passed"

    return {
        "detours_found": detours_found,
        "detours": detours,
        "overall_geo_status": overall_status,
        "overall_geo_score": overall_score,
        "warnings": warnings,
        "notes": "stub 实现 — Haversine + 贪心算法，无真实地图数据",
    }
