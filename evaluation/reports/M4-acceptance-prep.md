# M4 验收准备报告

- Stage: M4
- Current status: `PENDING_MANUAL_ACCEPTANCE`
- Preparation date: 2026-08-07
- Scope: Task Graph、Research Agent、Evidence/Candidate 汇总、Composer、Schedule、Budget、Fake vertical slice、CLI Use Case 接入
- Explicitly excluded: M5 G0～G5、Critic、Targeted Repair、Action、交易写操作

## 已准备内容

1. 新增 M4 ADR，记录手写 Task Graph、`asyncio.TaskGroup` 并发、确定性合并、失败取消和 fail-fast 传播。
2. 新增 `live_e2e` 标记和 `tests/e2e/test_m4_live_vertical_slice.py`。
3. 新增 `start-local.ps1 -LiveM4`，只运行 M4 Live Vertical Slice；普通 pytest 不会调用真实 API。
4. 新增脱敏报告工具和当前状态报告：`evaluation/reports/M4-live-vertical-slice.json`。
5. 启动脚本已允许 `WORKFLOW_USE_CASE`，默认仍为 M4，legacy 仍需显式选择。

## Offline 证据

详细结果见：evaluation/reports/M4-coverage.md。

执行命令：

```powershell
venv\Scripts\python.exe -m pytest -p no:cacheprovider --basetemp .pytest-tmp-m4-acceptance -m "not slow"
```

验收要求：所有离线测试通过，且 M4 变更范围聚合覆盖率不低于 90%。覆盖率报告由以下命令生成：

```powershell
venv\Scripts\python.exe -m pytest -p no:cacheprovider --basetemp .pytest-tmp-m4-coverage -m "not slow" `
  --cov=src.application.task_graph --cov=src.application.task_graph_builder `
  --cov=src.application.budget_policy --cov=src.application.orchestrator `
  --cov=src.application.fake_provider_workflow --cov=src.application.use_cases.m4_plan `
  --cov=src.agents.research --cov=src.agents.itinerary_composer `
  --cov=src.domain.services.schedule_service --cov=src.domain.services.budget_service `
  --cov=src.application.interaction_facade --cov=src.config `
  --cov-report=term-missing
```

## Live Vertical Slice 手动门

Codex 不自动调用真实 LLM 或供应商 API。用户在具备真实密钥的环境中执行：

```powershell
.\start-local.ps1 -EnvFile .env -LiveM4
```

该命令执行 4 次 M4 运行：

- `m4-live-normal`：执行 2 次，验证相同结构化输入的稳定性；
- `m4-live-constraint`：预算上限与多偏好约束；
- `m4-live-complex`：多人、多个偏好和弹性节奏约束。

每次运行固定：`retry_count=0`、无缓存、无 fallback、无 partial success。Live slice 使用已验证可返回住宿候选的 Tuniu hotel capability；航班和门票属于独立的 M3 工具契约，不作为本切片的必选能力。测试仍断言：

- TaskGraph 合法，关键任务全部 `SUCCEEDED`；
- Evidence/Candidate/PlanCandidate 引用完整；
- hard constraint 已被每个 PlanCandidate 引用；
- 预算未违反硬上限；
- 真实工具或模型失败直接使切片失败；
- 报告不记录凭证、原始供应商 payload、完整 Prompt 或不必要 PII。

当前 Live 报告仍为 `PENDING_MANUAL_ACCEPTANCE`。只有用户完成上述命令并生成 `SUCCESS` 报告后，M4 才能正式验收。

## 当前不应做的事

- 不进入 M5；
- 不实现 G0～G5、Critic、Repair；
- 不为 Live 失败切换 Fake、缓存、估算、备用供应商或部分成功；
- 不把 `main.py` 当前缺少真实 `DEEPSEEK_API_KEY` 的环境失败标记为代码成功。

## 验收结论

M4 开发实现已完成，验收准备材料已齐备；阶段状态仍为 `PENDING_MANUAL_ACCEPTANCE`，等待真实 Live Vertical Slice 人工结果。
