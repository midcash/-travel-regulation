# M3 Handoff Report

Stage: M3

Status: PASSED; M3 acceptance evidence is complete and the stable data-plane contracts are
ready for M4 consumption.

## Handoff to M4

M4 may consume only the following stable boundaries:

- `src.ports.tool_provider` for capability-specific async provider calls;
- `src.ports.tool_errors` for typed fail-fast provider errors;
- `src.ports.clock.Clock` for time-sensitive decisions;
- `src.ports.evidence_repository.EvidenceRepository` for immutable evidence snapshots;
- `src.domain.services.candidate_pool.CandidatePool` and the typed Candidate models.

M4 must not import supplier adapters directly, read provider credentials, pass raw supplier
payloads to an Agent, or treat stale/conflicting/missing evidence as verified.

## Acceptance evidence to attach

- [`evaluation/reports/live-tool-contract.json`](live-tool-contract.json): `SUCCESS`; Amap and
  Tuniu normal/expected-empty contracts passed in four bounded network calls;
- [`evaluation/reports/live-llm-smoke.json`](live-llm-smoke.json): `SUCCESS`; two real DeepSeek
  smoke calls passed;
- [`evaluation/reports/M2-live-interpreter.json`](M2-live-interpreter.json): `SUCCESS`; 18
  real interpreter runs passed with retry count zero;
- [`evaluation/reports/M3-coverage.json`](M3-coverage.json): 488 offline tests passed and
  M3 aggregate coverage is 93.4% against the 90% threshold;
- the commit containing the M3 implementation and these acceptance materials.

## Acceptance boundary

M3 is accepted as the provider/evidence/candidate data foundation. The reports prove the
real provider contracts and the post-M3 LLM availability, but they do not prove that the
ordinary CLI already invokes Amap/Tuniu while generating a complete itinerary. M4 owns the
Task Graph, Research Agent, Evidence/Candidate aggregation, and hybrid planning vertical
slice; M6 owns the user-facing delivery path.

## Live commands

PowerShell, from the repository root:

```powershell
.\start-local.ps1 -EnvFile .env -LiveTool
.\start-local.ps1 -EnvFile .env -LiveSmoke
```

`-LiveTool` requires real `AMAP_API_KEY` and `TUNIU_API_KEY`. It performs only bounded
read-only contract queries. Configure `AMAP_LIVE_EMPTY_TEXT` and
`TUNIU_LIVE_EMPTY_DESTINATION` in the local `.env` when the provider needs a known no-result
query. Never commit `.env` or paste keys into logs or reports.

## Failure handling

Any real provider timeout, authentication failure, schema failure, empty-result mismatch, or
unexpected response keeps the stage failed. The test suite must not switch to a Fake,
historical value, cache, or another supplier after a Live failure.
