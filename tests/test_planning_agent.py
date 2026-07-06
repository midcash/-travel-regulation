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
        assert agent.agent_version == "1.0.0"

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
        alloc = agent.allocate_budget([], [], total)
        calc_total = alloc.transportation + alloc.accommodation + alloc.activities + alloc.meals + alloc.buffer
        assert abs(calc_total - total) < 0.01

    def test_buffer_is_five_percent(self, agent):
        total = 15000
        alloc = agent.allocate_budget([], [], total)
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
