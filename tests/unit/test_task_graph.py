"""M4 第一步：Task Graph 契约测试。"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from src.application.task_graph import TaskGraph, TaskResult, TaskSpec, TaskStatus


def _task(task_id: str, *, dependencies: tuple[str, ...] = ()) -> TaskSpec:
    return TaskSpec(
        task_id=task_id,
        task_type="research",
        capability="geo",
        dependencies=dependencies,
        expected_output_type="EvidenceDraft",
        timeout=30.0,
        tool_call_budget=2,
        model_call_budget=1,
    )


def test_task_spec_is_immutable_and_rejects_duplicate_references() -> None:
    task = _task("geo")

    with pytest.raises(ValidationError):
        task.task_id = "other"  # type: ignore[misc]

    with pytest.raises(ValidationError, match="unique"):
        _task("geo", dependencies=("upstream", "upstream"))


def test_task_graph_accepts_valid_dag_and_rejects_missing_dependency() -> None:
    graph = TaskGraph(
        graph_id="graph-1",
        trip_id="trip-1",
        constraint_snapshot_id="snapshot-1",
        tasks=(_task("geo"), _task("transport", dependencies=("geo",))),
        graph_version=1,
    )

    assert tuple(task.task_id for task in graph.tasks) == ("geo", "transport")

    with pytest.raises(ValidationError, match="does not exist"):
        TaskGraph(
            graph_id="graph-2",
            trip_id="trip-1",
            constraint_snapshot_id="snapshot-1",
            tasks=(_task("transport", dependencies=("geo",)),),
            graph_version=1,
        )


def test_task_graph_rejects_duplicate_self_dependency_and_cycle() -> None:
    with pytest.raises(ValidationError, match="task_id must be unique"):
        TaskGraph(
            graph_id="graph-1",
            trip_id="trip-1",
            constraint_snapshot_id="snapshot-1",
            tasks=(_task("geo"), _task("geo")),
            graph_version=1,
        )

    with pytest.raises(ValidationError, match="itself"):
        TaskGraph(
            graph_id="graph-2",
            trip_id="trip-1",
            constraint_snapshot_id="snapshot-1",
            tasks=(_task("geo", dependencies=("geo",)),),
            graph_version=1,
        )

    with pytest.raises(ValidationError, match="acyclic"):
        TaskGraph(
            graph_id="graph-3",
            trip_id="trip-1",
            constraint_snapshot_id="snapshot-1",
            tasks=(
                _task("geo", dependencies=("transport",)),
                _task("transport", dependencies=("geo",)),
            ),
            graph_version=1,
        )


def test_task_result_requires_structured_success_or_failure_reference() -> None:
    success = TaskResult(
        task_id="geo",
        status=TaskStatus.SUCCEEDED,
        output_ref="output-1",
        evidence_refs=("evidence-1",),
        candidate_refs=("candidate-1",),
        metrics={"duration_ms": 12.5},
    )
    assert success.output_ref == "output-1"

    with pytest.raises(ValidationError, match="output_ref"):
        TaskResult(task_id="geo", status=TaskStatus.SUCCEEDED)
    with pytest.raises(ValidationError, match="error_ref"):
        TaskResult(task_id="geo", status=TaskStatus.FAILED)
    with pytest.raises(ValidationError, match="finite"):
        TaskResult(
            task_id="geo",
            status=TaskStatus.PENDING,
            metrics={"duration_ms": float("nan")},
        )
