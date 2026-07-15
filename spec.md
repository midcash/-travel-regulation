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
              └─────────────────────────────┘
                        │
                        ▼
                Evaluation Record


┌──────────────────────────────────────────────────────┐
│              基础设施层（所有 Agent 共享）             │
│                                                      │
│   State Store     Tool Registry    Memory Center     │
│   (全局状态)       (工具注册/发现)   (Session/User)    │
│                                                      │
│   Config Center                                     │
│   (模型/Prompt/Workflow/Tool 全局配置)                │
└──────────────────────────────────────────────────────┘


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
- Agent 统一接口：`run() → None`，内部从 State Store 读、向 State Store 写
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

## 五、State Store 设计要点

```text
State Store
├── session_id       → 会话标识
├── user_input       → 用户原始需求
├── analyzed_req     → Requirement Analyzer 输出（意图 + 信息缺口）
├── plan             → Planner 生成的行程草案
├── knowledge_data   → Knowledge Agent 查询的真实数据
├── refined_plan     → Planner Refinement 修正后的方案
├── review_result    → Reviewer 评分和问题列表
├── retry_count      → 当前重试次数（max 3）
├── retry_history    → 每次重试的原因和路由目标
└── checkpoints[]    → 关键节点的状态快照
```

---

## 六、Retry Router 失败分类与路由表

| 失败类型 | 判断依据 | 路由目标 | 说明 |
|----------|---------|---------|------|
| 可行性失败 | 价格偏差 >20% / 时间冲突 / 地理不合理 | Knowledge Agent | 需要重新查询真实数据 |
| 体验失败 | 活动类型 <3 种 / 节奏不合理 / 个性化不足 | Planner Refinement | 需调整行程结构但不需重查数据 |
| 完整性失败 | 字段缺失 / 格式错误 / JSON 解析失败 | Planner Agent | 需重新生成行程 |
| 综合失败 | 多项不达标 | Planner Agent | 从头重来 |

---

## 七、迭代路线图

### Phase 1: State Store + Workflow Engine（当前）
- 实现 State Store（dataclass + 字典存储）
- 实现确定性 Workflow Engine（替代 LLM 路由决策）
- Agent 迁移到新接口

### Phase 2: Tool Registry + Retry Router
- 抽离 Tool Registry，Knowledge Agent 变为 Tool Router
- 实现差异化重试路由

### Phase 3: Requirement Analyzer + Clarification + Observability
- 增加需求分析节点
- 信息不完整时触发追问
- 结构化 Trace 记录

### Phase 4: Output Formatter + Evaluation
- Formatter 多格式输出
- 持久化评审记录
- eval_stats 统计分析

### Phase 5: Memory + Configuration + Gateway
- Session Memory 实现
- 全局配置中心
- FastAPI Gateway 包装
