"""Tests for core/task_decomposer.py — LLM 驱动的动态任务分解器。

覆盖:
- Fallback 分解: LLM 不可用时标准 T1-T4
- LLM 输出校验: 循环依赖、孤立依赖、重复 ID
- DAG 构建: TaskDAG 验证
- 边界: 空任务列表、空 payload
"""

import asyncio

import pytest

from core.task_decomposer import TaskDecomposer, _check_cycles, _check_orphans
from core.message import TaskType


# ============================================================
# Fixtures
# ============================================================

@pytest.fixture
def decomposer():
    """无 LLM 的 TaskDecomposer — 始终走 fallback。"""
    return TaskDecomposer(llm_client=None)


@pytest.fixture
def sample_request():
    return {
        "destination": {"city": "Tokyo", "country": "Japan"},
        "dates": {"arrival": "2026-12-20", "departure": "2026-12-25", "duration_days": 5},
        "budget": {"total": 15000, "currency": "CNY"},
        "travelers": {"adults": 2, "children": 0},
        "preferences": {"style": ["food", "culture"], "pace": "moderate", "dietary": []},
    }


# ============================================================
# Fallback 分解测试
# ============================================================

class TestFallbackDecomposition:
    """LLM 不可用时应正确输出标准 T1-T4。"""

    def test_four_tasks_created(self, decomposer, sample_request):
        dag = asyncio.run(decomposer.decompose(sample_request))
        assert dag.task_count == 4

    def test_task_ids(self, decomposer, sample_request):
        dag = asyncio.run(decomposer.decompose(sample_request))
        ids = {t.task_id for t in dag.get_all_tasks()}
        assert ids == {"T1", "T2", "T3", "T4"}

    def test_dependencies(self, decomposer, sample_request):
        dag = asyncio.run(decomposer.decompose(sample_request))
        t1 = dag.get_task("T1")
        t2 = dag.get_task("T2")
        t3 = dag.get_task("T3")
        t4 = dag.get_task("T4")
        assert t1.dependencies == []
        assert t2.dependencies == []
        assert t3.dependencies == ["T1", "T2"]
        assert t4.dependencies == ["T1", "T2", "T3"]

    def test_topological_order(self, decomposer, sample_request):
        dag = asyncio.run(decomposer.decompose(sample_request))
        order = dag.topological_order()
        ids = [t.task_id for t in order]
        assert ids.index("T1") < ids.index("T3")
        assert ids.index("T2") < ids.index("T3")
        assert ids.index("T3") < ids.index("T4")

    def test_all_create_itinerary(self, decomposer, sample_request):
        dag = asyncio.run(decomposer.decompose(sample_request))
        for t in dag.get_all_tasks():
            assert t.task_type == TaskType.TASK_CREATE_ITINERARY

    def test_payload_aspects(self, decomposer, sample_request):
        dag = asyncio.run(decomposer.decompose(sample_request))
        aspects = {t.payload.get("aspect") for t in dag.get_all_tasks()}
        assert "transportation" in aspects
        assert "accommodation" in aspects
        assert "daily_itinerary" in aspects
        assert "budget_allocation" in aspects

    def test_llm_unavailable_property(self, decomposer):
        assert decomposer.llm_available is False


# ============================================================
# 循环依赖检测
# ============================================================

class TestCycleDetection:
    def test_no_cycle_valid_dag(self):
        tasks = [
            {"task_id": "T1", "title": "A", "task_type": "task.create_itinerary", "dependencies": []},
            {"task_id": "T2", "title": "B", "task_type": "task.create_itinerary", "dependencies": ["T1"]},
            {"task_id": "T3", "title": "C", "task_type": "task.create_itinerary", "dependencies": ["T1", "T2"]},
        ]
        _check_cycles(tasks)

    def test_simple_cycle_raises(self):
        tasks = [
            {"task_id": "T1", "title": "A", "task_type": "task.create_itinerary", "dependencies": ["T2"]},
            {"task_id": "T2", "title": "B", "task_type": "task.create_itinerary", "dependencies": ["T1"]},
        ]
        with pytest.raises(ValueError, match="循环"):
            _check_cycles(tasks)

    def test_self_loop_raises(self):
        tasks = [
            {"task_id": "T1", "title": "A", "task_type": "task.create_itinerary", "dependencies": ["T1"]},
        ]
        with pytest.raises(ValueError, match="循环"):
            _check_cycles(tasks)

    def test_three_node_cycle_raises(self):
        tasks = [
            {"task_id": "T1", "title": "A", "task_type": "task.create_itinerary", "dependencies": ["T3"]},
            {"task_id": "T2", "title": "B", "task_type": "task.create_itinerary", "dependencies": ["T1"]},
            {"task_id": "T3", "title": "C", "task_type": "task.create_itinerary", "dependencies": ["T2"]},
        ]
        with pytest.raises(ValueError, match="循环"):
            _check_cycles(tasks)

    def test_empty_tasks_no_error(self):
        _check_cycles([])


# ============================================================
# 孤立依赖检测
# ============================================================

class TestOrphanDetection:
    def test_valid_deps_no_error(self):
        tasks = [
            {"task_id": "T1", "title": "A", "task_type": "task.create_itinerary", "dependencies": []},
            {"task_id": "T2", "title": "B", "task_type": "task.create_itinerary", "dependencies": ["T1"]},
        ]
        _check_orphans(tasks)

    def test_orphan_dep_raises(self):
        tasks = [
            {"task_id": "T1", "title": "A", "task_type": "task.create_itinerary",
             "dependencies": ["NONEXISTENT"]},
        ]
        with pytest.raises(ValueError, match="NONEXISTENT"):
            _check_orphans(tasks)

    def test_empty_deps_no_error(self):
        tasks = [
            {"task_id": "T1", "title": "A", "task_type": "task.create_itinerary", "dependencies": []},
        ]
        _check_orphans(tasks)

    def test_empty_tasks_no_error(self):
        _check_orphans([])


# ============================================================
# DAG 构建测试
# ============================================================

class TestBuildDag:
    def test_build_from_valid_dicts(self):
        tasks = [
            {"task_id": "T1", "title": "交通", "task_type": "task.create_itinerary",
             "dependencies": [], "payload": {"aspect": "transportation"}},
            {"task_id": "T2", "title": "住宿", "task_type": "task.create_itinerary",
             "dependencies": [], "payload": {"aspect": "accommodation"}},
        ]
        dag = TaskDecomposer._build_dag(tasks)
        assert dag.task_count == 2
        assert dag.get_task("T1").title == "交通"

    def test_build_preserves_payload(self):
        tasks = [
            {"task_id": "T1", "title": "X", "task_type": "task.validate_feasibility",
             "dependencies": [], "payload": {"key": "value"}},
        ]
        dag = TaskDecomposer._build_dag(tasks)
        assert dag.get_task("T1").payload == {"key": "value"}
        assert dag.get_task("T1").task_type == TaskType.TASK_VALIDATE_FEASIBILITY


# ============================================================
# 格式化辅助方法
# ============================================================

class TestFormatting:
    def test_fmt_destination_dict(self, sample_request):
        result = TaskDecomposer._fmt_destination(sample_request)
        assert "Tokyo" in result
        assert "Japan" in result

    def test_fmt_destination_str(self):
        result = TaskDecomposer._fmt_destination({"destination": "Paris"})
        assert "Paris" in result

    def test_fmt_dates(self, sample_request):
        result = TaskDecomposer._fmt_dates(sample_request)
        assert "2026-12-20" in result
        assert "5天" in result

    def test_fmt_dates_missing(self):
        result = TaskDecomposer._fmt_dates({})
        assert result == "未指定"

    def test_fmt_budget(self, sample_request):
        result = TaskDecomposer._fmt_budget(sample_request)
        assert "15000" in result
        assert "CNY" in result

    def test_fmt_travelers(self, sample_request):
        result = TaskDecomposer._fmt_travelers(sample_request)
        assert "2成人" in result

    def test_fmt_travelers_with_children(self):
        result = TaskDecomposer._fmt_travelers({"travelers": {"adults": 2, "children": 1}})
        assert "2成人" in result
        assert "1儿童" in result

    def test_fmt_preferences(self, sample_request):
        result = TaskDecomposer._fmt_preferences(sample_request)
        assert "food" in result
        assert "culture" in result

    def test_fmt_preferences_empty(self):
        result = TaskDecomposer._fmt_preferences({})
        assert result == "无特殊偏好"


# ============================================================
# 边界测试
# ============================================================

class TestEdgeCases:
    def test_llm_none_decomposer(self, sample_request):
        """显式传入 None 仍应 fallback 到标准 T1-T4。"""
        dec = TaskDecomposer(llm_client=None)
        dag = asyncio.run(dec.decompose(sample_request))
        assert dag.task_count == 4
