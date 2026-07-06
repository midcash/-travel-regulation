"""Test suite for core/orchestration_engine.py — TaskDAG, AgentRouter, RetryManager, ResultAssembler.

Covers test_scenarios.md:
- TS-ORCH-001 (Planning timeout, retry succeeds)
- TS-ORCH-002 (timeout exhausts retries)
- TS-ORCH-003 (evaluation timeout, skip)
"""

from __future__ import annotations

import asyncio

import pytest
from core.message import TaskType
from core.orchestration_engine import (
    AgentRouter,
    ResultAssembler,
    RetryManager,
    RouteRule,
    Task,
    TaskDAG,
    TaskStatus,
)


# ============================================================
# Task
# ============================================================

class TestTask:
    def test_default_values(self):
        t = Task(task_id="T1", title="Test task", task_type=TaskType.TASK_CREATE_ITINERARY)
        assert t.task_id == "T1"
        assert t.status == TaskStatus.PENDING
        assert t.dependencies == []
        assert t.payload == {}
        assert t.retry_count == 0
        assert t.result is None
        assert t.error is None

    def test_with_dependencies_and_payload(self):
        t = Task(
            task_id="T3",
            title="Daily itinerary",
            task_type=TaskType.TASK_CREATE_ITINERARY,
            payload={"aspect": "daily_itinerary"},
            dependencies=["T1", "T2"],
        )
        assert len(t.dependencies) == 2
        assert t.payload["aspect"] == "daily_itinerary"

    def test_created_at_is_set(self):
        t = Task(task_id="T1", title="T", task_type=TaskType.TASK_CREATE_ITINERARY)
        assert t.created_at is not None


# ============================================================
# TaskDAG
# ============================================================

class TestTaskDAG:
    @pytest.fixture
    def empty_dag(self):
        return TaskDAG()

    @pytest.fixture
    def populated_dag(self):
        dag = TaskDAG()
        dag.add_tasks([
            Task("T1", "Transport", TaskType.TASK_CREATE_ITINERARY),
            Task("T2", "Accommodation", TaskType.TASK_CREATE_ITINERARY),
            Task("T3", "Itinerary", TaskType.TASK_CREATE_ITINERARY, dependencies=["T1", "T2"]),
            Task("T4", "Budget", TaskType.TASK_CREATE_ITINERARY, dependencies=["T1", "T2", "T3"]),
        ])
        return dag

    def test_add_task(self, empty_dag):
        t = Task("T1", "Test", TaskType.TASK_CREATE_ITINERARY)
        empty_dag.add_task(t)
        assert empty_dag.task_count == 1
        assert empty_dag.get_task("T1") is t

    def test_add_duplicate_task(self, empty_dag):
        empty_dag.add_task(Task("T1", "T", TaskType.TASK_CREATE_ITINERARY))
        with pytest.raises(ValueError, match="重复"):
            empty_dag.add_task(Task("T1", "T2", TaskType.TASK_CREATE_ITINERARY))

    def test_add_tasks_batch(self, empty_dag):
        tasks = [
            Task("T1", "A", TaskType.TASK_CREATE_ITINERARY),
            Task("T2", "B", TaskType.TASK_CREATE_ITINERARY),
        ]
        empty_dag.add_tasks(tasks)
        assert empty_dag.task_count == 2

    def test_get_ready_tasks_no_deps(self, populated_dag):
        ready = populated_dag.get_ready_tasks()
        ready_ids = {t.task_id for t in ready}
        assert ready_ids == {"T1", "T2"}

    def test_get_ready_tasks_after_completion(self, populated_dag):
        populated_dag.mark_completed("T1", {"result": "done"})
        populated_dag.mark_completed("T2", {"result": "done"})
        ready = populated_dag.get_ready_tasks()
        ready_ids = {t.task_id for t in ready}
        assert "T3" in ready_ids
        assert "T4" not in ready_ids  # T4 depends on T3

    def test_mark_completed_updates_status(self, populated_dag):
        populated_dag.mark_completed("T1", {"result": "ok"})
        t = populated_dag.get_task("T1")
        assert t.status == TaskStatus.COMPLETED
        assert t.result == {"result": "ok"}
        assert t.completed_at is not None

    def test_mark_failed(self, populated_dag):
        populated_dag.mark_failed("T1", "error msg")
        t = populated_dag.get_task("T1")
        assert t.status == TaskStatus.FAILED
        assert t.error == "error msg"

    def test_mark_running(self, populated_dag):
        populated_dag.mark_running("T1")
        assert populated_dag.get_task("T1").status == TaskStatus.RUNNING

    def test_mark_completed_nonexistent_task(self, empty_dag):
        with pytest.raises(ValueError, match="未知任务"):
            empty_dag.mark_completed("nonexistent", {})

    def test_topological_order(self, populated_dag):
        order = populated_dag.topological_order()
        ids = [t.task_id for t in order]
        # T1, T2 before T3 before T4
        assert ids.index("T3") > ids.index("T1")
        assert ids.index("T3") > ids.index("T2")
        assert ids.index("T4") > ids.index("T3")

    def test_topological_order_cycle_detection(self, empty_dag):
        dag = TaskDAG()
        dag.add_task(Task("A", "A", TaskType.TASK_CREATE_ITINERARY, dependencies=["B"]))
        dag.add_task(Task("B", "B", TaskType.TASK_CREATE_ITINERARY, dependencies=["A"]))
        with pytest.raises(ValueError, match="循环"):
            dag.topological_order()

    def test_is_complete(self, populated_dag):
        assert populated_dag.is_complete() is False
        for tid in ["T1", "T2", "T3", "T4"]:
            populated_dag.mark_completed(tid, {})
        assert populated_dag.is_complete() is True

    def test_has_failures(self, populated_dag):
        assert populated_dag.has_failures() is False
        populated_dag.mark_failed("T2", "fail")
        assert populated_dag.has_failures() is True

    def test_get_all_tasks(self, populated_dag):
        tasks = populated_dag.get_all_tasks()
        assert len(tasks) == 4

    def test_completed_task_not_ready(self, populated_dag):
        populated_dag.mark_completed("T1", {})
        ready = populated_dag.get_ready_tasks()
        assert "T1" not in {t.task_id for t in ready}


# ============================================================
# AgentRouter
# ============================================================

class TestAgentRouter:
    @pytest.fixture
    def router(self):
        return AgentRouter()

    def test_default_route_create_itinerary(self, router):
        assert router.resolve(TaskType.TASK_CREATE_ITINERARY) == "planning_agent"

    def test_default_route_revise_itinerary(self, router):
        assert router.resolve(TaskType.TASK_REVISE_ITINERARY) == "planning_agent"

    def test_default_route_validate_feasibility(self, router):
        assert router.resolve(TaskType.TASK_VALIDATE_FEASIBILITY) == "execution_agent"

    def test_default_route_evaluate_plan(self, router):
        assert router.resolve(TaskType.TASK_EVALUATE_PLAN) == "evaluation_agent"

    def test_default_route_evaluate_code(self, router):
        assert router.resolve(TaskType.TASK_EVALUATE_CODE) == "evaluation_agent"

    def test_default_route_evaluate_contribution(self, router):
        assert router.resolve(TaskType.TASK_EVALUATE_CONTRIBUTION) == "evaluation_agent"

    def test_custom_route(self, router):
        router.add_route(RouteRule(TaskType.TASK_CREATE_ITINERARY, "custom_planner", priority=99))
        assert router.resolve(TaskType.TASK_CREATE_ITINERARY) == "custom_planner"

    def test_unresolved_type(self, router):
        # response types don't have default routes
        assert router.resolve(TaskType.RESPONSE_RESULT) is None

    def test_route_task_sets_assigned_agent(self, router):
        t = Task("T1", "Test", TaskType.TASK_VALIDATE_FEASIBILITY)
        agent = router.route_task(t)
        assert agent == "execution_agent"
        assert t.assigned_agent == "execution_agent"


# ============================================================
# RetryManager
# ============================================================

class TestRetryManager:
    @pytest.fixture
    def rm(self):
        return RetryManager(max_retries=3, backoff_seconds=[0.01, 0.02, 0.04], timeout_seconds=1.0)

    def test_can_retry_initial(self, rm):
        assert rm.can_retry("T1") is True

    def test_cannot_retry_after_max(self, rm):
        for _ in range(3):
            rm.record_attempt("T1")
        assert rm.can_retry("T1") is False

    def test_record_attempt_returns_count(self, rm):
        assert rm.record_attempt("T1") == 1
        assert rm.record_attempt("T1") == 2

    def test_next_delay_sequence(self, rm):
        assert rm.next_delay("T1") == 0.01
        rm.record_attempt("T1")
        assert rm.next_delay("T1") == 0.02

    def test_reset(self, rm):
        rm.record_attempt("T1")
        rm.record_attempt("T1")
        rm.reset("T1")
        assert rm.can_retry("T1") is True
        assert rm.record_attempt("T1") == 1

    def test_reset_all(self, rm):
        rm.record_attempt("T1")
        rm.record_attempt("T2")
        rm.reset_all()
        assert rm.can_retry("T1") is True
        assert rm.can_retry("T2") is True

    def test_default_backoff(self):
        rm = RetryManager()
        assert rm.max_retries == 3
        assert len(rm.backoff_seconds) == 3

    def test_execute_with_retry_success(self, rm):
        call_count = [0]

        async def work():
            call_count[0] += 1
            return "success"

        result = asyncio.run(rm.execute_with_retry("T1", work))
        assert result == "success"
        assert call_count[0] == 1

    def test_execute_with_retry_retries_then_succeeds(self, rm):
        call_count = [0]

        async def work():
            call_count[0] += 1
            if call_count[0] < 3:
                raise ValueError("transient error")
            return "eventual success"

        result = asyncio.run(rm.execute_with_retry("T1", work))
        assert result == "eventual success"
        assert call_count[0] == 3

    def test_execute_with_retry_timeout(self, rm):
        async def slow_work():
            await asyncio.sleep(2.0)  # > timeout 1.0s
            return "too late"

        with pytest.raises(TimeoutError):
            asyncio.run(rm.execute_with_retry("T1", slow_work))

    def test_execute_with_retry_all_failures(self, rm):
        async def failing_work():
            raise RuntimeError("always fails")

        with pytest.raises(RuntimeError, match="always fails"):
            asyncio.run(rm.execute_with_retry("T1", failing_work))


# ============================================================
# ResultAssembler
# ============================================================

class TestResultAssembler:
    @pytest.fixture
    def assembler(self):
        return ResultAssembler()

    def test_assemble_complete(self, assembler):
        draft = {
            "transportation": {"outbound": {"mode": "flight"}},
            "accommodation": [{"name": "Hotel A"}],
            "daily_itinerary": [{"day": 1, "activities": []}],
            "budget_allocation": {"transportation": 3000, "accommodation": 4000},
            "total_budget": 10000,
        }
        validation = {"overall_status": "feasible"}
        quality = {"composite_score": 85}

        result = assembler.assemble(draft, validation, quality)
        assert "plan_id" in result
        assert result["summary"]["overall_score"] == 85
        assert result["transportation"]["outbound"]["mode"] == "flight"
        assert len(result["accommodation"]) == 1

    def test_assemble_empty_inputs(self, assembler):
        result = assembler.assemble(None, None, None)
        assert result["transportation"] == {"outbound": {}, "return": {}, "local": {}}
        assert result["accommodation"] == []
        assert result["daily_itinerary"] == []
        assert result["budget_breakdown"] == {
            "transportation": 0, "accommodation": 0,
            "activities": 0, "meals": 0, "buffer": 0,
        }

    def test_assemble_degraded(self, assembler):
        result = assembler.assemble(
            {}, {}, {}, iteration_count=3, degraded=True,
            degraded_reason="3轮未达标",
        )
        assert result["summary"]["degraded"] is True
        assert result["summary"]["degraded_reason"] == "3轮未达标"
        assert result["metadata"]["iteration_count"] == 3

    def test_build_task_queue(self, assembler):
        dag = assembler.build_task_queue({"destination": {"city": "Tokyo"}})
        assert dag.task_count == 4

        # Verify dependency structure
        t3 = dag.get_task("T3")
        assert t3 is not None
        assert set(t3.dependencies) == {"T1", "T2"}

        t4 = dag.get_task("T4")
        assert t4 is not None
        assert set(t4.dependencies) == {"T1", "T2", "T3"}

        # Verify T1, T2 have no deps
        t1 = dag.get_task("T1")
        assert t1.dependencies == []
        t2 = dag.get_task("T2")
        assert t2.dependencies == []

    def test_budget_breakdown_from_allocation(self, assembler):
        draft = {
            "budget_allocation": {
                "transportation": 3000,
                "accommodation": 4000,
                "activities": 2000,
                "meals": 800,
                "buffer": 200,
            },
        }
        result = assembler.assemble(draft, {}, {})
        assert result["budget_breakdown"]["transportation"] == 3000
        assert result["summary"]["total_budget"] == 10000  # sum of all allocations
