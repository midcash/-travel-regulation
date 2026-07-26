# M0 Completion Evidence

Date: 2026-07-25

## Implemented

- Added a composition root that validates strict settings and the active LLM key before planning.
- Injected one `Settings` instance through CLI, planner, L2 review, Gateway, and tool entrypoints.
- Removed implicit runtime environment reads from the active Gateway and tool adapter path.
- Added `slow` + `live_llm` smoke tests for a normal response and a parseable JSON response.
- Added redacted LLM call records for model, status, latency, token counts, and failure type.
- Expanded Characterization coverage for L2 parsing, tool timeout/empty results, and Gateway observations.
- Expanded mypy from two files to all `src/` modules.

## Verification

- Default suite: 66 passed, 2 slow tests deselected.
- Ruff: passed.
- Mypy: passed, 21 source files.
- Compileall: passed.
- Offline baseline: 32 cases, network calls 0; metrics remain explicit in `baseline-v1.md`.
- Live collection: 2 tests collected under `slow and live_llm`.

## Manual acceptance

Status: PASSED (user-confirmed, 2026-07-26).

The M0 implementation, offline tests, and evaluation infrastructure are complete. The user confirmed the real API acceptance succeeded by running:

```powershell
powershell -ExecutionPolicy Bypass -File .\start-local.ps1
```

Codex did not rerun or fabricate the external API result. The existing `live-llm-smoke.json` remains a historical no-key bootstrap attempt and is not used as the manual acceptance record.

The user-owned acceptance command is recorded above; runtime secrets and external response metrics are not copied into the repository.
