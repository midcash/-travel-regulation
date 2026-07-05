# System Specification — 旅游规划编排系统

---

## 1. 系统概述

### 1.1 系统定位
TravelPlan Orchestrator 是一个基于多 Agent 协作的旅游规划编排系统。系统采用一主多从的 Hybrid Orchestrator-Specialist 架构，通过 Planning、Execution、Evaluation 三个专业 Agent 的协作，将用户的自然语言旅游需求转化为经过质量验证的完整旅行方案。

### 1.2 核心目标
- **自动化**: 从需求到方案全流程自动化，减少人工干预
- **高质量**: 通过三层评估体系和质量门系统保障产出质量
- **可观测**: 每个 Agent 的贡献度可量化、可追溯、可优化
- **可扩展**: Agent 可插拔，新增专业 Agent 不影响现有系统

### 1.3 技术约束
- 开发语言: Python 3.10+
- 通信协议: JSON 消息 + 同步请求-响应
- 超时策略: 30s 默认超时, 最多 3 次重试
- 迭代上限: Planning → Execution → Evaluation 闭环最多 3 轮

---

## 2. 系统架构

### 2.1 架构图

```
                        ┌─────────────────┐
                        │   用户输入 (NL)   │
                        └────────┬────────┘
                                 │
                        ┌────────▼────────┐
                        │   Gate 0: 输入校验 │
                        └────────┬────────┘
                                 │
                        ┌────────▼────────┐
                        │   Orchestrator   │
                        │   (主 Agent)      │
                        │   任务分解·路由   │
                        └──┬───┬───┬──────┘
                           │   │   │
              ┌────────────┘   │   └────────────┐
              ▼                ▼                ▼
        ┌──────────┐   ┌──────────┐   ┌──────────────┐
        │ Planning │   │Execution │   │  Evaluation   │
        │  Agent   │   │  Agent   │   │    Agent      │
        │ 行程规划  │   │ 可行性验证│   │  三层质量评估  │
        └────┬─────┘   └────┬─────┘   └──────┬───────┘
             │               │                │
             └───────────────┼────────────────┘
                             │
                    ┌────────▼────────┐
                    │  Shared Context │
                    │  (黑板模式)      │
                    └────────┬────────┘
                             │
                    ┌────────▼────────┐
                    │  Gate 1,2,3     │
                    │  质量门系统      │
                    └────────┬────────┘
                             │
                    ┌────────▼────────┐
                    │ 最终旅行方案输出  │
                    └─────────────────┘
```

### 2.2 核心模块

| 模块 | 路径 | 职责 |
|------|------|------|
| Agent 层 | `agents/` | Orchestrator + Planning + Execution + Evaluation |
| Playbook 层 | `playbooks/` | 每个 Agent 的操作手册 (System Prompt + SOP) |
| Spec 层 | `spec/` | 系统规格和各模块规格 |
| Evaluation 层 | `evaluation/` | 质量准则、质量门、消融实验协议 |
| Core 层 | `core/` | 消息协议、共享上下文、编排引擎、质量门执行器 |
| Models 层 | `models/` | 数据模型 (TravelPlan, Constraints, AgentMessage) |
| Tools 层 | `tools/` | Agent 可调用的工具集 |

### 2.3 数据流

```
User Request
  → Orchestrator.parse() → StructuredRequest
  → Orchestrator.decompose() → TaskQueue (DAG)
  → Planning Agent → TravelPlanDraft
  → Execution Agent → ValidationReport
  → Evaluation Agent (Mode B) → PlanQualityReport
  → [if score < 80] → Planning Agent (revise) → ... (max 3 rounds)
  → Orchestrator.assemble() → FinalTravelPlan
  → Gate 3 → Output
```

---

## 3. 质量保障体系

### 3.1 质量门

| Gate | 触发时机 | 输入 | 通过条件 | 失败处理 |
|------|---------|------|---------|---------|
| Gate 0 | 用户输入解析后 | StructuredRequest | 必填项完整 + 预算 > 0 + 日期合理 | 追问用户 / 拒绝 |
| Gate 1 | Execution 校验后 | ValidationReport | 0 blocking_issues | 回退 Planning 修订 |
| Gate 2 | Evaluation 评估后 | PlanQualityReport | composite_score ≥ 80 | 最多 3 轮迭代修订 |
| Gate 3 | 最终输出前 | FinalTravelPlan | 格式合规 + 完整性 100% | 自动补全 / 标注缺失 |

### 3.2 评估体系 (三层)

| 层级 | 名称 | 评估对象 | 评估方法 | 触发时机 |
|------|------|---------|---------|---------|
| Layer 1 | 代码质量评估 | Agent 代码 | 5 维度评分量表 (1-5) | 开发期·每次代码提交 |
| Layer 2 | 业务产出评估 | 旅行规划方案 | 5 维度加权评分 (0-100) | 运行时·每次方案生成 |
| Layer 3 | Agent 贡献度评估 | Agent 边际贡献 | LOO 消融 + 360° + 协同分析 | 批次任务后·定期回归 |

---

## 4. 通信协议

### 4.1 消息格式

所有 Agent 间通信必须遵循以下标准格式:

```json
{
  "message_id": "uuid v4",
  "sender": "orchestrator | planning_agent | execution_agent | evaluation_agent",
  "receiver": "orchestrator | planning_agent | execution_agent | evaluation_agent",
  "task_type": "task.* | response.* | control.*",
  "payload": {},
  "timestamp": "ISO 8601",
  "correlation_id": "uuid (optional, for request-response pairing)"
}
```

### 4.2 消息类型枚举

**任务消息 (task.*)**:
- `task.create_itinerary`: Orchestrator → Planning Agent
- `task.validate_feasibility`: Orchestrator → Execution Agent
- `task.evaluate_plan`: Orchestrator → Evaluation Agent (Mode B)
- `task.evaluate_code`: Orchestrator → Evaluation Agent (Mode A)
- `task.evaluate_contribution`: Orchestrator → Evaluation Agent (Mode C)
- `task.revise_itinerary`: Orchestrator → Planning Agent

**响应消息 (response.*)**:
- `response.itinerary_draft`: Planning Agent → Orchestrator
- `response.validation_report`: Execution Agent → Orchestrator
- `response.plan_quality_report`: Evaluation Agent → Orchestrator (Mode B)
- `response.code_quality_report`: Evaluation Agent → Orchestrator (Mode A)
- `response.contribution_report`: Evaluation Agent → Orchestrator (Mode C)
- `response.error`: Any Agent → Orchestrator

**控制消息 (control.*)**:
- `control.abort`: Orchestrator → All Agents (取消当前任务)
- `control.status_query`: Orchestrator → Any Agent (状态查询)
- `control.status_report`: Any Agent → Orchestrator (状态报告)

### 4.3 通信约束
- 通信拓扑: 星型 (所有子 agent 只与 Orchestrator 通信，不直接互连)
- 通信模式: 同步请求-响应
- 超时: 30 秒
- 重试: 最多 3 次，间隔 1s / 2s / 4s (指数退避)
- 消息大小限制: 单条 ≤ 1MB

---

## 5. 共享上下文 (Shared Context)

### 5.1 黑板模式

Shared Context 是 Agent 间共享状态的中心存储，采用黑板模式:

```
SharedContext
├── request: StructuredRequest        # 用户需求（不可变）
├── task_queue: TaskQueue             # 当前任务队列
├── current_draft: TravelPlanDraft    # 当前行程草稿
├── validation_report: ValidationReport # 最近校验报告
├── quality_report: PlanQualityReport   # 最近质量评估
├── iteration_count: int              # 当前迭代轮次
├── status: Enum                      # 整体状态
└── logs: List[LogEntry]              # 操作日志
```

### 5.2 状态机

```
IDLE → GATE_0 → DECOMPOSING → PLANNING → EXECUTING → GATE_1
                                                         │
                                                    ┌────┘
                                                    ▼
                                              EVALUATING
                                                    │
                                               ┌────┴────┐
                                               ▼         ▼
                                          GATE_2:PASS  GATE_2:FAIL
                                               │         │
                                               ▼         ▼
                                          ASSEMBLING  REVISING (max 3x)
                                               │         │
                                               ▼         └→ PLANNING
                                          GATE_3
                                               │
                                               ▼
                                          COMPLETED
```

---

## 6. 非功能性需求

### 6.1 性能
- 单次旅行方案生成: ≤ 60 秒 (不含人工交互等待)
- Agent 间单次通信延迟: ≤ 5 秒
- 并发支持: 至少 3 个用户请求并行处理

### 6.2 可靠性
- Agent 故障隔离: 单个 Agent 异常不影响其他 Agent
- 优雅降级: 某 Agent 不可用时降级输出 + 标注
- 状态持久化: Shared Context 支持序列化/恢复

### 6.3 可扩展性
- 新增 Agent: 只需注册到 Registry + 编写 Playbook + 实现 BaseAgent 接口
- 新增工具: Tools 目录独立，Agent 按需加载
- 新增评估维度: Evaluation Agent 支持评估维度的插件式扩展

### 6.4 可观测性
- 全链路日志: 每次 Agent 调用的输入/输出/耗时
- 质量趋势: 历史评估得分的时序追踪
- 贡献度趋势: Agent 贡献度随时间的变化追踪
- 异常告警: 贡献度下降 >10% 或质量得分连续下降 >3 次

---

## 7. 版本兼容性

| 版本 | 日期 | 变更内容 |
|------|------|---------|
| 1.0.0 | 2026-07-05 | 初始版本，包含完整的架构规格 |

---

## 附录: 术语表

| 术语 | 定义 |
|------|------|
| Orchestrator | 主控 Agent，负责任务分解、路由和结果整合 |
| Planning Agent | 行程规划 Agent，负责生成旅行行程草稿 |
| Execution Agent | 可行性验证 Agent，负责校验价格、时间、地理逻辑 |
| Evaluation Agent | 质量评估 Agent，负责三层评估（代码/方案/贡献度） |
| Shared Context | Agent 间共享状态的中央存储（黑板模式） |
| Quality Gate | 流程关键节点的质量检查关卡 |
| Gate 0-3 | 输入校验 / 可行性检查 / 质量评审 / 最终校验 |
| LOO | Leave-One-Out，逐一移除 Agent 的消融实验方法 |
| 360° Assessment | 自我-同行-上级三角评估 |
| CoQ | Cost-of-Quality，单位质量得分的资源成本 |
| Blocking Issue | 阻断性问题，必须解决才能通过质量门 |
| Soft Constraint | 软约束，偏好型条件，不满足时扣分但不阻断 |
| Hard Constraint | 硬约束，必须满足的条件，违反则阻断 |
