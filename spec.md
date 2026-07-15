# Agent Workflow Platform — 架构规格

## 一、项目定位

> 一个轻量级的 **Agent Workflow Platform**，旅游规划是其第一个示例 Workflow。

---

## 二、Travel Workflow 执行流程

```text
                    User Input
                        │
                        ▼
              ┌───────────────────┐
              │     Gateway       │
              │  validate / auth  │
              └───────────────────┘
                        │
                        ▼
              ┌──────────────────────┐
              │  Requirement Analyzer │
              │  意图识别 / 信息完整性  │
              └──────────────────────┘
                        │
              ┌─ 信息完整? ─┐
              │             │
            Missing       Complete
              │             │
              ▼             │
    ┌─ Clarification ─┐    │
    │  追问用户补全     │    │
    └─────────────────┘    │
              │             │
              └───→ 回到 Analyzer
                            │
                            ▼
              ┌─────────────────────────────┐
              │      Workflow Engine        │
              │     (State Machine)         │
              │                             │
              │  Planner Agent              │
              │       │                     │
              │       ▼                     │
              │  Knowledge Agent            │
              │       │                     │
              │       ▼                     │
              │  Planner Refinement         │
              │       │                     │
              │       ▼                     │
              │  Reviewer Agent             │
              │       │                     │
              │  ┌─ score ≥ 70? ─┐          │
              │  │               │          │
              │ YES              NO         │
              │  │               │          │
              │  ▼               ▼          │
              │ Output     Retry Router     │
              │ Formatter  (按失败类型路由)   │
              │            │                │
              │            ├─ 可行性失败 ──→ Knowledge
              │            ├─ 体验失败   ──→ Planner Refinement
              │            └─ 完整性失败 ──→ Planner
              │            │
              │            ▼
              │         Retry Exhausted ──→ Human Review  or  Safe Output
              └─────────────────────────────┘
                        │
                        ▼
                Evaluation Record



┌──────────────────────────────────────────────────────────────────────┐
│              基础设施层（所有 Agent 共享）                               │
│                                                                      │
│   State Store                     Tool Registry    Memory Center     │
│   (只能被Workflow Engine修改)       (工具注册/发现)   (Session/User)     │
│                                                                      │
│   Config Center                                                      │
│   (模型/Prompt/Workflow/Tool 全局配置)                                 │
└──────────────────────────────────────────────────────────────────────┘


━━━━━━━━━━━━━━━━━━━━━━━━━ Observability Trace ━━━━━━━━━━━━━━━━━━━━━━━━━
        (全流程贯穿：Gateway → Analyzer → Workflow → Output → Evaluation)
```

---

## 三、关键设计决策

### 3.1 Agent 串行执行，不并行
- Planner → Knowledge → Planner Refinement → Reviewer，依赖明确、可追溯
- 每个 Agent 只依赖上一个 Agent 的 State 输出

### 3.2 差异化重试路由（不全部回 Planner）
- **可行性失败**（价格/时间/地理不合理）→ 回 Knowledge Agent 重新查询
- **体验失败**（节奏/多样性/个性化不足）→ 回 Planner Refinement 调整
- **完整性失败**（字段缺失/格式错误）→ 回 Planner Agent 重新生成
- 最大重试 3 次，每次路由可能不同

### 3.3 State Store 是全局基础设施
- 所有 Agent 通过 State Store 读写状态，不通过参数传递
- Agent 统一接口：`run(context: AgentContext) → AgentResult`，内部从 State Store 读、向 State Store 写
- 支持 Checkpoint（状态快照），便于断点恢复和回溯

### 3.4 Observability 全流程贯穿
- 不是单独的层，而是横切关注点
- 每个节点（Gateway / Analyzer / 每个 Agent / Output）自动记录：
  - 输入 State 快照
  - 输出 State 快照
  - 耗时
  - 是否重试
- 预留 OpenTelemetry / LangSmith / Phoenix 集成点

### 3.5 Agent 互不调用
- 所有 Agent 由 Workflow Engine 调度
- 降低耦合，新增 Agent 无需修改现有 Agent 代码

### 3.6 先手写后框架
- 先手写状态机和 State Store 理解原理
- 再评估是否引入 LangGraph

---

## 四、平台分层映射

| 层 | 组件 | 说明 |
|----|------|------|
| Gateway | validate / auth / rate limit | 所有输入入口 |
| Pre-processing | Requirement Analyzer + Clarification Agent | 信息完整性检查和追问 |
| Workflow Engine | State Machine + Retry Router | Agent 调度和失败路由 |
| Agent Runtime | Planner / Knowledge / Reviewer | 业务 Agent |
| Output | Output Formatter | 多格式输出 |
| Evaluation | Evaluation Record | 评分持久化和统计分析 |
| Infrastructure | State Store / Tool Registry / Memory / Config | 全局共享 |
| Observability | Trace（横切） | 全流程贯穿 |

---

