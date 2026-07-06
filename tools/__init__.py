"""tools 包 — Agent 可调用的工具集。

v1.0.0 使用 stub/mock 实现，不接真实 API。
后续版本逐步接入真实数据源。

来源: spec/executor_spec.md §3, playbooks/executor_playbook.md §4
"""

from tools.price_checker import (
    check_budget_compliance,
    check_prices,
    estimate_market_price,
)
from tools.time_checker import (
    calculate_transit_time,
    check_opening_hours,
    check_time,
)
from tools.geo_checker import (
    check_geography,
    geocode_async,
    validate_geography,
)
from tools.risk_checker import (
    check_travel_requirements,
    check_weather_risk,
)

__version__ = "1.0.0-dev"

__all__ = [
    # 价格/预算
    "check_prices",
    "check_budget_compliance",
    "estimate_market_price",
    # 时间
    "check_time",
    "check_opening_hours",
    "calculate_transit_time",
    # 地理
    "check_geography",
    "geocode_async",
    "validate_geography",
    # 风险/证件
    "check_weather_risk",
    "check_travel_requirements",
]
