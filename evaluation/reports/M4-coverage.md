# M4 Offline Coverage Report

- Stage: M4
- Status: `PASSED`
- Run date: 2026-08-07
- Scope: M4 Task Graph, orchestration, research agents, itinerary composer, schedule/budget services, Fake vertical slice, M4 use case, facade, and configuration.

## Verification result

Command:

```powershell
venv/Scripts/python.exe -m pytest -p no:cacheprovider --basetemp .pytest-tmp-m4-coverage-record -m "not slow" --cov=src.application.task_graph --cov=src.application.task_graph_builder --cov=src.application.budget_policy --cov=src.application.orchestrator --cov=src.application.fake_provider_workflow --cov=src.application.use_cases.m4_plan --cov=src.agents.research --cov=src.agents.itinerary_composer --cov=src.domain.services.schedule_service --cov=src.domain.services.budget_service --cov=src.application.interaction_facade --cov=src.config --cov-report=term-missing --cov-fail-under=90
```

Result:

- Tests: `605 passed, 8 deselected`
- Statements: `2,613`
- Missed: `258`
- Covered: `2,355`
- Coverage tool result: `90.13%`
- Strict threshold check: `PASSED`; `--cov-fail-under=90` reports coverage `90.13%` and exits with code 0.

The strict aggregate coverage gate passed at `90.13%`, above the required `>=90%` threshold.

## Module coverage

| Module | Coverage |
| --- | ---: |
| `src/application/use_cases/m4_plan.py` | 68% |
| `src/application/fake_provider_workflow.py` | 83% |
| `src/application/orchestrator.py` | 84% |
| `src/application/task_graph_builder.py` | 85% |
| `src/application/task_graph.py` | 97% |
| `src/agents/itinerary_composer.py` | 93% |
| `src/agents/research/agents.py` | 92% |
| `src/agents/research/contracts.py` | 96% |
| `src/domain/services/schedule_service.py` | 90% |
| `src/domain/services/budget_service.py` | 94% |
| `src/application/interaction_facade.py` | 95% |
| `src/config.py` | 93% |

## Interpretation

The complete offline suite, strict coverage threshold, Ruff check, and `git diff --check` passed. This report is the offline evidence for the M4 acceptance gate; it must be combined with the Live Vertical Slice report.

The strict M4 offline coverage gate is closed. No M5 implementation is included in this follow-up.
