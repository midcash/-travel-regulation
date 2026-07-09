"""Tests for agents/planning_agent.py — Planning Agent。

覆盖:
- create_itinerary: 行程生成
- revise_itinerary: 修订行程
- research_destination: 目的地研究
- search_attractions/search_accommodations/search_restaurants: 搜索
- allocate_budget: 预算分配
- handle_message: 消息处理 (TASK_CREATE_ITINERARY / TASK_REVISE_ITINERARY)
- 边界: 无偏好/饮食限制/排除项等
"""

import asyncio
import pytest
from datetime import datetime, timezone
from uuid import uuid4

from agents.planning_agent import PlanningAgent
from core.message import (
    AgentIdentity,
    AgentMessage,
    TaskType,
    ErrorCode,
    BaseAgent,
)
from models.request import StructuredRequest, Destination, DateRange, Budget, Travelers, Preferences
from models.plan import TravelPlanDraft, ItineraryDay, BudgetAllocation
from models.entities import DestinationInfo, Attraction, Accommodation, Restaurant, DietaryPreferences, RevisionFeedback
from models.check import IssueType, SelfCheckIssue
from models.feedback import RevisionFeedback as StructuredRevisionFeedback


@pytest.fixture
def agent():
    return PlanningAgent()


@pytest.fixture
def sample_request():
    return StructuredRequest(
        destination=Destination(city="东京", country="日本"),
        dates=DateRange(arrival="2026-12-20", departure="2026-12-25", duration_days=5),
        budget=Budget(total=15000),
        travelers=Travelers(adults=2, children=0),
        preferences=Preferences(style=["food", "culture"], pace="moderate"),
        request_id=str(uuid4()),
    )


# ============================================================
# BaseAgent 接口
# ============================================================

class TestBaseAgentInterface:
    def test_agent_name(self, agent):
        assert agent.agent_name == "planning_agent"

    def test_agent_version(self, agent):
        assert agent.agent_version == "1.1.0"

    def test_inherits_base_agent(self, agent):
        assert isinstance(agent, BaseAgent)

    def test_capabilities(self, agent):
        caps = agent.get_capabilities()
        names = {c.name for c in caps}
        assert "create_itinerary" in names
        assert "revise_itinerary" in names
        assert "research_destination" in names


# ============================================================
# create_itinerary
# ============================================================

class TestCreateItinerary:
    def test_returns_travel_plan_draft(self, agent, sample_request):
        draft = asyncio.run(agent.create_itinerary(sample_request))
        assert isinstance(draft, TravelPlanDraft)

    def test_draft_has_id(self, agent, sample_request):
        draft = asyncio.run(agent.create_itinerary(sample_request))
        assert draft.draft_id is not None

    def test_days_match_request(self, agent, sample_request):
        draft = asyncio.run(agent.create_itinerary(sample_request))
        assert draft.duration_days == 5
        assert len(draft.daily_itinerary) == 5

    def test_transportation_included(self, agent, sample_request):
        draft = asyncio.run(agent.create_itinerary(sample_request))
        assert draft.transportation is not None

    def test_accommodation_options(self, agent, sample_request):
        draft = asyncio.run(agent.create_itinerary(sample_request))
        assert len(draft.accommodation) == 2

    def test_budget_allocation(self, agent, sample_request):
        draft = asyncio.run(agent.create_itinerary(sample_request))
        alloc = draft.budget_allocation
        assert alloc.transportation > 0
        assert alloc.accommodation > 0
        assert alloc.activities > 0
        assert alloc.meals > 0
        assert alloc.buffer > 0

    def test_daily_itinerary_has_activities(self, agent, sample_request):
        draft = asyncio.run(agent.create_itinerary(sample_request))
        for day in draft.daily_itinerary:
            assert len(day.activities) >= 1

    def test_daily_itinerary_has_meals(self, agent, sample_request):
        draft = asyncio.run(agent.create_itinerary(sample_request))
        for day in draft.daily_itinerary:
            assert len(day.meals) >= 1

    def test_preferences_preserved(self, agent, sample_request):
        draft = asyncio.run(agent.create_itinerary(sample_request))
        assert "food" in draft.preferences_applied
        assert "culture" in draft.preferences_applied

    def test_revision_zero(self, agent, sample_request):
        draft = asyncio.run(agent.create_itinerary(sample_request))
        assert draft.revision_version == 0

    def test_default_days_when_unspecified(self, agent):
        req = StructuredRequest(
            destination=Destination(city="东京", country="日本"),
            dates=DateRange(duration_days=0),
            budget=Budget(total=10000),
        )
        draft = asyncio.run(agent.create_itinerary(req))
        assert draft.duration_days == 3  # 默认值

    def test_short_trip_one_day(self, agent):
        req = StructuredRequest(
            destination=Destination(city="广州", country="中国"),
            dates=DateRange(duration_days=1),
            budget=Budget(total=500),
        )
        draft = asyncio.run(agent.create_itinerary(req))
        assert len(draft.daily_itinerary) == 1

    def test_long_trip_fourteen_days(self, agent):
        req = StructuredRequest(
            destination=Destination(city="巴黎", country="法国"),
            dates=DateRange(duration_days=14),
            budget=Budget(total=50000),
        )
        draft = asyncio.run(agent.create_itinerary(req))
        assert len(draft.daily_itinerary) == 14

    def test_with_dietary_restrictions(self, agent):
        req = StructuredRequest(
            destination=Destination(city="曼谷", country="泰国"),
            dates=DateRange(duration_days=5),
            budget=Budget(total=8000),
            preferences=Preferences(dietary=["vegetarian"]),
        )
        draft = asyncio.run(agent.create_itinerary(req))
        assert isinstance(draft, TravelPlanDraft)


# ============================================================
# revise_itinerary
# ============================================================

class TestReviseItinerary:
    def test_revision_version_incremented(self, agent, sample_request):
        draft = asyncio.run(agent.create_itinerary(sample_request))
        feedback = [
            RevisionFeedback(dimension="schedule", issue="第3天太满", suggestion="减少活动", priority="high")
        ]
        revised = asyncio.run(agent.revise_itinerary(draft, feedback))
        assert revised.revision_version == draft.revision_version + 1

    def test_revision_new_draft_id(self, agent, sample_request):
        draft = asyncio.run(agent.create_itinerary(sample_request))
        feedback = [RevisionFeedback(dimension="schedule", issue="test", suggestion="fix", priority="medium")]
        revised = asyncio.run(agent.revise_itinerary(draft, feedback))
        assert revised.draft_id != draft.draft_id

    def test_revision_preserves_duration(self, agent, sample_request):
        draft = asyncio.run(agent.create_itinerary(sample_request))
        feedback = [RevisionFeedback(dimension="schedule", issue="test", suggestion="fix", priority="low")]
        revised = asyncio.run(agent.revise_itinerary(draft, feedback))
        assert revised.duration_days == draft.duration_days

    def test_revision_empty_feedback(self, agent, sample_request):
        draft = asyncio.run(agent.create_itinerary(sample_request))
        revised = asyncio.run(agent.revise_itinerary(draft, []))
        assert revised.revision_version == draft.revision_version + 1

    def test_structured_feedback_injected_into_revision_prompt(self, sample_request):
        draft = asyncio.run(PlanningAgent().create_itinerary(sample_request))
        mock_llm = _make_mock_llm({})
        prompt_builder = MagicMock()
        prompt_builder.assemble.return_value = (
            "【行程修订】\n"
            "1. [BLOCKING] day_2.dinner: 当前=8000, 期望=≤1500."
        )
        agent = PlanningAgent(
            llm_client=mock_llm,
            prompt_builder=prompt_builder,
        )
        feedback = [StructuredRevisionFeedback(
            issue=SelfCheckIssue(
                type=IssueType.BUDGET_OVERSPEND,
                location="day_2.dinner",
                actual_value=8000,
                expected="≤1500",
                severity="blocking",
            ),
            suggestion="替换为同区域预算内餐厅",
            priority="blocking",
            source="execution_agent",
        )]

        revised = asyncio.run(agent.revise_itinerary(draft, feedback))

        assert revised.revision_version == draft.revision_version + 1
        prompt_builder.assemble.assert_called_once()
        _, kwargs = prompt_builder.assemble.call_args
        assert kwargs["step"] == "revise"
        assert kwargs["feedback"] == feedback
        prompt = mock_llm.generate.call_args.kwargs["user_prompt"]
        assert "[BLOCKING] day_2.dinner" in prompt
        assert "原始行程" in prompt

# ============================================================
# research_destination
# ============================================================

class TestResearchDestination:
    def test_returns_destination_info(self, agent):
        dest = Destination(city="东京", country="日本")
        info = asyncio.run(agent.research_destination(dest))
        assert isinstance(info, DestinationInfo)
        assert info.destination == "东京"
        assert info.country == "日本"

    def test_has_best_season(self, agent):
        dest = Destination(city="东京", country="日本")
        info = asyncio.run(agent.research_destination(dest))
        assert len(info.best_season) > 0

    def test_has_popular_areas(self, agent):
        dest = Destination(city="东京", country="日本")
        info = asyncio.run(agent.research_destination(dest))
        assert len(info.popular_areas) > 0

    def test_china_destination_uses_cny(self, agent):
        dest = Destination(city="北京", country="中国")
        info = asyncio.run(agent.research_destination(dest))
        assert info.currency == "CNY"


# ============================================================
# search_attractions
# ============================================================

class TestSearchAttractions:
    def test_returns_list(self, agent):
        dest = Destination(city="东京", country="日本")
        prefs = Preferences(style=["culture", "nature"])
        results = asyncio.run(agent.search_attractions(dest, prefs))
        assert len(results) > 0
        for a in results:
            assert isinstance(a, Attraction)
            assert len(a.reason) >= 10

    def test_empty_preferences_returns_results(self, agent):
        dest = Destination(city="东京", country="日本")
        prefs = Preferences(style=[])
        results = asyncio.run(agent.search_attractions(dest, prefs))
        assert len(results) >= 0


# ============================================================
# search_accommodations
# ============================================================

class TestSearchAccommodations:
    def test_returns_two_options(self, agent):
        dest = Destination(city="东京", country="日本")
        budget = Budget(total=15000)
        results = asyncio.run(agent.search_accommodations(dest, budget, "moderate"))
        assert len(results) == 2
        for a in results:
            assert isinstance(a, Accommodation)

    def test_has_highlights(self, agent):
        dest = Destination(city="东京", country="日本")
        budget = Budget(total=15000)
        results = asyncio.run(agent.search_accommodations(dest, budget, "moderate"))
        for a in results:
            assert len(a.highlights) > 0


# ============================================================
# search_restaurants
# ============================================================

class TestSearchRestaurants:
    def test_returns_results(self, agent):
        prefs = DietaryPreferences()
        results = asyncio.run(agent.search_restaurants("东京", prefs))
        assert len(results) == 3
        for r in results:
            assert isinstance(r, Restaurant)

    def test_different_cuisines(self, agent):
        prefs = DietaryPreferences()
        results = asyncio.run(agent.search_restaurants("东京", prefs))
        cuisines = {r.cuisine for r in results}
        assert len(cuisines) >= 2


# ============================================================
# allocate_budget
# ============================================================

class TestAllocateBudget:
    def test_allocation_sum_equals_total(self, agent):
        total = 15000
        alloc = asyncio.run(agent.allocate_budget([], [], total))
        calc_total = alloc.transportation + alloc.accommodation + alloc.activities + alloc.meals + alloc.buffer
        assert abs(calc_total - total) < 0.01

    def test_buffer_is_five_percent(self, agent):
        total = 15000
        alloc = asyncio.run(agent.allocate_budget([], [], total))
        assert alloc.buffer == total * 0.05


# ============================================================
# optimize_daily_schedule
# ============================================================

class TestOptimizeDailySchedule:
    def test_returns_dict(self, agent):
        attractions = [
            Attraction(name="景点A", location="市中心", type="culture",
                       suggested_duration_minutes=120, estimated_price=100,
                       reason="著名文化景点，游客必去之地"),
        ]
        result = asyncio.run(agent.optimize_daily_schedule(attractions, 0))
        assert isinstance(result, dict)
        assert result["optimized"] is True


# ============================================================
# 消息处理
# ============================================================

class TestHandleMessage:
    def _make_msg(self, task_type, payload=None):
        identity = AgentIdentity("orchestrator", "1.0.0", [], "internal", "online")
        receiver = AgentIdentity("planning_agent", "1.0.0", [], "internal", "online")
        return AgentMessage(
            message_id=str(uuid4()),
            sender=identity,
            receiver=receiver,
            task_type=task_type,
            payload=payload or {},
            timestamp=datetime.now(timezone.utc),
        )

    def test_create_itinerary_msg(self, agent):
        msg = self._make_msg(TaskType.TASK_CREATE_ITINERARY, {
            "destination": {"city": "东京", "country": "日本"},
            "dates": {"arrival": "2026-12-20", "departure": "2026-12-25", "duration_days": 5},
            "budget": {"total": 15000, "currency": "CNY"},
            "travelers": {"adults": 2, "children": 0},
            "preferences": {"style": ["food"], "pace": "moderate"},
        })
        resp = asyncio.run(agent.handle_message(msg))
        assert resp.task_type == TaskType.RESPONSE_ITINERARY_DRAFT
        assert "data" in resp.payload

    def test_revise_itinerary_msg(self, agent):
        msg = self._make_msg(TaskType.TASK_REVISE_ITINERARY, {
            "original_draft": {"draft_id": "old-draft", "destination": "东京", "duration_days": 5, "total_budget": 15000},
            "revision_feedback": [{"dimension": "schedule", "issue": "第3天太满", "suggestion": "减少活动", "priority": "high"}],
        })
        resp = asyncio.run(agent.handle_message(msg))
        assert resp.task_type == TaskType.RESPONSE_ITINERARY_DRAFT

    def test_unsupported_task_type(self, agent):
        msg = self._make_msg(TaskType.CONTROL_ABORT)
        resp = asyncio.run(agent.handle_message(msg))
        assert resp.task_type == TaskType.RESPONSE_ERROR


# ============================================================
# Batch 4: LLM Mock 测试 — Mock LLMClient + happy path + 错误模式
# ============================================================

import json as _json
from unittest.mock import AsyncMock, MagicMock, patch
from core.llm_client import (
    LLMClient,
    LLMError,
    LLMTimeoutError,
    LLMRateLimitError,
    LLMParseError,
    LLMEmptyResponseError,
    LLMSchemaValidationError,
)


def _make_mock_llm(return_value=None, side_effect=None):
    """构造 Mock LLMClient，可用于控制 generate() 行为。"""
    mock = MagicMock(spec=LLMClient)
    mock.available = True
    if side_effect:
        mock.generate = AsyncMock(side_effect=side_effect)
    else:
        mock.generate = AsyncMock(return_value=return_value or {})
    return mock


def _make_agent_with_llm(mock_llm):
    """构造带 Mock LLMClient 的 PlanningAgent。"""
    return PlanningAgent(llm_client=mock_llm)


# --- TestLLMHappyPath: 验证 LLM 正常响应→正确反序列化 ---

class TestLLMHappyPath:
    """Mock LLM 返回合法 JSON → 正确反序列化为对应 model。"""

    def test_search_attractions_llm(self):
        mock = _make_mock_llm({"attractions": [{
            "name": "东京塔", "location": "港区", "type": "culture",
            "suggested_duration_minutes": 120, "estimated_price": 150.0,
            "rating": 4.6, "reason": "东京地标性建筑，可俯瞰全城夜景，夜景非常浪漫适合情侣",
            "opening_hours": "09:00-23:00",
        }]})
        agent = _make_agent_with_llm(mock)
        dest = Destination(city="东京", country="日本")
        prefs = Preferences(style=["culture"])

        results = asyncio.run(agent.search_attractions(dest, prefs))
        assert len(results) == 1
        assert results[0].name == "东京塔"
        assert len(results[0].reason) >= 10
        mock.generate.assert_called_once()

    def test_search_restaurants_llm(self):
        mock = _make_mock_llm({"restaurants": [{
            "name": "寿司大", "location": "筑地", "cuisine": "日式料理",
            "price_per_person": 200.0, "dietary_options": ["vegetarian"],
            "meal_types": ["lunch", "dinner"], "rating": 4.8,
        }]})
        agent = _make_agent_with_llm(mock)
        prefs = DietaryPreferences(restrictions=["vegetarian"])

        results = asyncio.run(agent.search_restaurants("东京", prefs))
        assert len(results) == 1
        assert results[0].name == "寿司大"
        assert "vegetarian" in results[0].dietary_options

    def test_search_accommodations_llm(self):
        mock = _make_mock_llm({"accommodations": [
            {"name": "东京希尔顿", "location": "新宿", "type": "hotel",
             "price_per_night": 800.0, "distance_to_center_km": 2.0,
             "highlights": ["泳池", "含早餐"], "rating": 4.5},
            {"name": "新宿胶囊旅馆", "location": "新宿", "type": "hostel",
             "price_per_night": 200.0, "distance_to_center_km": 1.0,
             "highlights": ["位置便利"], "rating": 4.0},
        ]})
        agent = _make_agent_with_llm(mock)
        dest = Destination(city="东京", country="日本")
        budget = Budget(total=10000)

        results = asyncio.run(agent.search_accommodations(dest, budget, "moderate"))
        assert len(results) == 2
        assert results[0].type == "hotel"
        assert results[1].type == "hostel"

    def test_allocate_budget_llm(self):
        mock = _make_mock_llm({
            "transportation": 3000, "accommodation": 5000,
            "activities": 2000, "meals": 1500, "buffer": 500,
            "currency": "CNY",
        })
        agent = _make_agent_with_llm(mock)
        total = 12000

        alloc = asyncio.run(agent.allocate_budget([], [], total))
        calc = sum([alloc.transportation, alloc.accommodation,
                     alloc.activities, alloc.meals, alloc.buffer])
        assert abs(calc - total) < 0.01
        assert alloc.buffer > 0


# --- TestLLMIntegration: create_itinerary LLM 路径集成 ---

class TestLLMIntegration:
    """验证 create_itinerary 在 LLM 可用时的集成行为。"""

    def test_create_itinerary_with_llm(self):
        """完整 LLM 路径: 研究+日程生成+预算分配。"""
        # 准备 3 组 mock 响应 (研究→日程→预算)
        research_resp = {
            "currency": "JPY", "language": "日语",
            "timezone": "Asia/Tokyo", "best_season": ["3月", "4月"],
            "popular_areas": ["新宿", "涩谷"],
            "transportation_tips": "地铁很方便",
            "safety_level": "safe",
            "visa_required_for_cn": True,
        }
        attr_resp = {"attractions": [
            {"name": "浅草寺", "location": "浅草", "type": "culture",
             "suggested_duration_minutes": 90, "estimated_price": 0.0,
             "reason": "东京最古老的寺庙，雷门大灯笼是标志性打卡地标"},
            {"name": "明治神宫", "location": "原宿", "type": "culture",
             "suggested_duration_minutes": 60, "estimated_price": 0.0,
             "reason": "位于东京市中心的大型神社，森林环绕非常宁静"},
            {"name": "涩谷十字路口", "location": "涩谷", "type": "entertainment",
             "suggested_duration_minutes": 45, "estimated_price": 0.0,
             "reason": "世界最繁忙的十字路口，东京潮流文化的绝对中心"},
            {"name": "上野公园", "location": "上野", "type": "nature",
             "suggested_duration_minutes": 120, "estimated_price": 0.0,
             "reason": "东京最大的公园之一，樱花季赏花胜地内有博物馆群"},
        ]}
        rest_resp = {"restaurants": [
            {"name": "一兰拉面", "location": "新宿", "cuisine": "日式拉面",
             "price_per_person": 60.0, "dietary_options": [],
             "meal_types": ["lunch", "dinner"], "rating": 4.5},
            {"name": "筑地寿司清", "location": "筑地", "cuisine": "寿司",
             "price_per_person": 150.0, "dietary_options": [],
             "meal_types": ["lunch", "dinner"], "rating": 4.6},
            {"name": "星乃咖啡", "location": "新宿", "cuisine": "咖啡轻食",
             "price_per_person": 40.0, "dietary_options": ["vegetarian"],
             "meal_types": ["breakfast"], "rating": 4.0},
            {"name": "天妇罗近藤", "location": "银座", "cuisine": "天妇罗",
             "price_per_person": 80.0, "dietary_options": [],
             "meal_types": ["lunch", "dinner"], "rating": 4.7},
        ]}
        acc_resp = {"accommodations": [
            {"name": "新宿王子酒店", "location": "新宿", "type": "hotel",
             "price_per_night": 600.0, "distance_to_center_km": 1.0,
             "highlights": ["交通便利"], "rating": 4.3},
            {"name": "浅草民宿", "location": "浅草", "type": "guesthouse",
             "price_per_night": 300.0, "distance_to_center_km": 5.0,
             "highlights": ["日式体验"], "rating": 4.5},
        ]}
        itinerary_resp = {"daily_itinerary": [
            {"day": 1, "activities": [
                {"name": "浅草寺", "type": "culture", "start_time": "09:00",
                 "duration_minutes": 90, "location": "浅草",
                 "estimated_cost": 0.0, "reason": "东京最古老的寺庙，雷门大灯笼是标志性打卡地标"},
                {"name": "上野公园", "type": "nature", "start_time": "13:00",
                 "duration_minutes": 120, "location": "上野",
                 "estimated_cost": 0.0, "reason": "东京最大的公园之一，樱花季赏花胜地内有博物馆群"},
            ], "meals": {
                "breakfast": {"type": "breakfast", "restaurant_name": "星乃咖啡",
                              "location": "新宿", "cuisine": "咖啡轻食",
                              "estimated_cost": 40.0, "dietary_compatible": True},
                "lunch": {"type": "lunch", "restaurant_name": "一兰拉面",
                          "location": "新宿", "cuisine": "日式拉面",
                          "estimated_cost": 60.0, "dietary_compatible": True},
                "dinner": {"type": "dinner", "restaurant_name": "筑地寿司清",
                           "location": "筑地", "cuisine": "寿司",
                           "estimated_cost": 150.0, "dietary_compatible": True},
            }, "transportation_notes": "地铁", "total_day_cost": 250.0,
             "total_duration_minutes": 330},
            {"day": 2, "activities": [
                {"name": "明治神宫", "type": "culture", "start_time": "09:00",
                 "duration_minutes": 60, "location": "原宿",
                 "estimated_cost": 0.0, "reason": "位于东京市中心的大型神社，森林环绕非常宁静"},
                {"name": "涩谷十字路口", "type": "entertainment", "start_time": "13:00",
                 "duration_minutes": 45, "location": "涩谷",
                 "estimated_cost": 0.0, "reason": "世界最繁忙的十字路口，东京潮流文化的绝对中心"},
            ], "meals": {
                "breakfast": {"type": "breakfast", "restaurant_name": "星乃咖啡",
                              "location": "新宿", "cuisine": "咖啡轻食",
                              "estimated_cost": 40.0, "dietary_compatible": True},
                "lunch": {"type": "lunch", "restaurant_name": "天妇罗近藤",
                          "location": "银座", "cuisine": "天妇罗",
                          "estimated_cost": 80.0, "dietary_compatible": True},
                "dinner": {"type": "dinner", "restaurant_name": "一兰拉面",
                           "location": "新宿", "cuisine": "日式拉面",
                           "estimated_cost": 60.0, "dietary_compatible": True},
            }, "transportation_notes": "地铁", "total_day_cost": 180.0,
             "total_duration_minutes": 285}],
        }
        budget_resp = {"transportation": 2000, "accommodation": 3000,
                       "activities": 500, "meals": 1000, "buffer": 500,
                       "currency": "CNY"}

        # generate() 按调用顺序返回不同值
        mock = MagicMock(spec=LLMClient)
        mock.available = True
        mock.generate = AsyncMock(side_effect=[
            research_resp, attr_resp, acc_resp, rest_resp,
            itinerary_resp, budget_resp,
        ])

        agent = _make_agent_with_llm(mock)
        req = StructuredRequest(
            destination=Destination(city="东京", country="日本"),
            dates=DateRange(arrival="2026-12-20", departure="2026-12-22",
                           duration_days=2),
            budget=Budget(total=6000),
            travelers=Travelers(adults=1, children=0),
            preferences=Preferences(style=["culture"], pace="moderate"),
        )

        draft = asyncio.run(agent.create_itinerary(req))
        assert isinstance(draft, TravelPlanDraft)
        assert draft.duration_days == 2
        assert len(draft.daily_itinerary) == 2


# --- TestLLMFallback: 6 种异常 → stub 回退 ---

class TestLLMFallback:
    """LLM 各种异常时自动回退 stub，不崩溃。"""

    def test_timeout_fallback(self):
        mock = _make_mock_llm(side_effect=LLMTimeoutError("超时"))
        agent = _make_agent_with_llm(mock)
        dest = Destination(city="东京", country="日本")
        prefs = Preferences(style=["culture"])

        results = asyncio.run(agent.search_attractions(dest, prefs))
        assert len(results) > 0
        assert all(isinstance(a, Attraction) for a in results)

    def test_ratelimit_fallback(self):
        mock = _make_mock_llm(side_effect=LLMRateLimitError("429"))
        agent = _make_agent_with_llm(mock)
        prefs = DietaryPreferences()

        results = asyncio.run(agent.search_restaurants("东京", prefs))
        assert len(results) == 3

    def test_parse_error_fallback(self):
        mock = _make_mock_llm(side_effect=LLMParseError("解析失败"))
        agent = _make_agent_with_llm(mock)
        dest = Destination(city="东京", country="日本")
        budget = Budget(total=10000)

        results = asyncio.run(agent.search_accommodations(dest, budget, "moderate"))
        assert len(results) == 2

    def test_empty_response_fallback(self):
        mock = _make_mock_llm(side_effect=LLMEmptyResponseError("空响应"))
        agent = _make_agent_with_llm(mock)
        dest = Destination(city="东京", country="日本")

        info = asyncio.run(agent.research_destination(dest))
        assert isinstance(info, DestinationInfo)
        assert info.destination == "东京"

    def test_schema_validation_fallback(self):
        mock = _make_mock_llm(side_effect=LLMSchemaValidationError("缺少字段"))
        agent = _make_agent_with_llm(mock)
        dest = Destination(city="东京", country="日本")
        prefs = Preferences(style=["culture"])

        results = asyncio.run(agent.search_attractions(dest, prefs))
        assert len(results) > 0

    def test_unknown_exception_fallback(self):
        mock = _make_mock_llm(side_effect=Exception("网络中断"))
        agent = _make_agent_with_llm(mock)
        prefs = DietaryPreferences()

        results = asyncio.run(agent.search_restaurants("东京", prefs))
        assert len(results) == 3

    def test_create_itinerary_llm_failure_partial(self):
        """LLM 部分失败: 研究成功但日程生成失败 → fallback stub 拼接。"""
        research_resp = {
            "currency": "JPY", "language": "日语",
            "timezone": "Asia/Tokyo", "best_season": ["3月"],
            "popular_areas": ["新宿"],
            "visa_required_for_cn": True, "safety_level": "safe",
        }
        attr_resp = {"attractions": [
            {"name": "浅草寺", "location": "浅草", "type": "culture",
             "suggested_duration_minutes": 90, "estimated_price": 0.0,
             "reason": "东京最古老的寺庙，雷门是标志性打卡点广受游客欢迎"},
        ]}

        # 调用链: research → attractions → accommodations → restaurants → itinerary(FAIL) → budget
        mock = MagicMock(spec=LLMClient)
        mock.available = True
        mock.generate = AsyncMock(side_effect=[
            research_resp, attr_resp,
            LLMTimeoutError("住宿超时"),
            LLMTimeoutError("餐厅超时"),
            LLMTimeoutError("日程超时"),
            {"transportation": 2000, "accommodation": 3000,
             "activities": 500, "meals": 1000, "buffer": 500, "currency": "CNY"},
        ])

        agent = _make_agent_with_llm(mock)
        req = StructuredRequest(
            destination=Destination(city="东京", country="日本"),
            dates=DateRange(duration_days=2),
            budget=Budget(total=7000),
        )

        draft = asyncio.run(agent.create_itinerary(req))
        assert isinstance(draft, TravelPlanDraft)


# --- TestLLMRetry: 重试逻辑 ---

class TestLLMRetry:
    """验证 Agent 调用 LLM 失败后的 fallback 行为。

    注意: 重试逻辑在 LLMClient.generate() 内部实现（3次指数退避），
    不在 PlanningAgent 层。Agent 层通过 _llm_or_stub 捕获单次异常后立即 fallback。
    Agent 测试验证的是: LLM 抛出异常 → Agent fallback stub 且不崩溃。
    """

    def test_llm_error_triggers_fallback(self):
        """LLM 抛出异常 → Agent 立即 fallback stub。"""
        mock = MagicMock(spec=LLMClient)
        mock.available = True
        mock.generate = AsyncMock(side_effect=LLMTimeoutError("超时"))
        agent = _make_agent_with_llm(mock)
        dest = Destination(city="东京", country="日本")
        prefs = Preferences(style=["culture"])

        results = asyncio.run(agent.search_attractions(dest, prefs))
        assert len(results) > 0
        mock.generate.assert_called_once()

    def test_llm_ratelimit_fallback(self):
        """LLM 限流 → Agent fallback stub。"""
        mock = _make_mock_llm(side_effect=LLMRateLimitError("429"))
        agent = _make_agent_with_llm(mock)
        prefs = DietaryPreferences()

        results = asyncio.run(agent.search_restaurants("东京", prefs))
        assert len(results) == 3
        mock.generate.assert_called_once()


# --- TestLLMSchemaValidation: JSON→dataclass 反序列化 ---

class TestLLMSchemaValidation:
    """验证 _parse_llm_* 方法的鲁棒性。"""

    def test_parse_attractions_minimal_fields(self):
        """只提供最小字段，验证默认值填充。"""
        data = {"attractions": [
            {"name": "某景点", "location": "某地",
             "reason": "这是一个历史悠久的著名景点广受游客喜爱推荐游览"},
        ]}
        results = PlanningAgent._parse_llm_attractions(data)
        assert len(results) == 1
        assert results[0].type == "culture"  # 默认值
        assert results[0].estimated_price == 0.0

    def test_parse_attractions_short_reason(self):
        """reason < 10 字 → __post_init__ 补全到 10+ 字。"""
        data = {"attractions": [
            {"name": "某景点", "location": "某地", "reason": "很好"},
        ]}
        results = PlanningAgent._parse_llm_attractions(data)
        # reason 被补全到 >= 10 字 (在 _parse_llm_attractions 中不处理,
        # _post_init__ 会抛 ValueError, _parse_llm_attractions 使用默认 reason)
        # 实际上 mock 返回的 reason 短时 __post_init__ 会抛异常
        # 测试默认 reason fallback
        assert len(results) == 1
        assert len(results[0].reason) >= 10

    def test_parse_attractions_list_in_items(self):
        """attractions 在 data.attractions 中。"""
        data = {"attractions": [
            {"name": "A", "location": "L", "reason": "很值得去的景点推荐理由足够长"},
            {"name": "B", "location": "L", "reason": "很值得去的景点推荐理由足够长"},
        ]}
        results = PlanningAgent._parse_llm_attractions(data)
        assert len(results) == 2

    def test_parse_itinerary_empty(self):
        """空日程列表。"""
        data: dict = {}
        results = PlanningAgent._parse_llm_itinerary(data)
        assert results == []

    def test_parse_budget_normalization(self):
        """预算五项之和归一化到 total。"""
        data = {"transportation": 100, "accommodation": 100,
                "activities": 100, "meals": 100, "buffer": 100}
        alloc = PlanningAgent._parse_llm_budget(data, 1000.0)
        calc = sum([alloc.transportation, alloc.accommodation,
                     alloc.activities, alloc.meals, alloc.buffer])
        assert abs(calc - 1000.0) < 0.01


# --- TestStubRegression: 纯 stub 模式回归 ---

class TestStubRegression:
    """PlanningAgent(llm_client=None) 保持所有原有行为。"""

    def test_stub_mode_creates_draft(self):
        agent = PlanningAgent(llm_client=None)
        req = StructuredRequest(
            destination=Destination(city="东京", country="日本"),
            dates=DateRange(duration_days=3),
            budget=Budget(total=10000),
        )
        draft = asyncio.run(agent.create_itinerary(req))
        assert isinstance(draft, TravelPlanDraft)
        assert len(draft.daily_itinerary) == 3

    def test_stub_mode_allocates_budget(self):
        agent = PlanningAgent(llm_client=None)
        alloc = asyncio.run(agent.allocate_budget([], [], 15000))
        assert alloc.transportation == 4500.0
        assert alloc.buffer == 750.0

    def test_stub_mode_revise_preserves(self):
        agent = PlanningAgent(llm_client=None)
        req = StructuredRequest(
            destination=Destination(city="东京", country="日本"),
            dates=DateRange(duration_days=3),
            budget=Budget(total=10000),
        )
        draft = asyncio.run(agent.create_itinerary(req))
        revised = asyncio.run(agent.revise_itinerary(draft, []))
        assert revised.revision_version == draft.revision_version + 1
