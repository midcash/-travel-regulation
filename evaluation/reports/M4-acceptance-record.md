# M4 Acceptance Record

Date: 2026-08-07

Status: `PASSED`

## Decision

M4 的核心实现、真实端到端切片和严格覆盖率门均已通过验证，阶段验收条件满足，M4 可正式闭合。

## Evidence summary

| Gate | Result | Evidence |
| --- | --- | --- |
| M3 prerequisite handoff | PASSED | `M3-completion.md`、`M3-handoff.md` |
| M4 implementation scope | PASSED | M4 Task Graph、Orchestrator、Research Agent、Composer、Schedule、Budget、Fake vertical slice、CLI Use Case |
| Offline functional suite | PASSED | `605 passed, 8 deselected` |
| Static checks | PASSED | Ruff、`git diff --check` |
| Live Vertical Slice | PASSED | `M4-live-vertical-slice.json`，4/4 runs successful |
| Aggregate coverage | PASSED, 90.13% | `M4-coverage.md` |
| Strict aggregate coverage | PASSED | `90.13%`; `--cov-fail-under=90` exited 0 |

## Live evidence

The user-run Live report uses the real `deepseek-v4-flash` model and configured `tuniu` Provider. It covers normal case repeated twice, one constraint case, and one complex case. Every observation succeeded with complete references, complete hard-constraint checks, budget within limit, zero retries, and no cache/fallback/partial success.

## Acceptance boundary

The strict coverage command now passes, so the M4 acceptance record is closed. This task did not start M5. M5 G0～G5、Critic、Repair、Action and production resilience remain out of scope.

