"""Tests for agents/evaluation_agent.py — Evaluation Agent Mode A/B/C。

覆盖:
- Mode A: evaluate_code (代码质量评估)
- Mode B: evaluate_plan (业务产出评估)
- Mode C: evaluate_contribution (贡献度评估 LOO+360+协同)
- Mode A 维度评分方法
- 消息处理 handle_message
- 边界: 空code_files, 小样本消融等
"""

import asyncio
import pytest
from datetime import datetime, timezone
from uuid import uuid4

from agents.evaluation_agent import EvaluationAgent
from core.message import (
    AgentIdentity,
    AgentMessage,
    TaskType,
    ErrorCode,
    BaseAgent,
)
from models.plan import TravelPlanDraft, ItineraryDay, Activity, Meal, BudgetAllocation
from models.quality import (
    CodeQualityReport,
    PlanQualityReport,
    ContributionReport,
    DimensionScore,
    PlanDimensionScore,
    AblationResult,
    AblationResults,
    ImportanceScore,
    Assessment360,
    SynergyReport,
)


@pytest.fixture
def agent():
    return EvaluationAgent()


@pytest.fixture
def sample_draft():
    return TravelPlanDraft(
        draft_id=str(uuid4()),
        destination="东京, 日本",
        duration_days=5,
        total_budget=15000,
        daily_itinerary=[
            ItineraryDay(
                day=1,
                activities=[
                    Activity(name="浅草寺", type="culture", start_time="09:00", duration_minutes=120,
                             location="浅草", estimated_cost=0, reason="东京最古老的历史文化寺庙必游之地"),
                    Activity(name="上野公园", type="nature", start_time="13:00", duration_minutes=90,
                             location="上野", estimated_cost=0, reason="自然风光与文化艺术融合的大型公园"),
                ],
                meals={
                    "breakfast": Meal(type="breakfast", restaurant_name="早餐店", location="浅草",
                                     cuisine="日式", estimated_cost=50),
                    "lunch": Meal(type="lunch", restaurant_name="拉面馆", location="上野",
                                 cuisine="日式", estimated_cost=80),
                    "dinner": Meal(type="dinner", restaurant_name="居酒屋", location="浅草",
                                  cuisine="日式", estimated_cost=120),
                },
            ),
        ],
        accommodation=[],
        budget_allocation=BudgetAllocation(transportation=4500, accommodation=5250, activities=2250, meals=2250, buffer=750),
    )


# ============================================================
# BaseAgent 接口
# ============================================================

class TestBaseAgentInterface:
    def test_agent_name(self, agent):
        assert agent.agent_name == "evaluation_agent"

    def test_agent_version(self, agent):
        assert agent.agent_version == "1.0.0"

    def test_inherits_base_agent(self, agent):
        assert isinstance(agent, BaseAgent)

    def test_capabilities(self, agent):
        caps = agent.get_capabilities()
        names = {c.name for c in caps}
        assert "evaluate_code" in names
        assert "evaluate_plan" in names
        assert "evaluate_contribution" in names


# ============================================================
# Mode A: evaluate_code
# ============================================================

class TestModeAEvaluateCode:
    def test_evaluate_code_returns_report(self, agent):
        report = asyncio.run(agent.evaluate_code("test_agent", ["test_file.py"]))
        assert isinstance(report, CodeQualityReport)
        assert report.target_agent == "test_agent"
        assert report.total_score > 0
        assert report.verdict in ("PASS", "PASS_WITH_SUGGESTIONS", "NEEDS_REVISION", "REJECT")

    def test_evaluate_code_all_dimensions(self, agent):
        report = asyncio.run(agent.evaluate_code("test_agent", ["test_file.py"]))
        expected_dims = {"correctness", "robustness", "readability", "performance", "security"}
        assert set(report.dimensions.keys()) == expected_dims

    def test_evaluate_code_scores_in_range(self, agent):
        report = asyncio.run(agent.evaluate_code("test_agent", ["test_file.py"]))
        for dim in report.dimensions.values():
            assert 1.0 <= dim.score <= 5.0

    def test_evaluate_code_empty_files_raises(self, agent):
        with pytest.raises(ValueError, match="不能为空"):
            asyncio.run(agent.evaluate_code("test_agent", []))

    def test_evaluate_code_report_id(self, agent):
        report = asyncio.run(agent.evaluate_code("test_agent", ["a.py"]))
        assert report.report_id is not None

    def test_evaluate_code_multiple_files(self, agent):
        report = asyncio.run(agent.evaluate_code("agent_x", ["a.py", "b.py", "c.py"]))
        assert len(report.code_files) == 3


# ============================================================
# Mode A: 维度评分方法
# ============================================================

class TestModeADimensionScorers:
    def test_score_correctness(self, agent):
        dim = asyncio.run(agent.score_correctness("code", "spec"))
        assert isinstance(dim, DimensionScore)
        assert dim.dimension == "correctness"

    def test_score_robustness(self, agent):
        dim = asyncio.run(agent.score_robustness("code"))
        assert dim.dimension == "robustness"

    def test_score_readability(self, agent):
        dim = asyncio.run(agent.score_readability("code"))
        assert dim.dimension == "readability"

    def test_score_performance(self, agent):
        dim = asyncio.run(agent.score_performance("code"))
        assert dim.dimension == "performance"

    def test_score_security(self, agent):
        dim = asyncio.run(agent.score_security("code"))
        assert dim.dimension == "security"


# ============================================================
# Mode B: evaluate_plan
# ============================================================

class TestModeBEvaluatePlan:
    def test_evaluate_plan_returns_report(self, agent, sample_draft):
        report = asyncio.run(agent.evaluate_plan(sample_draft))
        assert isinstance(report, PlanQualityReport)
        assert report.composite_score > 0
        assert report.verdict in ("PASS", "REVISE", "REJECT")

    def test_evaluate_plan_dimensions(self, agent, sample_draft):
        report = asyncio.run(agent.evaluate_plan(sample_draft))
        expected = {"completeness", "feasibility", "constraint_satisfaction",
                    "experience_quality", "information_accuracy"}
        assert set(report.dimensions.keys()) == expected

    def test_evaluate_plan_scores_in_range(self, agent, sample_draft):
        report = asyncio.run(agent.evaluate_plan(sample_draft))
        for dim in report.dimensions.values():
            assert 1.0 <= dim.score <= 5.0

    def test_evaluate_plan_composite_0_100(self, agent, sample_draft):
        report = asyncio.run(agent.evaluate_plan(sample_draft))
        assert 0 <= report.composite_score <= 100

    def test_evaluate_plan_idempotent(self, agent, sample_draft):
        r1 = asyncio.run(agent.evaluate_plan(sample_draft))
        r2 = asyncio.run(agent.evaluate_plan(sample_draft))
        # 幂等: 缓存命中 → 相同 report_id
        assert r1.report_id == r2.report_id

    def test_evaluate_plan_low_quality(self, agent):
        """缺住宿+缺活动+缺预算的草稿 → 低分。"""
        draft = TravelPlanDraft(
            draft_id=str(uuid4()),
            destination="东京",
            duration_days=1,
            total_budget=100,
            daily_itinerary=[],
            accommodation=[],
        )
        report = asyncio.run(agent.evaluate_plan(draft))
        assert report.composite_score < 70

    def test_evaluate_plan_empty_draft(self, agent):
        draft = TravelPlanDraft(draft_id=str(uuid4()))
        report = asyncio.run(agent.evaluate_plan(draft))
        assert isinstance(report, PlanQualityReport)


# ============================================================
# Mode B: 维度评分方法
# ============================================================

class TestModeBDimensionScorers:
    def test_score_completeness_full(self, agent, sample_draft):
        dim = asyncio.run(agent.score_completeness(sample_draft))
        assert dim.dimension == "completeness"
        assert 1.0 <= dim.score <= 5.0

    def test_score_completeness_empty(self, agent):
        draft = TravelPlanDraft(draft_id=str(uuid4()))
        dim = asyncio.run(agent.score_completeness(draft))
        assert dim.score <= 3

    def test_score_feasibility_no_validation(self, agent):
        dim = asyncio.run(agent.score_feasibility(None))
        assert dim.score == 3  # 无校验报告默认3分

    def test_score_experience(self, agent, sample_draft):
        dim = asyncio.run(agent.score_experience(sample_draft))
        assert dim.dimension == "experience_quality"

    def test_score_accuracy_no_validation(self, agent):
        dim = asyncio.run(agent.score_accuracy(None))
        assert dim.score == 3


# ============================================================
# Mode C: evaluate_contribution
# ============================================================

class TestModeCEvaluateContribution:
    @pytest.fixture
    def sample_test_suite(self):
        return [{"id": f"tc-{i}", "input": {}, "expected": {}} for i in range(5)]

    def test_evaluate_contribution_basic(self, agent, sample_test_suite):
        report = asyncio.run(
            agent.evaluate_contribution(sample_test_suite, ["orchestrator", "planning_agent", "execution_agent", "evaluation_agent"])
        )
        assert isinstance(report, ContributionReport)
        assert report.ablation is not None
        assert report.synergy is not None

    def test_ablation_baseline_score(self, agent, sample_test_suite):
        report = asyncio.run(
            agent.evaluate_contribution(sample_test_suite, ["orchestrator", "planning_agent", "execution_agent", "evaluation_agent"])
        )
        assert report.ablation.baseline_score > 0

    def test_ablation_results_count(self, agent, sample_test_suite):
        report = asyncio.run(
            agent.evaluate_contribution(sample_test_suite, ["orchestrator", "planning_agent", "execution_agent", "evaluation_agent"])
        )
        # full + 3 LOO configs = 4 results
        assert len(report.ablation.results) == 4

    def test_marginal_contributions(self, agent, sample_test_suite):
        report = asyncio.run(
            agent.evaluate_contribution(sample_test_suite, ["orchestrator", "planning_agent", "execution_agent", "evaluation_agent"])
        )
        for agent_name in ["planning_agent", "execution_agent", "evaluation_agent"]:
            assert agent_name in report.ablation.marginal_contributions

    def test_contribution_rates_sum_100(self, agent, sample_test_suite):
        report = asyncio.run(
            agent.evaluate_contribution(sample_test_suite, ["orchestrator", "planning_agent", "execution_agent", "evaluation_agent"])
        )
        total_cr = sum(report.ablation.contribution_rates.values())
        assert 95 <= total_cr <= 105

    def test_importance_scores(self, agent, sample_test_suite):
        report = asyncio.run(
            agent.evaluate_contribution(sample_test_suite, ["orchestrator", "planning_agent", "execution_agent", "evaluation_agent"])
        )
        assert len(report.importance_scores) == 3
        for imp in report.importance_scores:
            assert isinstance(imp, ImportanceScore)
            assert imp.rank > 0
            assert imp.label in ("veto", "bottleneck", "free_rider", "standard")

    def test_360_assessments(self, agent, sample_test_suite):
        report = asyncio.run(
            agent.evaluate_contribution(sample_test_suite, ["orchestrator", "planning_agent", "execution_agent", "evaluation_agent"])
        )
        assert len(report.assessments_360) == 3
        for a in report.assessments_360:
            assert isinstance(a, Assessment360)
            assert a.alignment in ("aligned", "overconfident", "underconfident")

    def test_synergy_report(self, agent, sample_test_suite):
        report = asyncio.run(
            agent.evaluate_contribution(sample_test_suite, ["orchestrator", "planning_agent", "execution_agent", "evaluation_agent"])
        )
        syn = report.synergy
        assert isinstance(syn, SynergyReport)
        assert syn.level in ("strong", "moderate", "weak")

    def test_small_sample_still_works(self, agent):
        """样本不足5个也继续执行（降低置信度）。"""
        small_suite = [{"id": f"tc-{i}"} for i in range(3)]
        report = asyncio.run(agent.evaluate_contribution(small_suite, ["orchestrator", "planning_agent"]))
        assert isinstance(report, ContributionReport)


# ============================================================
# 消息处理
# ============================================================

class TestHandleMessage:
    def _make_msg(self, task_type, payload=None):
        identity = AgentIdentity("orchestrator", "1.0.0", [], "internal", "online")
        receiver = AgentIdentity("evaluation_agent", "1.0.0", [], "internal", "online")
        return AgentMessage(
            message_id=str(uuid4()),
            sender=identity,
            receiver=receiver,
            task_type=task_type,
            payload=payload or {},
            timestamp=datetime.now(timezone.utc),
        )

    def test_evaluate_code_msg(self, agent):
        msg = self._make_msg(TaskType.TASK_EVALUATE_CODE, {
            "target_agent": "test_agent",
            "code_files": ["test.py"],
        })
        resp = asyncio.run(agent.handle_message(msg))
        assert resp.task_type == TaskType.RESPONSE_RESULT
        assert resp.payload["result_type"] == "code_quality_report"

    def test_evaluate_plan_msg(self, agent):
        msg = self._make_msg(TaskType.TASK_EVALUATE_PLAN, {
            "travel_plan_draft": {"draft_id": "d1", "destination": "东京", "duration_days": 3, "total_budget": 10000},
        })
        resp = asyncio.run(agent.handle_message(msg))
        assert resp.task_type == TaskType.RESPONSE_RESULT
        assert resp.payload["result_type"] == "plan_quality_report"

    def test_evaluate_contribution_msg(self, agent):
        suite = [{"id": f"tc-{i}"} for i in range(5)]
        msg = self._make_msg(TaskType.TASK_EVALUATE_CONTRIBUTION, {
            "test_cases": suite,
            "baseline_config": ["orchestrator", "planning_agent", "execution_agent", "evaluation_agent"],
        })
        resp = asyncio.run(agent.handle_message(msg))
        assert resp.task_type == TaskType.RESPONSE_RESULT
        assert resp.payload["result_type"] == "contribution_report"

    def test_unsupported_task_type(self, agent):
        msg = self._make_msg(TaskType.CONTROL_ABORT)
        resp = asyncio.run(agent.handle_message(msg))
        assert resp.task_type == TaskType.RESPONSE_ERROR
