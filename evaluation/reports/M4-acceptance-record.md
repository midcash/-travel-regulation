# M4 Acceptance Record

Date: 2026-08-07

Status: `REVALIDATION_IN_PROGRESS`

## Decision

本次重新验证已确认 M4 离线链路和质量门通过，但真实 Live M4 在 Interpreter 阶段遭遇外部 `APIConnectionError`，因此 M4 暂不闭合，不进入 M5。

## Evidence summary

| Gate | Result | Evidence |
| --- | --- | --- |
| M3 prerequisite handoff | PASSED | `M3-completion.md`、`M3-handoff.md` |
| Geo Research Agent | PASSED offline | Geo provider wiring and fail-fast regression tests |
| M2→M4 request synchronization | PASSED offline | `M4InputResolver` regression tests |
| Dynamic capability routing | PASSED offline | Router regression tests; no implicit place/context tasks |
| Past-date G1 blocker | PASSED offline | `DATE_RANGE_IN_PAST` readiness and Facade tests |
| Failure persistence logging | PASSED offline | Root failure preserved without secondary misleading error |
| Offline functional suite | PASSED | `618 passed, 8 deselected` |
| Static checks | PASSED | Ruff |
| Aggregate coverage | PASSED | `93.44%`, strict `>=90%` |
| Real Live M4 revalidation | PENDING | DeepSeek `APIConnectionError` at `interpreter`; no Geo-stage evidence yet |

## Acceptance boundary

M4 remains the active acceptance target. M5 GateRunner、Critic、Repair、Action 和生产韧性能力仍未实现，也未因本次修复提前启用。

历史 `M4-live-vertical-slice.json` 不删除，但仅作为接口变更前的历史证据；新的 Live M4 成功记录产生后，才可将本记录改为 `PASSED`。
