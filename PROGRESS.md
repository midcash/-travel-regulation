# PROGRESS.md — 项目进度跟踪

---

## 总体进度

| 阶段 | 状态 | 开始日期 | 完成日期 |
|------|------|---------|---------|
| Phase 0: 基础设施 (core/, models/, tools/) | 未开始 | — | — |
| Phase 1: Orchestrator | 未开始 | — | — |
| Phase 2: Planning Agent + Execution Agent | 未开始 | — | — |
| Phase 3: Evaluation Agent | 未开始 | — | — |
| Phase 4: 集成测试 + 消融实验 | 未开始 | — | — |

**状态说明**: 未开始 → 进行中 → 已完成 → 已评估

---

## 文档-代码同步状态

### core/ (框架内核)

| spec 文件 | 对应代码 | 同步状态 | 备注 |
|-----------|---------|---------|------|
| `spec/agent_contract.md` | `core/message.py` | 未开始 | AgentMessage 数据类 |
| `spec/agent_contract.md` | `core/context.py` | 未开始 | SharedContext 黑板实现 |
| `spec/system_spec.md` | `core/orchestration_engine.py` | 未开始 | 编排引擎 |

### agents/ (业务 Agent)

| spec 文件 | 对应代码 | 同步状态 | 备注 |
|-----------|---------|---------|------|
| `spec/orchestrator_spec.md` | `agents/orchestrator.py` | 未开始 | P0 |
| `spec/planner_spec.md` | `agents/planning_agent.py` | 未开始 | P1 |
| `spec/executor_spec.md` | `agents/execution_agent.py` | 未开始 | P1 |
| `spec/evaluator_spec.md` | `agents/evaluation_agent.py` | 未开始 | Mode A/B/C |

### models/ (数据模型)

| spec 文件 | 对应代码 | 同步状态 | 备注 |
|-----------|---------|---------|------|
| `spec/system_spec.md` §3 | `models/` | 未开始 | 行程/用户/约束等数据模型 |

### tools/ (工具集)

| spec 文件 | 对应代码 | 同步状态 | 备注 |
|-----------|---------|---------|------|
| `spec/executor_spec.md` §工具 | `tools/` | 未开始 | 价格查询/地理校验/时间校验 |

### tests/ (测试)

| 来源 | 对应代码 | 同步状态 | 备注 |
|------|---------|---------|------|
| `evaluation/test_scenarios.md` | `tests/` | 未开始 | 23 个场景 |

### 规格文件自身 (准备阶段)

| 规格文件 | 状态 | 完成日期 |
|---------|------|---------|
| `CLAUDE.md` | 已完成 | 2026-07-05 |
| `PROGRESS.md` | 已完成 | 2026-07-05 |
| `spec/system_spec.md` | 已完成 | 2026-07-05 |
| `spec/agent_contract.md` | 已完成 | 2026-07-05 |
| `spec/orchestrator_spec.md` | 已完成 | 2026-07-05 |
| `spec/planner_spec.md` | 已完成 | 2026-07-05 |
| `spec/executor_spec.md` | 已完成 | 2026-07-05 |
| `spec/evaluator_spec.md` | 已完成 | 2026-07-05 |
| `playbooks/orchestrator_playbook.md` | 已完成 | 2026-07-05 |
| `playbooks/planner_playbook.md` | 已完成 | 2026-07-05 |
| `playbooks/executor_playbook.md` | 已完成 | 2026-07-05 |
| `playbooks/evaluator_playbook.md` | 已完成 | 2026-07-05 |
| `evaluation/quality_criteria.md` | 已完成 | 2026-07-05 |
| `evaluation/gate_definitions.md` | 已完成 | 2026-07-05 |
| `evaluation/test_scenarios.md` | 已完成 | 2026-07-05 |
| `evaluation/metrics.md` | 已完成 | 2026-07-05 |
| `evaluation/code_quality_rubric.md` | 已完成 | 2026-07-05 |
| `evaluation/plan_quality_rubric.md` | 已完成 | 2026-07-05 |
| `evaluation/ablation_protocol.md` | 已完成 | 2026-07-05 |
| `evaluation/contribution_metrics.md` | 已完成 | 2026-07-05 |
| `devagents/context_agent.md` | 已完成 | 2026-07-05 |
| `devagents/plan_agent.md` | 已完成 | 2026-07-05 |
| `devagents/code_agent.md` | 已完成 | 2026-07-05 |
| `devagents/test_agent.md` | 已完成 | 2026-07-05 |

---

## 变更日志

### 规则
- 任何 spec/evaluation/playbook/devagents 的修改必须记录于此
- 每次记录包含: 日期、变更类型、涉及文件、原因

| 日期 | 变更类型 | 涉及文件 | 原因 |
|------|---------|---------|------|
| 2026-07-05 | 创建 | 全部 24 个 .md 文件 | 项目初始化，完成所有准备文件 |
| — | — | — | — |

---

## 评估知识更新影响追踪

当评估层面学到新知识时，使用此表追踪需要检查的文件:

| 评估知识变更 | 需检查的源文件 | 需检查的被约束文件 | 检查日期 | 状态 |
|-------------|---------------|-------------------|---------|------|
| — | — | — | — | — |

**检查清单**（每次评估知识更新后执行）:
- [ ] `evaluation/` 下的 rubric/gate/metrics/scenarios
- [ ] `playbooks/evaluator_playbook.md` (Mode A/B/C)
- [ ] `spec/evaluator_spec.md`
- [ ] `devagents/code_agent.md` §7 (代码质量约束)
- [ ] `devagents/test_agent.md` §7 (测试质量约束)
- [ ] `devagents/plan_agent.md` §7 (方案合规约束)
