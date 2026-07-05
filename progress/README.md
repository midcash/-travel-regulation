# progress/ — 进度跟踪索引

---

## 模块碎片索引

| 模块 | 碎片文件 | 所属阶段 | 状态 |
|------|---------|---------|------|
| core/ (框架内核) | [core.md](core.md) | Phase 0 | 未开始 |
| models/ (数据模型) | [models.md](models.md) | Phase 0 | 未开始 |
| tools/ (工具集) | [tools.md](tools.md) | Phase 0 | 未开始 |
| Orchestrator | [orchestrator.md](orchestrator.md) | Phase 1 | 未开始 |
| Planning Agent | [planning.md](planning.md) | Phase 2 | 未开始 |
| Execution Agent | [execution.md](execution.md) | Phase 2 | 未开始 |
| Evaluation Agent | [evaluation.md](evaluation.md) | Phase 3 | 未开始 |
| tests/ (测试) | [tests.md](tests.md) | Phase 4 | 未开始 |

---

## 总体阶段进度

| 阶段 | 状态 | 开始日期 | 完成日期 |
|------|------|---------|---------|
| Phase 0: 基础设施 (core/, models/, tools/) | 未开始 | — | — |
| Phase 1: Orchestrator | 未开始 | — | — |
| Phase 2: Planning Agent + Execution Agent | 未开始 | — | — |
| Phase 3: Evaluation Agent | 未开始 | — | — |
| Phase 4: 集成测试 + 消融实验 | 未开始 | — | — |

**状态说明**: 未开始 → 进行中 → 已完成 → 已评估

---

## 准备文件清单 (已完成)

以下规格/约束文件在准备阶段已完成，编码阶段开始后不再单独追踪：

| 目录 | 文件数 | 状态 |
|------|--------|------|
| `spec/` | 6 | 已完成 (2026-07-05) |
| `playbooks/` | 4 | 已完成 (2026-07-05) |
| `evaluation/` | 8 | 已完成 (2026-07-05) |
| `devagents/` | 4 | 已完成 (2026-07-05) |
| 根配置 (CLAUDE.md, PROGRESS.md, VERSION) | 3 | 已完成 (2026-07-05) |

---

## 变更日志

| 日期 | 变更类型 | 涉及文件 | 原因 |
|------|---------|---------|------|
| 2026-07-05 | 创建 | 全部 24 个 .md 文件 | 项目初始化，完成所有准备文件 |
| 2026-07-05 | 重构 | PROGRESS.md → progress/*.md | 拆分为 per-module 碎片，避免并行开发时的合并冲突 |

---

## 评估知识更新影响追踪

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
