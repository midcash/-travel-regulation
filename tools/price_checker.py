"""价格校验工具 — stub 实现。

v1.0.0: 使用内置参考价格表，不接真实 API。
后续版本: 接入携程/飞猪/Booking.com 等价格 API。

来源: spec/executor_spec.md §2.2, §2.5
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

# ============================================================
# 内置参考价格表 (stub 数据)
# ============================================================

_MARKET_PRICES: Dict[str, Dict[str, List[float]]] = {
    # item_type → { location → [low, median, high] }
    "flight_domestic": {
        "default": [300, 800, 2000],
        "北京": [400, 1000, 2500], "Beijing": [400, 1000, 2500],
        "上海": [350, 900, 2200], "Shanghai": [350, 900, 2200],
        "广州": [300, 700, 1800], "Guangzhou": [300, 700, 1800],
        "成都": [400, 900, 2000], "Chengdu": [400, 900, 2000],
        "三亚": [500, 1200, 3000], "Sanya": [500, 1200, 3000],
        "东京": [1500, 3000, 6000], "Tokyo": [1500, 3000, 6000],
        "曼谷": [800, 1800, 3500], "Bangkok": [800, 1800, 3500],
        "巴黎": [3000, 6000, 12000], "Paris": [3000, 6000, 12000],
    },
    "hotel_per_night": {
        "default": [100, 300, 800],
        "东京": [300, 600, 1500], "Tokyo": [300, 600, 1500],
        "北京": [150, 350, 1000], "Beijing": [150, 350, 1000],
        "上海": [150, 350, 1000], "Shanghai": [150, 350, 1000],
        "曼谷": [80, 200, 600], "Bangkok": [80, 200, 600],
        "巴黎": [400, 800, 2000], "Paris": [400, 800, 2000],
        "马尔代夫": [1000, 3000, 10000], "Maldives": [1000, 3000, 10000],
    },
    "attraction_ticket": {
        "default": [20, 80, 200],
        "东京": [30, 100, 300], "Tokyo": [30, 100, 300],
        "北京": [20, 60, 150], "Beijing": [20, 60, 150],
        "巴黎": [50, 120, 300], "Paris": [50, 120, 300],
    },
    "meal_per_person": {
        "default": [15, 40, 100],
        "东京": [25, 60, 150], "Tokyo": [25, 60, 150],
        "北京": [10, 30, 80], "Beijing": [10, 30, 80],
        "巴黎": [20, 50, 120], "Paris": [20, 50, 120],
    },
    "local_transport_per_day": {
        "default": [10, 30, 80],
        "东京": [20, 50, 120], "Tokyo": [20, 50, 120],
        "北京": [5, 15, 40], "Beijing": [5, 15, 40],
    },
}


def estimate_market_price(
    item_type: str,
    location: str,
    date: Optional[str] = None,
) -> Dict[str, Any]:
    """查询市场行情价 (stub)。

    Args:
        item_type: 价格类型 (flight_domestic / hotel_per_night / attraction_ticket / meal_per_person)
        location: 城市名称
        date: 日期 (当前 stub 实现忽略)

    Returns:
        {low, median, high, currency, source_type, data_date}
    """
    type_prices = _MARKET_PRICES.get(item_type, _MARKET_PRICES.get("hotel_per_night", {}))
    prices = type_prices.get(location, type_prices.get("default", [100, 300, 800]))

    return {
        "low": prices[0],
        "median": prices[1],
        "high": prices[2],
        "currency": "CNY",
        "source_type": "estimated",
        "data_date": None,
        "confidence": "medium",
    }


def check_prices(
    items: List[Dict[str, Any]],
    location: str = "default",
) -> Dict[str, Any]:
    """价格合理性校验 (stub)。

    对每一项预估价格进行市场行情比对，计算偏差率。

    校验规则 (spec/executor_spec.md §2.2):
    - 偏差率 ≤ 10%: severity=low
    - 偏差率 10%-30%: severity=medium
    - 偏差率 > 30%: severity=high
    - 累计异常项 ≥ 3 项 → overall_status="failed"

    Args:
        items: 待校验的价格项列表，每项含 {item, type, estimated_price}
        location: 目的地城市

    Returns:
        PriceCheckResult 字典
    """
    anomalies: List[Dict[str, Any]] = []
    items_checked = 0
    total_deviation = 0.0

    for item in items:
        item_name = item.get("item", "unknown")
        item_type = item.get("type", "hotel_per_night")
        estimated = item.get("estimated_price", 0)

        if estimated <= 0:
            continue

        market = estimate_market_price(item_type, location)
        median = market["median"]

        if median > 0:
            deviation_pct = abs(estimated - median) / median * 100
        else:
            deviation_pct = 0

        total_deviation += deviation_pct
        items_checked += 1

        if deviation_pct > 30:
            severity = "high"
        elif deviation_pct > 10:
            severity = "medium"
        else:
            severity = "low"

        if severity != "low":
            anomalies.append({
                "item": item_name,
                "estimated": estimated,
                "market_median": median,
                "market_range": [market["low"], market["high"]],
                "deviation_pct": round(deviation_pct, 1),
                "severity": severity,
                "suggestion": (
                    f"建议核实 {item_name} 价格" if severity == "medium"
                    else f"建议重新评估 {item_name} 价格，偏差过大"
                ),
            })

    # 计算综合准确度得分
    if items_checked > 0:
        avg_deviation = total_deviation / items_checked
        accuracy_score = max(0, 100 - avg_deviation * 2)
    else:
        accuracy_score = 100

    # 判定 overall_status
    high_count = sum(1 for a in anomalies if a["severity"] == "high")
    if len(anomalies) >= 3 and high_count > 0:
        overall_status = "failed"
    elif anomalies:
        overall_status = "passed_with_warnings"
    else:
        overall_status = "passed"

    return {
        "items_checked": items_checked,
        "anomalies": anomalies,
        "overall_accuracy_score": round(accuracy_score, 1),
        "overall_status": overall_status,
        "notes": "stub 实现 — 使用内置参考价格表",
    }


def check_budget_compliance(
    planned_total: float,
    budget_limit: float,
    tolerance_pct: float = 10.0,
) -> Dict[str, Any]:
    """预算合规性校验 (stub)。

    硬约束: 总费用 ≤ 预算上限 (含容差)。
    超支 > tolerance_pct 视为 blocking。

    Args:
        planned_total: 规划总费用
        budget_limit: 用户预算上限
        tolerance_pct: 容差百分比 (默认 10%)

    Returns:
        {compliant, overage_pct, blocking, message}
    """
    if budget_limit <= 0:
        return {
            "compliant": False,
            "overage_pct": 100.0,
            "blocking": True,
            "message": "预算上限无效 (≤ 0)",
        }

    if planned_total <= budget_limit:
        return {
            "compliant": True,
            "overage_pct": 0.0,
            "blocking": False,
            "message": "预算合规",
        }

    overage_pct = (planned_total - budget_limit) / budget_limit * 100

    if overage_pct <= tolerance_pct:
        return {
            "compliant": True,
            "overage_pct": round(overage_pct, 1),
            "blocking": False,
            "message": f"预算在容差范围内 (超出 {overage_pct:.1f}%)",
        }

    return {
        "compliant": False,
        "overage_pct": round(overage_pct, 1),
        "blocking": True,
        "message": f"预算超支 {overage_pct:.1f}%，超出容差上限 {tolerance_pct}%",
    }
