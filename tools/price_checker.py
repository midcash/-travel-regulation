"""价格校验工具 — API 接入版。

v1.1.0: 双轨架构 — API 可用时调用 Amadeus Self-Service；不可用时降级到内置价格表。
所有降级结果标记 degraded: true + 日志 warning。

来源: spec/executor_spec.md §2.2, §2.5, handoff.md §5.1 §5.5
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any, Dict, List, Optional, Tuple

from core.config import API_TIMEOUT, MAX_RETRIES, RETRY_BACKOFF, get_config

logger = logging.getLogger(__name__)

# ============================================================
# 内置参考价格表 (降级 stub)
# ============================================================

_MARKET_PRICES: Dict[str, Dict[str, List[float]]] = {
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
        "纽约": [3500, 7000, 15000], "New York": [3500, 7000, 15000],
        "新加坡": [1000, 2000, 4000], "Singapore": [1000, 2000, 4000],
        "首尔": [800, 1500, 3000], "Seoul": [800, 1500, 3000],
    },
    "hotel_per_night": {
        "default": [100, 300, 800],
        "东京": [300, 600, 1500], "Tokyo": [300, 600, 1500],
        "北京": [150, 350, 1000], "Beijing": [150, 350, 1000],
        "上海": [150, 350, 1000], "Shanghai": [150, 350, 1000],
        "曼谷": [80, 200, 600], "Bangkok": [80, 200, 600],
        "巴黎": [400, 800, 2000], "Paris": [400, 800, 2000],
        "马尔代夫": [1000, 3000, 10000], "Maldives": [1000, 3000, 10000],
        "纽约": [500, 1200, 3000], "New York": [500, 1200, 3000],
        "新加坡": [200, 500, 1200], "Singapore": [200, 500, 1200],
        "首尔": [150, 350, 800], "Seoul": [150, 350, 800],
    },
    "attraction_ticket": {
        "default": [20, 80, 200],
        "东京": [30, 100, 300], "Tokyo": [30, 100, 300],
        "北京": [20, 60, 150], "Beijing": [20, 60, 150],
        "巴黎": [50, 120, 300], "Paris": [50, 120, 300],
        "纽约": [40, 100, 250], "New York": [40, 100, 250],
    },
    "meal_per_person": {
        "default": [15, 40, 100],
        "东京": [25, 60, 150], "Tokyo": [25, 60, 150],
        "北京": [10, 30, 80], "Beijing": [10, 30, 80],
        "巴黎": [20, 50, 120], "Paris": [20, 50, 120],
        "纽约": [20, 50, 150], "New York": [20, 50, 150],
    },
    "local_transport_per_day": {
        "default": [10, 30, 80],
        "东京": [20, 50, 120], "Tokyo": [20, 50, 120],
        "北京": [5, 15, 40], "Beijing": [5, 15, 40],
        "纽约": [15, 40, 100], "New York": [15, 40, 100],
    },
}


# ============================================================
# API 客户端基类
# ============================================================

class _APIClientBase:
    """API 客户端基类 — 提供超时+重试通用逻辑。

    参考 core/llm_client.py 的架构模式。
    """

    def __init__(self, timeout: int = API_TIMEOUT, max_retries: int = MAX_RETRIES):
        self._timeout = timeout
        self._max_retries = max_retries
        self._backoff = RETRY_BACKOFF

    async def _call_with_retry(self, coro_factory, error_label: str) -> Any:
        """带重试的 API 调用包装器。

        Args:
            coro_factory: 返回协程的可调用对象。
            error_label: 错误日志标签。

        Returns:
            API 响应。

        Raises:
            最后一次重试的异常（超时/限流耗尽重试后抛出）。
        """
        last_error: Optional[Exception] = None
        for attempt in range(self._max_retries):
            try:
                return await asyncio.wait_for(coro_factory(), timeout=self._timeout)
            except asyncio.TimeoutError:
                last_error = TimeoutError(f"{error_label}: 超时 ({self._timeout}s), 第 {attempt + 1} 次")
                logger.warning(str(last_error))
            except Exception as exc:
                last_error = exc
                error_str = str(exc).lower()
                if "429" in error_str or "rate" in error_str:
                    logger.warning(f"{error_label}: 限流 (429), 第 {attempt + 1} 次")
                else:
                    logger.warning(f"{error_label}: {exc}, 第 {attempt + 1} 次")

            if attempt < self._max_retries - 1:
                backoff = self._backoff[min(attempt, len(self._backoff) - 1)]
                await asyncio.sleep(backoff)

        raise last_error  # type: ignore[misc]


# ============================================================
# Amadeus 价格 API 客户端
# ============================================================

class AmadeusPriceClient(_APIClientBase):
    """Amadeus Self-Service API 价格查询客户端。

    免费层: 2000 req/month (测试环境)。
    支持: 航班价格 (Flight Offers Search) / 酒店价格 (Hotel List)。
    """

    def __init__(self):
        super().__init__()
        self._config = get_config()
        self._access_token: Optional[str] = None
        self._token_expiry: float = 0.0

    @property
    def available(self) -> bool:
        """客户端是否可用（Amadeus API key + secret 已配置）。"""
        return self._config.is_configured("amadeus")

    async def _ensure_token(self) -> Optional[str]:
        """获取或刷新 OAuth2 access token。"""
        import time
        if self._access_token and time.time() < self._token_expiry - 60:
            return self._access_token

        if not self.available:
            return None

        try:
            import urllib.request
            import urllib.parse
            import json as _json

            data = urllib.parse.urlencode({
                "grant_type": "client_credentials",
                "client_id": self._config.amadeus_api_key,
                "client_secret": self._config.amadeus_api_secret,
            }).encode()

            async def _fetch():
                req = urllib.request.Request(
                    f"{self._config.amadeus_base_url}/v1/security/oauth2/token",
                    data=data,
                    headers={"Content-Type": "application/x-www-form-urlencoded"},
                    method="POST",
                )
                return urllib.request.urlopen(req, timeout=self._timeout)

            # OAuth token 请求不使用标准 retry（token 获取本身轻量）
            response = await asyncio.wait_for(_fetch(), timeout=self._timeout)
            body = _json.loads(response.read())
            self._access_token = body.get("access_token")
            expires_in = body.get("expires_in", 1800)
            self._token_expiry = time.time() + expires_in
            return self._access_token
        except Exception as exc:
            logger.warning(f"Amadeus OAuth token 获取失败: {exc}")
            return None

    async def search_flight_prices(
        self, origin: str, destination: str, date_str: str
    ) -> Optional[Dict[str, Any]]:
        """查询航班价格 (Amadeus Flight Offers Search API)。

        Returns:
            {low, median, high, currency, source_type} 或 None（API 不可用）。
        """
        token = await self._ensure_token()
        if not token:
            return None

        try:
            import urllib.request
            import json as _json

            url = (
                f"{self._config.amadeus_base_url}/v2/shopping/flight-offers"
                f"?originLocationCode={origin}&destinationLocationCode={destination}"
                f"&departureDate={date_str}&adults=1&max=5"
            )

            async def _call():
                req = urllib.request.Request(
                    url,
                    headers={"Authorization": f"Bearer {token}"},
                )
                resp = urllib.request.urlopen(req, timeout=self._timeout)
                return _json.loads(resp.read())

            data = await self._call_with_retry(_call, "Amadeus Flight Search")
            prices = [
                float(o["price"]["grandTotal"])
                for o in (data.get("data") or [])
                if "price" in o
            ]
            if not prices:
                return None

            prices.sort()
            n = len(prices)
            return {
                "low": prices[0],
                "median": prices[n // 2],
                "high": prices[-1],
                "currency": data.get("meta", {}).get("currency", "CNY"),
                "source_type": "api",
                "data_date": date_str,
                "confidence": "high" if n >= 3 else "medium",
            }
        except Exception as exc:
            logger.warning(f"Amadeus 航班价格查询失败: {exc}")
            return None

    async def search_hotel_prices(
        self, city_code: str, check_in: str
    ) -> Optional[Dict[str, Any]]:
        """查询酒店价格 (Amadeus Hotel List API)。

        Returns:
            {low, median, high, currency, source_type} 或 None。
        """
        token = await self._ensure_token()
        if not token:
            return None

        try:
            import urllib.request
            import json as _json

            url = (
                f"{self._config.amadeus_base_url}/v1/reference-data/locations/hotels/by-city"
                f"?cityCode={city_code}"
            )

            async def _call():
                req = urllib.request.Request(
                    url,
                    headers={"Authorization": f"Bearer {token}"},
                )
                resp = urllib.request.urlopen(req, timeout=self._timeout)
                return _json.loads(resp.read())

            data = await self._call_with_retry(_call, "Amadeus Hotel Search")
            # Hotel List 不直接返回价格；实际价格需通过 Hotel Offers API
            # 这里返回 None 让调用方降级到 stub
            return None
        except Exception as exc:
            logger.warning(f"Amadeus 酒店价格查询失败: {exc}")
            return None


# ============================================================
# 模块级客户端实例 (懒加载)
# ============================================================

_price_client: Optional[AmadeusPriceClient] = None


def _get_price_client() -> AmadeusPriceClient:
    global _price_client
    if _price_client is None:
        _price_client = AmadeusPriceClient()
    return _price_client


# ============================================================
# 公共 API — 价格查询
# ============================================================

async def estimate_market_price_async(
    item_type: str,
    location: str,
    date: Optional[str] = None,
) -> Dict[str, Any]:
    """查询市场行情价 (async, API + stub 降级)。

    优先调用 Amadeus API，不可用时降级到内置价格表。

    Args:
        item_type: 价格类型 (flight_domestic / hotel_per_night / attraction_ticket / meal_per_person)
        location: 城市名称
        date: 日期 YYYY-MM-DD

    Returns:
        {low, median, high, currency, source_type, data_date, degraded, confidence}
    """
    degraded = False
    api_result = None

    # 尝试 API 查询 (目前仅航班有真实 API 支持)
    client = _get_price_client()
    if client.available and item_type == "flight_domestic" and date:
        api_result = await client.search_flight_prices(
            origin="PEK", destination=location, date_str=date
        )

    if api_result is not None:
        return {**api_result, "degraded": False}

    # 降级到 stub
    if client.available:
        logger.warning(
            f"价格 API 查询失败，降级到 stub: item_type={item_type}, location={location}"
        )
    degraded = True

    type_prices = _MARKET_PRICES.get(item_type, _MARKET_PRICES.get("hotel_per_night", {}))
    prices = type_prices.get(location, type_prices.get("default", [100, 300, 800]))

    return {
        "low": prices[0],
        "median": prices[1],
        "high": prices[2],
        "currency": "CNY",
        "source_type": "estimated",
        "data_date": None,
        "confidence": "low" if location not in type_prices else "medium",
        "degraded": degraded,
    }


def estimate_market_price(
    item_type: str,
    location: str,
    date: Optional[str] = None,
) -> Dict[str, Any]:
    """查询市场行情价 (同步包装器)。

    保持 v1.0.0 签名完全兼容。
    """
    import asyncio as _asyncio
    try:
        loop = _asyncio.get_running_loop()
        # 在已有 event loop 中不能 run(); 返回降级结果
        type_prices = _MARKET_PRICES.get(item_type, _MARKET_PRICES.get("hotel_per_night", {}))
        prices = type_prices.get(location, type_prices.get("default", [100, 300, 800]))
        return {
            "low": prices[0], "median": prices[1], "high": prices[2],
            "currency": "CNY", "source_type": "estimated",
            "data_date": None, "confidence": "medium", "degraded": True,
        }
    except RuntimeError:
        return _asyncio.run(estimate_market_price_async(item_type, location, date))


# ============================================================
# 公共 API — 价格校验
# ============================================================

def check_prices(
    items: List[Dict[str, Any]],
    location: str = "default",
) -> Dict[str, Any]:
    """价格合理性校验。

    校验规则 (spec/executor_spec.md §2.2):
    - 偏差率 ≤ 10%: severity=low
    - 偏差率 10%-30%: severity=medium
    - 偏差率 > 30%: severity=high
    - 累计 high ≥ 3 或 anomalies ≥ 4 → overall_status="failed"

    Args:
        items: 待校验价格项 [{item, type, estimated_price}]
        location: 目的地城市

    Returns:
        {items_checked, anomalies, overall_accuracy_score, overall_status, degraded}
    """
    anomalies: List[Dict[str, Any]] = []
    items_checked = 0
    total_deviation = 0.0
    any_degraded = False

    for item in items:
        item_name = item.get("item", "unknown")
        item_type = item.get("type", "hotel_per_night")
        estimated = item.get("estimated_price", 0)

        if estimated <= 0:
            continue

        market = estimate_market_price(item_type, location)
        median = market["median"]
        if market.get("degraded"):
            any_degraded = True

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
                    f"建议重新评估 {item_name} 价格，偏差过大"
                    if severity == "high"
                    else f"建议核实 {item_name} 价格"
                ),
            })

    if items_checked > 0:
        avg_deviation = total_deviation / items_checked
        accuracy_score = max(0, 100 - avg_deviation * 2)
    else:
        accuracy_score = 100

    high_count = sum(1 for a in anomalies if a["severity"] == "high")
    if high_count >= 3 or len(anomalies) >= 4:
        overall_status = "failed"
    elif anomalies:
        overall_status = "passed_with_warnings"
    else:
        overall_status = "passed"

    result: Dict[str, Any] = {
        "items_checked": items_checked,
        "anomalies": anomalies,
        "overall_accuracy_score": round(accuracy_score, 1),
        "overall_status": overall_status,
        "degraded": any_degraded,
    }

    if any_degraded:
        result["notes"] = "部分价格数据来自内置参考表，非实时 API"

    return result


# ============================================================
# 公共 API — 预算校验
# ============================================================

def check_budget_compliance(
    planned_total: float,
    budget_limit: float,
    tolerance_pct: float = 10.0,
) -> Dict[str, Any]:
    """预算合规性校验。

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
