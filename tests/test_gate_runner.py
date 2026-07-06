"""Test suite for core/gate_runner.py — Gate 0-3 execution and GateResult.

Covers evaluation/test_scenarios.md:
- TS-GATE-001 (hard constraint violation)
- TS-GATE-002 (revision pass after 1 round)
- TS-GATE-003 (3-round degrade)
- TS-GATE-004 (format fix)
- TS-GATE-005 (budget overrun)
"""

from __future__ import annotations

import pytest
from core.gate_runner import BlockingIssue, GateResult, GateRunner, Warning_


# ============================================================
# GateResult / BlockingIssue / Warning_ unit tests
# ============================================================

class TestBlockingIssue:
    def test_basic_creation(self):
        issue = BlockingIssue(description="test error")
        assert issue.description == "test error"
        assert issue.constraint is None
        assert issue.fix_suggestion is None

    def test_with_all_fields(self):
        issue = BlockingIssue(
            description="budget overrun",
            constraint="budget.total",
            fix_suggestion="reduce cost by 20%",
        )
        assert issue.constraint == "budget.total"
        assert issue.fix_suggestion == "reduce cost by 20%"

    def test_immutable(self):
        issue = BlockingIssue(description="test")
        with pytest.raises(Exception):
            issue.description = "changed"  # type: ignore


class TestWarning:
    def test_basic_creation(self):
        w = Warning_(description="low risk")
        assert w.description == "low risk"

    def test_with_suggestion(self):
        w = Warning_(description="high density", suggestion="spread activities")
        assert w.suggestion == "spread activities"


class TestGateResult:
    def test_default_values(self):
        r = GateResult(gate_id=0, passed=True)
        assert r.gate_id == 0
        assert r.passed is True
        assert r.blocking_issues == []
        assert r.warnings == []
        assert r.degraded is False
        assert r.rejected is False
        assert r.revision_feedback is None

    def test_with_issues(self):
        r = GateResult(
            gate_id=1,
            passed=False,
            blocking_issues=[BlockingIssue(description="err")],
            warnings=[Warning_(description="warn")],
        )
        assert len(r.blocking_issues) == 1
        assert len(r.warnings) == 1


# ============================================================
# GateRunner — construction and history
# ============================================================

class TestGateRunnerLifecycle:
    def test_empty_history(self):
        runner = GateRunner()
        assert runner.get_gate_history() == []
        assert runner.all_passed() is False
        assert runner.last_result() is None

    def test_all_passed(self):
        runner = GateRunner()
        runner.gate_log.append(GateResult(gate_id=0, passed=True))
        runner.gate_log.append(GateResult(gate_id=1, passed=True))
        assert runner.all_passed() is True

    def test_not_all_passed(self):
        runner = GateRunner()
        runner.gate_log.append(GateResult(gate_id=0, passed=True))
        runner.gate_log.append(GateResult(gate_id=1, passed=False))
        assert runner.all_passed() is False

    def test_last_result(self):
        runner = GateRunner()
        r0 = GateResult(gate_id=0, passed=True)
        r1 = GateResult(gate_id=1, passed=False)
        runner.gate_log.extend([r0, r1])
        assert runner.last_result() is r1

    def test_reset(self):
        runner = GateRunner()
        runner.gate_log.append(GateResult(gate_id=0, passed=True))
        runner.reset()
        assert runner.get_gate_history() == []


# ============================================================
# Gate 0: Input Validation — TS-ERR-001 ~ TS-ERR-007
# ============================================================

class TestGate0:
    """Covers test_scenarios: TS-ERR-001 (missing dest), TS-ERR-002 (missing date),
    TS-ERR-003 (missing budget), TS-ERR-004 (past date), TS-ERR-005 (departure < arrival),
    TS-ERR-006 (empty input), TS-EDGE-004 (no preferences)."""

    @pytest.fixture
    def runner(self):
        return GateRunner()

    @pytest.fixture
    def valid_request(self):
        return {
            "destination": {"city": "Tokyo", "country": "Japan"},
            "dates": {"arrival": "2026-08-01", "departure": "2026-08-05"},
            "budget": {"total": 10000},
            "travelers": {"adults": 2, "children": 0},
        }

    # -- Happy path --
    def test_all_valid(self, runner, valid_request):
        r = runner.run_gate_0(valid_request)
        assert r.passed is True
        assert len(r.blocking_issues) == 0

    # -- Missing destination (TS-ERR-001) --
    def test_missing_destination_city(self, runner):
        r = runner.run_gate_0({
            "destination": {"city": "", "country": ""},
            "dates": {"arrival": "2026-08-01", "departure": "2026-08-05"},
            "budget": {"total": 10000},
            "travelers": {"adults": 1},
        })
        assert r.passed is False
        assert any("目的地" in i.description for i in r.blocking_issues)

    def test_no_destination_key(self, runner):
        r = runner.run_gate_0({
            "dates": {"arrival": "2026-08-01", "departure": "2026-08-05"},
            "budget": {"total": 10000},
            "travelers": {"adults": 1},
        })
        assert r.passed is False
        assert any("目的地" in i.description for i in r.blocking_issues)

    # -- Missing date (TS-ERR-002) --
    def test_missing_arrival(self, runner):
        r = runner.run_gate_0({
            "destination": {"city": "Tokyo", "country": "Japan"},
            "dates": {"departure": "2026-08-05"},
            "budget": {"total": 10000},
            "travelers": {"adults": 1},
        })
        assert r.passed is False
        assert any("出发日期" in i.description for i in r.blocking_issues)

    def test_missing_departure(self, runner):
        r = runner.run_gate_0({
            "destination": {"city": "Tokyo", "country": "Japan"},
            "dates": {"arrival": "2026-08-01"},
            "budget": {"total": 10000},
            "travelers": {"adults": 1},
        })
        assert r.passed is False
        assert any("返回日期" in i.description for i in r.blocking_issues)

    # -- Missing budget (TS-ERR-003) --
    def test_missing_budget(self, runner):
        r = runner.run_gate_0({
            "destination": {"city": "Tokyo", "country": "Japan"},
            "dates": {"arrival": "2026-08-01", "departure": "2026-08-05"},
            "travelers": {"adults": 1},
        })
        assert r.passed is False
        assert any("预算" in i.description for i in r.blocking_issues)

    def test_zero_budget(self, runner):
        r = runner.run_gate_0({
            "destination": {"city": "Tokyo", "country": "Japan"},
            "dates": {"arrival": "2026-08-01", "departure": "2026-08-05"},
            "budget": {"total": 0},
            "travelers": {"adults": 1},
        })
        assert r.passed is False

    def test_negative_budget(self, runner):
        r = runner.run_gate_0({
            "destination": {"city": "Tokyo", "country": "Japan"},
            "dates": {"arrival": "2026-08-01", "departure": "2026-08-05"},
            "budget": {"total": -500},
            "travelers": {"adults": 1},
        })
        assert r.passed is False

    # -- Past date (TS-ERR-004) --
    def test_past_date(self, runner):
        r = runner.run_gate_0({
            "destination": {"city": "Tokyo", "country": "Japan"},
            "dates": {"arrival": "2020-01-01", "departure": "2020-01-05"},
            "budget": {"total": 10000},
            "travelers": {"adults": 1},
        })
        assert r.passed is False
        assert any("过去" in i.description for i in r.blocking_issues)

    # -- Departure before arrival (TS-ERR-005) --
    def test_departure_before_arrival(self, runner):
        r = runner.run_gate_0({
            "destination": {"city": "Tokyo", "country": "Japan"},
            "dates": {"arrival": "2026-12-25", "departure": "2026-12-20"},
            "budget": {"total": 10000},
            "travelers": {"adults": 1},
        })
        assert r.passed is False
        assert any("返回日期" in i.description and "早于" in i.description
                   for i in r.blocking_issues)

    # -- Invalid date format --
    def test_invalid_date_format(self, runner):
        r = runner.run_gate_0({
            "destination": {"city": "Tokyo", "country": "Japan"},
            "dates": {"arrival": "not-a-date", "departure": "2026-08-05"},
            "budget": {"total": 10000},
            "travelers": {"adults": 1},
        })
        assert r.passed is False
        assert any("格式" in i.description for i in r.blocking_issues)

    # -- Adults default (TS-EDGE-004) --
    def test_zero_adults_auto_default(self, runner, valid_request):
        valid_request["travelers"]["adults"] = 0
        r = runner.run_gate_0(valid_request)
        assert r.passed is True
        assert any("自动设为" in w.description for w in r.warnings)

    # -- None request --
    def test_none_request(self, runner):
        r = runner.run_gate_0(None)
        assert r.passed is False
        assert len(r.blocking_issues) >= 2  # destination + budget at minimum


# ============================================================
# Gate 1: Feasibility Check — TS-GATE-001
# ============================================================

class TestGate1:
    """Covers TS-GATE-001 (hard constraint violation)."""

    @pytest.fixture
    def runner(self):
        return GateRunner()

    @pytest.fixture
    def clean_validation(self):
        return {
            "constraint_check": {
                "blocking_issues": [],
                "warnings": [],
            },
            "summary": {"blocking_count": 0, "warning_count": 0},
            "price_check": {"anomalies": []},
            "time_check": {"conflicts": []},
            "geography_check": {"detours": []},
        }

    def test_all_clean(self, runner, clean_validation):
        r = runner.run_gate_1(clean_validation)
        assert r.passed is True
        assert len(r.blocking_issues) == 0

    # TS-GATE-001: hard constraint violation
    def test_hard_constraint_violation(self, runner, clean_validation):
        clean_validation["constraint_check"]["blocking_issues"] = [
            {"constraint": "budget.total", "fix_suggestion": "reduce by 30%"}
        ]
        clean_validation["summary"]["blocking_count"] = 1
        r = runner.run_gate_1(clean_validation)
        assert r.passed is False
        assert any("硬约束" in i.description for i in r.blocking_issues)

    def test_price_anomalies_warning(self, runner, clean_validation):
        clean_validation["price_check"]["anomalies"] = [
            {"severity": "high"}, {"severity": "high"}, {"severity": "medium"}, {"severity": "low"}
        ]
        r = runner.run_gate_1(clean_validation)
        assert r.passed is True  # price anomalies alone don't block Gate 1
        assert len(r.warnings) >= 1

    def test_time_conflicts_warning(self, runner, clean_validation):
        clean_validation["time_check"]["conflicts"] = [
            {"day": 1}, {"day": 2}, {"day": 3}
        ]
        r = runner.run_gate_1(clean_validation)
        assert r.passed is True
        assert len(r.warnings) >= 1

    def test_detour_warning(self, runner, clean_validation):
        clean_validation["geography_check"]["detours"] = [
            {"day": 1}, {"day": 2}
        ]
        r = runner.run_gate_1(clean_validation)
        assert r.passed is True
        assert len(r.warnings) >= 1

    def test_warning_count(self, runner, clean_validation):
        clean_validation["summary"]["warning_count"] = 5
        r = runner.run_gate_1(clean_validation)
        assert any("5 个警告" in w.description for w in r.warnings)

    def test_none_validation(self, runner):
        r = runner.run_gate_1(None)
        assert r.passed is False
        assert any("缺少校验报告" in i.description for i in r.blocking_issues)

    def test_empty_validation(self, runner):
        # empty dict triggers "missing validation report" blocking — same as None
        r = runner.run_gate_1({})
        assert r.passed is False


# ============================================================
# Gate 2: Quality Review — TS-GATE-002, TS-GATE-003
# ============================================================

class TestGate2:
    """Covers TS-GATE-002 (1-round revision pass), TS-GATE-003 (3-round degrade)."""

    @pytest.fixture
    def runner(self):
        return GateRunner()

    @pytest.fixture
    def high_score_report(self):
        return {
            "composite_score": 85,
            "dimensions": {
                "completeness": 4.2,
                "feasibility": 4.5,
                "constraint_satisfaction": 4.0,
                "experience_quality": 4.0,
                "information_accuracy": 4.3,
            },
        }

    @pytest.fixture
    def mid_score_report(self):
        return {
            "composite_score": 72,
            "dimensions": {
                "completeness": 3.5,
                "feasibility": 3.8,
                "constraint_satisfaction": 3.2,
                "experience_quality": 3.5,
                "information_accuracy": 3.6,
            },
            "revision_feedback": [{"issue": "density too high"}],
        }

    @pytest.fixture
    def low_score_report(self):
        return {
            "composite_score": 55,
            "dimensions": {
                "completeness": 2.5,
                "feasibility": 2.0,
                "constraint_satisfaction": 3.0,
                "experience_quality": 2.8,
                "information_accuracy": 2.5,
            },
        }

    @pytest.fixture
    def uneven_high_score_report(self):
        """High composite but low individual dimensions."""
        return {
            "composite_score": 82,
            "dimensions": {
                "completeness": 2.0,
                "feasibility": 2.5,
                "constraint_satisfaction": 2.8,
                "experience_quality": 4.5,
                "information_accuracy": 4.5,
            },
        }

    # -- High score, pass (TS-GATE-002: revision success) --
    def test_high_score_passes(self, runner, high_score_report):
        r = runner.run_gate_2(high_score_report, iteration=1)
        assert r.passed is True

    def test_high_score_passes_iteration_2(self, runner, high_score_report):
        r = runner.run_gate_2(high_score_report, iteration=2)
        assert r.passed is True

    # -- High score but dimension escalation --
    def test_high_score_dimension_escalation(self, runner, uneven_high_score_report):
        r = runner.run_gate_2(uneven_high_score_report, iteration=1)
        assert r.passed is False  # blocked despite composite >= 80
        assert any("结构性缺陷" in i.description for i in r.blocking_issues)

    # -- Mid score, iteration 1 → REVISE (TS-GATE-002) --
    def test_mid_score_first_iteration_revise(self, runner, mid_score_report):
        r = runner.run_gate_2(mid_score_report, iteration=1)
        assert r.passed is False
        assert r.rejected is False
        assert r.degraded is False
        assert r.revision_feedback is not None

    # -- Mid score, iteration 3 → DEGRADE (TS-GATE-003) --
    def test_mid_score_third_iteration_degrade(self, runner, mid_score_report):
        r = runner.run_gate_2(mid_score_report, iteration=3)
        assert r.passed is True  # forced pass
        assert r.degraded is True
        assert any("降级" in w.description for w in r.warnings)

    # -- Mid score, iteration 4 (>max) → DEGRADE --
    def test_mid_score_beyond_max_iteration_degrade(self, runner, mid_score_report):
        r = runner.run_gate_2(mid_score_report, iteration=4)
        assert r.degraded is True

    # -- Low score → REJECT --
    def test_low_score_rejected(self, runner, low_score_report):
        r = runner.run_gate_2(low_score_report, iteration=1)
        assert r.passed is False
        assert r.rejected is True
        assert any("严重缺陷" in i.description for i in r.blocking_issues)

    # -- Low score rejected even on iteration 1 --
    def test_low_score_rejected_first_iteration(self, runner, low_score_report):
        r = runner.run_gate_2(low_score_report, iteration=3)
        assert r.rejected is True  # < 60 → reject regardless of iteration

    # -- Missing quality report --
    def test_none_report(self, runner):
        r = runner.run_gate_2(None, iteration=1)
        assert r.passed is False
        assert r.rejected is True

    # -- Dimension warnings collected --
    def test_dimension_warnings_collected(self, runner, mid_score_report):
        r = runner.run_gate_2(mid_score_report, iteration=1)
        # All dimensions >= 3, so no structural warnings
        assert all("维度" not in w.description for w in r.warnings)


# ============================================================
# Gate 3: Final Validation — TS-GATE-004, TS-GATE-005
# ============================================================

class TestGate3:
    """Covers TS-GATE-004 (format fix), TS-GATE-005 (budget overrun)."""

    @pytest.fixture
    def runner(self):
        return GateRunner()

    @pytest.fixture
    def valid_plan(self):
        return {
            "transportation": {"outbound": {}, "return": {}, "local": []},
            "accommodation": [{"name": "Hotel A"}],
            "daily_itinerary": [
                {
                    "day": 1,
                    "activities": [{"name": "act1"}, {"name": "act2"}],
                    "meals": {"breakfast": {"name": "hotel"}, "lunch": {"name": "ramen"}, "dinner": {"name": "sushi"}},
                },
                {
                    "day": 2,
                    "activities": [{"name": "act3"}, {"name": "act4"}],
                    "meals": {"breakfast": {"name": "cafe"}, "lunch": {"name": "soba"}, "dinner": {"name": "kaiseki"}},
                },
            ],
            "budget_breakdown": {"transportation": 3000, "accommodation": 4000, "activities": 2000, "meals": 800, "buffer": 200},
            "quality_report": {"score": 85},
            "summary": {"total_budget": 10000},
        }

    # -- Happy path --
    def test_all_valid(self, runner, valid_plan):
        r = runner.run_gate_3(valid_plan)
        assert r.passed is True
        assert len(r.blocking_issues) == 0

    # -- Missing transportation (TS-GATE-004) --
    def test_missing_transportation(self, runner, valid_plan):
        valid_plan["transportation"] = None
        r = runner.run_gate_3(valid_plan)
        assert r.passed is False
        assert any("交通" in i.description for i in r.blocking_issues)

    # -- Missing accommodation --
    def test_missing_accommodation(self, runner, valid_plan):
        valid_plan["accommodation"] = []
        r = runner.run_gate_3(valid_plan)
        assert r.passed is False
        assert any("住宿" in i.description for i in r.blocking_issues)

    # -- Missing daily itinerary --
    def test_missing_itinerary(self, runner, valid_plan):
        valid_plan["daily_itinerary"] = []
        r = runner.run_gate_3(valid_plan)
        assert r.passed is False

    # -- Insufficient activities --
    def test_insufficient_activities(self, runner, valid_plan):
        valid_plan["daily_itinerary"][0]["activities"] = [{"name": "only_one"}]
        r = runner.run_gate_3(valid_plan)
        assert r.passed is False
        assert any("活动不足" in i.description for i in r.blocking_issues)

    # -- Insufficient meals --
    def test_insufficient_meals(self, runner, valid_plan):
        valid_plan["daily_itinerary"][0]["meals"] = {"breakfast": {}}
        r = runner.run_gate_3(valid_plan)
        assert r.passed is False
        assert any("餐食" in i.description for i in r.blocking_issues)

    def test_meals_as_list(self, runner, valid_plan):
        """Test meal counting when meals is a list instead of dict."""
        valid_plan["daily_itinerary"][0]["meals"] = [{"type": "breakfast"}]
        r = runner.run_gate_3(valid_plan)
        assert r.passed is False
        assert any("餐食" in i.description for i in r.blocking_issues)

    # -- Budget overrun (TS-GATE-005) --
    def test_budget_overrun(self, runner, valid_plan):
        valid_plan["budget_breakdown"] = {"transportation": 6000, "accommodation": 5000, "activities": 1000, "meals": 500, "buffer": 100}
        # total allocated = 12600 > total_budget 10000
        r = runner.run_gate_3(valid_plan)
        assert r.passed is False
        assert any("超支" in i.description for i in r.blocking_issues)

    # -- Missing quality report --
    def test_missing_quality_report(self, runner, valid_plan):
        valid_plan.pop("quality_report")
        r = runner.run_gate_3(valid_plan)
        assert r.passed is False
        assert any("质量报告" in i.description for i in r.blocking_issues)

    # -- Degraded without reason --
    def test_degraded_without_reason(self, runner, valid_plan):
        valid_plan["summary"]["degraded"] = True
        r = runner.run_gate_3(valid_plan)
        assert r.passed is False
        assert any("降级" in i.description for i in r.blocking_issues)

    # -- Degraded with reason (OK) --
    def test_degraded_with_reason(self, runner, valid_plan):
        valid_plan["summary"]["degraded"] = True
        valid_plan["summary"]["degraded_reason"] = "3轮迭代未达标"
        r = runner.run_gate_3(valid_plan)
        assert r.passed is True

    # -- None plan --
    def test_none_plan(self, runner):
        r = runner.run_gate_3(None)
        assert r.passed is False
