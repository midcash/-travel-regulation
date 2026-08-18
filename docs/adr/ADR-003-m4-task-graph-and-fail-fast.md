# ADR-003: M4 Task Graph Orchestration and Fail-fast Planning

- Status: Accepted for the M4 implementation
- Date: 2026-08-07
- Scope: M4 Task Graph、Orchestrator、Research Agent、structured PlanCandidate、Schedule/Budget services

## Context

M4 must connect the M2 route and frozen constraint snapshot to the M3 provider/evidence/candidate contracts. The workflow needs explicit dependencies, bounded parallel research, deterministic aggregation, and a strict failure boundary. Agents must not call one another or write Trip State directly.

## Decisions

1. `TaskSpec`、`TaskGraph` and `TaskResult` are typed contracts. Graph construction validates task IDs, dependency existence, DAG acyclicity, allowlisted task types, and graph/version bindings.
2. The Orchestrator owns scheduling, dependency release, cancellation, optimistic-version checks, trace propagation, and the single registration point for Evidence/Candidate references.
3. Independent tasks may run concurrently through the controlled `asyncio.TaskGroup` path. Final aggregation is ordered by stable task identifiers, so completion timing does not change the result.
4. Research Agents return typed `AgentResult` values only. They do not call other Agents and do not mutate global Trip State.
5. Tool/model errors, invalid outputs, timeouts, budget exhaustion, cancellation, and state conflicts propagate as structured failure. M4 does not use retry, cache fallback, supplier failover, estimates, forced gates, or partial success.
6. Schedule and Budget calculations remain deterministic code. The Composer may generate differentiated plan skeletons, but it consumes validated Candidate/Evidence references and does not directly call providers.
7. The M4 Live gate is a separate real-API proof of the composed path. It cannot replace the Offline deterministic suite or its failure-injection coverage.

## Consequences

- M5 can consume stable `TaskResult` and `PlanCandidate` contracts to add G0～G5, Critic and targeted repair.
- The current M4 path is intentionally not a final quality adjudicator and does not execute external write actions.
- Acceptance requires both the Offline suite and the user-run Live Vertical Slice; a rounded coverage display does not override a strict threshold failure.

## Related evidence

- `evaluation/reports/M4-acceptance-record.md`
- `evaluation/reports/M4-coverage.md`
- `evaluation/reports/M4-live-vertical-slice.json`
- `docs/roadmap/M4-任务图研究Agent与混合规划.md`
