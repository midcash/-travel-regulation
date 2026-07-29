# M1 Completion Evidence

Date: 2026-07-29

Status: PASSED

## Scope completed

- 固化领域值对象、枚举、请求、约束快照、证据、候选、计划、验证问题、状态、Checkpoint 和 `WorkflowError`。
- 固化 `StateRepository` Port 与无磁盘 I/O 的 `InMemoryStateRepository`，包含深拷贝隔离、Checkpoint 和乐观并发冲突。
- 增加 `LegacyPlanMapper` 与 `PlanTripUseCase`，将 legacy 自由文本流程限制在 Facade 内部。
- 将 CLI 根切换到 Facade，并保留 M1 兼容行为。
- 生成并锁定 M1 JSON Schema 快照及契约测试。

## Acceptance gates

| Gate | Result | Evidence |
| --- | --- | --- |
| 核心模型存在且拒绝未知字段 | PASSED | `src/domain/models/`、`tests/unit/`、`tests/contract/` |
| Facade 不向外暴露裸 `dict` | PASSED | `src/application/use_cases/plan_trip.py`、`src/legacy/mapper.py` |
| Snapshot 不可原地修改 | PASSED | `tests/unit/test_trip_request_constraints.py`、`tests/unit/test_trip_state.py` |
| 状态转换白名单 | PASSED | `tests/unit/test_trip_state.py` |
| 乐观锁冲突可复现 | PASSED | `tests/unit/test_state_repository.py` |
| legacy 仅经 Facade 调用 | PASSED | `tests/unit/test_plan_trip_facade.py`、`tests/e2e/test_cli.py` |
| CLI 回归 | PASSED | `tests/e2e/test_cli.py` |
| Live LLM Smoke 回归 | PASSED | `evaluation/reports/live-llm-smoke.json` |
| M2 可直接开始解析与路由 | PASSED | Schema v1 已冻结，详见 M1 ADR |

## Verification

The following checks passed during M1 acceptance:

```powershell
venv\Scripts\python.exe -m pytest
venv\Scripts\python.exe -m pytest tests/unit tests/contract tests/integration tests/e2e/test_cli.py --cov=src/domain --cov=src/ports --cov=src/infrastructure/persistence --cov=src/legacy --cov=src/application --cov-report=term-missing
venv\Scripts\python.exe -m ruff check src evaluation tests
venv\Scripts\python.exe -m mypy
git diff --check
```

- Default suite: `154 passed, 2 deselected`。
- M1 focused suite: `88 passed`。
- M1 新增 domain、ports、InMemory、Mapper 与 Facade 覆盖率：`95%`。
- Ruff、Mypy 和 diff 检查：通过。
- 默认测试保持零网络；Fake/Fixture 只用于离线测试。

## Manual Live acceptance

Status: PASSED。

真实 LLM Smoke 已通过 `start-local.ps1 -LiveSmoke` 等价命令完成，两次调用均成功；脱敏报告记录了模型、调用次数、延迟、Token 数和失败分类。此前目标 CLI 的长耗时 revision 调用通过将本地进程 `LLM_TIMEOUT_SECONDS` 提升到 `60` 秒完成验证，未启用 retry、cache、fallback 或 partial success。

报告文件：[`evaluation/reports/live-llm-smoke.json`](live-llm-smoke.json)。报告不包含 API Key、完整 Prompt 或用户完整行程。

## M1 delivery checklist

- [x] 领域模型与 JSON Schema
- [x] `WorkflowError`
- [x] `StateRepository` Port/InMemory
- [x] `PlanTripUseCase` 与 legacy Mapper
- [x] 契约、状态机、仓储和兼容测试
- [x] M1 ADR：模型边界、版本策略、legacy 删除计划
- [x] Completion Evidence 与 Handoff
