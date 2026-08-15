# M4：动态 Task Graph、Research Agent 与混合规划

## 1. 阶段目标

实现受控 Orchestrator：根据 RouteDecision 和 ConstraintSnapshot 生成显式任务图，按依赖串并行调度 Research Agent，汇总 Evidence/Candidate，并生成结构化的多个可行计划候选。M4 建立“研究 → 候选 → 规划”主链路，不完成 M5 的最终质量裁决。

## 2. 前置条件

- M3 Provider、Evidence Registry、Candidate Pool 契约测试通过；
- M2 Router 能给出 required capabilities；
- 所有外部 I/O 可用异步 Fake；Fake 用于确定性并发/失败注入；
- M3 Live Tool Gate 和 M2 Live LLM Gate 已通过。
- strict 模式下工具失败显式抛错；
- TripState 支持 RESEARCHING、DRAFTING、FAILED。

## 3. 允许修改范围

- `src/application/task_graph.py`、`orchestrator.py`；
- `src/agents/research/`；
- `src/agents/itinerary_composer.py`；
- `src/domain/services/schedule_service.py`、`budget_service.py`；
- application policy、调用预算和相应测试；
- CLI/Facade 接入新的主链路，保留 legacy feature switch 仅用于对照测试，不得自动 fallback。

## 4. 禁止事项

- 不实现 G4 Critic 和完整 G0～G5 GateRunner；
- 不实现局部修复循环；
- 不执行预订、付款、取消；
- 不实现事件订阅与反馈学习；
- 不允许 Agent 直接调用 Agent；
- 不允许 Research Agent 写 Registry/TripState；
- 不使用 `asyncio.gather(..., return_exceptions=True)` 把失败当结果吞掉；
- 不在任务失败后返回正常部分计划；
- 不以 LLM confidence 替代证据完整性检查；
- 不引入 LangGraph，除非另有已批准 ADR。

## 5. Task Graph 模型

至少定义：

```text
TaskSpec
  task_id
  task_type
  capability
  dependencies[]
  input_refs[]
  expected_output_type
  timeout
  tool_call_budget
  model_call_budget
  priority

TaskResult
  task_id
  status
  output_ref
  evidence_refs[]
  candidate_refs[]
  metrics
  error_ref

TaskGraph
  graph_id
  trip_id
  constraint_snapshot_id
  tasks[]
  graph_version
```

约束：

- DAG 创建时检测环；
- task_id 稳定且唯一；
- dependency 必须存在；
- 输入只使用 ID/ref，不嵌入全量对象；
- TaskSpec 创建后不可变；
- 运行态与定义态分离；
- 图版本与 ConstraintSnapshot 绑定；
- Snapshot 更新后旧图不能继续提交结果。

## 6. Task Graph Builder

输入：RouteDecision、ConstraintSnapshot、当前计划引用（REFINE/COMPARE 时）。

输出：受 allowlist 约束的 TaskGraph。

规则：

- required capabilities 映射为有限任务模板；
- 地理消歧是交通、住宿、地点研究的前置；
- 天气/事件可与地理消歧并行，但依赖明确目的区域时必须等待；
- 不需要住宿时不得创建 stay task；
- 简单 ANSWER 不进入完整规划图；
- 模型可以提出任务建议，但代码 Builder 决定合法性和依赖；
- 未知 task type 直接失败；
- 每图任务数与预算有硬上限。

## 7. Orchestrator 执行语义

推荐使用 Python 3.11 `asyncio.TaskGroup`：

1. 读取同一版本 TripState/ConstraintSnapshot；
2. 构建并校验图；
3. 调度 dependency 已满足的任务；
4. 独立任务并行；
5. Agent 返回 AgentResult；
6. Orchestrator 单点注册 Evidence/Candidate；
7. 更新 Task 状态与 Trace；
8. 关键任务失败时取消同组尚未完成任务；
9. 写入 FAILED 和类型化错误；
10. 全部关键研究完成后进入 DRAFTING。

确定性要求：

- 合并顺序按 task_id/candidate_id，不依赖完成先后；
- 同一 Fake 输入生成同一图和同一排序；
- 并发任务不得共享可变上下文；
- State save 使用 expected_version；
- cancellation 不得吞掉最初根因；
- 达到时间/调用/成本上限即 FAILED。

## 8. Research Agent 规范

### 8.1 统一上下文

```text
AgentContext
  trace_id
  task_spec
  constraint_snapshot_ref
  allowed_tools[]
  prior_evidence_refs[]
  budget
  locale/timezone
```

AgentResult 仅包含结构化摘要、证据草稿、候选草稿、指标和错误；Orchestrator 负责落库。

### 8.2 TransportResearchAgent

- 城际/市内交通候选；
- 换乘次数、最短衔接、到达时段；
- 价格和班次必须引用证据；
- 不决定最终日程；
- 无结果抛 ToolEmptyResultError，不返回空成功。

### 8.3 StayResearchAgent

- 区域和住宿候选；
- 总价而非仅每晚价格；
- 入住/退房、取消条款、位置证据；
- 不生成不存在的评分；
- 不在本 Agent 做全局预算分配。

### 8.4 PlaceResearchAgent

- 景点、餐饮、活动；
- 营业窗口、预计时长、地理位置、适配标签；
- 外部描述视为不可信文本；
- 不决定哪一天访问。

### 8.5 ContextPolicyAgent

- 天气、节假日、会展、汇率、政策和安全提示；
- 区分事实、建议和免责声明；
- 政策事实必须有来源和时间；
- 不提供法律/医疗结论。

## 9. Hybrid Planner

### 9.1 Composer

`ItineraryComposer` 只读取已验证结构的 Candidate/Evidence，不直接调用供应商工具。

输出 2～3 个差异化 `PlanCandidate`：

- budget：优先成本；
- balanced：综合权衡；
- comfort：节奏和弹性优先。

若约束不支持三种方案，可减少数量，但必须返回结构化原因，不能复制同一方案换标签。

### 9.2 确定性服务

ScheduleService：

- 带时区日期；
- 营业窗口；
- 路程/换乘；
- 入住/退房；
- 每日活动时间与 flex buffer；
- 不允许负时长和重叠。

BudgetService：

- Money 精确计算，禁止 float；
- 统一币种和汇率证据；
- 分项、总计、缓冲；
- 缺失价格产生问题，不使用默认值；
- hard budget 超出时候选不可行。

M4 可以实现初级可行性检查，但最终 Gate 语义由 M5 统一。

## 10. 调用预算

每次工作流明确：

- max tasks；
- max concurrent tasks；
- max tool calls per task / total；
- max model calls；
- task timeout / workflow deadline；
- token/cost estimate 上限。

预算耗尽抛 `BudgetExhaustedError`，进入 FAILED。不得缩减任务后静默输出部分计划。

## 11. 实现顺序

1. TaskSpec/Graph/Result；
2. Graph validator/builder；
3. Budget policy；
4. Orchestrator + FakeTaskRunner；
5. cancellation、版本冲突和 Trace；
6. 四类 Research Agent；
7. Composer Schema/Prompt；
8. ScheduleService；
9. BudgetService；
10. 端到端 Fake Provider 集成；
11. CLI 切换到新 Use Case 的显式配置。

## 12. 测试矩阵

Task Graph：DAG、环、缺 dependency、未知类型、超任务数、稳定排序。

Orchestrator：

- 独立任务实际并行；
- dependency 严格等待；
- 完成顺序随机但结果稳定；
- 关键任务失败取消兄弟任务；
- 根因保留；
- timeout、budget、state version conflict；
- Agent 尝试返回非法 Schema；
- 无部分成功。

Research Agent：每类成功、空结果、工具错误、非法证据、注入文本、预算耗尽。

Planner：多方案差异、时区、重叠、闭馆、路程、预算、缺价格、缓冲、无可行候选。

并发测试必须使用可控 barrier/event，禁止依赖 sleep 猜时序。新增代码覆盖率 ≥ 90%。


### 12.1 Live Vertical Slice Gate

M4 阶段验收必须执行真实 API 的最小端到端切片：

- 使用真实 LLM、已启用工具 Adapter 和组合根 Settings；
- 至少覆盖 3～5 个正常/约束复杂案例，重复关键案例至少 2 次；
- 断言 TaskGraph 合法、关键任务完成、Evidence/Candidate 引用完整、PlanCandidate Schema 合法、硬约束未被违反；
- 固定总调用数、并发、超时和成本预算，`retry_count=0`；
- 任何工具/模型失败都使该切片 FAILED，不返回“可用部分”冒充成功；
- 真实失败脱敏后进入 Offline Fixture，修复后必须重新执行 Live Gate。
Fake Provider 集成负责并发、取消、依赖失败、空结果和预算耗尽等确定性场景；Live Vertical Slice 负责证明真实 LLM、工具 Adapter 和端到端组合可用，两者均为 M4 验收证据。

真实 API 验收由用户负责手动执行。Codex 不自动调用真实 LLM 或工具 Adapter，只准备切片用例、预算约束、断言和脱敏报告格式。用户应通过 `start-local.ps1` 或本阶段明确的等价启动方式加载真实配置；未提供人工执行结果时，Live Vertical Slice Gate 状态为 `PENDING_MANUAL_ACCEPTANCE`，不得标记 M4 完成。

## 13. 阶段验收门

- [x] Graph 明确表达所有依赖；
- [x] 独立研究并行且结果确定；
- [x] Agent 不直接互调、不写状态；
- [x] 任一关键任务失败使工作流 FAILED；
- [x] 所有计划项引用 Candidate/Evidence；
- [x] Schedule/Budget 使用确定性代码；
- [x] 无 fallback/cache/retry/partial success；
- [x] M5 能基于 PlanCandidate 和 TaskResult 实施 Gate；
- [x] 用户手动执行的 Live Vertical Slice 通过，且失败没有被 Fake、缓存、备用供应商或部分成功掩盖。

注：第 8 项表示 M4 已输出供 M5 使用的结构化 PlanCandidate/TaskResult 契约，不表示 M5 的 GateRunner、Critic 或 Repair 已实现。

## 14. 交付清单

- Task Graph/Builder/Validator；
- Orchestrator 和预算策略；
- 四类 Research Agent；
- Composer、ScheduleService、BudgetService；
- 并发/取消/确定性测试；
- M4 ADR：手写 Task Graph、并发与失败传播。
