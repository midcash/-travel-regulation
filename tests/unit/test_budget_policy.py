"""M4 第三步：Task Graph 预算策略测试。"""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal

import pytest

from src.application.budget_policy import (
    BudgetExhaustedError,
    BudgetPolicy,
    BudgetUsage,
)
from src.application.task_graph_builder import TaskGraphBuilder
from src.domain.models.constraint import ConstraintSnapshot
from src.domain.models.routing import RouteDecision, RouteReasonCode


def _snapshot() -> ConstraintSnapshot:
    return ConstraintSnapshot(
        version=1,
        created_at=datetime(2026, 8, 6, tzinfo=UTC),
        request_id="request-1",
    )


def _graph() -> object:
    route = RouteDecision(
        mode="plan",
        confidence=Decimal("0.9"),
        reason_codes=(RouteReasonCode.PLAN_REQUEST,),
        required_capabilities=("geo", "transport", "place", "context"),
    )
    return TaskGraphBuilder().build(route, _snapshot(), trip_id="trip-1")


def test_policy_preflight_returns_deterministic_graph_budget() -> None:
    allocation = BudgetPolicy().preflight(_graph())  # type: ignore[arg-type]

    assert allocation.task_count == 4
    assert allocation.peak_concurrency == 2
    assert allocation.total_tool_calls == 20
    assert allocation.total_model_calls == 1
    assert allocation.critical_path_timeout_seconds == 150.0


def test_policy_rejects_graph_when_declared_tool_budget_exceeds_limit() -> None:
    with pytest.raises(BudgetExhaustedError, match="max_total_tool_calls budget exhausted"):
        BudgetPolicy(max_total_tool_calls=19).preflight(_graph())  # type: ignore[arg-type]


def test_policy_rejects_graph_when_critical_path_exceeds_deadline() -> None:
    with pytest.raises(BudgetExhaustedError, match="workflow_timeout_seconds budget exhausted"):
        BudgetPolicy(workflow_timeout_seconds=149).preflight(_graph())  # type: ignore[arg-type]


def test_policy_rejects_runtime_usage_without_partial_success() -> None:
    usage = BudgetUsage(tool_calls=33)

    with pytest.raises(BudgetExhaustedError, match="max_total_tool_calls budget exhausted"):
        BudgetPolicy().check_usage(usage)


def test_policy_rejects_invalid_concurrency_limit() -> None:
    with pytest.raises(ValueError, match="max_concurrent_tasks"):
        BudgetPolicy(max_tasks=2, max_concurrent_tasks=3)

def test_policy_rejects_non_finite_workflow_timeout() -> None:
    with pytest.raises(ValueError, match="workflow_timeout_seconds must be finite"):
        BudgetPolicy(workflow_timeout_seconds=float("inf"))


def test_policy_rejects_non_task_graph_preflight_input() -> None:
    with pytest.raises(TypeError, match="graph must be a TaskGraph"):
        BudgetPolicy().preflight(object())  # type: ignore[arg-type]


def test_policy_rejects_non_budget_usage_check_input() -> None:
    with pytest.raises(TypeError, match="usage must be a BudgetUsage"):
        BudgetPolicy().check_usage(object())  # type: ignore[arg-type]


def test_policy_rejects_non_finite_runtime_elapsed_time() -> None:
    with pytest.raises(ValueError, match="elapsed_seconds must be finite"):
        BudgetUsage(elapsed_seconds=float("inf"))
