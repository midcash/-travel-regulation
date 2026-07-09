# tests/ — 进度跟踪

**所属阶段**: Phase 4: 集成测试 + 消融实验

---

## 文档-代码同步状态

| 来源 | spec commit | 对应代码 | 同步状态 | 备注 |
|------|-------------|---------|---------|------|
| `evaluation/test_scenarios.md` | `035c2d4` | `tests/` | 已完成 | 41 场景全覆盖 + Batch 6 真实案例 + Batch 7 桥接适配 |
| `handoff.md §12 R4` | `待提交` | `tests/test_models.py`, `tests/test_orchestrator.py`, `tests/test_planning_agent.py` | 已完成 | 复用现有测试文件，新增 5 个 StructuredFeedback 定向用例 |
| `evaluation/ablation_protocol.md` | `4c74fa1` | `tests/test_ablation.py` | 已完成 | LOO + AIS + 360° + 协同 + 成本-质量 |

> **spec commit**: 上次确认同步时 spec 文件的 commit hash。
> 检查漂移: `git diff <spec_commit>..HEAD -- <spec_file>`

---

## 测试文件清单

| 文件 | 测试数(约) | 状态 |
|------|-----------|------|
| `test_message.py` | ~40 | 已完成 |
| `test_context.py` | ~30 | 已完成 |
| `test_gate_runner.py` | ~50 | 已完成 |
| `test_orchestration_engine.py` | ~60 | 已完成 |
| `test_models.py` | 54 | 已完成 (含 R4 StructuredFeedback format 测试) |
| `test_tools.py` | ~80 | 已完成 |
| `test_orchestrator.py` | 54 | 已完成 (version→1.1.0 + R4 feedback 构造) |
| `test_planning_agent.py` | 61 | 已完成 (Batch 4 LLM + R4 revision prompt 注入) |
| `test_execution_agent.py` | 30 | 已完成 |
| `test_evaluation_agent.py` | 41 | 已完成 |
| `test_integration.py` | ~50 | 已完成 (Batch 7 适配 degraded 宽松断言) |
| `test_ablation.py` | ~15 | 已完成 |
| `test_api_integration.py` | 75 | Batch 5 新建 |
| `test_real_cases.py` | 14 | Batch 6 新建 |
| **总计** | **~692** | **654 passed, 22 deselected (2026-07-09 默认测试，slow 跳过)** |

---

## e2e 真实 API 验证

| 日期 | 案例 | 评分 | degraded | 备注 |
|------|------|------|----------|------|
| 2026-07-06 | 东京 5天 | 82.0 | false | 全链路真实 API: DeepSeek + 高德 + 途牛, 1轮 PASS |

---

## 任务历史

| 日期 | 任务 | 状态 | 备注 |
|------|------|------|------|
| 2026-07-06 | Batch 3: test_integration.py + test_ablation.py | 已完成 | E2E/Edge/Error/Gate/ORCH/PERF + LOO/AIS/Synergy |
| 2026-07-06 | Batch 5: test_api_integration.py | 已完成 | API config + 3 tool clients + execution agent 集成 (75 tests) |
| 2026-07-06 | Batch 6: test_real_cases.py | 已完成 | 5真实城市端到端 (14 tests) |
| 2026-07-06 | Batch 7: 桥接适配 | 已完成 | version 1.1.0 + degraded 宽松断言, 661 passed 0 regressions |
| 2026-07-09 | v1.2.0 R4: StructuredFeedback 测试 | 已完成 | 复用现有测试文件新增 5 个用例；默认全套 654 passed, 22 deselected |
