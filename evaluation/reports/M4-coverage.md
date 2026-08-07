# M4 Offline Coverage Report

- Stage: M4
- Status: `PASSED_OFFLINE_PENDING_LIVE`
- Run date: 2026-08-07
- Scope: M2→M4 adapter、dynamic router、Geo Research Agent、Task Graph、orchestration、research agents、Composer、Schedule/Budget、Fake vertical slice、M4 facade and configuration.

## Verification result

Command:

```powershell
venv/Scripts/python.exe -m pytest -q --basetemp="F:\\Commercial project\\skill\\.pytest-tmp-m4-strict-20260807" --cov=. --cov-report=term --cov-fail-under=90
```

Result:

- Tests: `618 passed, 8 deselected`
- Total coverage: `93.44%`
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

Offline M4 behavior is closed: the Geo prerequisite, snapshot binding, dynamic task selection, structured past-date blocker, and failure propagation have regression evidence. The M4 acceptance remains pending only the real Live M4 revalidation because the current attempt stopped at the external DeepSeek connection before the M4 orchestrator.

No M5 implementation is included in this follow-up.
