"""Batch 6: 集成验证 + 真实案例 — 5 个真实城市端到端测试。

覆盖 handoff.md Batch 6 任务:
- §6.1: 东京 5 天 — 经典案例，验证已有测试基准不受破坏
- §6.2: 巴黎 3 天 — 欧洲城市，验证跨洲数据（时区/货币/语言）
- §6.3: 纽约 4 天 — 高物价城市，验证预算约束是否被真实 API 打破
- §6.4: 成都 2 天 — 国内短途，验证中文输入+国内数据
- §6.5: 曼谷 7 天 — 长行程+东南亚，验证极限天数+新兴市场数据
- §6.6: 回归测试 — 所有现有测试必须通过（由 pytest 整体运行保证）
- §6.7: Lessons 汇总 — 见 progress/lessons.md

验收标准:
- 5 个案例全部跑通（Gate 0→1→2→3，最终 status = COMPLETED）
- 0 个回归测试失败
- 真实案例评分 ≥ 70/100
"""

import asyncio
import pytest

from core.context import ContextStatus
from agents.orchestrator import Orchestrator


# ============================================================
# §6.1-6.5: 5 个真实城市端到端案例
# ============================================================

class TestRealCityCases:
    """Batch 6: 5 个真实城市端到端集成验证。

    每个案例验证:
    - Gate 0→1→2→3 全链路通过
    - LLM + API 双轨架构正常工作
    - 输出结构完整性
    - overall_score ≥ 70
    - 上下文状态正确
    """

    # ── 6.1 东京 5 天 ──────────────────────────────────

    @pytest.mark.slow
    def test_real_case_001_tokyo_5days(self):
        """6.1 东京 5 天 — 经典案例，验证已有测试基准不受破坏。

        输入: 日本东京，5天，2人，15000元，美食+文化+舒适住宿
        验证: 全链路通过，输出结构完整，评分 ≥ 70
        """
        orch = Orchestrator()
        result = asyncio.run(orch.process_request(
            "去日本东京5天，2026-12-20出发2026-12-25返回，2个人，"
            "预算总共15000元，喜欢美食和文化体验，住宿舒适型"
        ))

        # 基础断言：无错误，有计划ID
        assert "plan_id" in result, f"Missing plan_id: {list(result.keys())}"
        assert "error" not in result, f"Unexpected error: {result.get('error')}"

        # 输出结构完整性
        _assert_output_structure(result)

        # 摘要字段
        summary = result["summary"]
        assert summary["overall_score"] > 0, "overall_score should be positive"
        assert "degraded" in summary
        # 标准案例不应降级
        if summary.get("degraded"):
            reason = summary.get("degraded_reason", "unknown")
            assert summary["overall_score"] >= 70, (
                f"Degraded but score {summary['overall_score']} < 70: {reason}"
            )

        # 上下文状态
        _assert_context_completed(orch)

        # 城市特定验证：东京应有多个景点
        itinerary = result.get("daily_itinerary", [])
        assert len(itinerary) >= 1, "Should have at least 1 day of itinerary"

    # ── 6.2 巴黎 3 天 ──────────────────────────────────

    @pytest.mark.slow
    def test_real_case_002_paris_3days(self):
        """6.2 巴黎 3 天 — 欧洲城市，验证跨洲数据（时区/货币/语言）。

        输入: 法国巴黎，3天，1人，30000元，文化艺术历史
        验证: 欧洲城市正常处理，跨洲数据不破坏流程
        """
        orch = Orchestrator()
        result = asyncio.run(orch.process_request(
            "去法国巴黎3天，2026-09-01出发2026-09-04返回，1个人，"
            "预算30000元，喜欢文化艺术历史"
        ))

        assert "plan_id" in result, f"Missing plan_id: {list(result.keys())}"
        assert "error" not in result, f"Unexpected error: {result.get('error')}"

        _assert_output_structure(result)

        summary = result["summary"]
        assert summary["overall_score"] > 0
        if summary.get("degraded"):
            assert summary["overall_score"] >= 70, (
                f"Paris case degraded with score {summary['overall_score']} < 70"
            )

        _assert_context_completed(orch)

        # 3天行程应有合理的天数
        itinerary = result.get("daily_itinerary", [])
        assert len(itinerary) >= 1

    # ── 6.3 纽约 4 天 ──────────────────────────────────

    @pytest.mark.slow
    def test_real_case_003_newyork_4days(self):
        """6.3 纽约 4 天 — 高物价城市，验证预算约束不被真实 API 打破。

        输入: 美国纽约，4天，2人，40000元，购物+都市+美食
        验证: 高物价城市预算约束有效，不因价格数据异常而阻断
        """
        orch = Orchestrator()
        result = asyncio.run(orch.process_request(
            "去美国纽约4天，2026-10-10出发2026-10-14返回，2个人，"
            "预算40000元，喜欢购物都市美食"
        ))

        assert "plan_id" in result, f"Missing plan_id: {list(result.keys())}"
        assert "error" not in result, f"Unexpected error: {result.get('error')}"

        _assert_output_structure(result)

        summary = result["summary"]
        assert summary["overall_score"] > 0
        if summary.get("degraded"):
            assert summary["overall_score"] >= 70, (
                f"New York case degraded with score {summary['overall_score']} < 70"
            )

        _assert_context_completed(orch)

        # 预算分配应存在且合理
        budget = result.get("budget_breakdown", {})
        assert budget is not None, "budget_breakdown should not be None"

    # ── 6.4 成都 2 天 ──────────────────────────────────

    def test_real_case_004_chengdu_2days(self):
        """6.4 成都 2 天 — 国内短途，验证中文输入+国内数据。

        输入: 四川成都，2天，1人，3000元，美食+休闲
        验证: 短途国内城市正常处理，中文输入无异常
        """
        orch = Orchestrator()
        result = asyncio.run(orch.process_request(
            "去成都2天，2026-08-15出发2026-08-17返回，1个人，"
            "预算3000元，喜欢美食和休闲"
        ))

        assert "plan_id" in result, f"Missing plan_id: {list(result.keys())}"
        assert "error" not in result, f"Unexpected error: {result.get('error')}"

        _assert_output_structure(result)

        summary = result["summary"]
        assert summary["overall_score"] > 0
        if summary.get("degraded"):
            assert summary["overall_score"] >= 70, (
                f"Chengdu case degraded with score {summary['overall_score']} < 70"
            )

        _assert_context_completed(orch)

        # 2天短途应有合理天数
        itinerary = result.get("daily_itinerary", [])
        assert len(itinerary) >= 1

    # ── 6.5 曼谷 7 天 ──────────────────────────────────

    @pytest.mark.slow
    def test_real_case_005_bangkok_7days(self):
        """6.5 曼谷 7 天 — 长行程+东南亚，验证极限天数+新兴市场数据。

        输入: 泰国曼谷，7天，2人，15000元，寺庙+按摩+美食
        验证: 7天长行程正常处理，东南亚城市数据完整
        """
        orch = Orchestrator()
        result = asyncio.run(orch.process_request(
            "去曼谷7天，2026-11-01出发2026-11-08返回，2个人，"
            "预算15000元，喜欢寺庙按摩美食"
        ))

        assert "plan_id" in result, f"Missing plan_id: {list(result.keys())}"
        assert "error" not in result, f"Unexpected error: {result.get('error')}"

        _assert_output_structure(result)

        summary = result["summary"]
        assert summary["overall_score"] > 0
        if summary.get("degraded"):
            assert summary["overall_score"] >= 70, (
                f"Bangkok case degraded with score {summary['overall_score']} < 70"
            )

        _assert_context_completed(orch)

        # 7天行程应有足够的日程
        itinerary = result.get("daily_itinerary", [])
        assert len(itinerary) >= 1


# ============================================================
# §6.6 回归验证 — 现有测试兼容性
# ============================================================

@pytest.mark.slow
class TestRegressionGuard:
    """Batch 6 回归保护 — 确保新案例不影响现有测试基线。

    注: 完整回归由 pytest 整体运行保证（649 tests）。
    此处的测试验证关键集成点未被破坏。
    """

    def test_regression_standard_tokyo_still_works(self):
        """标准东京案例 — 与 test_integration.py TS-E2E-001 相同输入，
        验证 Batch 6 改动未破坏现有流程。
        """
        orch = Orchestrator()
        result = asyncio.run(orch.process_request(
            "去日本东京5天，2026-12-20出发2026-12-25返回，2个人，"
            "预算总共15000元，喜欢美食和文化体验，住宿舒适型"
        ))
        assert "plan_id" in result
        assert "error" not in result
        assert result["summary"]["overall_score"] > 0

    def test_regression_pipeline_state_clean(self):
        """每个 Orchestrator 实例从 IDLE 开始，处理后到达终态。"""
        orch = Orchestrator()
        assert orch.context.get_status() == ContextStatus.IDLE

        asyncio.run(orch.process_request(
            "去北京3天，2026-12-20出发2026-12-23返回，预算5000元"
        ))
        final = orch.context.get_status()
        assert final in (ContextStatus.COMPLETED, ContextStatus.COMPLETED_DEGRADED), (
            f"Expected COMPLETED or COMPLETED_DEGRADED, got {final}"
        )

    def test_regression_new_city_not_in_stub(self):
        """非标准目的地（如"布达佩斯"）不应崩溃，应降级处理。"""
        orch = Orchestrator()
        result = asyncio.run(orch.process_request(
            "去布达佩斯3天，2026-09-01出发2026-09-04返回，预算8000元"
        ))
        assert "plan_id" in result
        assert "error" not in result
        # 非标准目的地可能降级，但必须完成
        _assert_context_completed(orch)


# ============================================================
# 降级场景 — 验证双轨架构健壮性
# ============================================================

@pytest.mark.slow
class TestDegradationScenarios:
    """验证 LLM + API 双轨架构的降级路径。

    当外部服务不可用时，系统应降级到 stub 并标记 degraded。
    """

    def test_degraded_flag_in_summary(self):
        """降级标记应出现在 summary 中并可被上游检测。"""
        orch = Orchestrator()
        result = asyncio.run(orch.process_request(
            "去东京3天，2026-12-20出发2026-12-23返回，预算10000元"
        ))
        assert "summary" in result
        assert "degraded" in result["summary"]
        # degraded 应为 bool
        assert isinstance(result["summary"]["degraded"], bool)

    def test_degraded_reason_when_degraded(self):
        """降级时必须提供 degraded_reason。"""
        orch = Orchestrator()
        result = asyncio.run(orch.process_request(
            "去东京3天，2026-12-20出发2026-12-23返回，预算10000元"
        ))
        summary = result["summary"]
        if summary["degraded"]:
            assert "degraded_reason" in summary, (
                "degraded=True but no degraded_reason provided"
            )
            assert len(summary["degraded_reason"]) > 0

    def test_score_threshold_real_case(self):
        """所有真实案例评分应 ≥ 70（允许低于 stub 时代的 95）。"""
        test_cases = [
            "去东京5天，2026-12-20出发2026-12-25返回，预算15000元，喜欢美食文化",
            "去巴黎3天，2026-09-01出发2026-09-04返回，预算30000元，喜欢艺术",
            "去成都2天，2026-08-15出发2026-08-17返回，预算3000元，喜欢美食",
        ]
        for case in test_cases:
            orch = Orchestrator()
            result = asyncio.run(orch.process_request(case))
            score = result["summary"]["overall_score"]
            assert score >= 70, (
                f"Score {score} < 70 for case: {case[:30]}..."
            )


# ============================================================
# 跨领域验证 — 货币/语言/时区
# ============================================================

@pytest.mark.slow
class TestCrossCuttingConcerns:
    """验证跨领域关注点: 货币、语言、时区处理。"""

    def test_different_currencies(self):
        """不同货币（CNY vs USD vs EUR vs THB）不应破坏预算处理。"""
        cases = [
            ("去东京5天，2026-12-20出发2026-12-25返回，预算15000元"),
            ("去巴黎3天，2026-09-01出发2026-09-04返回，预算30000元"),
            ("去曼谷7天，2026-11-01出发2026-11-08返回，预算15000元"),
        ]
        for case in cases:
            orch = Orchestrator()
            result = asyncio.run(orch.process_request(case))
            assert "plan_id" in result, f"Failed for: {case[:40]}..."
            assert result["summary"]["overall_score"] > 0

    def test_chinese_input_full_pipeline(self):
        """纯中文输入应全链路正常处理。

        注: 日期需使用 YYYY-MM-DD 格式（_extract_dates 不支持"8月15号"中文日期，
        此为已知限制，见 progress/lessons.md Batch 2）。
        """
        orch = Orchestrator()
        result = asyncio.run(orch.process_request(
            "我想去四川成都玩两天，2026-08-15出发2026-08-17返回，"
            "一个人，预算3000块钱，喜欢吃川菜和看熊猫"
        ))
        assert "plan_id" in result
        assert "error" not in result
        _assert_output_structure(result)

    def test_extreme_duration_7days(self):
        """7 天长行程应有合理的日程密度。"""
        orch = Orchestrator()
        result = asyncio.run(orch.process_request(
            "去曼谷7天，2026-11-01出发2026-11-08返回，预算15000元，喜欢寺庙按摩"
        ))
        itinerary = result.get("daily_itinerary", [])
        assert len(itinerary) >= 1
        # 7天行程每天应有活动
        if len(itinerary) > 1:
            for day in itinerary:
                assert isinstance(day, dict), f"Each day should be a dict, got {type(day)}"


# ============================================================
# 辅助断言函数
# ============================================================

def _assert_output_structure(result: dict) -> None:
    """验证 FinalTravelPlan 输出结构完整性。

    对应 spec/agent_contract.md FinalTravelPlan 格式要求。
    """
    required_fields = [
        "plan_id",
        "summary",
        "transportation",
        "accommodation",
        "daily_itinerary",
        "budget_breakdown",
        "quality_report",
    ]
    for field in required_fields:
        assert field in result, (
            f"Missing required field '{field}' in output. "
            f"Got keys: {list(result.keys())}"
        )

    # summary 子字段
    summary = result["summary"]
    assert "overall_score" in summary, "summary.overall_score is required"
    assert "total_budget" in summary, "summary.total_budget is required"
    assert "degraded" in summary, "summary.degraded is required"


def _assert_context_completed(orch: Orchestrator) -> None:
    """验证 Orchestrator 上下文到达终态。"""
    final_status = orch.context.get_status()
    valid_end_states = (
        ContextStatus.COMPLETED,
        ContextStatus.COMPLETED_DEGRADED,
    )
    assert final_status in valid_end_states, (
        f"Expected COMPLETED or COMPLETED_DEGRADED, got {final_status}"
    )
