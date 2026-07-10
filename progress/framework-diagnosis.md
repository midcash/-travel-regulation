# Development Framework Diagnosis — 为什么规格完整却产生了架构问题

> 诊断日期: 2026-07-10 | 诊断范围: 项目全部 53 个 .md 文件

---

## 一、核心结论

**开发框架本身没有根本性缺陷，但存在一个致命盲区：它能保证"代码严格符合 spec"，但不能保证"spec 本身的架构是合理的"。**

你的框架像一个高精度的 GPS —— 它能确保你精确到达目的地，但目的地是你在 spec 里自己设定的。如果 spec 写的是"硬编码流水线"，框架会忠实地帮你实现一个完美的硬编码流水线。

---

## 二、问题溯源：三层同构的线性思维

项目存在一个三层递归的线性结构，每一层都强化了下一层：

```
Layer 1: 开发流程 (CLAUDE.md 5-round protocol)
    Context → Plan → Code → Test → Evaluate  (严格顺序，不可跳过)
        ↓ 塑造了
Layer 2: Spec/Playbook 设计
    Orchestrator → Planning → Execution → Evaluation  (固定流水线)
        ↓ 塑造了
Layer 3: 代码实现
    _run_planning_cycle(): Planning → Execution → Evaluation → 修订循环
```

**这不是巧合——这是设计方法论的结构性传递。** 你用线性流程设计系统，自然会设计出线性系统。

### 2.1 Layer 1 → Layer 2 的传递机制

`devagents/plan_agent.md` 的规则明确要求：

> "Implementation plan must be 100% aligned with spec — must not add features not present in spec."
> "spec_coverage_check < 100% causes plan rejection."

Plan Agent **被禁止**设计 spec 之外的架构。如果 spec 里写的是固定路由表，Plan Agent 不能提出动态路由方案。

`devagents/code_agent.md` 更进一步：

> "Must not modify interface contracts defined in spec."
> "If you find spec or plan issues, do not modify the spec yourself. Record the issue and report to Plan Agent."

Code Agent 即使发现了架构问题也**被禁止修复**。这是框架的"上游阻塞"规则在起作用——Code Agent 只能等待 Plan Agent 的修正指令。

### 2.2 Layer 2 → Layer 3 的传递机制

`playbooks/orchestrator_playbook.md` §3 直接写了硬编码流程：

> Step 3: Route & Execute — Send T1-T3 concurrently to Planning Agent → Send draft to Execution Agent → Send validated draft to Evaluation Agent

这不是"建议"，这是 **SOP（标准操作流程）**。开发 Agent 按 playbook 实现代码，自然产生硬编码的 `_run_planning_cycle()`。

### 2.3 Layer 3 的问题：消息协议设计但未使用

`spec/agent_contract.md` 定义了完整的消息协议：

- `AgentMessage` 数据类 + 11 种 `TaskType`
- `BaseAgent.handle_message()` 抽象方法
- `AgentRegistry` 服务发现
- 超时/重试/版本协商

但 `playbooks/orchestrator_playbook.md` 从未要求 Orchestrator **使用**消息协议。它的 SOP 写的是直接方法调用流程。所以代码忠实地实现了直接方法调用，消息协议只剩测试中使用。

**这不是框架的 bug——这是一个 spec 层面的 gap。** 两份文件说了不同的事：
- `agent_contract.md` 说："Agent 间通信应使用 AgentMessage"
- `orchestrator_playbook.md` 说："Step 3: 调用 Planning Agent 生成草稿，再调用 Execution Agent 验证"

后者没有说"通过 AgentMessage 调用"，Code Agent 自然会选择最直接的实现方式——直接方法调用。

---

## 三、评估框架的"强化效应"

`evaluation/` 下的 17 个 rubric 文件全部**假设了一个固定架构**来评分：

| Rubric | 评估对象 | 隐含假设 |
|--------|---------|---------|
| `plan_quality_rubric.md` | 行程方案质量 | 方案由 Planning→Execution→Evaluation 流水线产出 |
| `reasoning_quality_rubric.md` | 推理链质量 | 推理链是 Planning→SelfCheck→修订 的顺序流程 |
| `protocol_quality_rubric.md` | 消息协议质量 | 状态转换路径是固定的 15 状态状态机 |
| `tool_quality_rubric.md` | 工具质量 | 4 个独立 checker，无动态工具选择 |

**没有任何一个 rubric 评估"编排灵活性"或"路由质量"。**

这意味着：即使你实现了一个 LLM 驱动的动态编排器，评估框架也**无法测量它是否更好**——因为评估框架根本不知道"动态路由"是什么。

更严重的是：`protocol_quality_rubric.md` 的状态转换正确性维度会把"偏离固定状态机"的行为标记为**扣分项**。动态路由在现有框架里会被判定为"状态转换错误"。

---

## 四、进展文件中的预警信号

`progress/lessons.md` 记录了 76+ 个问题，其中多个是框架自身的盲区造成的：

### 信号 1: Wiring 遗漏 (Batch 9)

> "CoTPipeline 核心代码已提交，但 orchestrator.py::_init_agents() 未注入 prompt_builder 和 self_checker，导致 CoT 路径不可达"

**根因**: 5 轮协议的每轮产出是独立的，跨文件的依赖注入（wiring）不在任何一方的 spec 里。框架的"严格顺序"规则让每轮只关注自己的交付物，遗漏了跨轮次的集成点。

### 信号 2: 状态机死角 (Batch 7)

> "stub 版本的 Gate 2 始终返回 PASS...修订循环从未被执行。接入真实 EvaluationAgent 后触发 REVISE → 状态机报 ValueError"

**根因**: Stub 的"快乐路径"设计掩盖了状态机的未测试分支。框架的 R4（Test）本应发现这个问题，但 test_scenarios.md 中的 Gate 2 修订场景是在接入真实 Agent 后才被触发的。

### 信号 3: 消息协议与运行时脱节 (Batch 7, 未明确命名)

progress 文件从未直接说"AgentMessage 定义了但没用"，但记录了症状：

> "dict<->dataclass 转换问题"、"维度嵌套/扁平不匹配"、"状态转换死角"

这些本质上都是因为**代码走了直接方法调用路径**，而 spec 期待的是消息传递路径。桥接层的存在本身就是这个 gap 的证据。

---

## 五、框架是否需要重新设计

### 不需要推翻的部分

| 组件 | 评价 |
|------|------|
| spec/ 三层文档体系 | 结构完整，是项目最大亮点 |
| evaluation/ 评估框架 | Layer 0-3 分层合理，覆盖全面 |
| playbooks/ 操作手册 | SOP 格式规范，可执行性强 |
| devagents/ 开发约束 | 分工清晰，规则明确 |
| 5-Round 协议 | 确保了代码质量和可追溯性 |
| 769 tests + 零回归 | 证明了框架的工程质量纪律 |

### 需要修补的部分

| 问题 | 修补方案 |
|------|---------|
| Spec 强制固定编排 | 在 `orchestrator_spec.md` 中增加 §2.6 "动态编排模式"，定义 LLM 驱动路由的接口和约束 |
| Playbook 强制固定序列 | 在 `orchestrator_playbook.md` 中增加 §3.6 "动态决策模式"，替代/补充固定 SOP |
| 评估框架缺少路由质量维度 | 在 `evaluation/` 中新增 `orchestration_quality_rubric.md`，评估路由决策的正确性和效率 |
| 消息协议定义了但未强制使用 | 在 `agent_contract.md` 中增加约束："运行时通信 MUST 使用 AgentMessage，禁止绕过消息层直接调用" |
| Code Agent 被禁止修复架构问题 | 在 `devagents/code_agent.md` 中增加例外："发现 spec-实现 架构级 gap 时，应在交付代码的同时产出 spec 修订建议" |
| 评估框架惩罚动态行为 | 修改 `protocol_quality_rubric.md` 的状态转换维度，允许"LLM 决策的合法动态路径" |

### 最重要的一个改动

在 `spec/orchestrator_spec.md` 中增加一个章节：

```
## 2.6 动态编排模式 (v1.3.0+)

当 `dynamic_orchestration = true` 时，Orchestrator 使用 LLM 驱动的动态决策循环
替代固定序列。LLM 在每步根据 SharedContext 摘要决定调用哪个 Agent。

### 动态决策接口
- _decide_next_step(context_summary) -> Decision
- Decision.action ∈ {CALL_PLANNING, CALL_EXECUTION, CALL_EVALUATION, 
                      CALL_REVISION, RUN_GATE_2, ASSEMBLE, STOP}

### 安全约束 (硬编码，不可被 LLM 覆盖)
1. score < 60 → 必定 REJECT
2. iteration >= 3 → 必定 DEGRADE
3. 不允许 CALL_EXECUTION 在 CALL_PLANNING 之前

### 与固定模式的兼容性
- dynamic_orchestration = false 或 LLM 不可用时 → 回退到 §2.2-2.5 的固定序列
- 外部接口 (process_request) 无变化
```

**这一个 spec 改动会触发框架的涟漪传播机制**（spec → playbooks → evaluation → devagents），让整个框架自我修正。这正是你设计的"文档-代码同步规则"应该发挥的作用。

---

## 六、总结

**你的框架没有错，它是被设计得过于"成功"了。** 它完美地保证了代码符合 spec，但 spec 本身有一个盲区（假定架构是静态的），而框架没有任何机制来检测 spec 层面的问题。

类比：你造了一台能完美执行图纸的 CNC 机床，但图纸上画的是一个方轮子。机床没错，图纸需要更新。

修复路径不是推翻框架，而是在框架中增加一个反馈回路：**让 spec 本身也接受评估**。这正是你的 `evaluation/meta_rubric.md`（Layer 0 元评估）的设计意图——评估"尺子"的质量。但目前 meta_rubric 只检查锚点、覆盖、公式一致性，不检查"架构假设是否合理"。扩展 meta_rubric 的评估维度是这个反馈回路的关键。
