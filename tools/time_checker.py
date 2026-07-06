"""时间可行性校验工具 — stub 实现。

v1.0.0: 使用内置规则引擎，不接真实 API。
后续版本: 接入景点开放时间 API、地图 API。

来源: spec/executor_spec.md §2.3
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

# ============================================================
# 内置常量
# ============================================================

_DEFAULT_TRANSIT_SAME_AREA = 30     # 同区域默认中转时间 (分钟)
_DEFAULT_TRANSIT_CROSS_AREA = 60    # 跨区域默认中转时间 (分钟)
_MAX_DAILY_TOTAL_MINUTES = 12 * 60  # 每日上限 12h = 720min
_WARNING_THRESHOLD_MINUTES = 10 * 60  # 告警阈值 10h = 600min

# 标准开放时间
_DEFAULT_OPENING_HOURS = {"open": "09:00", "close": "17:00"}

# 午餐/晚餐默认时段
_LUNCH_WINDOW = ("11:30", "13:30")
_DINNER_WINDOW = ("17:30", "20:00")


def check_opening_hours(
    place_name: str,
    date: Optional[str] = None,
) -> Dict[str, Any]:
    """查询景点开放时间 (stub)。

    Args:
        place_name: 景点名称
        date: 日期 (当前 stub 实现忽略)

    Returns:
        {open, close, is_closed, notes}
    """
    # 周一闭馆规则 (stub)
    is_monday = False
    if date:
        from datetime import date as dt, timedelta
        try:
            d = dt.fromisoformat(date)
            is_monday = d.weekday() == 0
        except (ValueError, TypeError):
            pass

    return {
        "place_name": place_name,
        "open": _DEFAULT_OPENING_HOURS["open"],
        "close": _DEFAULT_OPENING_HOURS["close"],
        "is_closed": is_monday and "museum" in place_name.lower(),
        "notes": "stub: 默认 9:00-17:00，博物馆类周一闭馆",
        "source_type": "estimated",
    }


def calculate_transit_time(
    origin: Dict[str, float],
    destination: Dict[str, float],
    mode: str = "public_transit",
) -> Dict[str, Any]:
    """计算两地之间的中转时间 (stub)。

    Args:
        origin: {"lat": float, "lng": float}
        destination: {"lat": float, "lng": float}
        mode: 交通方式 (public_transit / walking / driving)

    Returns:
        {duration_minutes, distance_km, mode}
    """
    import math

    lat1 = origin.get("lat", 0)
    lng1 = origin.get("lng", 0)
    lat2 = destination.get("lat", 0)
    lng2 = destination.get("lng", 0)

    # Haversine 公式计算球面距离
    R = 6371  # 地球半径 (km)
    dlat = math.radians(lat2 - lat1)
    dlng = math.radians(lng2 - lng1)
    a = (
        math.sin(dlat / 2) ** 2
        + math.cos(math.radians(lat1))
        * math.cos(math.radians(lat2))
        * math.sin(dlng / 2) ** 2
    )
    c = 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))
    distance_km = R * c

    # 估算时间 (stub)
    if mode == "walking":
        speed_kmh = 5.0
    elif mode == "driving":
        speed_kmh = 40.0
    else:  # public_transit
        speed_kmh = 25.0

    duration_minutes = int(distance_km / speed_kmh * 60)
    duration_minutes = max(duration_minutes, _DEFAULT_TRANSIT_SAME_AREA)

    # 判断同区域/跨区域
    is_cross_area = distance_km > 15

    return {
        "origin": origin,
        "destination": destination,
        "distance_km": round(distance_km, 1),
        "duration_minutes": duration_minutes,
        "mode": mode,
        "is_cross_area": is_cross_area,
        "source_type": "estimated",
    }


def check_time(
    daily_itinerary: List[Dict[str, Any]],
) -> Dict[str, Any]:
    """时间可行性校验 (stub)。

    校验规则 (spec/executor_spec.md §2.3):
    - 总时间 > 12h → conflict (severity: high)
    - 总时间 10-12h → warning (severity: low)
    - 用餐时间被活动占用 → warning (severity: medium)

    Args:
        daily_itinerary: 每日行程列表，每天含 {day, activities, meals, transit_minutes}

    Returns:
        TimeCheckResult 字典
    """
    conflicts: List[Dict[str, Any]] = []
    warnings_list: List[Dict[str, Any]] = []
    days_checked = 0

    for day_entry in daily_itinerary:
        day_num = day_entry.get("day", days_checked + 1)
        activities = day_entry.get("activities", [])
        transit_minutes = day_entry.get("transit_minutes", 0)

        # 计算活动总时长
        total_activity_minutes = sum(
            a.get("duration_minutes", 60) for a in activities
        )
        total_minutes = total_activity_minutes + transit_minutes

        # 超过 12h → conflict
        if total_minutes > _MAX_DAILY_TOTAL_MINUTES:
            conflicts.append({
                "day": day_num,
                "issue": f"第{day_num}天总时长 {total_minutes//60}h{total_minutes%60}min 超过上限 12h",
                "severity": "high",
                "suggestion": f"建议减少活动或缩短交通时间 (当前超出 {total_minutes - _MAX_DAILY_TOTAL_MINUTES}min)",
                "affected_activities": [a.get("name", "") for a in activities],
            })
        elif total_minutes > _WARNING_THRESHOLD_MINUTES:
            warnings_list.append({
                "day": day_num,
                "issue": f"第{day_num}天总时长接近上限 ({total_minutes//60}h{total_minutes%60}min / 12h)",
                "severity": "low",
                "suggestion": "关注疲劳度，避免安排过密",
            })

        # 检查午餐/晚餐时段冲突
        for activity in activities:
            start = activity.get("start_time", "")
            duration = activity.get("duration_minutes", 0)
            if not start or not duration:
                continue

            # 简单 stub: 检查活动是否覆盖 11:30-13:30 (午餐) 或 17:30-20:00 (晚餐)
            try:
                from datetime import datetime, timedelta
                act_start = datetime.strptime(start, "%H:%M")
                act_end = act_start + timedelta(minutes=duration)

                lunch_start = datetime.strptime(_LUNCH_WINDOW[0], "%H:%M")
                lunch_end = datetime.strptime(_LUNCH_WINDOW[1], "%H:%M")
                dinner_start = datetime.strptime(_DINNER_WINDOW[0], "%H:%M")
                dinner_end = datetime.strptime(_DINNER_WINDOW[1], "%H:%M")

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

    # 计算综合得分
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

    return {
        "days_checked": days_checked,
        "conflicts": conflicts,
        "overall_time_status": overall_status,
        "overall_time_score": overall_score,
        "warnings": warnings_list,
        "notes": "stub 实现 — 使用内置规则引擎",
    }
