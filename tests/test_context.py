"""core/context.py 单元测试。

覆盖: ContextStatus 枚举, LogEntry 数据类,
       SharedContext 所有写入/读取/生命周期方法
"""

import json
from datetime import datetime, timezone

import pytest

from core.context import ContextStatus, LogEntry, SharedContext


# ============================================================
# ContextStatus
# ============================================================

class TestContextStatus:
    """ContextStatus 枚举测试。"""

    def test_all_15_enum_values(self):
        """验证 15 个状态值全部存在。"""
        expected = {
            "IDLE", "VALIDATING", "DECOMPOSING", "DISPATCHING",
            "WAITING_PLANNER", "WAITING_EXECUTOR", "GATE_1",
            "WAITING_EVALUATOR", "DECIDING", "REVISING",
            "ASSEMBLING", "GATE_3", "COMPLETED", "COMPLETED_DEGRADED", "FAILED",
        }
        names = {s.name for s in ContextStatus}
        assert names == expected
        assert len(list(ContextStatus)) == 15

    def test_terminal_states(self):
        """三个终态 is_terminal() 返回 True。"""
        assert ContextStatus.COMPLETED.is_terminal() is True
        assert ContextStatus.COMPLETED_DEGRADED.is_terminal() is True
        assert ContextStatus.FAILED.is_terminal() is True

    def test_non_terminal_states(self):
        """非终态 is_terminal() 返回 False。"""
        assert ContextStatus.IDLE.is_terminal() is False
        assert ContextStatus.VALIDATING.is_terminal() is False
        assert ContextStatus.DECOMPOSING.is_terminal() is False
        assert ContextStatus.ASSEMBLING.is_terminal() is False

    def test_waiting_states(self):
        """三个等待状态 is_waiting() 返回 True。"""
        assert ContextStatus.WAITING_PLANNER.is_waiting() is True
        assert ContextStatus.WAITING_EXECUTOR.is_waiting() is True
        assert ContextStatus.WAITING_EVALUATOR.is_waiting() is True

    def test_non_waiting_states(self):
        """非等待状态 is_waiting() 返回 False。"""
        assert ContextStatus.IDLE.is_waiting() is False
        assert ContextStatus.COMPLETED.is_waiting() is False
        assert ContextStatus.DECIDING.is_waiting() is False


# ============================================================
# LogEntry
# ============================================================

class TestLogEntry:
    """LogEntry 数据类测试。"""

    def test_create_log_entry(self):
        """正常创建 LogEntry。"""
        now = datetime.now(timezone.utc)
        entry = LogEntry(
            timestamp=now,
            level="INFO",
            message="test log",
            source="orchestrator",
        )
        assert entry.timestamp == now
        assert entry.level == "INFO"
        assert entry.message == "test log"
        assert entry.source == "orchestrator"
        assert entry.details is None

    def test_create_with_details(self):
        """创建带 details 的 LogEntry。"""
        entry = LogEntry(
            timestamp=datetime.now(timezone.utc),
            level="ERROR",
            message="error occurred",
            source="planning_agent",
            details={"code": 500},
        )
        assert entry.details == {"code": 500}

    def test_is_frozen(self):
        """LogEntry 不可修改 (frozen dataclass)。"""
        entry = LogEntry(
            timestamp=datetime.now(timezone.utc),
            level="INFO",
            message="test",
            source="test",
        )
        with pytest.raises(Exception):
            entry.level = "ERROR"  # type: ignore[misc]


# ============================================================
# SharedContext — 初始状态
# ============================================================

class TestSharedContextInitial:
    """SharedContext 初始状态测试。"""

    def test_all_getters_return_none_or_default(self, sample_context):
        """初始状态: 所有 getter 返回 None / 0 / IDLE。"""
        assert sample_context.get_request() is None
        assert sample_context.get_task_queue() is None
        assert sample_context.get_current_draft() is None
        assert sample_context.get_validation_report() is None
        assert sample_context.get_quality_report() is None
        assert sample_context.get_iteration_count() == 0
        assert sample_context.get_status() == ContextStatus.IDLE
        assert sample_context.get_logs() == []


# ============================================================
# SharedContext — 写入与读取
# ============================================================

class TestSharedContextSetters:
    """SharedContext 写入操作测试。"""

    def test_set_and_get_request(self, sample_context):
        """set_request → get_request 往返正确。"""
        data = {"destination": "Paris", "budget": 3000}
        sample_context.set_request(data)
        assert sample_context.get_request() == data

    def test_set_and_get_task_queue(self, sample_context):
        """set_task_queue → get_task_queue 往返正确。"""
        queue = {"tasks": [{"id": "T1", "title": "test"}]}
        sample_context.set_task_queue(queue)
        assert sample_context.get_task_queue() == queue

    def test_set_and_get_current_draft(self, sample_context):
        """set_current_draft → get_current_draft 往返正确。"""
        draft = {"days": [{"date": "2026-07-10", "activities": []}]}
        sample_context.set_current_draft(draft)
        assert sample_context.get_current_draft() == draft

    def test_set_current_draft_none_clears(self, sample_context):
        """set_current_draft(None) 清除值。"""
        sample_context.set_current_draft({"data": "x"})
        sample_context.set_current_draft(None)
        assert sample_context.get_current_draft() is None

    def test_set_and_get_validation_report(self, sample_context):
        """set_validation_report → get_validation_report 往返正确。"""
        report = {"overall_status": "feasible", "issues": []}
        sample_context.set_validation_report(report)
        assert sample_context.get_validation_report() == report

    def test_set_validation_report_none_clears(self, sample_context):
        """set_validation_report(None) 清除值。"""
        sample_context.set_validation_report({"data": "x"})
        sample_context.set_validation_report(None)
        assert sample_context.get_validation_report() is None

    def test_set_and_get_quality_report(self, sample_context):
        """set_quality_report → get_quality_report 往返正确。"""
        report = {"composite_score": 85, "verdict": "PASS"}
        sample_context.set_quality_report(report)
        assert sample_context.get_quality_report() == report

    def test_set_quality_report_none_clears(self, sample_context):
        """set_quality_report(None) 清除值。"""
        sample_context.set_quality_report({"data": "x"})
        sample_context.set_quality_report(None)
        assert sample_context.get_quality_report() is None


# ============================================================
# SharedContext — iteration
# ============================================================

class TestSharedContextIteration:
    """SharedContext 迭代计数测试。"""

    def test_increment_starts_from_zero(self, sample_context):
        """increment_iteration 从 0 开始递增。"""
        assert sample_context.increment_iteration() == 1
        assert sample_context.increment_iteration() == 2
        assert sample_context.increment_iteration() == 3
        assert sample_context.get_iteration_count() == 3

    def test_reset_resets_iteration(self, sample_context):
        """reset() 后迭代计数归零。"""
        sample_context.increment_iteration()
        sample_context.increment_iteration()
        sample_context.reset()
        assert sample_context.get_iteration_count() == 0


# ============================================================
# SharedContext — 状态转换
# ============================================================

class TestSharedContextStatusTransitions:
    """SharedContext 状态转换测试。"""

    # --- 合法转换 ---

    @pytest.mark.parametrize("from_status, to_status", [
        (ContextStatus.IDLE, ContextStatus.VALIDATING),
        (ContextStatus.IDLE, ContextStatus.FAILED),
        (ContextStatus.VALIDATING, ContextStatus.DECOMPOSING),
        (ContextStatus.VALIDATING, ContextStatus.FAILED),
        (ContextStatus.DECOMPOSING, ContextStatus.DISPATCHING),
        (ContextStatus.DECOMPOSING, ContextStatus.FAILED),
        (ContextStatus.DISPATCHING, ContextStatus.WAITING_PLANNER),
        (ContextStatus.DISPATCHING, ContextStatus.FAILED),
        (ContextStatus.WAITING_PLANNER, ContextStatus.WAITING_EXECUTOR),
        (ContextStatus.WAITING_PLANNER, ContextStatus.REVISING),
        (ContextStatus.WAITING_PLANNER, ContextStatus.FAILED),
        (ContextStatus.WAITING_EXECUTOR, ContextStatus.GATE_1),
        (ContextStatus.WAITING_EXECUTOR, ContextStatus.FAILED),
        (ContextStatus.GATE_1, ContextStatus.WAITING_EVALUATOR),
        (ContextStatus.GATE_1, ContextStatus.REVISING),
        (ContextStatus.GATE_1, ContextStatus.FAILED),
        (ContextStatus.WAITING_EVALUATOR, ContextStatus.DECIDING),
        (ContextStatus.WAITING_EVALUATOR, ContextStatus.FAILED),
        (ContextStatus.DECIDING, ContextStatus.ASSEMBLING),
        (ContextStatus.DECIDING, ContextStatus.REVISING),
        (ContextStatus.DECIDING, ContextStatus.COMPLETED_DEGRADED),
        (ContextStatus.DECIDING, ContextStatus.FAILED),
        (ContextStatus.REVISING, ContextStatus.WAITING_PLANNER),
        (ContextStatus.REVISING, ContextStatus.FAILED),
        (ContextStatus.ASSEMBLING, ContextStatus.GATE_3),
        (ContextStatus.ASSEMBLING, ContextStatus.FAILED),
        (ContextStatus.GATE_3, ContextStatus.COMPLETED),
        (ContextStatus.GATE_3, ContextStatus.COMPLETED_DEGRADED),
        (ContextStatus.GATE_3, ContextStatus.FAILED),
    ])
    def test_valid_transition_passes(self, sample_context, from_status, to_status):
        """合法状态转换通过，不抛出异常。"""
        # 手动设置初始状态 (绕过校验)
        sample_context._status = from_status
        sample_context.set_status(to_status)
        assert sample_context.get_status() == to_status

    # --- 非法转换 ---

    @pytest.mark.parametrize("from_status, to_status", [
        (ContextStatus.IDLE, ContextStatus.COMPLETED),
        (ContextStatus.IDLE, ContextStatus.DECOMPOSING),
        (ContextStatus.VALIDATING, ContextStatus.IDLE),
        (ContextStatus.DECOMPOSING, ContextStatus.IDLE),
        (ContextStatus.WAITING_PLANNER, ContextStatus.IDLE),
        (ContextStatus.WAITING_EXECUTOR, ContextStatus.COMPLETED),
        (ContextStatus.DECIDING, ContextStatus.IDLE),
        (ContextStatus.ASSEMBLING, ContextStatus.IDLE),
        (ContextStatus.GATE_3, ContextStatus.IDLE),
    ])
    def test_invalid_transition_raises_value_error(self, sample_context, from_status, to_status):
        """非法状态转换抛出 ValueError。"""
        sample_context._status = from_status
        with pytest.raises(ValueError, match="非法状态转换"):
            sample_context.set_status(to_status)

    # --- 终态不可转出 ---

    @pytest.mark.parametrize("terminal_status", [
        ContextStatus.COMPLETED,
        ContextStatus.COMPLETED_DEGRADED,
        ContextStatus.FAILED,
    ])
    def test_terminal_state_cannot_transition(self, sample_context, terminal_status):
        """终态不可转换到任何其他状态。"""
        sample_context._status = terminal_status
        for target in ContextStatus:
            if target != terminal_status:
                with pytest.raises(ValueError, match="非法状态转换"):
                    sample_context.set_status(target)

    # --- TypeError ---

    def test_set_status_non_enum_raises_type_error(self, sample_context):
        """传入非 ContextStatus 抛出 TypeError。"""
        with pytest.raises(TypeError, match="ContextStatus"):
            sample_context.set_status("IDLE")  # type: ignore[arg-type]


# ============================================================
# SharedContext — 日志
# ============================================================

class TestSharedContextLogging:
    """SharedContext 日志操作测试。"""

    def test_add_log_appends_entry(self, sample_context):
        """add_log 追加日志条目。"""
        sample_context.add_log("INFO", "msg1", "orchestrator")
        sample_context.add_log("ERROR", "msg2", "planning_agent")
        assert len(sample_context.get_logs()) == 2
        assert sample_context.get_logs()[0].level == "INFO"
        assert sample_context.get_logs()[0].message == "msg1"
        assert sample_context.get_logs()[1].level == "ERROR"

    def test_add_log_sets_timestamp(self, sample_context):
        """add_log 自动设置时间戳。"""
        before = datetime.now(timezone.utc)
        sample_context.add_log("INFO", "test", "orchestrator")
        entry = sample_context.get_logs()[0]
        assert entry.timestamp >= before

    def test_get_logs_filter_by_level(self, sample_context):
        """get_logs(level=...) 正确过滤。"""
        sample_context.add_log("INFO", "i1", "a")
        sample_context.add_log("INFO", "i2", "b")
        sample_context.add_log("ERROR", "e1", "a")
        sample_context.add_log("WARNING", "w1", "b")

        info_logs = sample_context.get_logs(level="INFO")
        assert len(info_logs) == 2
        assert all(e.level == "INFO" for e in info_logs)

        error_logs = sample_context.get_logs(level="ERROR")
        assert len(error_logs) == 1
        assert error_logs[0].message == "e1"

    def test_get_logs_filter_by_source(self, sample_context):
        """get_logs(source=...) 正确过滤。"""
        sample_context.add_log("INFO", "m1", "orchestrator")
        sample_context.add_log("INFO", "m2", "planning_agent")
        sample_context.add_log("ERROR", "m3", "orchestrator")

        orch_logs = sample_context.get_logs(source="orchestrator")
        assert len(orch_logs) == 2
        assert all(e.source == "orchestrator" for e in orch_logs)

    def test_get_logs_filter_by_both(self, sample_context):
        """同时按 level 和 source 过滤。"""
        sample_context.add_log("INFO", "m1", "orchestrator")
        sample_context.add_log("ERROR", "m2", "orchestrator")
        sample_context.add_log("ERROR", "m3", "planning_agent")

        filtered = sample_context.get_logs(level="ERROR", source="orchestrator")
        assert len(filtered) == 1
        assert filtered[0].message == "m2"

    def test_get_logs_no_filter_returns_all(self, sample_context):
        """无过滤参数时返回全部日志。"""
        sample_context.add_log("INFO", "m1", "a")
        sample_context.add_log("ERROR", "m2", "b")
        assert len(sample_context.get_logs()) == 2

    def test_add_log_with_details(self, sample_context):
        """add_log 支持 details 参数。"""
        sample_context.add_log("INFO", "test", "orchestrator", details={"key": "val"})
        entry = sample_context.get_logs()[0]
        assert entry.details == {"key": "val"}


# ============================================================
# SharedContext — 生命周期
# ============================================================

class TestSharedContextLifecycle:
    """SharedContext 生命周期测试 (reset / to_dict / from_dict)。"""

    def test_reset_clears_all_fields(self, populated_context):
        """reset() 将所有字段恢复到初始状态。"""
        populated_context.reset()
        assert populated_context.get_request() is None
        assert populated_context.get_task_queue() is None
        assert populated_context.get_current_draft() is None
        assert populated_context.get_validation_report() is None
        assert populated_context.get_quality_report() is None
        assert populated_context.get_iteration_count() == 0
        assert populated_context.get_status() == ContextStatus.IDLE
        assert populated_context.get_logs() == []

    def test_to_dict_contains_all_keys(self, populated_context):
        """to_dict() 包含所有顶层键。"""
        data = populated_context.to_dict()
        expected_keys = {
            "request", "task_queue", "current_draft",
            "validation_report", "quality_report",
            "iteration_count", "status", "logs",
        }
        assert set(data.keys()) == expected_keys

    def test_to_dict_status_is_string(self, populated_context):
        """to_dict() 中 status 是字符串值。"""
        data = populated_context.to_dict()
        assert isinstance(data["status"], str)
        assert data["status"] == "decomposing"

    def test_to_dict_is_json_serializable(self, populated_context):
        """to_dict() 输出可 JSON 序列化。"""
        data = populated_context.to_dict()
        serialized = json.dumps(data)
        assert isinstance(serialized, str)

    def test_from_dict_restores_state(self, populated_context):
        """from_dict 正确恢复状态。"""
        data = populated_context.to_dict()
        restored = SharedContext.from_dict(data)
        assert restored.get_request() == populated_context.get_request()
        assert restored.get_status() == populated_context.get_status()
        assert restored.get_iteration_count() == populated_context.get_iteration_count()

    def test_round_trip_preserves_data(self, populated_context):
        """to_dict → from_dict 往返保持数据一致。"""
        populated_context.set_task_queue({"tasks": [1, 2, 3]})
        populated_context.increment_iteration()

        data = populated_context.to_dict()
        restored = SharedContext.from_dict(data)

        assert restored.get_request() == {"destination": "Tokyo", "budget": 5000}
        assert restored.get_task_queue() == {"tasks": [1, 2, 3]}
        assert restored.get_iteration_count() == 1
        assert restored.get_status() == ContextStatus.DECOMPOSING

    def test_from_dict_handles_empty_data(self):
        """from_dict 处理空字典 (使用默认值)。"""
        ctx = SharedContext.from_dict({})
        assert ctx.get_status() == ContextStatus.IDLE
        assert ctx.get_iteration_count() == 0
        assert ctx.get_logs() == []

    def test_from_dict_handles_missing_fields(self):
        """from_dict 处理缺失字段 (使用默认值)。"""
        ctx = SharedContext.from_dict({"status": "completed"})
        assert ctx.get_status() == ContextStatus.COMPLETED
        assert ctx.get_request() is None
        assert ctx.get_logs() == []

    def test_from_dict_restores_logs(self, populated_context):
        """from_dict 正确恢复日志条目。"""
        populated_context.add_log("ERROR", "error msg", "executor", {"code": 1})
        data = populated_context.to_dict()
        restored = SharedContext.from_dict(data)

        logs = restored.get_logs()
        assert len(logs) == 2  # 初始日志 + 新增
        assert logs[1].level == "ERROR"
        assert logs[1].message == "error msg"
        assert logs[1].source == "executor"
        assert logs[1].details == {"code": 1}

    def test_reset_then_reuse(self, sample_context):
        """reset() 后可以重新使用 SharedContext。"""
        sample_context.set_request({"dest": "A"})
        sample_context.set_status(ContextStatus.VALIDATING)
        sample_context.reset()

        # 重新使用
        sample_context.set_request({"dest": "B"})
        sample_context.set_status(ContextStatus.VALIDATING)
        assert sample_context.get_request() == {"dest": "B"}
        assert sample_context.get_status() == ContextStatus.VALIDATING


# ============================================================
# SharedContext — 完整流程模拟
# ============================================================

class TestSharedContextFullFlow:
    """SharedContext 完整流水线模拟。"""

    def test_simulate_full_pipeline(self, sample_context):
        """模拟完整的流水线状态转换。"""
        # Gate 0
        sample_context.set_request({"destination": "Tokyo", "dates": {"arrival": "2026-08-01"}})
        sample_context.set_status(ContextStatus.VALIDATING)

        # 任务分解
        sample_context.set_status(ContextStatus.DECOMPOSING)
        sample_context.set_task_queue({"tasks": ["T1", "T2"]})

        # 分发
        sample_context.set_status(ContextStatus.DISPATCHING)
        sample_context.set_status(ContextStatus.WAITING_PLANNER)

        # Planning 完成 → Execution
        sample_context.set_current_draft({"days": []})
        sample_context.set_status(ContextStatus.WAITING_EXECUTOR)

        # Execution 完成 → Gate 1
        sample_context.set_validation_report({"overall_status": "feasible"})
        sample_context.set_status(ContextStatus.GATE_1)

        # 进入评估
        sample_context.set_status(ContextStatus.WAITING_EVALUATOR)
        sample_context.set_quality_report({"composite_score": 85})
        sample_context.set_status(ContextStatus.DECIDING)

        # 质量通过 → 组装
        sample_context.set_status(ContextStatus.ASSEMBLING)
        sample_context.set_status(ContextStatus.GATE_3)

        # 最终输出
        sample_context.set_status(ContextStatus.COMPLETED)

        assert sample_context.get_status() == ContextStatus.COMPLETED
        assert sample_context.get_status().is_terminal() is True

    def test_simulate_revision_loop(self, sample_context):
        """模拟修订闭环: DECIDING → REVISING → WAITING_PLANNER。"""
        sample_context.set_status(ContextStatus.VALIDATING)
        sample_context.set_status(ContextStatus.DECOMPOSING)
        sample_context.set_status(ContextStatus.DISPATCHING)
        sample_context.set_status(ContextStatus.WAITING_PLANNER)
        sample_context.set_status(ContextStatus.WAITING_EXECUTOR)
        sample_context.set_status(ContextStatus.GATE_1)
        sample_context.set_status(ContextStatus.WAITING_EVALUATOR)
        sample_context.set_status(ContextStatus.DECIDING)

        # 分数不够 → 修订
        sample_context.set_status(ContextStatus.REVISING)
        sample_context.increment_iteration()
        assert sample_context.get_iteration_count() == 1

        # 回到 Planning
        sample_context.set_status(ContextStatus.WAITING_PLANNER)
        assert sample_context.get_status() == ContextStatus.WAITING_PLANNER


# ============================================================
# v1.2.0 I1 — StateMachine 辅助工具测试 (P2)
# ============================================================


class TestStateMachineTools:
    """get_legal_transitions / get_transition_path / force_status / strict_mode。"""

    def test_get_legal_transitions_idle(self):
        """get_legal_transitions(IDLE) → {VALIDATING, FAILED}。"""
        allowed = SharedContext.get_legal_transitions(ContextStatus.IDLE)
        names = {s.name for s in allowed}
        assert "VALIDATING" in names
        assert "FAILED" in names
        assert len(allowed) == 2

    def test_get_legal_transitions_completed(self):
        """get_legal_transitions(COMPLETED) → 空集合（终态不可转出）。"""
        allowed = SharedContext.get_legal_transitions(ContextStatus.COMPLETED)
        assert len(allowed) == 0

    def test_get_legal_transitions_deciding(self):
        """get_legal_transitions(DECIDING) 包含 ASSEMBLING, REVISING 等。"""
        allowed = SharedContext.get_legal_transitions(ContextStatus.DECIDING)
        names = {s.name for s in allowed}
        assert "ASSEMBLING" in names
        assert "REVISING" in names
        assert "COMPLETED_DEGRADED" in names
        assert "FAILED" in names

    def test_get_transition_path_idle_to_failed(self):
        """get_transition_path(IDLE, FAILED) → [IDLE, FAILED]（直接路径）。"""
        path = SharedContext.get_transition_path(
            ContextStatus.IDLE, ContextStatus.FAILED
        )
        assert len(path) == 2
        assert path[0] == ContextStatus.IDLE
        assert path[1] == ContextStatus.FAILED

    def test_get_transition_path_idle_to_completed(self):
        """get_transition_path(IDLE, COMPLETED) → 非空 BFS 路径。"""
        path = SharedContext.get_transition_path(
            ContextStatus.IDLE, ContextStatus.COMPLETED
        )
        assert len(path) > 1
        assert path[0] == ContextStatus.IDLE
        assert path[-1] == ContextStatus.COMPLETED

    def test_get_transition_path_same_state(self):
        """同状态间路径 → [状态]。"""
        path = SharedContext.get_transition_path(
            ContextStatus.IDLE, ContextStatus.IDLE
        )
        assert path == [ContextStatus.IDLE]

    def test_get_transition_path_no_path_returns_empty(self):
        """不可达状态对返回空列表（如 COMPLETED → IDLE 为终态逆转换）。"""
        path = SharedContext.get_transition_path(
            ContextStatus.COMPLETED, ContextStatus.IDLE
        )
        assert path == []

    def test_force_status_non_strict(self):
        """strict_mode=False → force_status() 成功。"""
        ctx = SharedContext(strict_mode=False)
        ctx.force_status(ContextStatus.DECIDING)
        assert ctx.get_status() == ContextStatus.DECIDING

    def test_force_status_strict_raises(self):
        """strict_mode=True → force_status() 抛 RuntimeError。"""
        ctx = SharedContext(strict_mode=True)
        with pytest.raises(RuntimeError, match="strict_mode"):
            ctx.force_status(ContextStatus.DECIDING)

    def test_set_status_error_message_format(self):
        """set_status 非法转换时错误消息包含'合法目标'。"""
        ctx = SharedContext(strict_mode=True)
        with pytest.raises(ValueError, match="合法目标"):
            ctx.set_status(ContextStatus.COMPLETED)  # IDLE → COMPLETED 非法

    def test_set_status_non_strict_skips_validation(self):
        """strict_mode=False → set_status 跳过转换合法性校验。"""
        ctx = SharedContext(strict_mode=False)
        ctx.set_status(ContextStatus.COMPLETED)
        assert ctx.get_status() == ContextStatus.COMPLETED

    def test_force_status_non_enum_raises(self):
        """force_status 传入非 ContextStatus 类型 → TypeError。"""
        ctx = SharedContext(strict_mode=False)
        with pytest.raises(TypeError, match="ContextStatus"):
            ctx.force_status("IDLE")
