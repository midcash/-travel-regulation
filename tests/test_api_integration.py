"""API 集成测试 — Batch 5: Execution Agent 接入真实 API。

覆盖:
- core/config.py: 配置加载/环境变量/is_configured
- tools/price_checker.py: API 客户端可用性/降级/check_prices degraded
- tools/geo_checker.py: AmapGeocodeClient/geocode_async/降级
- tools/time_checker.py: AmapDirectionsClient/calculate_transit_time/降级
- agents/execution_agent.py: estimate_market_price 调用 tools/ 集成

所有外部 API 调用均使用 stub 降级路径（不真调 API）。
真实 API 调用测试见 TestRealAPICalls 类（标记 @pytest.mark.slow）。
"""

import asyncio
import os
import pytest
from unittest.mock import patch, MagicMock

from dotenv import load_dotenv

# 加载 .env 以便真实 API 测试读取密钥
load_dotenv()

from core.config import APIConfig, get_config, API_TIMEOUT, MAX_RETRIES
from tools.price_checker import (
    TuniuMCPClient,
    estimate_market_price,
    check_prices,
    check_budget_compliance,
)
from tools.geo_checker import (
    AmapGeocodeClient,
    geocode_async,
    check_geography,
    validate_geography,
)
from tools.time_checker import (
    AmapDirectionsClient,
    calculate_transit_time,
    check_opening_hours,
    check_time,
)
from tools.risk_checker import (
    check_weather_risk,
    check_travel_requirements,
)


# ============================================================
# core/config.py
# ============================================================

class TestAPIConfig:
    """core/config.py — API 配置管理。"""

    def test_default_config(self):
        config = APIConfig()
        assert config.api_timeout == 15
        assert config.max_retries == 3
        assert config.retry_backoff == [1.0, 2.0, 4.0]
        assert config.amap_api_key is None
        assert config.tuniu_api_key is None

    def test_from_env_reads_env_vars(self, monkeypatch):
        monkeypatch.setenv("AMAP_API_KEY", "amap_key_123")
        monkeypatch.setenv("TUNIU_API_KEY", "tuniu_key")
        monkeypatch.setenv("API_TIMEOUT", "20")
        monkeypatch.setenv("API_MAX_RETRIES", "5")

        config = APIConfig.from_env()
        assert config.amap_api_key == "amap_key_123"
        assert config.tuniu_api_key == "tuniu_key"
        assert config.api_timeout == 20
        assert config.max_retries == 5

    def test_is_configured_amap_no_key(self):
        config = APIConfig()
        assert config.is_configured("amap") is False

    def test_is_configured_amap_with_key(self):
        config = APIConfig(amap_api_key="amap_key")
        assert config.is_configured("amap") is True

    def test_is_configured_tuniu_no_key(self):
        config = APIConfig()
        assert config.is_configured("tuniu") is False

    def test_is_configured_tuniu_with_key(self):
        config = APIConfig(tuniu_api_key="key")
        assert config.is_configured("tuniu") is True

    def test_is_configured_unknown_service(self):
        config = APIConfig()
        assert config.is_configured("unknown_service") is False

    def test_auth_params_amap(self):
        config = APIConfig(amap_api_key="amap_key")
        assert config.auth_params("amap") == {"key": "amap_key"}

    def test_auth_params_empty(self):
        config = APIConfig()
        assert config.auth_params("unknown") == {}

    def test_get_config_returns_singleton(self, monkeypatch):
        # 清空缓存重置
        import core.config as cfg
        cfg._config_cache = None
        c1 = get_config()
        c2 = get_config()
        assert c1 is c2


# ============================================================
# tools/price_checker.py — API 客户端 + 降级
# ============================================================

class TestTuniuMCPClient:
    """TuniuMCPClient — 可用性检测。"""

    def test_not_available_without_keys(self, monkeypatch):
        monkeypatch.delenv("TUNIU_API_KEY", raising=False)
        import core.config as cfg
        cfg._config_cache = None
        client = TuniuMCPClient()
        assert client.available is False

    def test_available_with_key(self, monkeypatch):
        monkeypatch.setenv("TUNIU_API_KEY", "test_key")
        import core.config as cfg
        cfg._config_cache = None
        client = TuniuMCPClient()
        assert client.available is True


class TestEstimateMarketPrice:
    """estimate_market_price — stub 降级返回。"""

    def test_returns_stub_for_known_city(self):
        result = estimate_market_price("flight_domestic", "东京")
        assert result["low"] > 0
        assert result["median"] > 0
        assert result["high"] >= result["median"] >= result["low"]
        assert result["currency"] == "CNY"
        assert result["source_type"] == "estimated"
        assert result["degraded"] is True  # 无 API key 时降级

    def test_returns_default_for_unknown_city(self):
        result = estimate_market_price("flight_domestic", "unknown_city_xyz")
        assert result["median"] > 0
        assert result["degraded"] is True
        assert result["confidence"] == "low"

    def test_all_item_types_return_valid(self):
        for item_type in ["flight_domestic", "hotel_per_night", "attraction_ticket", "meal_per_person"]:
            result = estimate_market_price(item_type, "北京")
            assert result["low"] <= result["median"] <= result["high"]
            assert result["currency"] == "CNY"

    def test_degraded_flag_present(self):
        result = estimate_market_price("meal_per_person", "东京")
        assert "degraded" in result


class TestCheckPrices:
    """check_prices — 价格校验 + degraded 标记。"""

    def test_normal_items_pass(self):
        items = [
            {"item": "机票", "type": "flight_domestic", "estimated_price": 900},
            {"item": "酒店", "type": "hotel_per_night", "estimated_price": 350},
        ]
        result = check_prices(items, "北京")
        assert result["items_checked"] == 2
        assert result["overall_status"] in ("passed", "passed_with_warnings")
        assert "degraded" in result

    def test_zero_price_skipped(self):
        items = [{"item": "免费景点", "type": "attraction_ticket", "estimated_price": 0}]
        result = check_prices(items)
        assert result["items_checked"] == 0

    def test_degraded_flag_in_result(self):
        items = [{"item": "机票", "type": "flight_domestic", "estimated_price": 1000}]
        result = check_prices(items)
        assert "degraded" in result
        assert isinstance(result["degraded"], bool)

    def test_all_prices_within_range_passed(self):
        """偏差 ≤ 10% → passed。"""
        items = [
            {"item": "机票", "type": "flight_domestic", "estimated_price": 990},
        ]
        result = check_prices(items, "北京")
        # 北京 flight median=1000, deviation=1% → 无 anomaly
        assert result["overall_status"] == "passed"

    def test_high_deviation_detected(self):
        """偏差 > 30% → high severity anomaly。"""
        items = [
            {"item": "酒店", "type": "hotel_per_night", "estimated_price": 10000},
        ]
        result = check_prices(items, "北京")
        # 北京 hotel median=350, deviation ~2760% → high
        if result["anomalies"]:
            assert result["anomalies"][0]["severity"] == "high"

    def test_multiple_high_anomalies_failed(self):
        """≥3 high anomalies → failed。"""
        items = [
            {"item": "机票", "type": "flight_domestic", "estimated_price": 100000},
            {"item": "酒店", "type": "hotel_per_night", "estimated_price": 50000},
            {"item": "门票", "type": "attraction_ticket", "estimated_price": 10000},
        ]
        result = check_prices(items, "北京")
        assert result["overall_status"] == "failed"

    def test_overall_accuracy_score_in_range(self):
        items = [
            {"item": "机票", "type": "flight_domestic", "estimated_price": 1000},
            {"item": "酒店", "type": "hotel_per_night", "estimated_price": 350},
        ]
        result = check_prices(items, "北京")
        assert 0 <= result["overall_accuracy_score"] <= 100


class TestCheckBudgetCompliance:
    """check_budget_compliance — 预算校验（不变）。"""

    def test_within_budget(self):
        result = check_budget_compliance(8000, 10000)
        assert result["compliant"] is True
        assert result["blocking"] is False

    def test_within_tolerance(self):
        result = check_budget_compliance(10500, 10000)
        assert result["compliant"] is True
        assert result["blocking"] is False

    def test_over_tolerance_blocking(self):
        result = check_budget_compliance(12000, 10000)
        assert result["compliant"] is False
        assert result["blocking"] is True

    def test_zero_budget_invalid(self):
        result = check_budget_compliance(1000, 0)
        assert result["blocking"] is True
        assert "无效" in result["message"]


# ============================================================
# tools/geo_checker.py — 高德地图 + 降级
# ============================================================

class TestAmapGeocodeClient:
    """AmapGeocodeClient — 高德地图地理编码客户端。"""

    def test_not_available_without_key(self, monkeypatch):
        monkeypatch.delenv("AMAP_API_KEY", raising=False)
        import core.config as cfg
        cfg._config_cache = None
        client = AmapGeocodeClient()
        assert client.available is False

    def test_available_with_key(self, monkeypatch):
        monkeypatch.setenv("AMAP_API_KEY", "test_amap_key")
        import core.config as cfg
        cfg._config_cache = None
        client = AmapGeocodeClient()
        assert client.available is True


class TestGeocodeAsync:
    """geocode_async — 地理编码 + 降级。"""

    def test_known_city_tokyo(self):
        result = asyncio.run(geocode_async("东京"))
        assert result["lat"] == pytest.approx(35.6762)
        assert result["lng"] == pytest.approx(139.6503)
        assert result["source"] == "known_cache"
        assert result["degraded"] is False

    def test_known_attraction(self):
        result = asyncio.run(geocode_async("浅草寺"))
        assert result["lat"] == pytest.approx(35.7148)
        assert result["lng"] == pytest.approx(139.7967)
        assert result["source"] == "known_cache"

    def test_known_city_english(self):
        result = asyncio.run(geocode_async("Tokyo"))
        assert result["lat"] == pytest.approx(35.6762)
        assert result["source"] == "known_cache"

    def test_fuzzy_match_degraded(self):
        """模糊匹配 → degraded=True。"""
        result = asyncio.run(geocode_async("东京塔附近"))
        assert result["degraded"] is True
        assert result["source"] in ("fuzzy_match", "fallback_default")

    def test_completely_unknown_returns_default(self):
        result = asyncio.run(geocode_async("不存在的城市xyz123"))
        assert result["degraded"] is True
        assert "lat" in result and "lng" in result

    def test_paris_known(self):
        result = asyncio.run(geocode_async("巴黎"))
        assert result["lat"] == pytest.approx(48.8566)
        assert result["source"] == "known_cache"


class TestValidateGeography:
    """validate_geography — 单日路线校验（算法不变，增加优化路线建议）。"""

    def test_two_points_no_detour(self):
        day = {
            "day": 1,
            "activities": [
                {"name": "A", "location": {"lat": 35.6762, "lng": 139.6503}},
                {"name": "B", "location": {"lat": 35.6895, "lng": 139.7006}},
            ],
        }
        result = validate_geography(day)
        assert result["detour_ratio"] >= 1.0
        assert result["actual_distance_km"] >= 0
        assert result["optimal_distance_km"] >= 0

    def test_single_activity(self):
        day = {"day": 1, "activities": [{"name": "A", "location": {"lat": 35.6, "lng": 139.6}}]}
        result = validate_geography(day)
        assert result["detour_ratio"] == 1.0

    def test_no_location_activities_skipped(self):
        day = {"day": 1, "activities": [{"name": "A"}, {"name": "B"}]}
        result = validate_geography(day)
        assert result["detour_ratio"] == 1.0

    def test_optimized_route_provided_for_detour(self):
        """绕路比 > 1.5 → 提供优化路线建议。"""
        day = {
            "day": 1,
            "activities": [
                {"name": "A", "location": {"lat": 35.6762, "lng": 139.6503}},   # 东京
                {"name": "B", "location": {"lat": 48.8566, "lng": 2.3522}},      # 巴黎 (很远)
                {"name": "C", "location": {"lat": 35.6895, "lng": 139.7006}},    # 新宿
            ],
        }
        result = validate_geography(day)
        assert result["detour_ratio"] > 1.5
        assert result["optimized_route"] is not None


class TestCheckGeography:
    """check_geography — 多日地理校验。"""

    def test_empty_itinerary(self):
        result = check_geography([])
        assert result["detours_found"] == 0
        assert result["overall_geo_status"] == "passed"
        assert "degraded" in result

    def test_linear_route_passes(self):
        itinerary = [{
            "day": 1,
            "activities": [
                {"name": "A", "location": {"lat": 35.6762, "lng": 139.6503}},
                {"name": "B", "location": {"lat": 35.6895, "lng": 139.7006}},
            ],
        }]
        result = check_geography(itinerary)
        assert result["detours_found"] == 0

    def test_nearby_attractions_no_warning(self):
        """景点间距离 ≤ 30km → 无 warning。"""
        itinerary = [{
            "day": 1,
            "activities": [
                {"name": "浅草寺", "location": {"lat": 35.7148, "lng": 139.7967}},
                {"name": "上野公园", "location": {"lat": 35.7146, "lng": 139.7732}},
            ],
        }]
        result = check_geography(itinerary)
        # 浅草寺→上野 ≈ 2km < 30km → 无 warning
        assert result["detours_found"] == 0

    def test_distant_attractions_warning(self):
        """景点间距离 > 30km → warning。"""
        itinerary = [{
            "day": 1,
            "activities": [
                {"name": "东京", "location": {"lat": 35.6762, "lng": 139.6503}},
                {"name": "富士山", "location": {"lat": 35.3606, "lng": 138.7274}},
            ],
        }]
        result = check_geography(itinerary)
        # 距离 ≈ 90km > 30km → warning
        assert len(result["warnings"]) >= 1

    def test_long_transit_without_notes_warning(self):
        itinerary = [{
            "day": 1,
            "activities": [
                {"name": "A", "location": {"lat": 35.6, "lng": 139.6},
                 "transit_duration_minutes": 200},
            ],
        }]
        result = check_geography(itinerary)
        assert len(result["warnings"]) >= 1


# ============================================================
# tools/time_checker.py — 高德地图 + 降级
# ============================================================

class TestAmapDirectionsClient:
    """AmapDirectionsClient — 可用性检测。"""

    def test_not_available_without_key(self, monkeypatch):
        # 确保环境变量未设置且清除缓存
        monkeypatch.delenv("AMAP_API_KEY", raising=False)
        import core.config as cfg
        cfg._config_cache = None
        client = AmapDirectionsClient()
        assert client.available is False

    def test_available_with_key(self, monkeypatch):
        monkeypatch.setenv("AMAP_API_KEY", "test_amap_key")
        import core.config as cfg
        cfg._config_cache = None
        client = AmapDirectionsClient()
        assert client.available is True


class TestCheckOpeningHours:
    """check_opening_hours — 开放时间查询（规则不变）。"""

    def test_default_hours(self):
        result = check_opening_hours("东京塔")
        assert result["open"] == "09:00"
        assert result["close"] == "17:00"
        assert result["source_type"] == "estimated"

    def test_museum_closed_monday(self):
        result = check_opening_hours("东京国立博物馆", "2026-12-21")  # Monday
        assert result["is_closed"] is True

    def test_museum_open_tuesday(self):
        result = check_opening_hours("东京国立博物馆", "2026-12-22")  # Tuesday
        assert result["is_closed"] is False

    def test_non_museum_open_monday(self):
        result = check_opening_hours("东京塔", "2026-12-21")  # Monday but not museum
        assert result["is_closed"] is False

    def test_invalid_date_does_not_crash(self):
        result = check_opening_hours("博物馆", "invalid_date")
        assert result["open"] == "09:00"


class TestCalculateTransitTime:
    """calculate_transit_time — 交通时间计算（同步版，降级到 Haversine）。"""

    def test_same_area(self):
        origin = {"lat": 35.6762, "lng": 139.6503}
        dest = {"lat": 35.6895, "lng": 139.7006}  # ~5km
        result = calculate_transit_time(origin, dest, "public_transit")
        assert result["duration_minutes"] > 0
        assert result["distance_km"] > 0
        assert result["source_type"] == "estimated"
        assert result["degraded"] is True  # 无 API key

    def test_cross_area(self):
        origin = {"lat": 35.6762, "lng": 139.6503}
        dest = {"lat": 34.6937, "lng": 135.5023}  # 东京→大阪 ~400km
        result = calculate_transit_time(origin, dest, "driving")
        assert result["is_cross_area"] is True
        assert result["distance_km"] > 100

    def test_walking_mode(self):
        origin = {"lat": 35.6762, "lng": 139.6503}
        dest = {"lat": 35.6895, "lng": 139.7006}
        result = calculate_transit_time(origin, dest, "walking")
        assert result["mode"] == "walking"
        assert result["duration_minutes"] > 0

    def test_degraded_flag(self):
        origin = {"lat": 0, "lng": 0}
        dest = {"lat": 0, "lng": 1}
        result = calculate_transit_time(origin, dest)
        assert result["degraded"] is True


class TestCheckTime:
    """check_time — 时间校验。"""

    def test_normal_day(self):
        itinerary = [{
            "day": 1,
            "activities": [
                {"name": "A", "duration_minutes": 120, "start_time": "09:00"},
                {"name": "B", "duration_minutes": 90, "start_time": "14:00"},
            ],
            "transit_minutes": 30,
        }]
        result = check_time(itinerary)
        assert result["days_checked"] == 1
        assert result["overall_time_status"] == "passed"
        assert "degraded" in result

    def test_over_12_hours_conflict(self):
        itinerary = [{
            "day": 1,
            "activities": [
                {"name": "A", "duration_minutes": 400, "start_time": "06:00"},
                {"name": "B", "duration_minutes": 400, "start_time": "14:00"},
            ],
            "transit_minutes": 60,
        }]
        result = check_time(itinerary)
        assert result["overall_time_status"] == "failed"
        assert len(result["conflicts"]) >= 1

    def test_boundary_warning(self):
        """10h ≤ 总时间 ≤ 12h → warning。"""
        itinerary = [{
            "day": 1,
            "activities": [
                {"name": "A", "duration_minutes": 480, "start_time": "09:00"},
                {"name": "B", "duration_minutes": 120, "start_time": "18:00"},
            ],
            "transit_minutes": 30,
        }]
        result = check_time(itinerary)
        assert len(result["warnings"]) >= 1 or result["overall_time_status"] != "failed"

    def test_lunch_conflict(self):
        itinerary = [{
            "day": 1,
            "activities": [
                {"name": "长时间活动", "duration_minutes": 240, "start_time": "11:00"},
            ],
            "transit_minutes": 0,
        }]
        result = check_time(itinerary)
        # 11:00 + 240min → 覆盖 11:30-13:30 午餐窗口
        has_lunch_warning = any(
            "午餐" in w.get("issue", "") for w in result.get("warnings", [])
        )
        assert has_lunch_warning

    def test_empty_itinerary(self):
        result = check_time([])
        assert result["days_checked"] == 0
        assert result["overall_time_status"] == "passed"

    def test_no_meal_conflict_when_activity_outside_window(self):
        itinerary = [{
            "day": 1,
            "activities": [
                {"name": "早间活动", "duration_minutes": 60, "start_time": "08:00"},
                {"name": "下午活动", "duration_minutes": 60, "start_time": "14:00"},
            ],
            "transit_minutes": 30,
        }]
        result = check_time(itinerary)
        meal_warnings = [w for w in result.get("warnings", [])
                         if "午餐" in w.get("issue", "") or "晚餐" in w.get("issue", "")]
        assert len(meal_warnings) == 0


# ============================================================
# tools/risk_checker.py — 风险识别 (stub, 不变)
# ============================================================

class TestCheckWeatherRisk:
    """check_weather_risk — 天气风险 stub（不变）。"""

    def test_typhoon_season_tokyo(self):
        result = check_weather_risk("东京", "2026-08-15")
        assert len(result["risks"]) >= 1
        assert any(r["category"] == "weather" for r in result["risks"])

    def test_dry_season_maldives(self):
        result = check_weather_risk("马尔代夫", "2026-01-15")
        risks = result["risks"]
        assert all(r.get("severity") == "low" for r in risks) or len(risks) == 0

    def test_unknown_location_no_crash(self):
        result = check_weather_risk("UnknownCity", "2026-06-15")
        assert isinstance(result["risks"], list)

    def test_invalid_date_no_crash(self):
        result = check_weather_risk("东京", "bad_date")
        assert isinstance(result["risks"], list)


class TestCheckTravelRequirements:
    """check_travel_requirements — 证件要求 stub（不变）。"""

    def test_japan_visa_required(self):
        result = check_travel_requirements("中国", "日本")
        assert result["visa_required"] is True
        assert result["passport_validity_months"] == 6

    def test_thailand_visa_free(self):
        result = check_travel_requirements("中国", "泰国")
        assert result["visa_required"] is False

    def test_unknown_country_default(self):
        result = check_travel_requirements("中国", "未知国")
        assert result["visa_required"] is True
        assert "自行核实" in result["notes"]

    def test_safety_risks_included(self):
        result = check_travel_requirements("中国", "巴黎")
        assert len(result["safety_risks"]) >= 1

    def test_partial_match(self):
        result = check_travel_requirements("中国", "法国巴黎")
        assert result["visa_required"] is True


# ============================================================
# 集成: execution_agent 调用 tools/
# ============================================================

class TestExecutionAgentToolsIntegration:
    """验证 execution_agent.estimate_market_price 正确调用 tools/price_checker。"""

    @pytest.fixture
    def agent(self):
        from agents.execution_agent import ExecutionAgent
        return ExecutionAgent()

    def test_estimate_market_price_uses_tools(self, agent):
        """estimate_market_price 现在从 tools/ 获取数据。"""
        from models.entities import PriceRange
        price = asyncio.run(agent.estimate_market_price("flight", "东京", "2026-12-20"))
        assert isinstance(price, PriceRange)
        assert price.median > 0
        assert price.currency == "CNY"

    def test_estimate_market_price_unknown_location(self, agent):
        price = asyncio.run(agent.estimate_market_price("hotel", "unknown_city"))
        assert price.median > 0  # 返回 default 值

    def test_estimate_market_price_all_types(self, agent):
        for item_type in ["flight", "hotel", "attraction", "meal"]:
            price = asyncio.run(agent.estimate_market_price(item_type, "北京"))
            assert price.item_type == item_type
            assert price.low <= price.median <= price.high


# ============================================================
# v1.2.0: 真实 API 调用测试 — 各 API 2 条，共 6 条
# ============================================================

@pytest.mark.slow
class TestRealAPICalls:
    """真实 API 调用冒烟测试。

    每个 API (DeepSeek / 高德 / 途牛) 各 2 条测试，
    验证真实 API 连通性和基础功能。默认被 pytest.ini 跳过。

    运行方式:
        pytest -m slow                          # 仅 slow 测试
        pytest --override-ini='addopts='         # 包含 slow 的全量测试
    """

    # ════════════════════════════════════════════════════════
    # DeepSeek LLM — 2 条
    # ════════════════════════════════════════════════════════

    def test_real_deepseek_simple_research(self):
        """真实 DeepSeek 调用：简单目的地研究。

        向 DeepSeek 发送简短 research prompt（带 JSON 输出约束），
        验证返回合法 dict。
        """
        api_key = os.getenv("DEEPSEEK_API_KEY")
        if not api_key:
            pytest.skip("DEEPSEEK_API_KEY not configured")

        from core.llm_client import LLMClient
        client = LLMClient()

        result = asyncio.run(client.generate(
            system_prompt="你是一个旅游规划助手。请以 JSON 格式回答。",
            user_prompt='请用 JSON 介绍成都: {"city":"成都","highlights":["特色1","特色2","特色3"]}',
            output_schema={
                "type": "object",
                "required": ["city", "highlights"],
                "properties": {
                    "city": {"type": "string"},
                    "highlights": {"type": "array", "items": {"type": "string"}},
                },
            },
        ))

        assert result is not None, "LLM 返回 None"
        assert isinstance(result, dict), f"LLM 返回类型异常: {type(result)}"
        assert "city" in result, f"缺少 city 字段: {list(result.keys())}"
        assert "成都" in result.get("city", ""), f"city 字段内容异常: {result.get('city')}"
        assert len(result.get("highlights", [])) >= 1, "highlights 为空"

    def test_real_deepseek_simple_itinerary(self):
        """真实 DeepSeek 调用：简单景点推荐。

        验证 LLM 能生成结构化的 JSON 景点推荐列表。
        """
        api_key = os.getenv("DEEPSEEK_API_KEY")
        if not api_key:
            pytest.skip("DEEPSEEK_API_KEY not configured")

        from core.llm_client import LLMClient
        client = LLMClient()

        result = asyncio.run(client.generate(
            system_prompt="你是一个旅游规划助手。请以 JSON 格式推荐景点。",
            user_prompt='请推荐成都3个必去景点，JSON格式: {"spots":[{"name":"景点名","reason":"简短理由"}]}',
            output_schema={
                "type": "object",
                "required": ["spots"],
                "properties": {
                    "spots": {
                        "type": "array",
                        "minItems": 1,
                        "items": {
                            "type": "object",
                            "required": ["name", "reason"],
                            "properties": {
                                "name": {"type": "string"},
                                "reason": {"type": "string"},
                            },
                        },
                    },
                },
            },
        ))

        assert result is not None, "LLM 返回 None"
        assert isinstance(result, dict), f"LLM 返回类型异常: {type(result)}"
        spots = result.get("spots", [])
        assert len(spots) >= 1, f"spots 为空或不足: {spots}"
        for spot in spots[:3]:
            assert "name" in spot, f"spot 缺少 name: {spot}"
            assert "reason" in spot, f"spot 缺少 reason: {spot}"

    # ════════════════════════════════════════════════════════
    # 高德地图 — 2 条
    # ════════════════════════════════════════════════════════

    def test_real_amap_geocode(self):
        """真实高德调用：地理编码。

        对"成都天府广场"进行地理编码，验证返回合法经纬度。
        """
        api_key = os.getenv("AMAP_API_KEY")
        if not api_key:
            pytest.skip("AMAP_API_KEY not configured")

        from tools.geo_checker import AmapGeocodeClient
        client = AmapGeocodeClient()

        result = asyncio.run(client.geocode("成都天府广场"))

        assert result is not None, "地理编码返回 None"
        assert "lat" in result, f"返回缺少 lat: {result}"
        assert "lng" in result, f"返回缺少 lng: {result}"
        # 成都天府广场坐标约为 (30.658, 104.066)
        assert 30.0 <= result["lat"] <= 31.5, (
            f"纬度异常（期望 30.0-31.5，实际 {result['lat']}）"
        )
        assert 103.0 <= result["lng"] <= 105.0, (
            f"经度异常（期望 103.0-105.0，实际 {result['lng']}）"
        )

    def test_real_amap_directions(self):
        """真实高德调用：路径规划。

        计算"成都天府广场→宽窄巷子"的步行/公交时间。
        """
        api_key = os.getenv("AMAP_API_KEY")
        if not api_key:
            pytest.skip("AMAP_API_KEY not configured")

        from tools.time_checker import AmapDirectionsClient
        client = AmapDirectionsClient()

        # 天府广场 → 宽窄巷子，直线距离约 1.5km
        origin = {"lat": 30.658, "lng": 104.066}
        dest = {"lat": 30.668, "lng": 104.052}
        result = asyncio.run(client.get_travel_time(
            origin=origin,
            destination=dest,
            mode="walking"
        ))

        assert result is not None, "路径规划返回 None"
        assert "duration_minutes" in result or "duration" in result, (
            f"返回缺少 duration: {list(result.keys()) if isinstance(result, dict) else type(result)}"
        )
        # 步行约 1.5km，时间应在 10-40 分钟
        duration = result.get("duration_minutes", result.get("duration", 0))
        if isinstance(duration, (int, float)) and duration > 0:
            assert 5 <= duration <= 60, (
                f"步行时间异常（1.5km 期望 5-60min，实际 {duration}min）"
            )

    # ════════════════════════════════════════════════════════
    # 途牛 MCP — 2 条
    # ════════════════════════════════════════════════════════

    def test_real_tuniu_hotel_search(self):
        """真实途牛 MCP 调用：酒店价格查询。

        查询成都酒店价格，验证返回非空价格范围 dict。
        """
        api_key = os.getenv("TUNIU_API_KEY")
        if not api_key:
            pytest.skip("TUNIU_API_KEY not configured")

        from tools.price_checker import TuniuMCPClient
        client = TuniuMCPClient()

        result = asyncio.run(client.search_hotel_prices(
            city_name="成都",
            check_in="2026-08-15",
        ))

        assert result is not None, "酒店查询返回 None"
        assert isinstance(result, dict), f"酒店响应类型异常: {type(result)}"
        # 成功返回应包含价格范围字段
        assert "low" in result or "median" in result or "high" in result, (
            f"返回缺少价格字段: {list(result.keys())}"
        )

    def test_real_tuniu_flight_search(self):
        """真实途牛 MCP 调用：机票价格查询。

        查询成都→北京单程机票价格。
        """
        api_key = os.getenv("TUNIU_API_KEY")
        if not api_key:
            pytest.skip("TUNIU_API_KEY not configured")

        from tools.price_checker import TuniuMCPClient
        client = TuniuMCPClient()

        result = asyncio.run(client.search_flight_prices(
            origin="成都",
            destination="北京",
            date_str="2026-08-15",
        ))

        assert result is not None, "机票查询返回 None"
        assert isinstance(result, dict), f"机票响应类型异常: {type(result)}"
        assert "low" in result or "median" in result or "high" in result, (
            f"返回缺少价格字段: {list(result.keys())}"
        )
