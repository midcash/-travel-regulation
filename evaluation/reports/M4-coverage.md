# M4 Offline Coverage Report

- Stage: M4
- Status: `PASSED` for the offline aggregate coverage gate
- Run date: 2026-08-07
- Scope: M4 Task Graph, orchestration, research agents, itinerary composer, schedule/budget services, Fake vertical slice, M4 use case, facade, and configuration.

## Verification result

Command: `venv\\Scripts\\python.exe -m pytest -p no:cacheprovider --basetemp .pytest-tmp-m4-coverage -m "not slow" --cov=<M4 scope> --cov-report=term-missing`

- Tests: `599 passed, 8 deselected`
- Statements: `2,610`
- Missed: `262`
- Covered: `2,348`
- Aggregate coverage: `90%`
- Roadmap threshold: `>= 90%`

The aggregate threshold passes. The following module-level values remain visible for follow-up and are not hidden by aggregation:

| Module | Coverage |
|---|---:|
| `src/application/use_cases/m4_plan.py` | 68% |
| `src/application/fake_provider_workflow.py` | 83% |
| `src/application/orchestrator.py` | 84% |
| `src/application/task_graph_builder.py` | 85% |
| `src/application/task_graph.py` | 97% |
| `src/agents/research` | 100% |
| `src/agents/itinerary_composer.py` | 93% |
| `src/domain/services/schedule_service.py` | 90% |
| `src/domain/services/budget_service.py` | 94% |
| `src/application/interaction_facade.py` | 95% |
| `src/config.py` | 93% |

This report covers only offline evidence. It cannot replace the M4 Live Vertical Slice gate; `evaluation/reports/M4-live-vertical-slice.json` remains `PENDING_MANUAL_ACCEPTANCE` until the user runs the real-credential command.