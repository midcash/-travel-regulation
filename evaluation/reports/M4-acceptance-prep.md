# M4 验收准备与当前记录

- Stage: M4
- Current status: `PASSED`
- Record date: 2026-08-08
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
| Offline 全量测试 | PASSED | `637 passed, 8 deselected` |
| Ruff | PASSED | `venv/Scripts/python.exe -m ruff check .` |
| 严格覆盖率门 | PASSED | `93.48%`，`--cov-fail-under=90` 退出码 0 |
| 真实 Live M4 Vertical Slice | PASSED | 4 个真实案例全部通过，normal 案例重复 2 次；报告为 `evaluation/reports/M4-live-vertical-slice.json` |

## 离线端到端证据

未来日期的 Fake Provider 请求使用 2026-08-10 至 2026-08-12，上海→杭州，2 人 fixture，已验证：

- `geo` Agent 对上海和杭州分别发出稳定 GeoQuery；
- `task-geo` 先于 transport/stay/place 任务；
- Geo、transport、stay、place、context 全链路可完成候选、排程和预算；
- Geo 空结果、工具错误、Schema 错误、超时、预算耗尽和后续地点失败均 fail-fast；
- 无地点类别时不创建 `place`，无上下文类型时不创建 `context`；
- M2 冻结快照中的地点、日期、人数和预算不会被 LLM 猜测或默认值覆盖；
- 过去日期在 G1 生成 `DATE_RANGE_IN_PAST` blocker，状态进入澄清，不调用外部工具。

## Live 验收结果

本次通过命令：

```powershell
.\start-local.ps1 -EnvFile .env -LiveM4
```

真实 LLM 与途牛配置加载成功，Live Vertical Slice 执行 4 个案例并全部通过。报告状态为 `SUCCESS`，Prompt 版本为 `m4-itinerary-composer-v2`，Evidence/Candidate 引用、硬约束、硬预算和 fail-fast 预算断言均通过。

## 当前验收判断

M4 的离线实现、质量门和真实 Live Vertical Slice 均已通过，当前 M4 标记为最终 `PASSED`。M5 GateRunner、Critic、Repair、Action 和生产韧性能力仍属于后续阶段，未在本次验收中实现。
