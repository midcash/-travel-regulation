# Handoff — v1.0.0 全面铺开

## 当前状态

- **版本**: `1.0.0-dev`
- **分支**: `main`（与 `origin/main` 同步）
- **已完成**: 试点编码 `core/message.py` + `core/context.py`，Pipeline R1-R5 全部通过（96% 覆盖率，131 tests）

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

### 试点编码（core/）
| 文件 | 行数 | 功能 |
|------|------|------|
| `core/message.py` | 426 | AgentMessage / TaskType / ErrorCode / AgentIdentity / BaseAgent / AgentRegistry |
| `core/context.py` | 387 | ContextStatus(15状态) / LogEntry / SharedContext / to_dict / from_dict |
| `core/__init__.py` | — | 完整公共 API 导出 |
| `tests/test_message.py` | — | 80+ tests |
| `tests/test_context.py` | — | 50+ tests |
| `tests/conftest.py` | — | pytest fixtures |

### 现存代码文件
```
core/
  message.py  ← 已完成
  context.py  ← 已完成
  __init__.py ← 已完成
models/       ← 空（只有 .gitkeep）
tools/        ← 空（只有 .gitkeep）
agents/       ← 空（只有 .gitkeep）
tests/
  test_message.py  ← 已完成
  test_context.py  ← 已完成
  conftest.py      ← 已完成
  __init__.py      ← 已完成
```

---

## 下一步：v1.0.0 全面铺开

### Batch 1: 并行（3 个 Pipeline，无相互依赖）

#### 1A. `core/` 剩余 — gate_runner.py + orchestration_engine.py（P0）
- **spec**: `spec/system_spec.md`, `spec/orchestrator_spec.md`, `evaluation/gate_definitions.md`
- **依赖**: core/message.py, core/context.py（已完成）
- **产出**: GateRunner 类 + orchestration_engine.py（任务分解/路由/整合）
- **Pipeline**: Context → Plan → Code → Test → Evaluate(Mode A)

#### 1B. `models/` 全部（P0）
- **spec**: `spec/system_spec.md` §2（Models 层定义）, `spec/agent_contract.md` §3.1（AgentMessage 数据模型）, 各 Agent spec 中的数据结构定义
- **依赖**: 无代码依赖
- **产出**: TripPlan / Budget / ItineraryDay / Constraint / UserPreferences / TravelPlanDraft / ValidationReport / PlanQualityReport / FinalTravelPlan 等数据模型
- **Pipeline**: Context → Plan → Code → Test → Evaluate(Mode A)

#### 1C. `tools/` 全部（P1）
- **spec**: `spec/executor_spec.md` §2（功能规格，check_prices/check_time/check_geography 定义）, §3（接口规格）
- **依赖**: models/（逻辑依赖，可先用 dataclass stub）
- **产出**: check_prices() / check_time() / check_geography() / check_budget_compliance() 等 stub 实现
- **注意**: v1.0.0 用 stub/mock，不接真实 API
- **Pipeline**: Context → Plan → Code → Test → Evaluate(Mode A)

### Batch 2: 串行（按依赖链：Orchestrator → Planning → Execution → Evaluation）

#### 2A. `agents/orchestrator.py`（P0）
- **spec**: `spec/orchestrator_spec.md`, `spec/system_spec.md`
- **参考**: `playbooks/orchestrator_playbook.md`
- **依赖**: core/ 全部 + models/ 全部
- **产出**: Orchestrator 主控（parse_request / decompose_task / route_task / assemble_plan / Gate 0 + Gate 3）
- **Pipeline**: Context → Plan → Code → Test → Evaluate(Mode A)

#### 2B. `agents/planning_agent.py`（P1）
- **spec**: `spec/planner_spec.md`
- **参考**: `playbooks/planner_playbook.md`
- **依赖**: core/ + models/ + tools/
- **产出**: Planning Agent（create_itinerary / revise_itinerary / 目的地研究 / 预算分配）
- **Pipeline**: Context → Plan → Code → Test → Evaluate(Mode A)

#### 2C. `agents/execution_agent.py`（P1）
- **spec**: `spec/executor_spec.md`
- **参考**: `playbooks/executor_playbook.md`
- **依赖**: core/ + models/ + tools/
- **产出**: Execution Agent（validate_feasibility / check_prices / check_time / check_geography / Gate 1）
- **Pipeline**: Context → Plan → Code → Test → Evaluate(Mode A)

#### 2D. `agents/evaluation_agent.py`（P1）
- **spec**: `spec/evaluator_spec.md`
- **参考**: `playbooks/evaluator_playbook.md`
- **依赖**: core/ + models/
- **产出**: Evaluation Agent（Mode A 代码质量 / Mode B 方案质量 / Mode C 贡献度评估 / Gate 2）
- **Pipeline**: Context → Plan → Code → Test → Evaluate(Mode A)

### Batch 3: 集成测试 + 消融实验（Phase 4）
- 端到端测试：按 `evaluation/test_scenarios.md` 41 个场景全量覆盖
- 消融实验：按 `evaluation/ablation_protocol.md` 执行 LOO
- 回归测试套件建立

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

以下为第二轮约束推演中未修复的重要级/优化级问题，在对应模块实现时自然修复：

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
| 进度 | `progress/README.md` | 阶段总览+模块索引 |
| 进度 | `progress/core.md` | core/ 模块同步状态 |
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
| 现有代码 | `core/message.py` | 426行 AgentMessage/TaskType/ErrorCode/BaseAgent |
| 现有代码 | `core/context.py` | 387行 ContextStatus/SharedContext/LogEntry |
