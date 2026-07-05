# CLAUDE.md — Travel Planning Multi-Agent Orchestration Harness

## Project Identity

**项目名称**: TravelPlan Orchestrator (旅游规划编排系统)
**架构模式**: Hybrid Orchestrator-Specialist (一主多从)
**开发方法论**: Spec-Driven + Evaluation-Driven + Harness Development

## Architecture Overview

项目采用 **双层 Agent 架构**:

### Layer 1: 开发 Agent (Dev Agents) — Harness 五层映射

```
┌─────────────────────────────────────────────┐
│  Harness 层        开发 Agent       约束文件  │
├─────────────────────────────────────────────┤
│  记忆层 (Memory)   Context Agent    ← devagents/context_agent.md
│  编排层 (Orch.)    Plan Agent       ← devagents/plan_agent.md
│  执行层 (Exec.)    Code Agent       ← devagents/code_agent.md
│  测试层 (Test)     Test Agent       ← devagents/test_agent.md
│  反馈层 (Feedback) Evaluation Agent ← evaluation/code_quality_rubric.md
└─────────────────────────────────────────────┘
```

### Layer 2: 业务 Agent (Business Agents) — 旅游规划编排

```
User Request → Orchestrator (主Agent)
                   ├─→ Planning Agent   (行程规划)
                   ├─→ Execution Agent  (可行性验证)
                   └─→ Evaluation Agent (三层评估: 业务产出+贡献度)
                           ↓
                   Shared Context (黑板模式)
                           ↓
                   Quality Gates (0→1→2→3)
                           ↓
                   Final Travel Plan Output
```

## Agent Inventory

### 开发 Agent (负责构建系统)

| Agent | 文件路径 | 角色 | Harness层 |
|-------|---------|------|-----------|
| Context Agent | `devagents/context_agent.md` | 项目状态理解·上下文摘要 | 记忆层 |
| Plan Agent | `devagents/plan_agent.md` | 实现方案设计·任务分解 | 编排层 |
| Code Agent | `devagents/code_agent.md` | 代码编写·spec实现 | 执行层 |
| Test Agent | `devagents/test_agent.md` | 测试编写·质量验证 | 测试层 |
| Evaluation Agent | `agents/evaluation_agent.py` | 代码评估(Mode A)·质量门 | 反馈层 |

### 业务 Agent (旅游规划系统本身)

| Agent | 文件路径 | 角色 | 优先级 |
|-------|---------|------|--------|
| Orchestrator | `agents/orchestrator.py` | 任务分解·路由·整合 | P0 |
| Planning Agent | `agents/planning_agent.py` | 行程规划·目的地研究 | P1 |
| Execution Agent | `agents/execution_agent.py` | 可行性验证·成本估算 | P1 |
| Evaluation Agent | `agents/evaluation_agent.py` | 业务产出评估(Mode B)·贡献度评估(Mode C) | P1 |

## Development Workflow (5-Round Protocol + Dev Agent Pipeline)

### 开发 Agent 流水线 (每次编码任务的标准流程)

```
Context Agent → Plan Agent → Code Agent → Test Agent → Evaluation Agent(Mode A)
  (记忆层)       (编排层)      (执行层)      (测试层)        (反馈层)
     │               │             │             │              │
     └─ 上下文摘要 ─→ └─ 实现方案 ─→ └─ 代码产出 ─→ └─ 测试代码 ─→ └─ 质量评估
                                                                      │
                                                           ┌─ PASS → 交付
                                                           └─ FAIL → 退回Code/Test Agent
```

### R1: Context (记忆层·Context Agent)
- Context Agent 扫描 `spec/`、`playbooks/`、`evaluation/`、现有代码
- 输出结构化上下文摘要（项目结构、spec要点、实现状态）
- 标注 spec 中的矛盾/模糊/缺失

### R2: Plan (编排层·Plan Agent)
- Plan Agent 对照 spec 设计实现方案
- 分解为原子编码任务（含依赖关系 DAG）
- 为每个任务定义验收标准（引用 spec + rubric）
- 确保 spec_coverage_check = 100%

### R3: Execute (执行层·Code Agent)
- Code Agent 按 Plan 的分配编写代码
- 严格遵循 spec 接口契约和 playbook 约束
- 接口优先 → 核心逻辑 → 边界处理 → 自检交付
- 代码交付给 Evaluation Agent (Mode A) 独立评估

### R4: Test (测试层·Test Agent)
- Test Agent 对照 `test_scenarios.md` 编写测试
- 覆盖单元测试 + 集成测试 + 质量门测试
- 保证代码覆盖率 ≥ 70%
- 发现的 bug 记录上报但不自行修复

### R5: Verify (反馈层·Evaluation Agent)
- Evaluation Agent (Mode A) 评估代码质量 (code_quality_rubric)
- 检查测试覆盖率、场景覆盖度、mutation testing
- 未通过质量门 → 退回对应 Agent → 最多 3 轮迭代
- 通过后代码进入业务 Agent 的集成测试

### 业务 Agent 工作流 (运行时)
- 同原有流程: Orchestrator → Planning → Execution → Evaluation(Mode B/C)
- Quality Gates 0→1→2→3
- 最多 3 轮 Planning → Evaluation 修订闭环

## Quality Gate System

| Gate | 位置 | 阻断级别 | 通过条件 |
|------|------|---------|---------|
| Gate 0 | 用户输入后 | 阻断 | 需求完整性 ≥ 80% |
| Gate 1 | 执行验证后 | 阻断 | 可行性得分 ≥ 70% |
| Gate 2 | 评估反馈后 | 条件阻断 | 综合质量 ≥ 80/100，最多3轮迭代 |
| Gate 3 | 最终输出前 | 阻断 | 格式合规 + 完整性 = 100% |

## Key Design Decisions

1. **通信协议**: 同步请求-响应 + 超时重试（30s 超时，最多3次重试）
2. **约束处理**: 硬约束由 Execution Agent 原子校验；软约束由 Evaluation Agent 评分扣减
3. **迭代上限**: Planning → Execution → Evaluation 反馈闭环最多3轮
4. **消融实验**: LOO 方法（Leave-One-Out），结构性移除而非 LLM 内省判断

## Directory Map

| 目录 | 用途 | 性质 |
|------|------|------|
| `devagents/` | 开发Agent定义 (Context/Plan/Code/Test) | 开发约束 |
| `agents/` | 业务Agent代码实现 | 代码 |
| `playbooks/` | 业务Agent运行时操作手册 (prompt模板) | 配置 |
| `spec/` | 系统/模块规格 (WHAT) | 规格 |
| `evaluation/` | 评估准则/质量门/消融协议 (HOW TO JUDGE) | 评估 |
| `PROGRESS.md` | 项目进度入口 → 指向 progress/ 各模块碎片 | 元信息 |
| `progress/` | 各模块独立进度碎片 (core/orch/plan/exec/eval/models/tools/tests) | 元信息 |
| `ROADMAP.md` | 版本路线图 (仅在 main 分支维护) | 元信息 |
| `.gitmessage` | Commit message 格式模板 | 配置 |
| `core/` | 框架内核 (消息/上下文/编排引擎) | 基础设施 |
| `models/` | 数据模型定义 | 数据 |
| `tools/` | Agent 可调用工具集 | 工具 |
| `tests/` | 单元测试和集成测试 | 测试 |

## Dev Agent Pipeline Rules

1. **严格顺序**: Context → Plan → Code → Test → Evaluate，不可跳过
2. **上游阻塞**: Context 不完整 → Plan 不得开始；Plan 未完成 → Code 不得开始
3. **独立评估**: Evaluation Agent (Mode A) 独立于 Code/Test Agent，不共享评分预期
4. **契约优先**: Plan 中的接口定义必须先于 Code 中的实现
5. **追溯链**: 每一行代码 → 对应 Plan 中的任务 → 对应 spec 中的要求 → 对应 test_scenarios 中的场景
6. **进度回写**: Code/Test Agent 完成后 → 更新 `progress/<module>.md` 的同步状态和任务历史
7. **差异阻塞**: Context Agent 发现 blocking 级别的 spec-代码差异 → 阻塞下游直到差异解决
8. **碎片隔离**: 每个分支只修改自己负责的 `progress/<module>.md`，不修改其他模块的碎片

## Document-Code Synchronization Rules

**核心原则**: spec 是单一事实来源，progress/ 碎片是同步账本，Context Agent 是差异检测器。

### 规则 1: 规格变更的涟漪传播
修改 `spec/` 中的任何文件后，必须检查并同步:
1. 对应的 `playbooks/` — 操作手册是否仍与 spec 一致
2. 对应的 `evaluation/` — 评估标准是否仍能验证新 spec
3. 对应的 `devagents/` — 开发 Agent 的被约束方式是否受影响

**传播路径**: `spec/` → `playbooks/` → `evaluation/` → `devagents/`

### 规则 2: 评估知识更新的涟漪传播
修改 `evaluation/` 中的评分标准/门禁/指标后，必须检查:
1. `playbooks/evaluator_playbook.md` — 评估者自身的行为规范
2. `spec/evaluator_spec.md` — 评估 Agent 的接口规格
3. `devagents/code_agent.md` §7 — Code Agent 的质量约束
4. `devagents/test_agent.md` §7 — Test Agent 的覆盖率/有效性约束
5. `devagents/plan_agent.md` §7 — Plan Agent 的验收标准约束

### 规则 3: 代码完成后的回写
每次 Code Agent 完成实现任务后:
1. 更新 `progress/<module>.md` 中对应模块的同步状态（`未开始` → `进行中` → `已完成`）
2. 写入 `spec commit` 列（当前 spec 文件的 commit hash）用于后续漂移检测
3. 记录任务历史行
4. 如发现 spec 与实现的偏差，记录到 `progress/README.md` 变更日志

### 规则 4: 流水线启动前的差异检测
每次 Dev Agent Pipeline 启动前:
1. Context Agent 执行增量扫描（`scope: diff_since_last`）
2. 对比 `spec/` 定义 vs `agents/` 实际代码
3. 用 `progress/<module>.md` 的 `spec commit` 列检测漂移: `git diff <spec_commit>..HEAD -- <spec_file>`
4. blocking 级别的差异 → 阻塞下游 Agent

### 规则 5: progress/ 作为同步锚点
- `progress/README.md` 是跨模块的索引（阶段进度 + 变更日志 + 评估影响追踪）
- `progress/<module>.md` 是每个模块的独立进度碎片（互不冲突）
- 任何同步状态变更必须反映到对应的碎片文件
- 不可跳过 progress/ 碎片直接开始编码

## Spec-Driven Development Rules

1. 任何代码实现必须首先对照 `spec/` 中的对应规格文件
2. 接口变更必须同步更新 spec 文件
3. spec 文件是所有 agent 的单一事实来源 (Single Source of Truth)
4. Agent 间通信必须符合 `spec/agent_contract.md` 的消息格式

## Commit Convention

1. Commit message 格式: `[module] type: 描述`（模板见 `.gitmessage`）
2. 每个 commit 应关联对应的 spec 文件（在正文中注明 `spec: spec/xxx.md`）
3. 提交粒度: 一个 commit = 一个逻辑变更单元

## Evaluation-Driven Development Rules

1. 每个 agent 产出必须经过 Evaluation Agent 评估
2. 质量门检查结果记录到评估日志
3. 消融实验在每次重大变更后自动运行
4. 贡献度下降 >10% 触发回归告警
5. 评估结果用于持续优化 agent 的 playbook 和 prompt
