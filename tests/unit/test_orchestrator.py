"""M4 step four: Orchestrator and FakeTaskRunner tests."""

from __future__ import annotations

import asyncio
import socket
from contextlib import contextmanager
from datetime import UTC, datetime
from decimal import Decimal

import pytest
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import SimpleSpanProcessor
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter

from src.application.budget_policy import BudgetPolicy
from src.application.orchestrator import FakeTaskRunner, Orchestrator
from src.application.task_graph_builder import TaskGraphBuilder
from src.domain.errors import WorkflowError
from src.domain.models.constraint import ConstraintSnapshot
from src.domain.models.enums import WorkflowStatus
from src.domain.models.routing import RouteDecision, RouteReasonCode
from src.domain.models.state import TripState
from src.domain.models.trip_request import TravelerProfile, TripRequest
from src.infrastructure.persistence.in_memory import InMemoryStateRepository
from src.obs import trace as trace_module

if hasattr(asyncio, "WindowsSelectorEventLoopPolicy"):
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())


_NATIVE_SOCKET = socket.socket


@contextmanager
def _event_loop_socket() -> object:
    """Allow asyncio's internal socketpair without enabling runner network I/O."""
    guarded_socket = socket.socket
    socket.socket = _NATIVE_SOCKET
    try:
        yield
    finally:
        socket.socket = guarded_socket


def _request() -> TripRequest:
    return TripRequest(
        request_id="request-1",
        trip_id="trip-1",
        session_id="session-1",
        origin="Shanghai",
        destinations=("Hangzhou",),
        duration_days=3,
        travelers=TravelerProfile(adults=1),
    )


def _state(*, status: WorkflowStatus = WorkflowStatus.RESEARCHING) -> TripState:
    request = _request()
    snapshot = ConstraintSnapshot(
        version=1,
        created_at=datetime(2026, 8, 6, tzinfo=UTC),
        request_id=request.request_id,
    )
    return TripState(
        trip_id=request.trip_id,
        session_id=request.session_id,
        status=status,
        trip_request=request,
        constraint_snapshot=snapshot,
    )


def _route(
    *,
    mode: str = "plan",
    capabilities: tuple[str, ...] = ("geo", "transport", "place"),
) -> RouteDecision:
    return RouteDecision(
        mode=mode,
        confidence=Decimal("0.9"),
        reason_codes=(RouteReasonCode.PLAN_REQUEST,),
        required_capabilities=capabilities,
    )


def _configured_runner(route: RouteDecision) -> FakeTaskRunner:
    graph = TaskGraphBuilder().build(route, _state().constraint_snapshot, trip_id="trip-1")
    assert graph is not None
    from src.application.task_graph import TaskResult, TaskStatus

    return FakeTaskRunner(
        {
            task.task_id: TaskResult(
                task_id=task.task_id,
                status=TaskStatus.SUCCEEDED,
                output_ref=f"output:{task.task_id}",
            )
            for task in graph.tasks
        }
    )


def test_orchestrator_executes_dependency_waves_and_saves_drafting_state() -> None:
    state = _state()
    repository = InMemoryStateRepository()
    repository.create(state)
    runner = _configured_runner(_route())

    with _event_loop_socket():
        result = Orchestrator(
            state_repository=repository,
            task_runner=runner,
        ).execute(state, _route(), trace_id="trace-1")

    assert result.state.status is WorkflowStatus.DRAFTING
    assert tuple(item.task_id for item in result.task_results) == (
        "task-geo",
        "task-place",
        "task-transport",
    )
    assert runner.started_task_ids == ["task-geo", "task-place", "task-transport"]
    assert runner.contexts[1].dependency_output_refs == ("output:task-geo",)
    assert repository.get("trip-1").status is WorkflowStatus.DRAFTING


def test_orchestrator_runs_independent_tasks_in_parallel_without_sleep() -> None:
    async def scenario() -> None:
        state = _state()
        repository = InMemoryStateRepository()
        repository.create(state)
        route = _route(capabilities=("geo", "transport", "place"))
        graph = TaskGraphBuilder().build(route, state.constraint_snapshot, trip_id="trip-1")
        assert graph is not None
        from src.application.task_graph import TaskResult, TaskStatus

        first_started = asyncio.Event()
        second_started = asyncio.Event()
        release = asyncio.Event()
        runner = FakeTaskRunner(
            {
                task.task_id: TaskResult(
                    task_id=task.task_id,
                    status=TaskStatus.SUCCEEDED,
                    output_ref=f"output:{task.task_id}",
                )
                for task in graph.tasks
            },
            started_events={"task-transport": first_started, "task-place": second_started},
            release_events={"task-transport": release, "task-place": release},
        )
        execution = asyncio.create_task(
            Orchestrator(state_repository=repository, task_runner=runner).run(
                state,
                route,
                trace_id="trace-1",
            )
        )
        await asyncio.wait_for(first_started.wait(), timeout=1)
        await asyncio.wait_for(second_started.wait(), timeout=1)
        release.set()
        await execution

    with _event_loop_socket():
        asyncio.run(scenario())


def test_orchestrator_task_failure_marks_failed_and_does_not_return_partial_result() -> None:
    state = _state()
    repository = InMemoryStateRepository()
    repository.create(state)
    from src.application.task_graph import TaskResult, TaskStatus

    graph = TaskGraphBuilder().build(_route(), state.constraint_snapshot, trip_id="trip-1")
    assert graph is not None
    runner = FakeTaskRunner(
        {
            "task-geo": TaskResult(
                task_id="task-geo",
                status=TaskStatus.FAILED,
                error_ref="error:task-geo:provider",
            ),
            "task-transport": TaskResult(
                task_id="task-transport",
                status=TaskStatus.SUCCEEDED,
                output_ref="output:task-transport",
            ),
            "task-place": TaskResult(
                task_id="task-place",
                status=TaskStatus.SUCCEEDED,
                output_ref="output:task-place",
            ),
        }
    )

    with _event_loop_socket():
        with pytest.raises(WorkflowError) as raised:
            Orchestrator(state_repository=repository, task_runner=runner).execute(
                state,
                _route(),
                trace_id="trace-1",
            )

    assert raised.value.stage == "orchestrator"
    assert raised.value.category.value == "internal"
    assert raised.value.payload.code == "TASK_FAILED"
    assert repository.get("trip-1").status is WorkflowStatus.FAILED
    assert repository.get("trip-1").last_error is not None


def test_orchestrator_budget_exhaustion_fails_before_starting_tasks() -> None:
    state = _state()
    repository = InMemoryStateRepository()
    repository.create(state)
    runner = _configured_runner(_route())

    with _event_loop_socket():
        with pytest.raises(WorkflowError) as raised:
            Orchestrator(
                state_repository=repository,
                task_runner=runner,
                budget_policy=BudgetPolicy(max_total_tool_calls=9),
            ).execute(state, _route(), trace_id="trace-1")

    assert raised.value.category.value == "budget"
    assert raised.value.payload.code == "BUDGET_EXHAUSTED"
    assert runner.started_task_ids == []
    assert repository.get("trip-1").status is WorkflowStatus.FAILED


def test_orchestrator_task_timeout_fails_and_persists_timeout_category() -> None:
    class TimeoutRunner:
        def run(self, context: object) -> object:
            raise TimeoutError("fake task timeout")

    state = _state()
    repository = InMemoryStateRepository()
    repository.create(state)

    with _event_loop_socket():
        with pytest.raises(WorkflowError) as raised:
            Orchestrator(
                state_repository=repository,
                task_runner=TimeoutRunner(),
            ).execute(state, _route(capabilities=("geo",)), trace_id="trace-1")

    assert raised.value.category.value == "timeout"
    assert raised.value.payload.code == "TASK_TIMEOUT"
    assert repository.get("trip-1").status is WorkflowStatus.FAILED


def test_orchestrator_rejects_stale_state_without_marking_newer_state_failed() -> None:
    state = _state()
    repository = InMemoryStateRepository()
    repository.create(state)
    newer = state.transition_to(WorkflowStatus.DRAFTING)
    repository.save(newer, expected_version=state.version)

    with _event_loop_socket():
        with pytest.raises(WorkflowError) as raised:
            Orchestrator(
                state_repository=repository,
                task_runner=_configured_runner(_route()),
            ).execute(state, _route(), trace_id="trace-1")

    assert raised.value.category.value == "state_conflict"
    assert raised.value.payload.code == "STATE_VERSION_CONFLICT"
    assert repository.get("trip-1").status is WorkflowStatus.DRAFTING


def test_fake_runner_without_explicit_result_fails_instead_of_defaulting_to_success() -> None:
    state = _state()
    repository = InMemoryStateRepository()
    repository.create(state)
    runner = FakeTaskRunner({})

    with _event_loop_socket():
        with pytest.raises(WorkflowError, match="task execution failed"):
            Orchestrator(state_repository=repository, task_runner=runner).execute(
                state,
                _route(capabilities=("geo",)),
                trace_id="trace-1",
            )


def test_orchestrator_failure_cancels_sibling_and_preserves_root_cause() -> None:
    async def scenario() -> None:
        state = _state()
        repository = InMemoryStateRepository()
        repository.create(state)
        route = _route()
        graph = TaskGraphBuilder().build(route, state.constraint_snapshot, trip_id="trip-1")
        assert graph is not None
        from src.application.task_graph import TaskResult, TaskStatus

        place_started = asyncio.Event()
        transport_started = asyncio.Event()
        runner = FakeTaskRunner(
            {
                "task-geo": TaskResult(
                    task_id="task-geo",
                    status=TaskStatus.SUCCEEDED,
                    output_ref="output:task-geo",
                ),
                "task-place": TaskResult(
                    task_id="task-place",
                    status=TaskStatus.SUCCEEDED,
                    output_ref="output:task-place",
                ),
                "task-transport": TaskResult(
                    task_id="task-transport",
                    status=TaskStatus.FAILED,
                    error_ref="error:task-transport:provider",
                ),
            },
            started_events={
                "task-place": place_started,
                "task-transport": transport_started,
            },
            release_events={"task-place": asyncio.Event()},
        )
        execution = asyncio.create_task(
            Orchestrator(state_repository=repository, task_runner=runner).run(
                state,
                route,
                trace_id="trace-cancel",
            )
        )

        await asyncio.wait_for(place_started.wait(), timeout=1)
        await asyncio.wait_for(transport_started.wait(), timeout=1)
        with pytest.raises(WorkflowError) as raised:
            await execution

        assert raised.value.payload.code == "TASK_FAILED"
        assert raised.value.payload.upstream_refs[0] == "task-transport"
        assert runner.cancelled_task_ids == ["task-place"]
        assert repository.get("trip-1").status is WorkflowStatus.FAILED

    with _event_loop_socket():
        asyncio.run(scenario())


def test_orchestrator_save_conflict_preserves_original_version_error() -> None:
    class ConflictOnDraftingRepository(InMemoryStateRepository):
        def __init__(self) -> None:
            super().__init__()
            self.injected = False

        def save(self, state: TripState, expected_version: int) -> TripState:
            if state.status is WorkflowStatus.DRAFTING and not self.injected:
                self.injected = True
                current = super().get(state.trip_id)
                conflicting = current.transition_to(WorkflowStatus.FAILED)
                super().save(conflicting, expected_version=current.version)
            return super().save(state, expected_version=expected_version)

    state = _state()
    repository = ConflictOnDraftingRepository()
    repository.create(state)

    with _event_loop_socket():
        with pytest.raises(WorkflowError) as raised:
            Orchestrator(
                state_repository=repository,
                task_runner=_configured_runner(_route()),
            ).execute(state, _route(), trace_id="trace-version")

    assert raised.value.payload.code == "STATE_VERSION_CONFLICT"
    assert raised.value.category.value == "state_conflict"
    assert repository.get("trip-1").status is WorkflowStatus.FAILED


def test_orchestrator_emits_workflow_and_task_trace_spans(monkeypatch) -> None:
    exporter = InMemorySpanExporter()
    provider = TracerProvider()
    provider.add_span_processor(SimpleSpanProcessor(exporter))
    monkeypatch.setattr(trace_module, "_tracer", provider.get_tracer("m4-step5-test"))

    state = _state()
    repository = InMemoryStateRepository()
    repository.create(state)

    with _event_loop_socket():
        result = Orchestrator(
            state_repository=repository,
            task_runner=_configured_runner(_route()),
        ).execute(state, _route(), trace_id="trace-span")

    spans = exporter.get_finished_spans()
    workflow = next(span for span in spans if span.name == "orchestrator.run")
    tasks = tuple(span for span in spans if span.name == "orchestrator.task")

    assert result.trace_id == "trace-span"
    assert workflow.attributes["workflow.trace_id"] == "trace-span"
    assert workflow.attributes["workflow.graph_id"] == result.graph.graph_id
    assert workflow.attributes["workflow.status"] == WorkflowStatus.DRAFTING.value
    assert tuple(sorted(span.attributes["workflow.task_id"] for span in tasks)) == tuple(
        sorted(task.task_id for task in result.graph.tasks)
    )
    assert all(
        span.attributes["workflow.trace_id"] == "trace-span"
        and span.attributes["workflow.task.status"] == "succeeded"
        and span.parent is not None
        and span.parent.span_id == workflow.context.span_id
        for span in tasks
    )
