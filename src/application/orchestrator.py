"""M4 step four: controlled Task Graph orchestration.

This module owns deterministic scheduling and failure propagation.
Evidence, candidates, and Research Agent contracts remain for later M4 steps.
"""

from __future__ import annotations

import asyncio
import inspect
from collections.abc import Awaitable, Mapping
from decimal import Decimal
from time import monotonic
from typing import Protocol, TypeAlias

from pydantic import BaseModel, ConfigDict, model_validator

from src.application.budget_policy import (
    BudgetAllocation,
    BudgetExhaustedError,
    BudgetPolicy,
    BudgetUsage,
)
from src.application.task_graph import TaskGraph, TaskResult, TaskSpec, TaskStatus
from src.application.task_graph_builder import TaskGraphBuilder, TaskGraphBuildError
from src.domain.errors import WorkflowError
from src.domain.models.constraint import ConstraintSnapshot
from src.domain.models.enums import ErrorCategory, InteractionMode, WorkflowStatus
from src.domain.models.routing import RouteDecision
from src.domain.models.state import TripState
from src.domain.models.value_objects import StableId, TraceId
from src.domain.state_repository_errors import StateConflictError, StateNotFoundError
from src.ports.state_repository import StateRepository


class TaskRunContext(BaseModel):
    """Internal contract."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    trace_id: TraceId
    graph_id: StableId
    trip_id: StableId
    constraint_snapshot_id: StableId
    task_spec: TaskSpec
    dependency_output_refs: tuple[StableId, ...] = ()
    prior_evidence_refs: tuple[StableId, ...] = ()
    prior_candidate_refs: tuple[StableId, ...] = ()


TaskRunnerOutput: TypeAlias = TaskResult | Awaitable[TaskResult]


class TaskRunner(Protocol):
    """Internal contract."""

    def run(self, context: TaskRunContext) -> TaskRunnerOutput:
        """Internal contract."""


class TaskExecutionError(RuntimeError):
    """Internal contract."""

    def __init__(
        self,
        *,
        task_id: StableId,
        task_result: TaskResult,
        category: ErrorCategory,
        code: str,
        safe_message: str,
        retryable: bool = False,
        cause: BaseException | None = None,
    ) -> None:
        self.task_id = task_id
        self.task_result = task_result
        self.category = category
        self.code = code
        self.safe_message = safe_message
        self.retryable = retryable
        self.cause = cause
        super().__init__(safe_message)


class OrchestratorResult(BaseModel):
    """Internal contract."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    trace_id: TraceId
    graph: TaskGraph
    budget: BudgetAllocation
    task_results: tuple[TaskResult, ...]
    state: TripState

    @model_validator(mode="after")
    def validate_completed_graph(self) -> OrchestratorResult:
        """Internal contract."""
        task_ids = tuple(result.task_id for result in self.task_results)
        graph_ids = tuple(sorted(task.task_id for task in self.graph.tasks))
        if task_ids != graph_ids:
            raise ValueError("orchestrator results must be sorted and cover the graph")
        if any(result.status is not TaskStatus.SUCCEEDED for result in self.task_results):
            raise ValueError("orchestrator success result requires all tasks to succeed")
        if self.budget.graph_id != self.graph.graph_id:
            raise ValueError("budget allocation must belong to graph")
        if self.state.status is not WorkflowStatus.DRAFTING:
            raise ValueError("successful orchestration must enter DRAFTING")
        return self


class FakeTaskRunner:
    """Internal contract."""

    def __init__(
        self,
        task_results: Mapping[StableId, TaskResult],
        *,
        started_events: Mapping[StableId, asyncio.Event] | None = None,
        release_events: Mapping[StableId, asyncio.Event] | None = None,
    ) -> None:
        if not isinstance(task_results, Mapping):
            raise TypeError("task_results must be a mapping")
        if any(not isinstance(key, str) for key in task_results):
            raise TypeError("fake task result keys must be strings")
        if any(not isinstance(value, TaskResult) for value in task_results.values()):
            raise TypeError("fake task results must be TaskResult instances")
        self._task_results = dict(task_results)
        self._started_events = dict(started_events or {})
        self._release_events = dict(release_events or {})
        self.started_task_ids: list[StableId] = []
        self.finished_task_ids: list[StableId] = []
        self.contexts: list[TaskRunContext] = []

    async def run(self, context: TaskRunContext) -> TaskResult:
        """Internal contract."""
        if not isinstance(context, TaskRunContext):
            raise TypeError("context must be a TaskRunContext")
        task_id = context.task_spec.task_id
        self.started_task_ids.append(task_id)
        self.contexts.append(context)
        started_event = self._started_events.get(task_id)
        if started_event is not None:
            started_event.set()
        release_event = self._release_events.get(task_id)
        if release_event is not None:
            await release_event.wait()

        result = self._task_results.get(task_id)
        if result is None:
            return TaskResult(
                task_id=task_id,
                status=TaskStatus.FAILED,
                error_ref=f"fake-missing-result:{task_id}",
            )
        self.finished_task_ids.append(task_id)
        return result


class Orchestrator:
    """Internal contract."""

    def __init__(
        self,
        *,
        state_repository: StateRepository,
        task_runner: TaskRunner,
        task_graph_builder: TaskGraphBuilder | None = None,
        budget_policy: BudgetPolicy | None = None,
    ) -> None:
        self._state_repository = state_repository
        self._task_runner = task_runner
        self._task_graph_builder = task_graph_builder or TaskGraphBuilder()
        self._budget_policy = budget_policy or BudgetPolicy()

    def execute(
        self,
        state: TripState,
        route_decision: RouteDecision,
        *,
        trace_id: TraceId,
        constraint_snapshot: ConstraintSnapshot | None = None,
    ) -> OrchestratorResult:
        """Internal contract."""
        return asyncio.run(
            self.run(
                state,
                route_decision,
                trace_id=trace_id,
                constraint_snapshot=constraint_snapshot,
            )
        )

    async def run(
        self,
        state: TripState,
        route_decision: RouteDecision,
        *,
        trace_id: TraceId,
        constraint_snapshot: ConstraintSnapshot | None = None,
    ) -> OrchestratorResult:
        """Build and execute one graph bound to the current state snapshot.

        Args:
            state: Current TripState snapshot.
            route_decision: Structured decision produced by the M2 router.
            trace_id: Business trace identifier for this workflow.
            constraint_snapshot: Optional snapshot that must equal state.snapshot.

        Returns:
            OrchestratorResult: Successful task results and the DRAFTING state.

        Raises:
            WorkflowError: Graph, budget, task, timeout, or persistence failure.
        """
        self._validate_inputs(state, route_decision, trace_id)
        authoritative_state = self._load_authoritative_state(state, trace_id)
        active_state = authoritative_state

        try:
            snapshot = self._resolve_snapshot(
                authoritative_state,
                constraint_snapshot,
            )
            graph = self._task_graph_builder.build(
                route_decision,
                snapshot,
                trip_id=authoritative_state.trip_id,
            )
            if graph is None:
                raise TaskGraphBuildError("orchestrator requires a planning route")
            allocation = self._budget_policy.preflight(graph)
            active_state = self._prepare_research_state(active_state, route_decision)
            started_at = monotonic()
            async with asyncio.timeout(self._budget_policy.workflow_timeout_seconds):
                task_results = await self._execute_graph(
                    graph,
                    trace_id=trace_id,
                    started_at=started_at,
                )
            final_state = self._save_drafting_state(active_state)
            return OrchestratorResult(
                trace_id=trace_id,
                graph=graph,
                budget=allocation,
                task_results=task_results,
                state=final_state,
            )
        except Exception as exc:
            failure = _workflow_error(exc, trace_id=trace_id)
            self._persist_failure(active_state, failure)
            raise failure from exc

    def _load_authoritative_state(self, state: TripState, trace_id: TraceId) -> TripState:
        """Internal contract."""
        try:
            stored = self._state_repository.get(state.trip_id)
        except StateNotFoundError as exc:
            raise WorkflowError(
                trace_id=trace_id,
                stage="state_repository",
                category=ErrorCategory.STATE_CONFLICT,
                code="TRIP_STATE_NOT_FOUND",
                safe_message="trip state is not available for orchestration",
                upstream_refs=(state.trip_id,),
                cause=exc,
            ) from exc
        if stored.version != state.version:
            conflict = StateConflictError(state.trip_id, state.version, stored.version)
            raise WorkflowError(
                trace_id=trace_id,
                stage="state_repository",
                category=ErrorCategory.STATE_CONFLICT,
                code="STATE_VERSION_CONFLICT",
                safe_message="trip state version changed before orchestration started",
                upstream_refs=(state.trip_id,),
                cause=conflict,
            ) from conflict
        if stored.constraint_snapshot != state.constraint_snapshot:
            raise WorkflowError(
                trace_id=trace_id,
                stage="state_repository",
                category=ErrorCategory.STATE_CONFLICT,
                code="CONSTRAINT_SNAPSHOT_MISMATCH",
                safe_message="trip state and constraint snapshot are not the same version",
                upstream_refs=(state.trip_id,),
            )
        return stored

    async def _execute_graph(
        self,
        graph: TaskGraph,
        *,
        trace_id: TraceId,
        started_at: float,
    ) -> tuple[TaskResult, ...]:
        """Internal contract."""
        task_by_id = {task.task_id: task for task in graph.tasks}
        pending = set(task_by_id)
        results: dict[StableId, TaskResult] = {}
        tool_calls = 0
        model_calls = 0
        estimated_cost = Decimal("0")

        while pending:
            ready = tuple(
                sorted(
                    (
                        task_by_id[task_id]
                        for task_id in pending
                        if all(
                            dependency in results for dependency in task_by_id[task_id].dependencies
                        )
                    ),
                    key=lambda task: task.task_id,
                )
            )
            if not ready:
                raise ValueError("task graph has no dependency-ready task")

            self._budget_policy.check_usage(
                BudgetUsage(
                    started_tasks=len(results) + len(ready),
                    active_tasks=len(ready),
                    tool_calls=tool_calls,
                    model_calls=model_calls,
                    elapsed_seconds=monotonic() - started_at,
                )
            )
            task_handles: dict[StableId, asyncio.Task[TaskResult]] = {}
            try:
                async with asyncio.TaskGroup() as group:
                    for task in ready:
                        context = _task_context(
                            graph,
                            task,
                            results,
                            trace_id=trace_id,
                        )
                        task_handles[task.task_id] = group.create_task(
                            self._run_task(context),
                            name=task.task_id,
                        )
            except* TaskExecutionError as exception_group:
                raise _first_task_execution_error(exception_group) from exception_group

            wave_results = tuple(task_handles[task.task_id].result() for task in ready)
            for task, result in zip(ready, wave_results, strict=True):
                task_tool_calls, task_model_calls, task_cost = _result_usage(result)
                if task_tool_calls > task.tool_call_budget:
                    raise BudgetExhaustedError(
                        f"task:{task.task_id}:tool_calls",
                        task.tool_call_budget,
                        task_tool_calls,
                    )
                if task_model_calls > task.model_call_budget:
                    raise BudgetExhaustedError(
                        f"task:{task.task_id}:model_calls",
                        task.model_call_budget,
                        task_model_calls,
                    )
                tool_calls += task_tool_calls
                model_calls += task_model_calls
                estimated_cost += task_cost
                results[task.task_id] = result
                pending.remove(task.task_id)

            self._budget_policy.check_usage(
                BudgetUsage(
                    started_tasks=len(results),
                    active_tasks=0,
                    tool_calls=tool_calls,
                    model_calls=model_calls,
                    elapsed_seconds=monotonic() - started_at,
                    estimated_cost=estimated_cost,
                )
            )

        return tuple(results[task_id] for task_id in sorted(results))

    async def _run_task(self, context: TaskRunContext) -> TaskResult:
        """Internal contract."""
        task = context.task_spec
        try:
            async with asyncio.timeout(task.timeout):
                outcome = self._task_runner.run(context)
                result = await outcome if inspect.isawaitable(outcome) else outcome
        except asyncio.CancelledError:
            raise
        except TimeoutError as exc:
            raise TaskExecutionError(
                task_id=task.task_id,
                task_result=_failed_result(task.task_id, "task-timeout"),
                category=ErrorCategory.TIMEOUT,
                code="TASK_TIMEOUT",
                safe_message="task execution timed out",
                cause=exc,
            ) from exc
        except WorkflowError as exc:
            raise TaskExecutionError(
                task_id=task.task_id,
                task_result=_failed_result(task.task_id, "task-workflow-error"),
                category=exc.category,
                code=exc.public_payload().code,
                safe_message=exc.public_payload().safe_message,
                retryable=exc.retryable,
                cause=exc,
            ) from exc
        except Exception as exc:
            raise TaskExecutionError(
                task_id=task.task_id,
                task_result=_failed_result(task.task_id, "task-runner-error"),
                category=ErrorCategory.INTERNAL,
                code="TASK_RUNNER_FAILED",
                safe_message="task runner failed",
                cause=exc,
            ) from exc

        if not isinstance(result, TaskResult):
            raise TaskExecutionError(
                task_id=task.task_id,
                task_result=_failed_result(task.task_id, "task-invalid-result"),
                category=ErrorCategory.VALIDATION,
                code="TASK_RESULT_INVALID",
                safe_message="task runner returned an invalid result",
            )
        if result.task_id != task.task_id:
            raise TaskExecutionError(
                task_id=task.task_id,
                task_result=_failed_result(task.task_id, "task-id-mismatch"),
                category=ErrorCategory.VALIDATION,
                code="TASK_RESULT_ID_MISMATCH",
                safe_message="task runner returned a result for another task",
            )
        if result.status is not TaskStatus.SUCCEEDED:
            raise TaskExecutionError(
                task_id=task.task_id,
                task_result=result
                if result.status is TaskStatus.FAILED
                else _failed_result(task.task_id, "task-not-succeeded"),
                category=ErrorCategory.INTERNAL,
                code="TASK_FAILED",
                safe_message="task execution failed",
            )
        return result

    def _prepare_research_state(
        self,
        state: TripState,
        route_decision: RouteDecision,
    ) -> TripState:
        """Internal contract."""
        mode = InteractionMode(route_decision.mode)
        if mode is InteractionMode.REPLAN:
            if state.status is WorkflowStatus.REPLANNING:
                researching = state.transition_to(WorkflowStatus.RESEARCHING)
                return self._state_repository.save(researching, expected_version=state.version)
            if state.status is not WorkflowStatus.RESEARCHING:
                raise ValueError("replan orchestration requires REPLANNING or RESEARCHING state")
            return state
        if state.status is not WorkflowStatus.RESEARCHING:
            raise ValueError("research orchestration requires RESEARCHING state")
        return state

    def _save_drafting_state(self, state: TripState) -> TripState:
        """Internal contract."""
        if not state.can_transition_to(WorkflowStatus.DRAFTING):
            raise ValueError("completed research cannot transition to DRAFTING")
        drafting = state.transition_to(WorkflowStatus.DRAFTING).model_copy(
            update={"last_error": None}
        )
        return self._state_repository.save(drafting, expected_version=state.version)

    def _persist_failure(self, state: TripState, failure: WorkflowError) -> None:
        """Internal contract."""
        if state.status is WorkflowStatus.FAILED:
            return
        if not state.can_transition_to(WorkflowStatus.FAILED):
            raise WorkflowError(
                trace_id=failure.trace_id,
                stage="state_persistence",
                category=ErrorCategory.STATE_CONFLICT,
                code="FAILED_STATE_TRANSITION_INVALID",
                safe_message="workflow failure cannot be persisted from the current state",
                upstream_refs=(state.trip_id,),
                cause=failure,
            )
        failed = state.transition_to(WorkflowStatus.FAILED).model_copy(
            update={"last_error": failure.public_payload()}
        )
        try:
            self._state_repository.save(failed, expected_version=state.version)
        except Exception as exc:
            raise WorkflowError(
                trace_id=failure.trace_id,
                stage="state_persistence",
                category=ErrorCategory.STATE_CONFLICT,
                code="FAILED_STATE_SAVE_ERROR",
                safe_message="workflow failure could not be persisted",
                upstream_refs=(state.trip_id,),
                cause=failure,
            ) from exc

    @staticmethod
    def _validate_inputs(
        state: TripState,
        route_decision: RouteDecision,
        trace_id: TraceId,
    ) -> None:
        if not isinstance(state, TripState):
            raise TypeError("state must be a TripState")
        if not isinstance(route_decision, RouteDecision):
            raise TypeError("route_decision must be a RouteDecision")
        if not isinstance(trace_id, str) or not trace_id.strip():
            raise TypeError("trace_id must be a non-empty string")

    @staticmethod
    def _resolve_snapshot(state: TripState, snapshot: object | None) -> object:
        current = state.constraint_snapshot
        if current is None:
            raise ValueError("orchestration requires a constraint snapshot")
        if snapshot is not None and snapshot != current:
            raise ValueError("provided constraint snapshot does not match TripState")
        return current


def _task_context(
    graph: TaskGraph,
    task: TaskSpec,
    results: Mapping[StableId, TaskResult],
    *,
    trace_id: TraceId,
) -> TaskRunContext:
    dependency_results = tuple(results[dependency] for dependency in task.dependencies)
    return TaskRunContext(
        trace_id=trace_id,
        graph_id=graph.graph_id,
        trip_id=graph.trip_id,
        constraint_snapshot_id=graph.constraint_snapshot_id,
        task_spec=task,
        dependency_output_refs=tuple(
            sorted(
                result.output_ref for result in dependency_results if result.output_ref is not None
            )
        ),
        prior_evidence_refs=tuple(
            sorted(
                evidence_ref
                for result in dependency_results
                for evidence_ref in result.evidence_refs
            )
        ),
        prior_candidate_refs=tuple(
            sorted(
                candidate_ref
                for result in dependency_results
                for candidate_ref in result.candidate_refs
            )
        ),
    )


def _failed_result(task_id: StableId, suffix: str) -> TaskResult:
    return TaskResult(
        task_id=task_id,
        status=TaskStatus.FAILED,
        error_ref=f"error:{task_id}:{suffix}",
    )


def _first_task_execution_error(
    exception_group: BaseExceptionGroup[BaseException],
) -> TaskExecutionError:
    errors = tuple(_walk_task_errors(exception_group))
    if not errors:
        raise RuntimeError("TaskGroup failed without a TaskExecutionError")
    return min(errors, key=lambda error: error.task_id)


def _walk_task_errors(
    exception: BaseException,
) -> tuple[TaskExecutionError, ...]:
    if isinstance(exception, TaskExecutionError):
        return (exception,)
    if isinstance(exception, BaseExceptionGroup):
        return tuple(error for child in exception.exceptions for error in _walk_task_errors(child))
    return ()


def _result_usage(result: TaskResult) -> tuple[int, int, Decimal]:
    tool_calls = _metric_int(result, "tool_calls")
    model_calls = _metric_int(result, "model_calls")
    cost = _metric_cost(result, "estimated_cost")
    return tool_calls, model_calls, cost


def _metric_int(result: TaskResult, name: str) -> int:
    raw = result.metrics.get(name, 0)
    if isinstance(raw, bool) or not isinstance(raw, int | float):
        raise TaskExecutionError(
            task_id=result.task_id,
            task_result=_failed_result(result.task_id, "metric-invalid"),
            category=ErrorCategory.VALIDATION,
            code="TASK_METRIC_INVALID",
            safe_message="task result contains an invalid metric",
        )
    if raw < 0 or int(raw) != raw:
        raise TaskExecutionError(
            task_id=result.task_id,
            task_result=_failed_result(result.task_id, "metric-invalid"),
            category=ErrorCategory.VALIDATION,
            code="TASK_METRIC_INVALID",
            safe_message="task result contains an invalid metric",
        )
    return int(raw)


def _metric_cost(result: TaskResult, name: str) -> Decimal:
    raw = result.metrics.get(name, 0)
    if isinstance(raw, bool) or not isinstance(raw, int | float | Decimal):
        raise TaskExecutionError(
            task_id=result.task_id,
            task_result=_failed_result(result.task_id, "metric-invalid"),
            category=ErrorCategory.VALIDATION,
            code="TASK_METRIC_INVALID",
            safe_message="task result contains an invalid metric",
        )
    try:
        value = Decimal(str(raw))
    except (ArithmeticError, TypeError, ValueError) as exc:
        raise TaskExecutionError(
            task_id=result.task_id,
            task_result=_failed_result(result.task_id, "metric-invalid"),
            category=ErrorCategory.VALIDATION,
            code="TASK_METRIC_INVALID",
            safe_message="task result contains an invalid metric",
            cause=exc,
        ) from exc
    if not value.is_finite() or value < 0:
        raise TaskExecutionError(
            task_id=result.task_id,
            task_result=_failed_result(result.task_id, "metric-invalid"),
            category=ErrorCategory.VALIDATION,
            code="TASK_METRIC_INVALID",
            safe_message="task result contains an invalid metric",
        )
    return value


def _workflow_error(exc: Exception, *, trace_id: TraceId) -> WorkflowError:
    if isinstance(exc, WorkflowError):
        return exc
    if isinstance(exc, TaskExecutionError):
        return WorkflowError(
            trace_id=trace_id,
            stage="orchestrator",
            category=exc.category,
            code=exc.code,
            safe_message=exc.safe_message,
            upstream_refs=(exc.task_id, exc.task_result.error_ref or exc.task_id),
            retryable=exc.retryable,
            cause=exc.cause or exc,
        )
    if isinstance(exc, BudgetExhaustedError):
        return WorkflowError(
            trace_id=trace_id,
            stage="orchestrator",
            category=ErrorCategory.BUDGET,
            code="BUDGET_EXHAUSTED",
            safe_message="workflow budget was exhausted",
            retryable=False,
            cause=exc,
        )
    if isinstance(exc, StateConflictError):
        return WorkflowError(
            trace_id=trace_id,
            stage="state_repository",
            category=ErrorCategory.STATE_CONFLICT,
            code="STATE_VERSION_CONFLICT",
            safe_message="trip state version changed during orchestration",
            upstream_refs=(exc.trip_id,),
            cause=exc,
        )
    if isinstance(exc, TimeoutError):
        return WorkflowError(
            trace_id=trace_id,
            stage="orchestrator",
            category=ErrorCategory.TIMEOUT,
            code="WORKFLOW_DEADLINE_EXCEEDED",
            safe_message="workflow deadline was exceeded",
            cause=exc,
        )
    if isinstance(exc, TaskGraphBuildError | TypeError | ValueError):
        return WorkflowError(
            trace_id=trace_id,
            stage="orchestrator",
            category=ErrorCategory.VALIDATION,
            code="ORCHESTRATOR_INPUT_INVALID",
            safe_message="orchestrator input or task graph is invalid",
            cause=exc,
        )
    return WorkflowError(
        trace_id=trace_id,
        stage="orchestrator",
        category=ErrorCategory.INTERNAL,
        code="ORCHESTRATOR_FAILED",
        safe_message="orchestrator failed",
        cause=exc,
    )
