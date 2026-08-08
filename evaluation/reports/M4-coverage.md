# M4 Offline Coverage Report

- Stage: M4
- Status: `PASSED`
- Run date: 2026-08-08
- Scope: M2→M4 adapter、dynamic router、Geo Research Agent、Task Graph、orchestration、research agents、Composer、Schedule/Budget、Fake vertical slice、M4 facade and configuration.

## Verification result

Command:

```powershell
$offlineBase = Join-Path $env:TEMP 'm4-offline-basetemp-20260808'
venv/Scripts/python.exe -m pytest -q --basetemp="$offlineBase" --cov=. --cov-report=term --cov-fail-under=90
```

Result:

- Tests: `637 passed, 8 deselected`
- Total coverage: `93.48%`
- Strict threshold: `PASSED`; `--cov-fail-under=90` reached the required threshold and exited with code 0.
- Ruff: `PASSED`; `venv/Scripts/python.exe -m ruff check .`

## Changed-path coverage

| Module | Coverage |
| --- | ---: |
| `src/agents/research/geo_agent.py` | 93% |
| `src/agents/research/agents.py` | 92% |
| `src/application/interaction_router.py` | 97% |
| `src/application/interaction_facade.py` | 94% |
| `src/application/fake_provider_workflow.py` | 78% |
| `src/application/m4_input_resolver.py` | 85% |
| `src/domain/services/readiness_evaluator.py` | 92% |

The aggregate gate is the acceptance threshold. Lower module-level percentages are retained transparently; no coverage exclusion or forced pass was added.

## Interpretation

Offline M4 behavior is closed: the Geo prerequisite, snapshot binding, dynamic task selection, structured past-date blocker, and failure propagation have regression evidence. The real Live M4 Vertical Slice also passed with 4/4 cases successful, including the required repeated normal case. The current M4 acceptance status is `PASSED`.

No M5 implementation is included in this follow-up.
