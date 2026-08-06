# M3 Completion Report

Stage: M3 - Tool, Evidence Registry, and Candidate Pool

Status: PASSED (offline implementation, coverage, Live Tool, and post-M3 Live LLM gates passed)

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

```powershell
venv\Scripts\python.exe -m pytest -p no:cacheprovider
venv\Scripts\python.exe -m pytest -p no:cacheprovider `
  --cov=src.ports.clock --cov=src.ports.evidence_repository `
  --cov=src.ports.tool_errors --cov=src.ports.tool_provider `
  --cov=src.domain.models.candidates --cov=src.domain.models.enums `
  --cov=src.domain.models.evidence --cov=src.domain.models.provider `
  --cov=src.domain.services.candidate_pool `
  --cov=src.infrastructure.evidence.in_memory `
  --cov=src.infrastructure.tools.amap --cov=src.infrastructure.tools.assembly `
  --cov=src.infrastructure.tools.tuniu --cov=src.obs.metric `
  --cov=src.tool.knowledge `
  --cov-report=json:evaluation/reports/M3-coverage.json
```

Result: `488 passed`, `7 deselected` by the default `not slow` marker. The detailed machine-
readable result is in [`M3-coverage.json`](M3-coverage.json).

### M3 coverage

| Scope | Statements | Covered | Coverage | Gate |
| --- | ---: | ---: | ---: | --- |
| M3 core modules | 1,731 | 1,617 | 93.4% | PASSED (>= 90%) |

| Module | Coverage |
| --- | ---: |
| `src/domain/models/candidates.py` | 92% |
| `src/domain/models/enums.py` | 100% |
| `src/domain/models/evidence.py` | 94% |
| `src/domain/models/provider.py` | 97% |
| `src/domain/services/candidate_pool.py` | 94% |
| `src/infrastructure/evidence/in_memory.py` | 95% |
| `src/infrastructure/tools/amap.py` | 92% |
| `src/infrastructure/tools/assembly.py` | 87% |
| `src/infrastructure/tools/tuniu.py` | 91% |
| `src/obs/metric.py` | 96% |
| `src/ports/clock.py` | 100% |
| `src/ports/evidence_repository.py` | 100% |
| `src/ports/tool_errors.py` | 100% |
| `src/ports/tool_provider.py` | 100% |
| `src/tool/knowledge.py` | 90% |

The stage threshold is applied to the aggregate of the changed M3 modules. The assembly
module's 87% file result is retained as a visible follow-up coverage gap; it does not lower
the aggregate gate below 90%.

## Manual gates

The manual gates are now evidenced by the user-run reports:

1. [`live-tool-contract.json`](live-tool-contract.json) is `SUCCESS`: Amap and Tuniu each
   passed normal and expected-empty contracts, with four network calls total and one call per
   scenario.
2. [`live-llm-smoke.json`](live-llm-smoke.json) is `SUCCESS`: two real DeepSeek calls passed
   with no recorded failure.
3. [`M2-live-interpreter.json`](M2-live-interpreter.json) is `SUCCESS`: 18 real interpreter
   runs passed with 14 network calls, retry count zero, and all six reported metrics at 1.0.

The Live Tool and post-M3 Live LLM gates are therefore `PASSED`. These reports validate the
provider and LLM contracts; they do not claim that the ordinary CLI already orchestrates a
full Tool -> Evidence -> Candidate -> itinerary workflow. That integration is an M4/M6 scope
boundary.

## Out of scope

M3 does not implement Task Graphs, Research Agents, itinerary scheduling, quality gates,
Critic/Repair, external write actions, persistence, caching, automatic retries, or supplier
failover.
