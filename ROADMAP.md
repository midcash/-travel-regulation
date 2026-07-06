# ROADMAP — 版本路线图

> 此文件仅在 `main` 分支维护。每个版本的具体改动在该版本的分支上执行。

---

## 版本规划

| 版本 | 目标 | 预计改动范围 | 状态 |
|------|------|-------------|------|
| v1.0.0 | 基础旅游规划能力 — 单目的地行程生成 + 可行性验证 + 评估反馈 | 全量初始化 | 已完成 |
| v1.1.0 | 多目的地行程串联 | `spec/planner_spec.md`, `spec/orchestrator_spec.md` | 规划中 |
| v1.2.0 | 实时价格 API 对接 | `spec/executor_spec.md`, `tools/` | 规划中 |
| v2.0.0 | 多人协作规划 + agent_contract v2 | `spec/system_spec.md`, `spec/agent_contract.md` | 规划中 |

---

## v1.0.0 范围定义

**目标**: 端到端跑通一次旅游规划请求，所有 Quality Gate 通过，消融实验基线建立。

**交付物**:

| 模块 | 关键功能 | 优先级 |
|------|---------|--------|
| `core/` | AgentMessage, SharedContext, GateRunner, 编排引擎 | P0 |
| `models/` | TripPlan, Itinerary, Budget, Constraint 数据模型 | P0 |
| `tools/` | 价格查询 stub, 地理校验 stub, 时间校验 stub | P1 |
| `agents/orchestrator.py` | 任务分解·路由·结果整合 + Gate 0/3 | P0 |
| `agents/planning_agent.py` | 行程规划·目的地研究·预算分配 | P1 |
| `agents/execution_agent.py` | 可行性验证·硬约束检查·风险识别 + Gate 1 | P1 |
| `agents/evaluation_agent.py` | Mode A/B/C 三层评估 + Gate 2 | P1 |
| `tests/` | 41 个 test scenarios 全覆盖 + 消融实验 + 回归测试套件，552 tests | P1 |

**不在此版本**:
- 真实 API 调用（用 stub/mock 替代）
- 多人协作
- Web UI
- 历史行程数据库

---

## 版本命名规则

采用语义化版本 (SemVer): `MAJOR.MINOR.PATCH`

| 变更类型 | 版本号变化 | 示例 |
|---------|-----------|------|
| 不兼容的 API/协议变更 | MAJOR +1, MINOR/PATCH 归零 | v1.2.3 → v2.0.0 |
| 向后兼容的新功能 | MINOR +1, PATCH 归零 | v1.2.3 → v1.3.0 |
| 向后兼容的 bug 修复 | PATCH +1 | v1.2.3 → v1.2.4 |
