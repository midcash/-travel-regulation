# tests/ — 进度跟踪

**所属阶段**: Phase 4: 集成测试 + 消融实验

---

## 文档-代码同步状态

| 来源 | spec commit | 对应代码 | 同步状态 | 备注 |
|------|-------------|---------|---------|------|
| `evaluation/test_scenarios.md` | 7681362 | `tests/` | 已完成 | 41 场景全覆盖: 集成测试 + 消融实验 |
| `evaluation/ablation_protocol.md` | 7681362 | `tests/test_ablation.py` | 已完成 | LOO + AIS + 360° + 协同 + 成本-质量 |

> **spec commit**: 上次确认同步时 spec 文件的 commit hash。
> 检查漂移: `git diff <spec_commit>..HEAD -- <spec_file>`

---

## 测试文件清单

| 文件 | 测试场景覆盖 | 状态 |
|------|------------|------|
| `test_message.py` | core/message.py 单元测试 | 已完成 |
| `test_context.py` | core/context.py 单元测试 | 已完成 |
| `test_gate_runner.py` | Gate 0-3, TS-ERR-001~005, TS-GATE-001~002/005 | 已完成 |
| `test_orchestration_engine.py` | TaskDAG/AgentRouter/RetryManager/ResultAssembler | 已完成 |
| `test_models.py` | models/ 全部数据类验证 | 已完成 |
| `test_tools.py` | tools/ 全部函数, TS-EXEC-001~009 | 已完成 |
| `test_orchestrator.py` | Orchestrator 全部方法, 52 tests | 已完成 |
| `test_planning_agent.py` | Planning Agent 全部方法, 35 tests | 已完成 |
| `test_execution_agent.py` | Execution Agent 全部方法, 30 tests | 已完成 |
| `test_evaluation_agent.py` | Evaluation Agent Mode A/B/C, 41 tests | 已完成 |
| `test_integration.py` | E2E + Edge + Error + Gate + ORCH + PERF | **Batch 3 新建** |
| `test_ablation.py` | TS-ABLATION-001~004 (LOO + AIS + 360 + Synergy) | **Batch 3 新建** |

---

## 41 场景覆盖矩阵

| 场景类别 | 场景数 | 完全覆盖 | 覆盖文件 |
|---------|--------|---------|---------|
| TS-E2E (端到端) | 5 | ✅ 5/5 | test_integration.py |
| TS-EDGE (边界) | 5 | ✅ 5/5 | test_integration.py |
| TS-ERR (异常) | 7 | ✅ 7/7 | test_gate_runner.py + test_integration.py |
| TS-GATE (质量门) | 5 | ✅ 5/5 | test_gate_runner.py + test_integration.py |
| TS-ABLATION (消融) | 4 | ✅ 4/4 | test_ablation.py |
| TS-PERF (性能) | 3 | ✅ 3/3 | test_integration.py |
| TS-ORCH (编排恢复) | 9 | ✅ 9/9 | test_integration.py + test_orchestration_engine.py |
| TS-EXEC (执行检查) | 9 | ✅ 9/9 | test_execution_agent.py + test_tools.py |
| **总计** | **41** | **✅ 41/41** | |

---

## 回归测试套件

### 最小回归集 (每次提交必跑)
- `test_gate_runner.py::TestGate0::test_gate0_fail_missing_destination` — TS-ERR-001
- `test_gate_runner.py::TestGate1::test_gate1_fail_blocking` — TS-GATE-001
- `test_integration.py::TestE2EHappyPath::test_e2e_001_standard_tokyo_trip` — TS-E2E-001
- `test_integration.py::TestOrchRecoveryTimeout::test_orch_001_planning_timeout_retry_success` — TS-ORCH-001
- `test_tools.py` (price check blocking) — TS-EXEC-003

### 完整回归集 (每次发布前必跑)
- 所有 `test_integration.py` E2E + Edge + Error + Gate 场景
- 所有 `test_orchestrator.py` + `test_planning_agent.py` + `test_execution_agent.py` + `test_evaluation_agent.py`
- `test_integration.py::TestPerformance::test_perf_001_standard_timing`

### 消融回归集 (每次架构变更必跑)
- 所有 `test_ablation.py` 场景 (TS-ABLATION-001~004)

---

## 任务历史

| 日期 | 任务 | 状态 | 备注 |
|------|------|------|------|
| 2026-07-06 | Batch 3: test_integration.py 创建 | 已完成 | E2E/Edge/Error/Gate/ORCH/PERF 全覆盖 |
| 2026-07-06 | Batch 3: test_ablation.py 创建 | 已完成 | LOO+AIS+360°+Synergy+C2C5 |
| 2026-07-06 | Batch 3: conftest.py 扩展 | 已完成 | 新增 integration/ablation 共享 fixtures |
| 2026-07-06 | Phase 4 完成 | 已完成 | 41/41 场景全量覆盖 |
