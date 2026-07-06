# Handoff — v1.0.0 全面铺开

## 当前状态

- **版本**: `1.0.0-dev`
- **分支**: `main`（与 `origin/main` 同步）
- **已完成**: Phase 0-4 全部完成 — 6个核心模块 + 4个业务Agent + 552 tests (41/41 场景全覆盖)
- **最近提交**: 待提交 — Batch 3 集成测试+消融实验完成

## 已完成清单

### 约束修补（11项）
| # | 类别 | 修复项 | 状态 |
|---|------|--------|------|
| 1 | 必须 | Gate 2 伪代码 <60→REJECT | ✅ |
| 2 | 必须 | CLAUDE.md Quality Gate 表对齐 | ✅ |
| 3 | 必须 | Code Agent §6 性能自检项 | ✅ |
| 4 | 必须 | Code Agent §6 测试覆盖率自检 | ✅ |
| 5 | 必须 | agent_contract 新增 response.result + control.abort | ✅ |
| 6 | 阻塞 | orchestrator 路由表新增 task.revise_itinerary | ✅ |
| 7 | 阻塞 | 4个playbooks+code_agent retry策略统一 | ✅ |
| 8 | 阻塞 | agent_contract §3.2 TaskType枚举(11个值) | ✅ |
| 9 | 阻塞 | Gate 2 维度级告警(5维度,≥3→blocking) | ✅ |
| 10 | 阻塞 | test_scenarios TS-EXEC-001~009 | ✅ |
| 11 | 阻塞 | test_scenarios TS-ORCH-001~009 | ✅ |

### Batch 1: core/models/tools（基础层）
| 文件 | 行数 | 功能 |
|------|------|------|
| `core/message.py` | 426 | AgentMessage / TaskType / ErrorCode / AgentIdentity / BaseAgent / AgentRegistry |
| `core/context.py` | 387 | ContextStatus(15状态) / LogEntry / SharedContext / to_dict / from_dict |
| `core/gate_runner.py` | 586 | GateRunner (Gate 0-3 执行器) / BlockingIssue / GateResult |
| `core/orchestration_engine.py` | 528 | Task / TaskDAG / AgentRouter / RetryManager / ResultAssembler |
| `models/entities.py` | 451 | Attraction / Restaurant / Accommodation / DestinationInfo / PriceRange 等 |
| `models/plan.py` | 297 | Transportation / ItineraryDay / BudgetAllocation / TravelPlanDraft / FinalTravelPlan |
| `models/request.py` | 391 | StructuredRequest / Destination / DateRange / Budget / Travelers / Preferences |
| `models/validation.py` | 370 | ValidationReport / PriceCheckResult / TimeCheckResult / GeographyCheckResult 等 |
| `models/quality.py` | 435 | CodeQualityReport / PlanQualityReport / ContributionReport / AblationResults 等 |
| `tools/price_checker.py` | — | check_prices / check_budget_compliance / estimate_market_price (stub) |
| `tools/time_checker.py` | — | check_time / check_opening_hours / calculate_transit_time (stub) |
| `tools/geo_checker.py` | — | check_geography / validate_geography (stub) |
| `tools/risk_checker.py` | — | check_weather_risk / check_travel_requirements (stub) |

### Batch 2: 业务Agent（编排层）

| 文件 | 行数 | 功能 | 覆盖率 |
|------|------|------|--------|
| `agents/orchestrator.py` | 333 | Orchestrator 主控 — parse_request / decompose_task / route_task / assemble_plan / manage_quality_gate (Gate 0-3) / handle_revision / process_request | 78% |
| `agents/planning_agent.py` | 134 | Planning Agent — create_itinerary / revise_itinerary / research_destination / search_attractions / search_accommodations / search_restaurants / allocate_budget | 94% |
| `agents/execution_agent.py` | 234 | Execution Agent — validate_feasibility / check_prices / check_time / check_geography / check_constraints / identify_risks / estimate_market_price | 88% |
| `agents/evaluation_agent.py` | 284 | Evaluation Agent — Mode A (代码质量5维度) / Mode B (方案质量5维度加权) / Mode C (LOO消融+360°+协同分析+C2C5) | 86% |
| `agents/__init__.py` | — | 完整公共 API 导出 | — |

**Agent 测试文件**:
| 文件 | 测试数 |
|------|--------|
| `tests/test_orchestrator.py` | 52 tests |
| `tests/test_planning_agent.py` | 35 tests |
| `tests/test_execution_agent.py` | 30 tests |
| `tests/test_evaluation_agent.py` | 41 tests |

### Batch 3: 集成测试 + 消融实验（Phase 4）

| 文件 | 测试数 | 覆盖场景 |
|------|--------|---------|
| `tests/test_integration.py` | 31 | E2E(5) + Edge(5) + Error(2) + Gate(4) + Perf(3) + ORCH Recovery(9) + Context(2) + Message(1) |
| `tests/test_ablation.py` | 22 | LOO Ablation(7) + AIS(5) + 360°(4) + Synergy(4) + Protocol(10) + Pipeline(2) |
| `tests/conftest.py` | — | 新增 10 个 Phase 4 共享 fixtures |

**41/41 测试场景全覆盖**: E2E✅ Edge✅ Error✅ Gate✅ Ablation✅ Perf✅ ORCH✅ EXEC✅
**全量测试**: 552 passed in 15.11s

### 现存代码文件总览
```
core/
  message.py              ← 已完成 (Batch 1)
  context.py              ← 已完成 (Batch 1)
  gate_runner.py          ← 已完成 (Batch 1)
  orchestration_engine.py ← 已完成 (Batch 1)
  __init__.py             ← 已完成
models/
  entities.py             ← 已完成 (Batch 1)
  plan.py                 ← 已完成 (Batch 1)
  request.py              ← 已完成 (Batch 1)
  validation.py           ← 已完成 (Batch 1)
  quality.py              ← 已完成 (Batch 1)
  __init__.py             ← 已完成
tools/
  price_checker.py        ← 已完成 (Batch 1)
  time_checker.py         ← 已完成 (Batch 1)
  geo_checker.py          ← 已完成 (Batch 1)
  risk_checker.py         ← 已完成 (Batch 1)
  __init__.py             ← 已完成
agents/
  orchestrator.py         ← 已完成 (Batch 2A)
  planning_agent.py       ← 已完成 (Batch 2B)
  execution_agent.py      ← 已完成 (Batch 2C)
  evaluation_agent.py     ← 已完成 (Batch 2D)
  __init__.py             ← 已完成
tests/
  test_message.py         ← 已完成
  test_context.py         ← 已完成
  test_orchestrator.py    ← 已完成 (Batch 2)
  test_planning_agent.py  ← 已完成 (Batch 2)
  test_execution_agent.py ← 已完成 (Batch 2)
  test_evaluation_agent.py← 已完成 (Batch 2)
  conftest.py             ← 已完成
  __init__.py             ← 已完成
```

---

## 下一步：Batch 3 — 集成测试 + 消融实验（Phase 4）

- 端到端测试：按 `evaluation/test_scenarios.md` 41 个场景全量覆盖
- 消融实验：按 `evaluation/ablation_protocol.md` 执行 LOO
- 回归测试套件建立
- 集成测试：Orchestrator → Planning → Execution → Evaluation 完整流程测试

---

## Pipeline 执行规则（每个模块复用）

```
主 Agent（你）
  │
  ├─ R1: 启动 Context Agent
  │    输入: 该模块对应的 spec/ playbook/ evaluation/ progress/ 文件路径
  │    输出: 结构化上下文摘要（spec要点/现有代码/实现状态/差异标注）
  │    审查: 是否覆盖全部 spec 要求？是否有 blocking 级差异？
  │
  ├─ R2: 启动 Plan Agent
  │    输入: Context Agent 的输出
  │    输出: 实现方案 + 原子任务 DAG + 验收标准（引用 spec + rubric）
  │    审查: spec_coverage_check = 100%？接口定义是否先于实现？
  │
  ├─ R3: 启动 Code Agent
  │    输入: Plan 的任务分配
  │    输出: 代码文件（接口优先 → 核心逻辑 → 边界处理）
  │    审查: 接口签名与 spec 一致？所有外部调用有超时设置？
  │
  ├─ R4: 启动 Test Agent
  │    输入: Code Agent 的代码 + evaluation/test_scenarios.md
  │    输出: 单元测试 + 集成测试，覆盖率 ≥ 70%
  │    审查: 是否覆盖对应 test_scenarios？覆盖率达标？
  │
  └─ R5: 启动 Evaluation Agent (Mode A)
       输入: 代码 + 测试
       输出: code_quality_report（按 code_quality_rubric.md 评分）
       审查: composite ≥ 80 (PASS) / < 60 (REJECT) / 60-79 (退回修订)
       FAIL → 退回 Code/Test Agent，最多 3 轮
       PASS → 更新 progress/<module>.md，commit
```

---

## 关键约束

### 契约优先
- 每个模块必须先读 spec，接口签名必须 100% 对齐
- `spec/agent_contract.md` 是所有消息的单一事实来源
- playbook 是 SOP，不可偏离

### 质量门
- Gate 0: 必填项完整（目的地/日期/预算/人数）
- Gate 1: blocking_issues == 0
- Gate 2: composite ≥ 80 PASS，< 60 REJECT，≥3维度 < 3 → blocking
- Gate 3: 格式合规 + 完整性 100%

### Commit 格式
```
[module] type: 描述
```
module: core/models/tools/orch/plan/exec/eval/test/meta
type: feat/fix/refactor/test/docs/chore

### 进度回写
- 每完成一个模块 → 更新 `progress/<module>.md`（同步状态 + 任务历史 + spec commit）
- 更新 `progress/README.md` 阶段状态

---

## 遗漏待修（在铺开过程中按需修复）

| 类别 | 问题 | 应修复时机 |
|------|------|-----------|
| playbooks | 未显式引用 error_codes（可追溯性缺口） | 编写对应 Agent 时 |
| evaluator spec | evaluator response types 仅引用式定义 | 实现 evaluation_agent 时 |
| code_agent §6 | 安全覆盖过窄（缺injection/error泄漏/CVE） | 编码横切关注点 |
| code_agent §6 | 自评项不映射 rubric 维度 | 评估体系修正 |
| 评分粒度 | 三文件判断区间粒度不统一（6 vs 3 vs 2级） | 评估体系修正 |
| test_scenarios | 13个基础设施接口无场景覆盖 | Phase 4 集成测试 |
| test_scenarios | Mode A（代码质量）不在测试场景中 | Phase 4 集成测试 |

---

## 关键文件速查

| 类别 | 文件 | 用途 |
|------|------|------|
| 总览 | `CLAUDE.md` | 项目架构/Pipeline规则/质量门/commit规范 |
| 版本 | `VERSION` | `1.0.0-dev` |
| 路线图 | `ROADMAP.md` | v1.0.0 范围定义+交付物清单 |
| 交结 | `progress/handoff.md` | 本文档 — 当前状态+下一步 |
| 进度 | `progress/README.md` | 阶段总览+模块索引+变更日志 |
| 进度 | `progress/orchestrator.md` | Orchestrator 同步状态 |
| 进度 | `progress/planning.md` | Planning Agent 同步状态 |
| 进度 | `progress/execution.md` | Execution Agent 同步状态 |
| 进度 | `progress/evaluation.md` | Evaluation Agent 同步状态 |
| Spec | `spec/agent_contract.md` | 消息格式/TaskType/ErrorCode/超时重试 SSOT |
| Spec | `spec/system_spec.md` | 系统架构/状态机/数据模型 |
| Spec | `spec/orchestrator_spec.md` | Orchestrator 接口/路由表/任务分解 |
| Spec | `spec/planner_spec.md` | Planning Agent 接口 |
| Spec | `spec/executor_spec.md` | Execution Agent 接口+工具定义 |
| Spec | `spec/evaluator_spec.md` | Evaluation Agent 接口+Mode A/B/C |
| Playbook | `playbooks/orchestrator_playbook.md` | Orchestrator SOP |
| Playbook | `playbooks/planner_playbook.md` | Planning Agent SOP |
| Playbook | `playbooks/executor_playbook.md` | Execution Agent SOP |
| Playbook | `playbooks/evaluator_playbook.md` | Evaluation Agent SOP |
| DevAgent | `devagents/context_agent.md` | Context Agent 约束 |
| DevAgent | `devagents/plan_agent.md` | Plan Agent 约束 |
| DevAgent | `devagents/code_agent.md` | Code Agent 约束（含§6自检清单） |
| DevAgent | `devagents/test_agent.md` | Test Agent 约束 |
| 评估 | `evaluation/code_quality_rubric.md` | Mode A 代码质量量表（5维度） |
| 评估 | `evaluation/plan_quality_rubric.md` | Mode B 方案质量量表（5维度） |
| 评估 | `evaluation/gate_definitions.md` | Gate 0-3 伪代码+判定逻辑 |
| 评估 | `evaluation/test_scenarios.md` | 41个测试场景 |
| 评估 | `evaluation/contribution_metrics.md` | Mode C 贡献度指标 |
| 评估 | `evaluation/ablation_protocol.md` | LOO 消融实验协议 |
| 代码 | `core/message.py` | 426行 — AgentMessage/TaskType/ErrorCode/BaseAgent |
| 代码 | `core/context.py` | 387行 — ContextStatus/SharedContext/LogEntry |
| 代码 | `core/gate_runner.py` | 586行 — GateRunner/GateResult |
| 代码 | `core/orchestration_engine.py` | 528行 — TaskDAG/AgentRouter/RetryManager |
| 代码 | `agents/orchestrator.py` | 333行 — Orchestrator 主控 |
| 代码 | `agents/planning_agent.py` | 134行 — Planning Agent |
| 代码 | `agents/execution_agent.py` | 234行 — Execution Agent |
| 代码 | `agents/evaluation_agent.py` | 284行 — Evaluation Agent |
