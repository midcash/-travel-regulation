"""Tests for agents/execution_agent.py — Execution Agent。

覆盖:
- validate_feasibility: 完整5项校验
- check_prices: 价格校验 (正常/边界/异常)
- check_time: 时间校验 (正常/边界/超时)
- check_geography: 地理校验 (正常/绕路)
- check_constraints: 硬约束/软约束校验
- identify_risks: 风险识别
- estimate_market_price: 市场价格查询
- handle_message: 消息处理
- 边界: 空行程/所有API不可用等
"""

import asyncio
import pytest
from datetime import datetime, timezone
from uuid import uuid4

from agents.execution_agent import ExecutionAgent
from core.message import (
    AgentIdentity,
    AgentMessage,
    TaskType,
    ErrorCode,
    BaseAgent,
)
from models.request import StructuredRequest, Destination, DateRange, Budget, Travelers, Preferences
from models.plan import TravelPlanDraft, ItineraryDay, Activity, Meal, BudgetAllocation
from models.validation import (
    ValidationReport,
    PriceCheckResult,
    TimeCheckResult,
    GeographyCheckResult,
    ConstraintCheckResult,
    RiskAlert,
    PriceAnomaly,
    TimeConflict,
    GeographyDetour,
    BlockingConstraint,
    ConstraintWarning,
)


@pytest.fixture
def agent():
    return ExecutionAgent()


@pytest.fixture
def sample_draft():
    return TravelPlanDraft(
        draft_id=str(uuid4()),
        destination="东京, 日本",
        duration_days=3,
        total_budget=15000,
        daily_itinerary=[
            ItineraryDay(
                day=1,
                activities=[
                    Activity(name="浅草寺", type="culture", start_time="09:00", duration_minutes=120,
                             location="浅草", estimated_cost=100, reason="东京最古老的历史文化寺庙，游客必去之地"),
                    Activity(name="上野公园", type="nature", start_time="13:00", duration_minutes=90,
                             location="上野", estimated_cost=50, reason="自然风光与文化展览融合的大型公园"),
                ],
                meals={
                    "breakfast": Meal(type="breakfast", restaurant_name="早餐店", location="浅草",
                                     cuisine="日式", estimated_cost=50),
                    "lunch": Meal(type="lunch", restaurant_name="拉面馆", location="上野",
                                 cuisine="日式", estimated_cost=80),
                },
                total_day_cost=280,
                total_duration_minutes=270,
            ),
        ],
        accommodation=[{"name": "酒店A", "cost_per_night": 500}],
        budget_allocation=BudgetAllocation(transportation=4500, accommodation=5250, activities=2250, meals=2250, buffer=750),
    )


@pytest.fixture
def sample_request():
    return StructuredRequest(
        destination=Destination(city="东京", country="日本"),
        dates=DateRange(arrival="2026-12-20", departure="2026-12-25", duration_days=5),
        budget=Budget(total=15000),
        travelers=Travelers(adults=2),
        preferences=Preferences(style=["food", "culture"]),
    )


# ============================================================
# BaseAgent 接口
# ============================================================

class TestBaseAgentInterface:
    def test_agent_name(self, agent):
        assert agent.agent_name == "execution_agent"

    def test_agent_version(self, agent):
        assert agent.agent_version == "1.0.0"

    def test_inherits_base_agent(self, agent):
        assert isinstance(agent, BaseAgent)

    def test_capabilities(self, agent):
        caps = agent.get_capabilities()
        names = {c.name for c in caps}
        assert "validate_feasibility" in names
        assert "check_prices" in names
        assert "check_time" in names
        assert "check_geography" in names


# ============================================================
# validate_feasibility — 集成校验
# ============================================================

class TestValidateFeasibility:
    def test_returns_validation_report(self, agent, sample_draft, sample_request):
        report = asyncio.run(agent.validate_feasibility(sample_draft, sample_request))
        assert isinstance(report, ValidationReport)
        assert report.validation_id is not None

    def test_report_has_all_sections(self, agent, sample_draft, sample_request):
        report = asyncio.run(agent.validate_feasibility(sample_draft, sample_request))
        assert report.price_check is not None
        assert report.time_check is not None
        assert report.geography_check is not None
        assert report.constraint_check is not None
        assert isinstance(report.risk_alerts, list)

    def test_overall_status(self, agent, sample_draft, sample_request):
        report = asyncio.run(agent.validate_feasibility(sample_draft, sample_request))
        assert report.overall_status in ("feasible", "feasible_with_warnings", "infeasible")

    def test_summary_has_counts(self, agent, sample_draft, sample_request):
        report = asyncio.run(agent.validate_feasibility(sample_draft, sample_request))
        assert report.summary.blocking_count >= 0
        assert report.summary.warning_count >= 0

    def test_feasible_for_normal_draft(self, agent, sample_draft, sample_request):
        """TS-EXEC正常场景: 正常草稿应 feasible。"""
        report = asyncio.run(agent.validate_feasibility(sample_draft, sample_request))
        assert report.overall_status != "infeasible"


# ============================================================
# check_prices — 价格校验
# ============================================================

class TestCheckPrices:
    def test_returns_price_check_result(self, agent, sample_draft):
        result = asyncio.run(agent.check_prices(sample_draft))
        assert isinstance(result, PriceCheckResult)

    def test_items_checked_positive(self, agent, sample_draft):
        result = asyncio.run(agent.check_prices(sample_draft))
        assert result.items_checked > 0

    def test_overall_accuracy_score_in_range(self, agent, sample_draft):
        result = asyncio.run(agent.check_prices(sample_draft))
        assert 0 <= result.overall_accuracy_score <= 100

    def test_empty_draft_no_anomalies(self, agent):
        draft = TravelPlanDraft(draft_id=str(uuid4()))
        result = asyncio.run(agent.check_prices(draft))
        assert result.items_checked == 0
        assert result.anomalies == []

    def test_anomaly_has_severity(self, agent, sample_draft):
        result = asyncio.run(agent.check_prices(sample_draft))
        for a in result.anomalies:
            assert a.severity in ("high", "medium", "low")


# ============================================================
# check_time — 时间校验
# ============================================================

class TestCheckTime:
    def test_returns_time_check_result(self, agent, sample_draft):
        result = asyncio.run(agent.check_time(sample_draft))
        assert isinstance(result, TimeCheckResult)

    def test_days_checked_matches(self, agent, sample_draft):
        result = asyncio.run(agent.check_time(sample_draft))
        assert result.days_checked == 1  # 1 ItineraryDay in fixture

    def test_overall_time_score_in_range(self, agent, sample_draft):
        result = asyncio.run(agent.check_time(sample_draft))
        assert 0 <= result.overall_time_score <= 100

    def test_empty_draft_no_conflicts(self, agent):
        draft = TravelPlanDraft(draft_id=str(uuid4()))
        result = asyncio.run(agent.check_time(draft))
        assert result.days_checked == 0

    def test_overloaded_day_has_conflict(self, agent):
        """某天总时长 > 12h → conflict high。"""
        draft = TravelPlanDraft(
            draft_id=str(uuid4()),
            daily_itinerary=[
                ItineraryDay(
                    day=1,
                    activities=[
                        Activity(name="A", type="culture", start_time="09:00", duration_minutes=360,
                                 location="X", estimated_cost=0, reason="长时间活动测试用例验证超时检测"),
                        Activity(name="B", type="culture", start_time="15:00", duration_minutes=360,
                                 location="Y", estimated_cost=0, reason="第二个长时间活动用于压力测试"),
                    ],
                    total_duration_minutes=800,  # > 720 min (12h)
                ),
            ],
        )
        result = asyncio.run(agent.check_time(draft))
        assert len(result.conflicts) >= 1
        assert result.conflicts[0].severity == "high"


# ============================================================
# check_geography — 地理校验
# ============================================================

class TestCheckGeography:
    def test_returns_geography_check_result(self, agent, sample_draft):
        result = asyncio.run(agent.check_geography(sample_draft))
        assert isinstance(result, GeographyCheckResult)

    def test_overall_geo_score_in_range(self, agent, sample_draft):
        result = asyncio.run(agent.check_geography(sample_draft))
        assert 0 <= result.overall_geo_score <= 100

    def test_empty_draft(self, agent):
        draft = TravelPlanDraft(draft_id=str(uuid4()))
        result = asyncio.run(agent.check_geography(draft))
        assert result.detours_found == 0


# ============================================================
# check_constraints — 约束校验
# ============================================================

class TestCheckConstraints:
    def test_returns_constraint_check_result(self, agent, sample_draft, sample_request):
        result = asyncio.run(agent.check_constraints(sample_draft, sample_request))
        assert isinstance(result, ConstraintCheckResult)

    def test_no_request_passes_with_defaults(self, agent, sample_draft):
        result = asyncio.run(agent.check_constraints(sample_draft, None))
        assert result.hard_constraints_passed >= 1

    def test_over_budget_blocking(self, agent):
        """预算超支 → blocking。"""
        draft = TravelPlanDraft(
            draft_id=str(uuid4()),
            total_budget=1000,
            daily_itinerary=[ItineraryDay(day=1, activities=[], meals={})],
            accommodation=[],
            budget_allocation=BudgetAllocation(transportation=2000, accommodation=0, activities=0, meals=0, buffer=0),
        )
        request = StructuredRequest(
            destination=Destination(city="东京", country="日本"),
            dates=DateRange(duration_days=3),
            budget=Budget(total=1000),
        )
        result = asyncio.run(agent.check_constraints(draft, request))
        assert len(result.blocking_issues) >= 1

    def test_few_accommodation_warning(self, agent, sample_request):
        draft = TravelPlanDraft(
            draft_id=str(uuid4()),
            daily_itinerary=[ItineraryDay(day=1, activities=[], meals={})],
            accommodation=[{"name": "仅1个"}],
        )
        result = asyncio.run(agent.check_constraints(draft, sample_request))
        has_accommodation_warning = any(
            "住宿" in w.issue or "accommodation" in w.constraint
            for w in result.warnings
        )
        assert has_accommodation_warning


# ============================================================
# identify_risks
# ============================================================

class TestIdentifyRisks:
    def test_returns_risk_alerts(self, agent, sample_draft):
        risks = asyncio.run(agent.identify_risks(sample_draft))
        assert len(risks) >= 1
        for r in risks:
            assert isinstance(r, RiskAlert)
            assert r.category in ("weather", "safety", "health", "documents")
            assert r.severity in ("high", "medium", "low")

    def test_includes_documents_risk(self, agent, sample_draft):
        risks = asyncio.run(agent.identify_risks(sample_draft))
        categories = {r.category for r in risks}
        assert "documents" in categories


# ============================================================
# estimate_market_price
# ============================================================

class TestEstimateMarketPrice:
    def test_returns_price_range(self, agent):
        price = asyncio.run(agent.estimate_market_price("flight", "东京", "2026-12-20"))
        from models.entities import PriceRange
        assert isinstance(price, PriceRange)
        assert price.item_type == "flight"
        assert price.low <= price.median <= price.high

    def test_default_location(self, agent):
        price = asyncio.run(agent.estimate_market_price("flight", "unknown_city"))
        assert price.median > 0

    def test_different_types(self, agent):
        for item_type in ["flight", "hotel", "attraction", "meal"]:
            price = asyncio.run(agent.estimate_market_price(item_type, "东京"))
            assert price.item_type == item_type
            assert price.median > 0


# ============================================================
# 消息处理
# ============================================================

class TestHandleMessage:
    def _make_msg(self, task_type, payload=None):
        identity = AgentIdentity("orchestrator", "1.0.0", [], "internal", "online")
        receiver = AgentIdentity("execution_agent", "1.0.0", [], "internal", "online")
        return AgentMessage(
            message_id=str(uuid4()),
            sender=identity,
            receiver=receiver,
            task_type=task_type,
            payload=payload or {},
            timestamp=datetime.now(timezone.utc),
        )

    def test_validate_feasibility_msg(self, agent, sample_draft):
        msg = self._make_msg(TaskType.TASK_VALIDATE_FEASIBILITY, {
            "travel_plan_draft": sample_draft.to_dict(),
            "request": {
                "destination": {"city": "东京", "country": "日本"},
                "dates": {"arrival": "2026-12-20", "departure": "2026-12-25", "duration_days": 5},
                "budget": {"total": 15000},
            },
        })
        resp = asyncio.run(agent.handle_message(msg))
        assert resp.task_type == TaskType.RESPONSE_VALIDATION_REPORT
        assert "data" in resp.payload

    def test_unsupported_task_type(self, agent):
        msg = self._make_msg(TaskType.CONTROL_ABORT)
        resp = asyncio.run(agent.handle_message(msg))
        assert resp.task_type == TaskType.RESPONSE_ERROR
