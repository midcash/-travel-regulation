# M3 Completion Report

Stage: M3 - Tool, Evidence Registry, and Candidate Pool

Status: READY_FOR_MANUAL_ACCEPTANCE (offline implementation complete; Live Tool and
post-M3 Live LLM evidence still required)

## Scope completed

- Capability-specific Provider Ports, typed Query/Result DTOs, explicit Provider Fakes,
  and typed ToolError failures.
- Settings-injected Amap and Tuniu adapters with one shared HTTP client per assembly,
  bounded response reads, untrusted text normalization, typed failures, and no retry,
  cache fallback, supplier switching, or partial success.
- Evidence Registry, stable evidence/snapshot IDs, injected Clock, TTL boundary handling,
  source conflict preservation, coverage/freshness/missing semantics, and Candidate Pool
  evidence validation, deduplication, provenance, and structured rejection reasons.
- `knowledge.py` compatibility Facade with no production imports from new M3 code into the
  legacy module.
- Low-cardinality M3 Metrics and `tool.*` OpenTelemetry child Spans.
- Default composition-root wiring for enabled real Amap/Tuniu adapters. Disabled providers
  remain unassembled; enabled providers without credentials fail before network access.
- Shared offline/live contract assertions and a redacted Live Tool report writer.

## Verification

The following checks were run locally after the implementation changes:

```text
venv/Scripts/python -m pytest -p no:cacheprovider
```

Expected local result: all default offline tests pass; tests marked `slow` are excluded by
`pytest.ini`. M3-related coverage is measured separately with `pytest-cov` and must remain
at least 90% for the changed M3 modules.

## Manual gates

The following are intentionally not claimed as passed by Codex:

1. Both enabled suppliers' real `live_tool` contracts must pass through the command below.
2. The command must generate `evaluation/reports/live-tool-contract.json` with `status` set
   to `SUCCESS`, two normal calls, two expected empty-result calls, schema version values,
   one network call per scenario, and no credentials or raw payloads.
3. The existing real DeepSeek smoke must be rerun after M3 and its report must be newer than
   the M3 changes.

Until these manual results exist, the M3 Live Tool Gate is
`PENDING_MANUAL_ACCEPTANCE`, as required by the roadmap.

## Out of scope

M3 does not implement Task Graphs, Research Agents, itinerary scheduling, quality gates,
Critic/Repair, external write actions, persistence, caching, automatic retries, or supplier
failover.
