# M4 验收准备与当前记录

- Stage: M4
- Current status: `PASSED`
- Record date: 2026-08-07
- Scope: Task Graph、Research Agent、Evidence/Candidate 汇总、Composer、Schedule、Budget、Fake vertical slice、CLI Use Case 接入
- Explicitly excluded: M5 G0～G5、Critic、Targeted Repair、Action、交易写操作

## 验收证据

| 验收项 | 当前结果 | 证据 |
| --- | --- | --- |
| M3 前置数据平面契约 | PASSED | `evaluation/reports/M3-completion.md`、`evaluation/reports/M3-handoff.md` |
| M4 11 步实现范围 | PASSED（实现已完成） | `src/application/`、`src/agents/`、`src/domain/services/`、对应 M4 测试 |
| Offline 测试套件 | PASSED | `605 passed, 8 deselected` |
| M4 聚合覆盖率 | PASSED（90.13%） | `evaluation/reports/M4-coverage.md` |
| 严格覆盖率门 `--cov-fail-under=90` | PASSED | 实际 `90.13%`，命令退出码 0 |
| Ruff | PASSED | `venv/Scripts/python.exe -m ruff check src tests evaluation` |
| `git diff --check` | PASSED | 当前验收记录整理前复核 |
| Live Vertical Slice | PASSED | `evaluation/reports/M4-live-vertical-slice.json`，状态 `SUCCESS` |

## Live Vertical Slice 记录

用户已通过以下命令完成人工 Live 验证：

```powershell
./start-local.ps1 -EnvFile .env -LiveM4
```

当前报告覆盖 4 次运行：

- `m4-live-normal`：2 次，均成功；
- `m4-live-constraint`：1 次，成功；
- `m4-live-complex`：1 次，成功。

4 次运行均记录真实模型 `deepseek-v4-flash` 和已配置的 `tuniu` Provider，并满足以下条件：

- `references_complete=true`；
- `hard_constraints_complete=true`；
- `hard_budget_within_limit=true`；
- `retry_count=0`；
- 无 cache、fallback、partial success；
- 无失败摘要，未缺失凭证；
- 每次生成 3 个 `PlanCandidate`。

## 当前验收判断

M4 的功能实现、离线测试、静态检查、严格覆盖率门和真实 Live 门均已通过，M4 阶段验收条件已满足并可标记为 `PASSED`。本次整理未进入 M5。

原覆盖率阻塞项已通过新增 fail-fast 分支回归测试关闭：当前覆盖率为 `90.13%`，严格命令退出码为 0。

## M4 边界

本记录不授权或实现 M5 的 G0～G5、Critic、Targeted Repair、最终质量裁决、交易 Action 或生产韧性能力。M4 验收记录已闭合；本次未进入 M5，后续如启动 M5 仍需遵守路线图前置条件。
