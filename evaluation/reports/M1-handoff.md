# M1 Handoff

Stage: M1

Scope: 固化后续阶段共同依赖的结构化领域契约、状态机、状态仓储 Port/InMemory 和 legacy 兼容 Facade；保持当前 CLI 可运行，不提前实现 M2～M5 行为。

Contracts: `TripRequest`、`Constraint`、`ConstraintSnapshot`、`EvidenceItem`、`EvidenceSnapshot`、`Candidate`、`ItineraryPlan`、`ValidationIssue`、`TripState`、`Checkpoint`、`WorkflowError`、`LegacyPlanResult`、`PlanTripResult` 以及值对象和枚举。公开 Schema 版本为 `1.0`，快照位于 `data/schemas/m1-domain-contracts.json`。

Migrations: 新代码通过 `PlanTripUseCase` 调用 legacy planner；`LegacyPlanMapper` 在 Facade 内校验旧结果。CLI 已切换到 Facade。`src/engine/loop.py` 暂保留，owner 为 M1 兼容层，计划在 M5 迁移完成且调用者归零后删除。

Tests: 默认 pytest、M1 focused pytest、覆盖率、Ruff、Mypy 和 `git diff --check` 均通过；失败注入覆盖未知字段、非法值、状态非法转换、快照修改、仓储并发冲突、Checkpoint 隔离、legacy 结果缺失/非法、WorkflowError 安全序列化以及 LLM 失败传播。

Evaluation: 继续沿用 `baseline-v1` 作为 M0 回归基线；M1 新增契约/状态/Facade 测试，不改变 M0 离线评测口径。Live LLM Smoke 使用真实 API 两次调用并已通过，脱敏证据位于 `evaluation/reports/live-llm-smoke.json`。

Failures verified: 未知字段、缺失字段、非法组合、不可变快照写入、非法状态转换、错误版本保存、仓储并发冲突、错误 cause 泄露、legacy 映射失败、LLM 超时/失败和修订失败均保持显式失败；没有使用缓存、估算、备用供应商、重试或部分成功掩盖失败。

Out of scope: LLM 解析 `TripRequest`、Intent/Constraint Interpreter、Interaction Router、真实工具 Adapter、Evidence Registry 行为、Candidate Pool 排序、Task Graph、Research Agent、混合规划、质量门、Critic、局部修复、SQLite、缓存、重试、fallback、部分成功和预订/付款等外部写操作。

Next stage prerequisites: M2 可直接基于 Schema v1 实现解析、澄清和路由，不应修改 M1 契约才能启动。M2 必须继续保持默认零网络、显式 Fake、strict fail-fast，并为真实解析增加独立 `live_llm` 用例；任何契约破坏性修改必须先提升 Schema 版本并提供迁移说明。

Current implementation limitations: M1 的 `PlanTripResult.plan` 仍是 legacy 自由文本，不是结构化 `ItineraryPlan`；CLI 目前将原始输入保留为兼容 Facade 的偏好字段；状态仅使用 InMemory，尚未提供进程重启后的持久化能力。这些限制已明确属于后续阶段，不应在 M1 交付中伪装为已实现。
