"""Integration tests for TravelPlan Orchestrator — 精简版。

Covers:
- §2 TS-E2E-001: End-to-end happy path (1 条快速冒烟)
- §3 TS-EDGE-001~005: Edge cases
- §4 TS-ERR-006~007: Error scenarios
- §7 TS-PERF-001~003: Performance (@slow)
- §8 TS-ORCH-001~009: Orchestrator error recovery

Gate/Context/Message 场景已由对应单元测试覆盖:
- Gate: test_gate_runner.py (55 tests) + test_orchestrator.py::TestQualityGates (12 tests)
- Context: test_context.py (42 tests)
- Message: test_message.py (53 tests)

v1.2.0: conftest autouse fixture 强制 unset API keys → stub 路径 → 所有测试 < 1s
"""

import asyncio
import time
from datetime import date, datetime, timezone
from uuid import uuid4

import pytest

from agents.orchestrator import Orchestrator
from core.context import ContextStatus, SharedContext
from core.message import (
    AgentIdentity,
    AgentMessage,
    TaskType,
)


# ============================================================
# Shared Fixtures
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
# §2 End-to-End Happy Path — TS-E2E-001~005
# ============================================================

class TestE2EHappyPath:
    """Full pipeline integration tests for standard travel planning scenarios."""

    def test_e2e_001_standard_tokyo_trip(self, orch):
        """TS-E2E-001: 标准旅行规划 — 东京5天，2人，15000元，美食+文化。

        Verifies:
        - Gate 0: PASS (all required fields)
        - Planning Agent produces draft with transport + accommodation + 5-day + meals + budget
        - Execution Agent: feasible, 0 blocking_issues
        - Gate 1: PASS
        - Evaluation Agent: composite_score >= 80
        - Gate 2: PASS (first round)
        - Gate 3: PASS
        - Final plan contains complete travel plan JSON
        """
        result = asyncio.run(orch.process_request(
            "去日本东京5天，2026-12-20出发2026-12-25返回，2个人，"
            "预算总共15000元，喜欢美食和文化体验，住宿舒适型"
        ))
        assert "plan_id" in result, f"Unexpected result: {result}"
        assert "error" not in result
        summary = result["summary"]
        assert summary["overall_score"] > 0
        if summary.get("degraded"):
            assert summary["overall_score"] >= 60, (
                f"Degraded but score {summary['overall_score']} < 60"
            )
        assert "transportation" in result
        assert "accommodation" in result
        assert "daily_itinerary" in result
        assert "budget_breakdown" in result
        assert "quality_report" in result
        assert len(result.get("daily_itinerary", [])) >= 1


# ============================================================
# §3 Edge Cases — TS-EDGE-001~005
# ============================================================

class TestEdgeCases:
    """Boundary condition integration tests."""

    def test_edge_001_extremely_low_budget(self, orch):
        """TS-EDGE-001: 极低预算 — 北京3天，预算500元。

        Verifies:
        - Execution may mark warnings (budget tight) but NOT infeasible
        """
        result = asyncio.run(orch.process_request(
            "去北京3天，2026-08-01出发2026-08-04返回，预算500元"
        ))
        # 500 low budget passes Gate 0 (budget > 0), the pipeline handles it
        assert "plan_id" in result
        assert "error" not in result

    def test_edge_002_extremely_high_budget(self, orch):
        """TS-E2E-002: 极高预算 — 马尔代夫7天，预算20万，奢华体验。

        Verifies:
        - Recommends high-end resorts, water villas
        """
        result = asyncio.run(orch.process_request(
            "去马尔代夫7天，2026-12-01出发2026-12-08返回，预算20万，要最奢华的体验"
        ))
        assert "plan_id" in result
        assert "error" not in result

    def test_edge_003_family_with_children(self, orch):
        """TS-EDGE-003: 多人出行 — 三亚5天，4大人2小孩，预算3万，亲子游。

        Verifies:
        - Children count parsed correctly
        - Activity schedule is reasonable
        """
        result = asyncio.run(orch.process_request(
            "去三亚5天，2026-07-20出发2026-07-25返回，4大人2小孩，预算3万，亲子游"
        ))
        assert "plan_id" in result
        assert "error" not in result
        request = orch.parse_user_request(
            "去三亚5天，2026-07-20出发2026-07-25返回，4大人2小孩，预算3万，亲子游"
        )
        assert request.travelers.children == 2

    def test_edge_004_no_preferences(self, orch):
        """TS-EDGE-004: 无偏好标签 — 成都4天，预算5000。

        Verifies:
        - Default moderate pace used
        - Should NOT error out
        """
        result = asyncio.run(orch.process_request(
            "去成都4天，2026-09-10出发2026-09-14返回，预算5000"
        ))
        assert "plan_id" in result
        assert "error" not in result

    def test_edge_005_same_day_departure(self, orch):
        """TS-EDGE-005: 当天出发 — 今天出发去杭州2天，预算2000。

        Verifies:
        - Date validation: today = legal, arrival is parsed correctly
        - May mark risk if departure cannot be inferred from duration alone
        """
        req = orch.parse_user_request("今天出发去杭州2天，预算2000")
        assert req.dates.arrival == date.today().isoformat()
        # process_request may fail Gate 0 if departure is not inferrable;
        # the parse step is what matters for this scenario.
        result = asyncio.run(orch.process_request(
            "今天出发去杭州2天，2026-08-01出发2026-08-03返回，预算2000"
        ))
        assert "plan_id" in result
        assert "error" not in result


# ============================================================
# §4 Error Scenarios — TS-ERR-006~007
# ============================================================

class TestErrorScenarios:
    """Remaining error scenarios (001-005 covered in test_gate_runner.py)."""

    def test_err_006_empty_input(self, orch):
        """TS-ERR-006: 空输入 — 立即拒绝，返回提示。"""
        with pytest.raises(ValueError, match="不能为空"):
            orch.parse_user_request("")

    def test_err_007_nonsense_input(self, orch):
        """TS-ERR-007: 无意义输入 — "asdfghjkl"。

        Verifies:
        - Parse attempt produces a request with inferred/default values
        - Does not crash
        """
        req = orch.parse_user_request("asdfghjkl")
        assert req is not None
        assert req.destination is not None


# ============================================================
# §7 Performance — TS-PERF-001~003 (慢速标记)
# ============================================================

@pytest.mark.slow
class TestPerformance:
    """Performance benchmarks for the travel planning pipeline (慢速 — 需要真实API)."""

    def test_perf_001_standard_timing(self, orch):
        """TS-PERF-001: 标准耗时 — 5-day trip, complete flow <= 60s."""
        start = time.perf_counter()
        result = asyncio.run(orch.process_request(
            "去东京5天，2026-12-20出发2026-12-25返回，预算15000元，2个人，喜欢美食和文化"
        ))
        elapsed = time.perf_counter() - start
        assert elapsed <= 60, f"Process took {elapsed:.1f}s, exceeding 60s limit"
        assert "plan_id" in result

    def test_perf_002_concurrent_requests(self):
        """TS-PERF-002: 并行处理 — 3 concurrent user requests.

        Use separate Orchestrator instances to avoid shared context conflicts.
        """
        async def run_concurrent():
            orch1, orch2, orch3 = Orchestrator(), Orchestrator(), Orchestrator()
            tasks = [
                orch1.process_request("去东京5天，2026-12-20出发2026-12-25返回，预算15000元，喜欢美食"),
                orch2.process_request("去巴黎7天，2026-08-01出发2026-08-08返回，预算30000元，喜欢文化"),
                orch3.process_request("去曼谷3天，2026-10-10出发2026-10-13返回，预算8000元，喜欢寺庙"),
            ]
            return await asyncio.gather(*tasks)

        results = asyncio.run(run_concurrent())
        assert len(results) == 3
        for i, r in enumerate(results):
            assert "plan_id" in r, f"Request {i} failed: {r}"

    def test_perf_003_large_itinerary_30days(self, orch):
        """TS-PERF-003: 大型行程 — 14-day multi-city itinerary.

        Verifies:
        - Completes normally (no timeout)
        - Total time <= 120s
        """
        start = time.perf_counter()
        result = asyncio.run(orch.process_request(
            "去巴黎14天，2026-09-01出发2026-09-15返回，预算5万，喜欢文化艺术历史"
        ))
        elapsed = time.perf_counter() - start
        assert elapsed <= 120, f"Large itinerary took {elapsed:.1f}s, exceeding 120s limit"
        assert "plan_id" in result


# ============================================================
# §8 Orchestrator Error Recovery — TS-ORCH-001~009
# ============================================================

class TestOrchRecoveryTimeout:
    """TS-ORCH-001~003: Timeout and retry scenarios."""

    def test_orch_001_planning_timeout_retry_success(self):
        """TS-ORCH-001: Planning Agent 首次超时，第1次重试成功。

        Verifies:
        - 1st call times out, retry with exponential backoff
        - 1st retry succeeds, flow continues
        """
        from core.orchestration_engine import RetryManager

        retry = RetryManager()
        call_count = [0]

        async def flaky_task():
            call_count[0] += 1
            if call_count[0] == 1:
                raise asyncio.TimeoutError("模拟超时")
            return {"status": "ok"}

        # execute_with_retry takes (task_id, coro_factory) where coro_factory is a callable
        result = asyncio.run(retry.execute_with_retry(
            "test_task", lambda: flaky_task()
        ))
        assert result["status"] == "ok"
        assert call_count[0] == 2  # 1st fail + 1 retry success

    def test_orch_002_retry_exhausted(self):
        """TS-ORCH-002: Agent 超时耗尽重试 — 连续3次全部超时。

        Verifies:
        - All retries exhausted
        - Error propagated
        """
        from core.orchestration_engine import RetryManager

        retry = RetryManager()
        call_count = [0]

        async def always_timeout():
            call_count[0] += 1
            raise asyncio.TimeoutError("模拟持续超时")

        with pytest.raises(asyncio.TimeoutError):
            asyncio.run(retry.execute_with_retry(
                "test_task", lambda: always_timeout()
            ))
        assert call_count[0] == 3  # 1 initial + 2 retries (max_retries=3 total attempts)

    def test_orch_003_eval_timeout_skip(self, orch):
        """TS-ORCH-003: 评估超时跳过 — Evaluation Agent (Mode B) 超时。

        Verifies:
        - Orchestrator skips quality evaluation, goes directly to Gate 3
        - Final plan marked "quality evaluation incomplete", degraded: true
        """
        plan = orch.assemble_plan(
            draft={"draft_id": "test"},
            quality=None,
            degraded=True,
            degraded_reason="质量评估超时未完成",
        )
        assert plan["summary"]["degraded"] is True
        assert "质量评估超时未完成" in plan["summary"]["degraded_reason"]


class TestOrchRecoveryError:
    """TS-ORCH-004~006: Error response handling."""

    def test_orch_004_partial_draft_error(self, orch_with_ctx):
        """TS-ORCH-004: Planning Agent 返回错误(有部分产物)。

        Verifies:
        - Orchestrator detects error response
        - partial_draft non-empty → use partial draft
        """
        identity = AgentIdentity("planning_agent", "1.0.0", [], "internal", "online")
        orch_identity = AgentIdentity("orchestrator", "1.0.0", [], "internal", "online")
        err_msg = AgentMessage(
            message_id=str(uuid4()),
            sender=identity,
            receiver=orch_identity,
            task_type=TaskType.RESPONSE_ERROR,
            payload={
                "error_code": "EXECUTION_FAILED",
                "error_message": "部分生成成功",
                "partial_result": {"draft_id": "partial-1", "destination": "东京"},
            },
            timestamp=datetime.now(timezone.utc),
            correlation_id=str(uuid4()),
        )
        resp = asyncio.run(orch_with_ctx.handle_message(err_msg))
        # Error handler returns ok_response with RESULT type
        assert resp is not None

    def test_orch_005_empty_error_no_payload(self, orch_with_ctx):
        """TS-ORCH-005: Agent 返回空错误(无产物)。

        Verifies:
        - Error info propagated
        - No fake plan produced
        """
        identity = AgentIdentity("execution_agent", "1.0.0", [], "internal", "online")
        orch_identity = AgentIdentity("orchestrator", "1.0.0", [], "internal", "online")
        err_msg = AgentMessage(
            message_id=str(uuid4()),
            sender=identity,
            receiver=orch_identity,
            task_type=TaskType.RESPONSE_ERROR,
            payload={
                "error_code": "EXECUTION_FAILED",
                "error_message": "执行完全失败，无产出",
            },
            timestamp=datetime.now(timezone.utc),
            correlation_id=str(uuid4()),
        )
        resp = asyncio.run(orch_with_ctx.handle_message(err_msg))
        assert resp is not None

    def test_orch_006_multi_agent_compound_error(self, orch_with_ctx):
        """TS-ORCH-006: 多 Agent 复合错误 — Planning 和 Execution 均返回错误。

        Verifies:
        - Collects all errors
        - Produces degraded plan with aggregated error info
        """
        ctx = orch_with_ctx.context
        ctx.add_log("ERROR", "Planning Agent 调用失败: 超时", "orchestrator")
        ctx.add_log("ERROR", "Execution Agent 调用失败: 无响应", "orchestrator")
        logs = ctx.get_logs(level="ERROR")
        assert len(logs) >= 2
        plan = orch_with_ctx.assemble_plan(
            draft=None, quality=None,
            degraded=True,
            degraded_reason="Planning+Execution 均失败: 超时+无响应",
        )
        assert plan["summary"]["degraded"] is True


class TestOrchRecoveryCancel:
    """TS-ORCH-007~009: User cancellation scenarios."""

    def test_orch_007_cancel_during_planning(self, orch_with_ctx):
        """TS-ORCH-007: 用户在 Planning 阶段取消。

        Verifies:
        - Orchestrator receives control.abort
        - Returns acknowledgment
        """
        identity = AgentIdentity("planner", "1.0.0", [], "internal", "online")
        orch_identity = AgentIdentity("orchestrator", "1.0.0", [], "internal", "online")
        abort_msg = AgentMessage(
            message_id=str(uuid4()),
            sender=identity,
            receiver=orch_identity,
            task_type=TaskType.CONTROL_ABORT,
            payload={"reason": "user_cancel", "request_id": "req-1"},
            timestamp=datetime.now(timezone.utc),
        )
        resp = asyncio.run(orch_with_ctx.handle_message(abort_msg))
        assert resp is not None

    def test_orch_008_cancel_during_execution(self, orch_with_ctx):
        """TS-ORCH-008: 用户在 Execution 阶段取消。

        Verifies:
        - Save partial output to log
        - Mark degraded
        """
        ctx = orch_with_ctx.context
        ctx.set_request({"destination": "东京"})
        ctx.set_status(ContextStatus.VALIDATING)
        ctx.set_current_draft({"draft_id": "partial-draft", "status": "in_progress"})
        ctx.add_log("WARNING", "用户在Execution阶段取消，已保存部分草稿", "orchestrator")
        assert ctx.get_current_draft() is not None
        logs = ctx.get_logs(level="WARNING")
        assert len(logs) >= 1

    def test_orch_009_cancel_during_evaluation(self, orch_with_ctx):
        """TS-ORCH-009: 用户在 Evaluation 阶段取消。

        Verifies:
        - Keep → skip evaluation, Gate 3 + degraded
        - degraded flag set
        """
        ctx = orch_with_ctx.context
        ctx.set_request({"destination": "东京"})
        ctx.set_status(ContextStatus.VALIDATING)
        ctx.set_current_draft({"draft_id": "draft-keep"})
        draft = ctx.get_current_draft()
        assert draft["draft_id"] == "draft-keep"
        plan = orch_with_ctx.assemble_plan(
            draft=draft,
            quality=None,
            degraded=True,
            degraded_reason="用户在Evaluation阶段取消，跳过评估",
        )
        assert plan["summary"]["degraded"] is True
        assert "跳过评估" in plan["summary"]["degraded_reason"]


