# M4 验收准备与当前记录

- Stage: M4
- Current status: `REVALIDATION_IN_PROGRESS`
- Record date: 2026-08-07
- Scope: Task Graph、Geo/Research Agent、Evidence/Candidate 汇总、Composer、Schedule、Budget、Fake vertical slice、CLI Use Case 接入，以及 M2→M4 接口适配
- Explicitly excluded: M5 GateRunner、Critic、Targeted Repair、Action、交易写操作和生产韧性能力

## 本次重新验证内容

| 验收项 | 当前结果 | 证据 |
| --- | --- | --- |
| M3 前置数据平面契约 | PASSED | `evaluation/reports/M3-completion.md`、`evaluation/reports/M3-handoff.md` |
| Geo Research Agent | PASSED（离线） | `src/agents/research/geo_agent.py`、`tests/unit/test_research_agents.py` |
| M2→M4 请求同步 | PASSED（离线） | `src/application/m4_input_resolver.py`、`tests/unit/test_m4_input_resolver.py` |
| 动态能力路由 | PASSED（离线） | `src/application/interaction_router.py`、路由回归测试 |
| Geo Task 依赖顺序 | PASSED（离线） | `tests/unit/test_task_graph_builder.py`、`tests/integration/test_m4_fake_provider_workflow.py` |
| G1 过去日期阻断 | PASSED（离线） | `src/domain/services/readiness_evaluator.py`、Facade/Readiness 回归测试 |
| 失败持久化日志 | PASSED（离线） | `tests/unit/test_m21_structured_errors.py` |
| Offline 全量测试 | PASSED | `618 passed, 8 deselected` |
| Ruff | PASSED | `venv/Scripts/python.exe -m ruff check .` |
| 严格覆盖率门 | PASSED | `93.44%`，`--cov-fail-under=90` 退出码 0 |
| 真实 Live M4 CLI | BLOCKED（外部） | 本次请求在 `interpreter` 阶段收到 `APIConnectionError`，未进入 Geo/供应商阶段 |

## 离线端到端证据

未来日期的 Fake Provider 请求使用 2026-08-10 至 2026-08-12，上海→杭州，2 人 fixture，已验证：

- `geo` Agent 对上海和杭州分别发出稳定 GeoQuery；
- `task-geo` 先于 transport/stay/place 任务；
- Geo、transport、stay、place、context 全链路可完成候选、排程和预算；
- Geo 空结果、工具错误、Schema 错误、超时、预算耗尽和后续地点失败均 fail-fast；
- 无地点类别时不创建 `place`，无上下文类型时不创建 `context`；
- M2 冻结快照中的地点、日期、人数和预算不会被 LLM 猜测或默认值覆盖；
- 过去日期在 G1 生成 `DATE_RANGE_IN_PAST` blocker，状态进入澄清，不调用外部工具。

## Live 复验状态

本次尝试命令：

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\start-local.ps1 -EnvFile .env "请安排上海到杭州的行程，时间是2026-8-10到2026-8-12，1人"
```

配置加载成功；请求随后在 `interpreter` 阶段因 `APIConnectionError` 失败，根错误为 `INTERPRETATION_INVALID`。这不是 Geo Agent 或 Fake Provider 错误，也没有证据表明已完成真实 Geo/transport 查询。历史 `M4-live-vertical-slice.json` 保留为此前验收证据，但本次接口变更后仍需重新执行真实 Live M4。

## 当前验收判断

M4 的离线实现和质量门已通过，但真实 Live 复验尚未通过，因此当前不能将 M4 标记为最终 `PASSED`，也不进入 M5。待 DeepSeek/API 网络恢复后，重新执行未来日期 Live M4；只有该复验成功，才可闭合 M4。
