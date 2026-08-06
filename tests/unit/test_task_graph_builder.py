"""M4 second step: Task Graph Builder and Validator tests."""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal

import pytest

from src.application.task_graph_builder import (
    TaskGraphBuilder,
    TaskGraphBuildError,
    TaskGraphValidator,
)
from src.domain.models.constraint import ConstraintSnapshot
from src.domain.models.routing import RouteDecision, RouteReasonCode


def _snapshot(version: int = 1) -> ConstraintSnapshot:
    return ConstraintSnapshot(
        version=version,
        created_at=datetime(2026, 8, 6, tzinfo=UTC),
        request_id="request-1",
    )


def _route(
    mode: str = "plan",
    capabilities: tuple[str, ...] = ("geo", "transport", "place"),
    current_plan_ref: str | None = None,
) -> RouteDecision:
    return RouteDecision(
        mode=mode,
        confidence=Decimal("0.9"),
        reason_codes=(RouteReasonCode.PLAN_REQUEST,),
        required_capabilities=capabilities,
        current_plan_ref=current_plan_ref,
    )


def test_builder_maps_allowlisted_capabilities_to_deterministic_dag() -> None:
    graph = TaskGraphBuilder().build(_route(), _snapshot(), trip_id="trip-1")

    assert graph is not None
    assert tuple(task.task_id for task in graph.tasks) == (
        "task-geo",
        "task-transport",
        "task-place",
    )
    assert graph.tasks[1].dependencies == ("task-geo",)
    assert graph.tasks[2].dependencies == ("task-geo",)
    assert graph.constraint_snapshot_id == "snapshot-request-1-1"


def test_builder_does_not_create_full_graph_for_answer() -> None:
    assert TaskGraphBuilder().build(_route("answer", ()), _snapshot(), trip_id="trip-1") is None


def test_builder_rejects_unknown_capability_and_missing_plan_reference() -> None:
    with pytest.raises(TaskGraphBuildError, match="unsupported task capability"):
        TaskGraphBuilder().build(_route(capabilities=("unknown",)), _snapshot(), trip_id="trip-1")

    graph = TaskGraphBuilder().build(
        _route("refine", capabilities=("plan_refinement",), current_plan_ref="plan-1"),
        _snapshot(),
        trip_id="trip-1",
    )
    assert graph is not None
    assert graph.tasks[0].input_refs == ("plan-1",)


def test_validator_rejects_snapshot_and_capability_mismatch() -> None:
    builder = TaskGraphBuilder()
    graph = builder.build(_route(), _snapshot(), trip_id="trip-1")
    assert graph is not None

    altered_route = _route(capabilities=("geo",))
    with pytest.raises(TaskGraphBuildError, match="capabilities do not match"):
        TaskGraphValidator().validate(graph, altered_route, _snapshot(), trip_id="trip-1")

    with pytest.raises(TaskGraphBuildError, match="different constraint snapshot"):
        TaskGraphValidator().validate(graph, _route(), _snapshot(2), trip_id="trip-1")
