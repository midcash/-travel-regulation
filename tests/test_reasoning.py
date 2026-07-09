"""Reasoning 模块单元测试 — v1.2.0 I1.

覆盖: PromptBuilder + SelfChecker + StructuredFeedback + CoTPipeline
"""

from __future__ import annotations

import uuid
from datetime import date, datetime, timezone
from dataclasses import dataclass
from typing import Any, Dict, List, Optional
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from core.prompt_builder import PromptBuilder
from core.self_check import SelfChecker
from core.cot_pipeline import CoTPipeline

from models.check import IssueType, SelfCheckIssue, SelfCheckResult
from models.feedback import RevisionFeedback
from models.reasoning import (
    CandidatePool,
    CoTResult,
    DestinationResearch,
    StepTrace,
)
from models.plan import (
    Activity,
    BudgetAllocation,
    ItineraryDay,
    Meal,
    TravelPlanDraft,
)
from models.entities import (
    Accommodation,
    Attraction,
    GeoLocation,
    Restaurant,
)
from models.request import (
    Budget,
    DateRange,
    Destination,
    Preferences,
    StructuredRequest,
    Travelers,
)


# ============================================================
# Fixtures
# ============================================================

@pytest.fixture
def sample_request():
    """标准 StructuredRequest: 东京5天 food+culture。"""
    return StructuredRequest(
        request_id=str(uuid.uuid4()),
        destination=Destination(city="东京", country="日本"),
        dates=DateRange(arrival="2026-12-20", departure="2026-12-25", duration_days=5),
        budget=Budget(total=15000, currency="CNY"),
        travelers=Travelers(adults=2, children=0),
        preferences=Preferences(style=["food", "culture"], pace="moderate"),
    )


@pytest.fixture
def request_with_excluded():
    """带排除项的请求: 排除赌博和夜店。"""
    return StructuredRequest(
        request_id=str(uuid.uuid4()),
        destination=Destination(city="澳门", country="中国"),
        dates=DateRange(arrival="2026-11-01", departure="2026-11-04", duration_days=3),
        budget=Budget(total=8000, currency="CNY"),
        travelers=Travelers(adults=1, children=0),
        preferences=Preferences(
            style=["culture", "food"],
            pace="moderate",
            excluded=["赌博", "夜店"],
        ),
    )


def _make_activity(name, atype="culture", cost=200, lat=None, lng=None, duration=120):
    """快捷构造 Activity。"""
    geo = GeoLocation(lat=lat, lng=lng) if lat is not None and lng is not None else None
    return Activity(
        name=name, type=atype, start_time="09:00",
        duration_minutes=duration, location=name, estimated_cost=cost,
        reason="详细的推荐理由至少满足15个字符的约束要求", geo=geo,
    )


def _make_meal(mtype="lunch", name="某餐厅", cost=80):
    """快捷构造 Meal。"""
    return Meal(
        type=mtype, restaurant_name=name, location=name,
        cuisine="当地特色", estimated_cost=cost, dietary_compatible=True,
    )


def _make_valid_draft(days=2):
    """构造一个合规的 TravelPlanDraft（通过所有 selfcheck）。"""
    daily = []
    for d in range(1, days + 1):
        day = ItineraryDay(
            day=d,
            activities=[
                _make_activity(f"景点{d}A", "culture", 150, 35.6 + d * 0.01, 139.7 + d * 0.01),
                _make_activity(f"景点{d}B", "food", 100, 35.61 + d * 0.01, 139.71 + d * 0.01),
            ],
            meals={
                "breakfast": _make_meal("breakfast", f"早餐{d}", 30),
                "lunch": _make_meal("lunch", f"午餐{d}", 80),
                "dinner": _make_meal("dinner", f"晚餐{d}", 120),
            },
            total_day_cost=480,
        )
        daily.append(day)
    return TravelPlanDraft(
        draft_id=str(uuid.uuid4()),
        destination={"city": "东京", "country": "日本"},
        duration_days=days,
        daily_itinerary=daily,
        total_budget=15000,
        budget_allocation=BudgetAllocation(
            transportation=5000, accommodation=4500,
            activities=2250, meals=2250, buffer=1000, currency="CNY",
        ),
        preferences_applied=["food", "culture"],
    )


# ============================================================
# PromptBuilder 测试 (≥8 tests)
# ============================================================

class TestPromptBuilder:
    """PromptBuilder 单元测试。"""

    def test_assemble_research_returns_nonempty_prompt(self, sample_request):
        builder = PromptBuilder()
        prompt = builder.assemble(sample_request, step="research")
        assert len(prompt) > 0
        assert "你是一个资深旅游规划师" in prompt
        assert "东京" in prompt

    def test_assemble_invalid_step_raises_valueerror(self, sample_request):
        builder = PromptBuilder()
        with pytest.raises(ValueError, match="无效的 step 值"):
            builder.assemble(sample_request, step="invalid_step")

    def test_assemble_all_valid_steps(self, sample_request):
        builder = PromptBuilder()
        valid_steps = [
            "research", "attractions", "accommodations",
            "restaurants", "itinerary", "budget",
        ]
        for step in valid_steps:
            prompt = builder.assemble(sample_request, step=step)
            assert len(prompt) > 0, f"Step {step} 应返回非空 prompt"

    def test_inject_excluded_types(self, request_with_excluded):
        builder = PromptBuilder()
        result = builder.inject_hard_constraints(request_with_excluded.preferences)
        assert "MUST_NOT" in result
        assert "赌博" in result
        assert "夜店" in result

    def test_inject_dietary_constraints(self):
        prefs = Preferences(style=["food"], dietary=["vegetarian", "halal"])
        builder = PromptBuilder()
        result = builder.inject_hard_constraints(prefs)
        assert "MUST" in result
        assert "vegetarian" in result
        assert "halal" in result

    def test_inject_empty_preferences_returns_empty(self):
        prefs = Preferences(style=["food"])
        builder = PromptBuilder()
        result = builder.inject_hard_constraints(prefs)
        assert result == ""

    def test_build_stable_contains_five_sections(self, sample_request):
        builder = PromptBuilder()
        prompt = builder.assemble(sample_request, step="research")
        assert "核心规则" in prompt
        assert "硬约束" in prompt
        assert "推理链" in prompt
        assert "自检清单" in prompt

    def test_assemble_revise_with_feedback(self, sample_request):
        builder = PromptBuilder()
        issue = SelfCheckIssue(
            type=IssueType.BUDGET_OVERSPEND,
            location="第1天",
            actual_value=5000,
            expected="≤ 3300 CNY",
            severity="blocking",
        )
        fb = RevisionFeedback(
            issue=issue,
            suggestion="建议替换为更经济的选项",
            priority="blocking",
            source="execution_agent",
        )
        prompt = builder.assemble(
            sample_request, step="revise", feedback=[fb], iteration=1,
        )
        assert "5000" in prompt or "3300" in prompt or "第1天" in prompt

    def test_price_knowledge_injection(self, sample_request):
        builder = PromptBuilder()
        prompt = builder.assemble(sample_request, step="research")
        # 物价参考应出现在 prompt 中
        has_price_info = any(
            kw in prompt for kw in ["日元", "JPY", "物价参考", "当地物价", "均价"]
        )
        assert has_price_info, "Prompt 应包含目的地物价参考"


# ============================================================
# SelfChecker 测试 (≥12 tests)
# ============================================================

class TestSelfChecker:
    """SelfChecker 规则引擎单元测试。"""

    def test_check_valid_draft_passes(self, sample_request):
        draft = _make_valid_draft(days=2)
        checker = SelfChecker()
        result = checker.check(draft, sample_request)
        assert result.passed is True
        assert len(result.blocking_issues) == 0

    def test_check_budget_overspend_blocking(self):
        """单日花费超出 daily_budget_limit × 1.1 → blocking。"""
        # 1天行程，总预算1000 → daily_limit = 1000/1*1.1 = 1100, overspend=2100 > 1100
        day = ItineraryDay(day=1, activities=[
            _make_activity("超贵景点", "culture", 2000),
        ], meals={}, total_day_cost=2000)
        draft = TravelPlanDraft(
            draft_id=str(uuid.uuid4()),
            destination={"city": "东京", "country": "日本"},
            duration_days=1,
            daily_itinerary=[day],
            total_budget=1000,
            budget_allocation=BudgetAllocation(
                transportation=300, accommodation=300,
                activities=150, meals=150, buffer=100,
            ),
        )
        sample_request = StructuredRequest(
            request_id=str(uuid.uuid4()),
            destination=Destination(city="东京", country="日本"),
            dates=DateRange(arrival="2026-12-20", departure="2026-12-21", duration_days=1),
            budget=Budget(total=1000, currency="CNY"),
            travelers=Travelers(adults=1, children=0),
            preferences=Preferences(style=["culture"]),
        )
        checker = SelfChecker()
        result = checker.check(draft, sample_request)
        assert result.passed is False
        blocking_types = [i.type for i in result.blocking_issues]
        assert IssueType.BUDGET_OVERSPEND in blocking_types

    def test_check_duplicate_attraction_blocking(self, sample_request):
        """同一景点跨天重复 → blocking。"""
        shared_activity = _make_activity("浅草寺", "culture", 0, 35.714, 139.796)
        day1 = ItineraryDay(day=1, activities=[
            shared_activity,
            _make_activity("晴空塔", "entertainment", 200, 35.710, 139.810),
        ], meals={
            "lunch": _make_meal("lunch", "拉面", 80),
            "dinner": _make_meal("dinner", "寿司", 150),
        })
        day2 = ItineraryDay(day=2, activities=[
            shared_activity,
            _make_activity("秋叶原", "shopping", 50, 35.702, 139.774),
        ], meals={
            "lunch": _make_meal("lunch", "咖喱", 70),
            "dinner": _make_meal("dinner", "烤肉", 130),
        })
        draft = TravelPlanDraft(
            draft_id=str(uuid.uuid4()),
            destination={"city": "东京", "country": "日本"},
            duration_days=2,
            daily_itinerary=[day1, day2],
            total_budget=5000,
            budget_allocation=BudgetAllocation(
                transportation=1500, accommodation=1500,
                activities=750, meals=750, buffer=500,
            ),
        )
        checker = SelfChecker()
        result = checker.check(draft, sample_request)
        dup_issues = [i for i in result.issues if i.type == IssueType.DUPLICATE_ATTRACTION]
        assert len(dup_issues) >= 1
        assert "浅草寺" in dup_issues[0].location

    def test_check_geo_distance_warning(self, sample_request):
        """同天两景点 Haversine 距离 >30km → warning。"""
        day = ItineraryDay(day=1, activities=[
            _make_activity("东京塔", "culture", 100, 35.7, 139.7),
            _make_activity("箱根温泉", "nature", 80, 35.7, 139.0),
        ], meals={
            "lunch": _make_meal("lunch", "定食", 80),
            "dinner": _make_meal("dinner", "居酒屋", 150),
        })
        draft = TravelPlanDraft(
            draft_id=str(uuid.uuid4()),
            destination={"city": "东京", "country": "日本"},
            duration_days=1,
            daily_itinerary=[day],
            total_budget=5000,
            budget_allocation=BudgetAllocation(
                transportation=1500, accommodation=1500,
                activities=750, meals=750, buffer=500,
            ),
        )
        checker = SelfChecker()
        result = checker.check(draft, sample_request)
        geo_issues = [i for i in result.issues if i.type == IssueType.GEO_DISTANCE]
        assert len(geo_issues) >= 1
        assert geo_issues[0].severity == "warning"

    def test_check_missing_activities_warning(self, sample_request):
        """每天不足 2 个活动 → warning。"""
        day = ItineraryDay(day=1, activities=[
            _make_activity("单一景点", "culture", 100),
        ], meals={
            "lunch": _make_meal("lunch", "面馆", 60),
            "dinner": _make_meal("dinner", "烧烤", 100),
        }, total_day_cost=260)
        draft = TravelPlanDraft(
            draft_id=str(uuid.uuid4()),
            destination={"city": "东京", "country": "日本"},
            duration_days=1,
            daily_itinerary=[day],
            total_budget=3000,
            budget_allocation=BudgetAllocation(
                transportation=900, accommodation=900,
                activities=450, meals=450, buffer=300,
            ),
        )
        checker = SelfChecker()
        result = checker.check(draft, sample_request)
        act_issues = [i for i in result.issues if i.type == IssueType.MISSING_ACTIVITY]
        assert len(act_issues) >= 1
        assert act_issues[0].severity == "warning"

    def test_check_missing_meals_warning(self, sample_request):
        """每天不足 2 餐推荐 → warning。"""
        day = ItineraryDay(day=1, activities=[
            _make_activity("景点A", "culture", 100),
            _make_activity("景点B", "nature", 50),
        ], meals={
            "lunch": _make_meal("lunch", "一碗拉面", 60),
        }, total_day_cost=210)
        draft = TravelPlanDraft(
            draft_id=str(uuid.uuid4()),
            destination={"city": "东京", "country": "日本"},
            duration_days=1,
            daily_itinerary=[day],
            total_budget=3000,
            budget_allocation=BudgetAllocation(
                transportation=900, accommodation=900,
                activities=450, meals=450, buffer=300,
            ),
        )
        checker = SelfChecker()
        result = checker.check(draft, sample_request)
        meal_issues = [i for i in result.issues if i.type == IssueType.MISSING_MEAL]
        assert len(meal_issues) >= 1
        assert meal_issues[0].severity == "warning"

    def test_check_excluded_type_blocking(self, request_with_excluded):
        """推荐了 excluded_types 中的类型 → blocking。"""
        day = ItineraryDay(day=1, activities=[
            _make_activity("赌场A", "赌博", 500, 22.1, 113.5),
            _make_activity("正常景点", "culture", 100, 22.2, 113.6),
        ], meals={
            "lunch": _make_meal("lunch", "茶餐厅", 60),
            "dinner": _make_meal("dinner", "海鲜", 120),
        }, total_day_cost=780)
        draft = TravelPlanDraft(
            draft_id=str(uuid.uuid4()),
            destination={"city": "澳门", "country": "中国"},
            duration_days=1,
            daily_itinerary=[day],
            total_budget=3000,
            budget_allocation=BudgetAllocation(
                transportation=900, accommodation=900,
                activities=450, meals=450, buffer=300,
            ),
        )
        checker = SelfChecker()
        result = checker.check(draft, request_with_excluded)
        exc_types = [i.type for i in result.blocking_issues]
        assert IssueType.EXCLUDED_TYPE in exc_types

    def test_check_style_mismatch_warning(self, sample_request):
        """活动类型与偏好风格不匹配 → warning（仅当匹配率 <50%）。"""
        day = ItineraryDay(day=1, activities=[
            _make_activity("购物中心A", "shopping", 200),
            _make_activity("购物中心B", "shopping", 150),
        ], meals={
            "lunch": _make_meal("lunch", "快餐", 50),
            "dinner": _make_meal("dinner", "餐厅", 100),
        }, total_day_cost=500)
        draft = TravelPlanDraft(
            draft_id=str(uuid.uuid4()),
            destination={"city": "东京", "country": "日本"},
            duration_days=1,
            daily_itinerary=[day],
            total_budget=3000,
            budget_allocation=BudgetAllocation(
                transportation=900, accommodation=900,
                activities=450, meals=450, buffer=300,
            ),
        )
        checker = SelfChecker()
        result = checker.check(draft, sample_request)
        style_issues = [i for i in result.issues if i.type == IssueType.STYLE_MISMATCH]
        assert len(style_issues) >= 1
        assert style_issues[0].severity == "warning"

    def test_haversine_distance_known_coordinates(self):
        """Haversine 公式: 东京塔→晴空塔 ≈ 7.5km。"""
        dist = SelfChecker._haversine_distance(35.658, 139.745, 35.710, 139.810)
        assert 6.0 <= dist <= 10.0, f"期望约 7.5km，实际: {dist:.1f}km"

    def test_calc_daily_spend_with_activities_and_meals(self):
        day = ItineraryDay(day=1, activities=[
            _make_activity("景点A", "culture", 150),
            _make_activity("景点B", "nature", 200),
        ], meals={
            "lunch": _make_meal("lunch", "餐厅", 80),
            "dinner": _make_meal("dinner", "烤肉", 120),
        }, total_day_cost=0)
        spend = SelfChecker._calc_daily_spend(day)
        assert spend == 550  # 150 + 200 + 80 + 120

    def test_get_activity_geo_from_geo_object(self):
        activity = _make_activity("test", lat=35.6, lng=139.7)
        geo = SelfChecker._get_activity_geo(activity)
        assert geo == (35.6, 139.7)

    def test_get_activity_geo_from_dict_location(self):
        """Activity with dict location containing lat/lng。"""
        activity = Activity(
            name="test", type="culture", start_time="09:00",
            duration_minutes=60, location={"lat": 31.2, "lng": 121.4},
            estimated_cost=100, reason="详细的推荐理由满足最少字符限制的要求",
        )
        geo = SelfChecker._get_activity_geo(activity)
        assert geo == (31.2, 121.4)


# ============================================================
# StructuredFeedback 测试 (≥5 tests)
# ============================================================

class TestStructuredFeedback:
    """RevisionFeedback 单元测试。"""

    def test_format_for_prompt_blocking(self):
        issue = SelfCheckIssue(
            type=IssueType.BUDGET_OVERSPEND,
            location="第2天晚餐",
            actual_value=8000,
            expected="≤ 1500 CNY",
            severity="blocking",
        )
        fb = RevisionFeedback(
            issue=issue,
            suggestion="替换为同区域 1500 日元以内的居酒屋",
            priority="blocking",
            source="execution_agent",
        )
        text = fb.format_for_prompt()
        assert "[BLOCKING]" in text
        assert "第2天晚餐" in text
        assert "8000" in text
        assert "≤ 1500" in text
        assert "居酒屋" in text

    def test_format_for_prompt_warning(self):
        issue = SelfCheckIssue(
            type=IssueType.GEO_DISTANCE,
            location="第1天 景点A vs 景点B",
            actual_value=45.0,
            expected="≤ 30km",
            severity="warning",
        )
        fb = RevisionFeedback(
            issue=issue,
            suggestion="考虑替换一个距离较近的景点",
            priority="warning",
            source="self_check",
        )
        text = fb.format_for_prompt()
        assert "[WARNING]" in text
        assert "45.0" in text
        assert "30km" in text

    def test_from_dict_to_dict_roundtrip(self):
        original = RevisionFeedback(
            issue=SelfCheckIssue(
                type=IssueType.DUPLICATE_ATTRACTION,
                location="景点 '浅草寺'",
                actual_value="出现于第1, 3天",
                expected="不重复",
                severity="blocking",
            ),
            suggestion="每景点仅出现一次",
            priority="blocking",
            source="self_check",
        )
        d = original.to_dict()
        restored = RevisionFeedback.from_dict(d)
        assert restored.issue.type == IssueType.DUPLICATE_ATTRACTION
        assert restored.issue.location == "景点 '浅草寺'"
        assert restored.priority == "blocking"
        assert restored.source == "self_check"

    def test_source_execution_agent(self):
        issue = SelfCheckIssue(
            type=IssueType.BUDGET_OVERSPEND,
            location="第3天",
            actual_value=6000,
            expected="≤ 3300 CNY",
            severity="blocking",
        )
        fb = RevisionFeedback(
            issue=issue,
            suggestion="减少不必要开支",
            source="execution_agent",
        )
        assert fb.source == "execution_agent"
        text = fb.format_for_prompt()
        assert "[BLOCKING]" in text

    def test_source_self_check(self):
        issue = SelfCheckIssue(
            type=IssueType.MISSING_MEAL,
            location="第1天",
            actual_value="仅 1 餐推荐",
            expected="≥ 2 餐推荐",
            severity="warning",
        )
        fb = RevisionFeedback(issue=issue, source="self_check")
        assert fb.source == "self_check"


# ============================================================
# CoTPipeline 测试 (≥5 tests)
# ============================================================

class TestCoTPipeline:
    """CoTPipeline 单元测试。"""

    def test_init_stores_dependencies(self):
        mock_llm = MagicMock()
        mock_prompts = MagicMock()
        mock_checker = MagicMock()
        pipeline = CoTPipeline(mock_llm, mock_prompts, mock_checker)
        assert pipeline._llm is mock_llm
        assert pipeline._prompts is mock_prompts
        assert pipeline._selfcheck is mock_checker

    def test_execute_degraded_when_llm_unavailable(self, sample_request):
        import asyncio
        mock_llm = AsyncMock()
        mock_llm.generate.side_effect = RuntimeError("LLM 不可用")
        mock_prompts = MagicMock()
        mock_prompts._build_stable.return_value = "stable prompt"
        mock_prompts._build_context_vars.return_value = {"destination": "东京"}
        mock_prompts._build_context.return_value = "context prompt"
        mock_checker = MagicMock()

        pipeline = CoTPipeline(mock_llm, mock_prompts, mock_checker)
        result = asyncio.run(pipeline.execute(sample_request))
        assert result.degraded is True
        assert result.draft is None
        assert "RuntimeError" in result.degraded_reason

    def test_parse_attractions_valid_data(self):
        data = {
            "attractions": [
                {
                    "name": "浅草寺",
                    "location": "东京浅草",
                    "type": "culture",
                    "suggested_duration_minutes": 120,
                    "estimated_price": 0,
                    "rating": 4.5,
                    "reason": "东京最古老的寺院，感受江户历史文化的最佳场所",
                },
                {
                    "name": "筑地市场",
                    "location": "东京筑地",
                    "type": "food",
                    "suggested_duration_minutes": 180,
                    "estimated_price": 50,
                    "rating": 4.6,
                    "reason": "东京美食天堂，新鲜海鲜和各种日本料理的集中地",
                },
            ]
        }
        result = CoTPipeline._parse_attractions(data)
        assert len(result) == 2
        assert result[0].name == "浅草寺"
        assert result[0].type == "culture"
        assert result[1].name == "筑地市场"

    def test_parse_itinerary_valid_data(self):
        data = {
            "daily_itinerary": [
                {
                    "day": 1,
                    "activities": [
                        {
                            "name": "浅草寺",
                            "type": "culture",
                            "start_time": "09:00",
                            "duration_minutes": 120,
                            "location": "浅草",
                            "estimated_cost": 0,
                            "reason": "东京最古老的寺院感受江户文化",
                        }
                    ],
                    "meals": {
                        "lunch": {
                            "type": "lunch",
                            "restaurant_name": "一兰拉面",
                            "location": "浅草",
                            "cuisine": "日式拉面",
                            "estimated_cost": 60,
                            "dietary_compatible": True,
                        },
                        "dinner": {
                            "type": "dinner",
                            "restaurant_name": "回转寿司",
                            "location": "上野",
                            "cuisine": "日式寿司",
                            "estimated_cost": 100,
                            "dietary_compatible": True,
                        },
                    },
                    "total_day_cost": 160,
                }
            ]
        }
        result = CoTPipeline._parse_itinerary(data)
        assert len(result) == 1
        assert len(result[0].activities) == 1
        assert result[0].activities[0].name == "浅草寺"
        assert result[0].meals["lunch"].restaurant_name == "一兰拉面"
        assert result[0].meals["dinner"].restaurant_name == "回转寿司"

    def test_assemble_draft_produces_valid_travel_plan_draft(self, sample_request):
        daily = [
            ItineraryDay(day=1, activities=[
                _make_activity("浅草寺", "culture", 0, 35.714, 139.796),
            ], meals={
                "lunch": _make_meal("lunch", "拉面", 80),
                "dinner": _make_meal("dinner", "寿司", 120),
            }, total_day_cost=200),
        ]
        budget_alloc = BudgetAllocation(
            transportation=5000, accommodation=4500,
            activities=2250, meals=2250, buffer=1000, currency="CNY",
        )
        draft = CoTPipeline._assemble_draft(
            dest=sample_request.destination,
            days=1,
            budget=sample_request.budget,
            daily_itinerary=daily,
            budget_alloc=budget_alloc,
            accommodations=[],
            prefs=sample_request.preferences,
            dates=sample_request.dates,
        )
        assert isinstance(draft, TravelPlanDraft)
        assert draft.destination["city"] == "东京"
        assert draft.duration_days == 1
        assert draft.total_budget == 15000
        assert len(draft.daily_itinerary) == 1

    def test_parse_budget_normalizes_to_total(self):
        data = {"transportation": 4000, "accommodation": 3500,
                "activities": 2000, "meals": 2000, "buffer": 500, "currency": "CNY"}
        result = CoTPipeline._parse_budget(data, 15000)
        assert abs(result.transportation + result.accommodation +
                   result.activities + result.meals +
                   result.buffer - 15000) < 0.01
