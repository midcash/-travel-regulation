# ADR: M4 手写 Task Graph、并发与失败传播

- Status: Accepted for M4 implementation
- Date: 2026-08-07
- Scope: M4 Task Graph、Orchestrator、Research Agent vertical slice

## Context

M4 needs a bounded workflow that can express research dependencies, run independent
tasks concurrently, preserve deterministic results, and make external failures visible.
The M4 stage is still in strict development mode: no retry, cache fallback, supplier
failover, estimated replacement, partial success, or Gate force-through is allowed.

## Decision

### 1. Use a handwritten typed Task Graph

`TaskSpec`, `TaskResult`, and `TaskGraph` are Pydantic contracts owned by the
application layer. `TaskGraphBuilder` maps the Router's capability allowlist to a finite
set of task templates. The Builder and Validator enforce:

- stable unique task IDs;
- existing dependencies and acyclic graph structure;
- graph version and `ConstraintSnapshot` identity alignment;
- task and budget upper bounds;
- no model- or user-supplied arbitrary task type.

LangGraph is not introduced. OR-Tools is not required for this stage because M4's
deterministic scheduling and budget calculations are implemented by typed application
and domain services; any future optimizer introduction requires a separate ADR.

### 2. Use `asyncio.TaskGroup` for dependency-aware concurrency

The Orchestrator starts only tasks whose dependencies have succeeded. Independent tasks
run in the same structured-concurrency group. Results are merged by stable task ID and
candidate ID, never by completion order. Shared mutable context is not passed between
parallel agents; each agent receives an immutable `AgentContext`.

The implementation does not use `asyncio.gather(..., return_exceptions=True)`. A failed
critical task cancels unfinished sibling tasks, and cancellation preserves the first
typed task failure as the workflow root cause.

### 3. Centralize state and evidence writes

Research Agents return only typed `AgentResult` drafts. The Orchestrator owns task
state transitions. The M4 workflow registers evidence and candidates after successful
research, then passes immutable snapshots to the Composer, ScheduleService, and
BudgetService. Agents never write `TripState` or the Evidence Registry directly.

### 4. Fail fast and never return a partial plan

Provider, schema, timeout, budget, evidence, and state-version failures become typed
workflow failures with a `trace_id`, stage, category, safe message, and upstream
references. The affected `TripState` transitions to `FAILED`. A failure cannot be
converted into a normal partial plan, and reaching a budget or time limit is not a
success condition.

## Consequences

The M4 workflow is explicit, inspectable, and deterministic under Fake inputs. It is
also intentionally limited: it produces structured `PlanCandidate`, `TaskResult`,
Evidence, Schedule, and Budget outputs, but it does not implement M5 G0-G5 quality
gates, Critic, or targeted repair. Those consumers may rely on the M4 output contracts
after the M4 Live Vertical Slice Gate passes.

## Verification

Offline verification is provided by the Task Graph, Orchestrator, Research Agent,
planner, and Fake Provider integration tests. Real LLM/provider compatibility is a
separate manual M4 Live Vertical Slice Gate and cannot be replaced by these Fake tests.
