# PROGRESS.md — 项目进度入口

> 此文件是进度跟踪的入口。各模块的详细同步状态在 [`progress/`](progress/) 目录下独立维护。

---

## 模块进度

| 模块 | 详细文件 | 所属阶段 | 状态 |
|------|---------|---------|------|
| core/ | [progress/core.md](progress/core.md) | Phase 0 | 已完成 |
| models/ | [progress/models.md](progress/models.md) | Phase 0 | 已完成 |
| tools/ | [progress/tools.md](progress/tools.md) | Phase 0 | 已完成 |
| Orchestrator | [progress/orchestrator.md](progress/orchestrator.md) | Phase 1 | 已完成 |
| Planning Agent | [progress/planning.md](progress/planning.md) | Phase 2 | 已完成 |
| Execution Agent | [progress/execution.md](progress/execution.md) | Phase 2 | 已完成 |
| Evaluation Agent | [progress/evaluation.md](progress/evaluation.md) | Phase 3 | 已完成 |
| tests/ | [progress/tests.md](progress/tests.md) | Phase 4 | 已完成 |

**详细内容见 [progress/README.md](progress/README.md)**（阶段进度、变更日志、评估知识影响追踪）

---

## 规则

- **并行开发**: 每个分支只修改自己负责的 `progress/<module>.md`，互不冲突
- **进度回写**: Code/Test Agent 完成后更新对应模块碎片
- **spec 漂移检测**: 用碎片中的 `spec commit` 列 + `git diff` 检查同步状态
