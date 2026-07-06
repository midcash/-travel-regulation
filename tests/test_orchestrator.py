"""Tests for agents/orchestrator.py — Orchestrator 主控 Agent。

覆盖:
- parse_user_request: 目的地/日期/预算/人数/偏好解析
- decompose_task: 任务DAG 构建
- route_task: 路由映射
- manage_quality_gate: Gate 0-3
- assemble_plan: plan 整合
- handle_revision: 修订决策
- 边界: 空输入/过去日期/超预算等
"""

import asyncio
import pytest
from datetime import date, datetime, timezone
from uuid import uuid4

from agents.orchestrator import Orchestrator
from core.message import (
    AgentIdentity,
    AgentMessage,
    TaskType,
    ErrorCode,
    BaseAgent,
    MessageValidationError,
)
from core.context import SharedContext, ContextStatus
from core.gate_runner import GateResult, GateRunner
from core.orchestration_engine import Task, TaskDAG, TaskStatus
from models.request import StructuredRequest, Destination, DateRange, Budget, Travelers, Preferences


# ============================================================
# Fixtures
# ============================================================

@pytest.fixture
def orch():
    return Orchestrator()


@pytest.fixture
def ctx():
    return SharedContext()


@pytest.fixture
def orch_with_ctx(ctx):
    return Orchestrator(context=ctx)


# ============================================================
# BaseAgent 接口
# ============================================================

class TestBaseAgentInterface:
    def test_agent_name(self, orch):
        assert orch.agent_name == "orchestrator"

    def test_agent_version(self, orch):
        assert orch.agent_version == "1.1.0"

    def test_inherits_base_agent(self, orch):
        assert isinstance(orch, BaseAgent)

    def test_capabilities(self, orch):
        caps = orch.get_capabilities()
        names = {c.name for c in caps}
        assert "parse_user_request" in names
        assert "assemble_plan" in names
        assert "manage_quality_gate" in names


# ============================================================
# parse_user_request — spec §2.1
# ============================================================

class TestParseUserRequest:
    def test_standard_request(self, orch):
        """TS-E2E-001: 标准旅行规划输入解析。"""
        req = orch.parse_user_request("我想去日本东京旅游，12月20号出发，12月25号返回，2个人，预算总共15000元，喜欢美食和文化体验")
        assert req.destination.city == "东京"
        assert req.destination.country == "日本"
        assert req.budget.total == 15000
        assert req.travelers.adults == 2
        assert "food" in req.preferences.style
        assert "culture" in req.preferences.style

    def test_short_trip(self, orch):
        """TS-E2E-002: 短途旅行解析。"""
        req = orch.parse_user_request("去广州玩1天，预算500块，喜欢美食")
        assert req.destination.city == "广州"
        assert req.dates.duration_days == 1
        assert req.budget.total == 500

    def test_long_trip(self, orch):
        """TS-E2E-003: 长途旅行解析。"""
        req = orch.parse_user_request("去欧洲法国巴黎，14天，预算5万")
        assert req.destination.city == "巴黎"
        assert req.dates.duration_days == 14
        assert req.budget.total == 50000

    def test_with_preferences(self, orch):
        """偏好标签提取。"""
        req = orch.parse_user_request("去成都4天，预算5000，喜欢美食和自然风光，节奏慢一点")
        assert req.destination.city == "成都"
        assert "food" in req.preferences.style
        assert "nature" in req.preferences.style

    def test_with_pace_relaxed(self, orch):
        req = orch.parse_user_request("去杭州3天，预算3000，轻松放松的旅行")
        assert req.preferences.pace == "relaxed"

    def test_with_dietary(self, orch):
        req = orch.parse_user_request("去曼谷5天，预算8000，素食者")
        assert "vegetarian" in req.preferences.dietary

    def test_with_children(self, orch):
        req = orch.parse_user_request("去三亚5天，4大人2小孩，预算3万，亲子游")
        assert req.travelers.adults == 4
        assert req.travelers.children == 2

    def test_unknown_destination(self, orch):
        """未知目的地仍有默认值 (regex excludes digits/chars)。"""
        req = orch.parse_user_request("去xyzabc玩5天，预算2000")
        assert req.destination.city == "xyzabc玩"

    def test_single_traveler_default(self, orch):
        """未指定人数默认为1。"""
        req = orch.parse_user_request("去北京3天，预算3000")
        assert req.travelers.adults == 1

    def test_budget_wan(self, orch):
        req = orch.parse_user_request("去上海3天，预算2万")
        assert req.budget.total == 20000

    def test_budget_k(self, orch):
        req = orch.parse_user_request("去东京5天，预算10k")
        assert req.budget.total == 10000

    def test_request_id_generated(self, orch):
        req = orch.parse_user_request("去东京5天，预算1万")
        assert req.request_id is not None

    def test_raw_text_preserved(self, orch):
        text = "去东京5天，预算1万"
        req = orch.parse_user_request(text)
        assert req.raw_text == text


# ============================================================
# decompose_task — spec §2.2
# ============================================================

class TestDecomposeTask:
    def test_four_tasks_created(self, orch):
        request = StructuredRequest(
            destination=Destination(city="东京", country="日本"),
            dates=DateRange(arrival="2026-12-20", departure="2026-12-25", duration_days=5),
            budget=Budget(total=15000),
        )
        dag = orch.decompose_task(request)
        assert dag.task_count == 4

    def test_task_ids(self, orch):
        request = StructuredRequest(
            destination=Destination(city="东京", country="日本"),
            dates=DateRange(duration_days=5),
            budget=Budget(total=15000),
        )
        dag = orch.decompose_task(request)
        task_ids = {t.task_id for t in dag.get_all_tasks()}
        assert "T1" in task_ids
        assert "T2" in task_ids
        assert "T3" in task_ids
        assert "T4" in task_ids

    def test_dependencies(self, orch):
        request = StructuredRequest(
            destination=Destination(city="东京", country="日本"),
            dates=DateRange(duration_days=5),
            budget=Budget(total=15000),
        )
        dag = orch.decompose_task(request)
        t1 = dag.get_task("T1")
        t2 = dag.get_task("T2")
        t3 = dag.get_task("T3")
        t4 = dag.get_task("T4")
        assert t1.dependencies == []
        assert t2.dependencies == []
        assert t3.dependencies == ["T1", "T2"]
        assert t4.dependencies == ["T1", "T2", "T3"]

    def test_topological_order(self, orch):
        request = StructuredRequest(
            destination=Destination(city="东京", country="日本"),
            dates=DateRange(duration_days=5),
            budget=Budget(total=15000),
        )
        dag = orch.decompose_task(request)
        order = dag.topological_order()
        assert len(order) == 4

    def test_all_tasks_are_create_itinerary(self, orch):
        request = StructuredRequest(
            destination=Destination(city="东京", country="日本"),
            dates=DateRange(duration_days=5),
            budget=Budget(total=15000),
        )
        dag = orch.decompose_task(request)
        for t in dag.get_all_tasks():
            assert t.task_type == TaskType.TASK_CREATE_ITINERARY


# ============================================================
# route_task
# ============================================================

class TestRouteTask:
    def test_route_create_itinerary(self, orch):
        task = Task(task_id="T1", title="test", task_type=TaskType.TASK_CREATE_ITINERARY)
        agent = orch.route_task(task)
        assert agent == "planning_agent"

    def test_route_revise_itinerary(self, orch):
        task = Task(task_id="T2", title="revise", task_type=TaskType.TASK_REVISE_ITINERARY)
        agent = orch.route_task(task)
        assert agent == "planning_agent"

    def test_route_validate_feasibility(self, orch):
        task = Task(task_id="T3", title="validate", task_type=TaskType.TASK_VALIDATE_FEASIBILITY)
        agent = orch.route_task(task)
        assert agent == "execution_agent"

    def test_route_evaluate_plan(self, orch):
        task = Task(task_id="T4", title="evaluate", task_type=TaskType.TASK_EVALUATE_PLAN)
        agent = orch.route_task(task)
        assert agent == "evaluation_agent"

    def test_route_sets_assigned_agent(self, orch):
        task = Task(task_id="T5", title="test", task_type=TaskType.TASK_CREATE_ITINERARY)
        orch.route_task(task)
        assert task.assigned_agent == "planning_agent"


# ============================================================
# manage_quality_gate — Gate 0-3
# ============================================================

class TestQualityGates:
    def test_gate_0_pass(self, orch):
        payload = {
            "destination": {"city": "东京", "country": "日本"},
            "dates": {"arrival": "2026-12-20", "departure": "2026-12-25"},
            "budget": {"total": 15000, "currency": "CNY"},
            "travelers": {"adults": 2, "children": 0},
        }
        result = orch.manage_quality_gate(0, payload)
        assert result.passed

    def test_gate_0_fail_missing_destination(self, orch):
        payload = {
            "destination": {"city": ""},
            "dates": {"arrival": "2026-12-20", "departure": "2026-12-25"},
            "budget": {"total": 15000},
            "travelers": {"adults": 2},
        }
        result = orch.manage_quality_gate(0, payload)
        assert not result.passed

    def test_gate_0_fail_past_date(self, orch):
        payload = {
            "destination": {"city": "东京", "country": "日本"},
            "dates": {"arrival": "2020-01-01", "departure": "2020-01-05"},
            "budget": {"total": 15000},
            "travelers": {"adults": 2},
        }
        result = orch.manage_quality_gate(0, payload)
        assert not result.passed

    def test_gate_0_fail_zero_budget(self, orch):
        payload = {
            "destination": {"city": "东京"},
            "dates": {"arrival": "2026-12-20", "departure": "2026-12-25"},
            "budget": {"total": 0},
            "travelers": {"adults": 2},
        }
        result = orch.manage_quality_gate(0, payload)
        assert not result.passed

    def test_gate_0_fail_departure_before_arrival(self, orch):
        payload = {
            "destination": {"city": "东京"},
            "dates": {"arrival": "2026-12-25", "departure": "2026-12-20"},
            "budget": {"total": 15000},
            "travelers": {"adults": 2},
        }
        result = orch.manage_quality_gate(0, payload)
        assert not result.passed

    def test_gate_1_pass(self, orch):
        payload = {
            "constraint_check": {"blocking_issues": [], "warnings": []},
            "summary": {"blocking_count": 0, "warning_count": 0},
            "price_check": {"anomalies": []},
            "time_check": {"conflicts": []},
            "geography_check": {"detours": []},
        }
        result = orch.manage_quality_gate(1, payload)
        assert result.passed

    def test_gate_1_fail_blocking(self, orch):
        payload = {
            "constraint_check": {
                "blocking_issues": [{"constraint": "budget_ceiling", "fix_suggestion": "缩减预算"}],
                "warnings": [],
            },
            "summary": {"blocking_count": 1, "warning_count": 0},
            "price_check": {"anomalies": []},
            "time_check": {"conflicts": []},
            "geography_check": {"detours": []},
        }
        result = orch.manage_quality_gate(1, payload)
        assert not result.passed

    def test_gate_2_pass(self, orch):
        payload = {
            "composite_score": 90,
            "dimensions": {
                "completeness": 5, "feasibility": 5, "constraint_satisfaction": 5,
                "experience_quality": 4, "information_accuracy": 4,
            },
            "revision_feedback": [],
        }
        result = orch.manage_quality_gate(2, payload)
        assert result.passed

    def test_gate_2_reject(self, orch):
        payload = {"composite_score": 45, "dimensions": {}, "revision_feedback": []}
        result = orch.manage_quality_gate(2, payload)
        assert result.rejected

    def test_gate_3_pass(self, orch):
        payload = {
            "transportation": {"outbound": {}, "return_trip": {}, "local": []},
            "accommodation": [{"name": "酒店A"}],
            "daily_itinerary": [
                {"day": 1, "activities": ["a1", "a2"], "meals": {"breakfast": "b", "lunch": "l", "dinner": "d"}},
            ],
            "budget_breakdown": {"transportation": 100, "accommodation": 200, "activities": 100, "meals": 100, "buffer": 0},
            "quality_report": {"score": 90},
            "summary": {"total_budget": 600, "degraded": False},
        }
        result = orch.manage_quality_gate(3, payload)
        assert result.passed

    def test_gate_3_fail_missing_sections(self, orch):
        payload = {
            "transportation": {},
            "accommodation": [],
            "daily_itinerary": [],
            "budget_breakdown": {},
            "quality_report": {},
            "summary": {"total_budget": 1000, "degraded": False},
        }
        result = orch.manage_quality_gate(3, payload)
        assert not result.passed


# ============================================================
# assemble_plan
# ============================================================

class TestAssemblePlan:
    def test_assemble_basic(self, orch):
        draft = {
            "draft_id": "draft-1",
            "destination": "东京",
            "duration_days": 5,
            "total_budget": 15000,
            "transportation": {"outbound": {}, "return_trip": {}, "local": []},
            "accommodation": [{"name": "酒店A"}],
            "daily_itinerary": [{"day": 1}],
            "budget_allocation": {},
        }
        quality = {"composite_score": 90}
        plan = orch.assemble_plan(draft=draft, quality=quality)
        assert "plan_id" in plan
        assert "summary" in plan
        assert "transportation" in plan
        assert "accommodation" in plan
        assert "daily_itinerary" in plan
        assert "budget_breakdown" in plan
        assert "quality_report" in plan

    def test_assemble_degraded(self, orch):
        plan = orch.assemble_plan(
            draft={}, quality={}, degraded=True, degraded_reason="测试降级"
        )
        assert plan["summary"]["degraded"] is True
        assert plan["summary"]["degraded_reason"] == "测试降级"

    def test_assemble_empty_draft(self, orch):
        plan = orch.assemble_plan(draft=None, quality=None)
        assert "plan_id" in plan
        assert plan["summary"]["overall_score"] == 0


# ============================================================
# handle_revision
# ============================================================

class TestHandleRevision:
    def test_approve_high_score(self, orch_with_ctx):
        orch_with_ctx.context._status = ContextStatus.DECIDING
        decision = orch_with_ctx.handle_revision({"composite_score": 85})
        assert decision == "APPROVE"

    def test_revise_medium_score(self, orch_with_ctx):
        orch_with_ctx.context._status = ContextStatus.DECIDING
        decision = orch_with_ctx.handle_revision({"composite_score": 70})
        assert decision == "REVISE"

    def test_degrade_after_max_iterations(self, orch_with_ctx):
        ctx = orch_with_ctx.context
        ctx._status = ContextStatus.DECIDING
        ctx.increment_iteration()
        ctx.increment_iteration()
        # 现在 iteration_count = 2, handle_revision 计算 iteration = 2 + 1 = 3, 触发降级
        decision = orch_with_ctx.handle_revision({"composite_score": 70})
        assert decision == "DEGRADE"


# ============================================================
# 边界 & 异常
# ============================================================

class TestEdgeCases:
    def test_empty_input_raises(self, orch):
        with pytest.raises(ValueError, match="不能为空"):
            orch.parse_user_request("")

    def test_whitespace_input_raises(self, orch):
        with pytest.raises(ValueError, match="不能为空"):
            orch.parse_user_request("   ")

    def test_budget_1_default(self, orch):
        req = orch.parse_user_request("去东京5天，美食和文化")
        assert req.budget.total == 1  # 无预算匹配时的默认值

    def test_today_departure(self, orch):
        req = orch.parse_user_request("今天出发去杭州2天，预算2000")
        assert req.dates.arrival == date.today().isoformat()

    def test_invalid_date_format(self, orch):
        """日期格式无效 → Gate 0 拒绝。"""
        payload = {
            "destination": {"city": "东京"},
            "dates": {"arrival": "not-a-date", "departure": "not-a-date"},
            "budget": {"total": 15000},
            "travelers": {"adults": 2},
        }
        result = orch.manage_quality_gate(0, payload)
        assert not result.passed


# ============================================================
# message handling
# ============================================================

class TestHandleMessage:
    def test_invalid_message(self, orch):
        identity = AgentIdentity("test", "1.0.0", [], "internal", "online")
        msg = AgentMessage(
            message_id="not-a-uuid",
            sender=identity,
            receiver=identity,
            task_type=TaskType.RESPONSE_RESULT,
            payload={},
            timestamp=datetime.now(timezone.utc),
        )
        resp = asyncio.run(orch.handle_message(msg))
        assert resp.task_type == TaskType.RESPONSE_ERROR

    def test_unsupported_task_type(self, orch):
        identity = AgentIdentity("test", "1.0.0", [], "internal", "online")
        msg = AgentMessage(
            message_id=str(uuid4()),
            sender=identity,
            receiver=identity,
            task_type=TaskType.CONTROL_ABORT,
            payload={},
            timestamp=datetime.now(timezone.utc),
        )
        resp = asyncio.run(orch.handle_message(msg))
        assert resp.task_type == TaskType.RESPONSE_ERROR


# ============================================================
# process_request — 集成测试
# ============================================================

class TestProcessRequest:
    def test_happy_path(self, orch):
        result = asyncio.run(orch.process_request(
            "去东京5天，2026-12-20出发2026-12-25返回，预算15000元，喜欢美食和文化，2个人"
        ))
        assert "plan_id" in result
        assert "summary" in result
        assert "transportation" in result
        assert "daily_itinerary" in result
        assert result["summary"]["overall_score"] > 0

    def test_gate0_failure(self, orch):
        result = asyncio.run(orch.process_request("去东京5天"))
        assert "error" in result
        assert result["error"] == "gate_0_failed"
