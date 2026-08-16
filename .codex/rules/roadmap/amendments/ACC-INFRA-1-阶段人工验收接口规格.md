# ACC-INFRA-1：阶段人工验收接口

> 文档类型：横切开发规格（Cross-cutting Development Specification）  
> 文档状态：Draft v0.5，待维护者批准后编写 Implementation Plan  
> 首批适用范围：M0、M1、M2、M2.1、M3、M4、M4.1 既有阶段的人工收口；M4.2 及后续阶段必须复用本合同  
> 阶段关系：不占用 M 系列编号，不改变 M4.2/M4.3 的路线位置

本规格只建立阶段人工验收入口，不修复商务差旅业务语义，不修改历史阶段报告，不修改 M4.1 Golden Dataset、Oracle、评分公式或正式验收结论。

本规格是总 Spec“阶段人工收口”架构原则的首个适配器。总 Spec 规定长期治理要求，本规格规定通用命令、Artifact、人工记录和复核合同；每个后续阶段必须在自身阶段 Spec 中声明适配器、案例和阶段特有输出，不得重新设计平行验收入口。

## 1. 问题定义

当前仓库已有 pytest、离线 Runner、Live Gate 和阶段评测报告，但这些证据主要回答“代码和评测器是否运行成功”，不能稳定回答“系统实际理解了什么、路由了什么、生成了哪些类型化中间结果，以及这些结果是否符合当前商务差旅目标”。

现有入口存在以下限制：

- `main.py` 只输出有限的交互摘要，不展示完整的 `ConstraintSnapshot`、`ReadinessResult`、`RouteDecision`、Task Graph 和计划结构；
- M2.1 测试通过 `capsys` 捕获事件后直接断言，人工无法直接查看事件链；
- M4 Live 测试直接调用内部 Use Case 并构造 `RouteDecision`，不能证明完整的 M2→M4 公开交互路径；
- M4.1 正式评测可以同时出现 `evaluation_status=PASS` 与 `business_assertion=FAIL`，两者不能合并成一个“通过”。

本问题定义以当前 `main.py`、`tests/e2e/test_m21_observability_acceptance.py`、`tests/e2e/test_m4_live_vertical_slice.py`、`evaluation/reports/M4.1/M4.1-completion.md` 和 `.codex/rules/roadmap/M4.2-差旅语义与能力路由.md` 为代码与规格依据；这些文件的当前限制不能由本规格假设性地视为已经修复。

因此，本规格将以下三个状态严格分开：

```text
命令运行成功
机器检查通过
人工验收完成
```

命令退出码为 0 只能证明观察结果已生成，不能自动产生人工验收结论。

## 2. 总体目标

ACC-INFRA-1 必须提供一个本地、只读、可复现的人工验收入口，使维护者能够：

1. 使用固定的商务差旅输入或历史合同输入运行指定阶段；
2. 看到真实阶段入口产生的关键类型化输出；
3. 分开查看预先固定的 `EXPECTED` 与实际运行的 `ACTUAL`；
4. 查看机器检查、失败阶段、调用次数、版本和运行模式；
5. 通过变异检查确认验收断言确实绑定关键逻辑；
6. 在独立上下文中复核 Artifact 后，手动记录 `ACCEPTED`、`REJECTED` 或 `BLOCKED`。

该入口必须使用现有生产代码的公开边界或只读适配器。不得为方便展示而重新实现一套业务判断。

## 3. 范围与非目标

### 3.1 本期必须实现

- 统一的本地命令行入口 `evaluation.manual_acceptance`；
- M0～M4.1 的阶段适配器；
- 固定案例与探索输入两种运行方式；
- 实际输出、期望输出、机器检查和人工记录的分离；
- 商务差旅转型基线案例；
- 阶段级人工检查清单；
- 关键逻辑的最小变异检查协议；
- 脱敏后的结构化 Artifact 和运行元数据；
- `BLOCKED`、`RUNTIME_FAILURE`、`EVALUATOR_ERROR`、`NON_ACCEPTANCE_RUN` 等失败状态。

### 3.2 本期明确不做

- 不新增 M4.2 或其他 M 系列编号；
- 不修改 M0～M4 的生产业务逻辑；
- 不提前实现 `BusinessTripScopeResolver`、M4.2 语义修复或 M4.3 真实差旅工具；
- 不修改 M4.1 Golden Dataset、Oracle、评分公式、M4-before 或正式验收记录；
- 不实现 Dashboard、FastAPI、SSE、WebSocket、SQLite、任务队列或远程观测平台；
- 不把完整 Prompt、系统指令、API Key、Authorization、Cookie、供应商原始响应或不必要 PII 写入 Artifact；
- 不自动生成 `human_decision=ACCEPTED`；
- 不把商务转型基线中的 `BASELINE_FAIL` 改写为业务成功。

## 4. 两类验收状态

每个历史阶段都必须分别记录以下两种结果。

### 4.1 历史合同人工收口

`historical_contract_acceptance` 检查该阶段原规格承诺的技术合同是否可以被人观察和核对。例如：

- M1 的类型化请求、Schema 错误、状态和 `WorkflowError`；
- M2 的解释、约束、澄清和交互路由；
- M3 的 Provider、Evidence、TTL 和 Candidate 合同；
- M4 的 Task Graph、Evidence、Candidate 和结构化计划边界。

### 4.2 商务转型基线

`business_transition_baseline` 记录当前代码面对商务差旅输入时的真实表现。允许的结果包括：

```text
CAPTURED_PASS
BASELINE_FAIL
NOT_APPLICABLE
```

`BASELINE_FAIL` 是 M4.2 的输入证据，不等于历史阶段人工收口失败，也不等于商务差旅业务已经验收通过。

## 5. 商务差旅人工案例

商务差旅案例现在建立，不等待 M4.2 实现完成。案例只作为当前代码的转型前观察基线，不修改 M4.1 正式评测资产。

目标目录为：

```text
evaluation/manual_cases/business-travel-v1/
```

### 5.1 BT-ACC-001：自然输入与必要澄清

用户输入：

```text
我当前在杭州，下周六早上8点我在上海东方明珠塔有一场会议，请规划我的差旅方案。
```

案例必须冻结：

```text
reference_now = 2026-08-16T12:00:00+08:00
resolved_meeting_date = 2026-08-22
```

人工必须核对系统是否识别出：

```text
origin = 杭州
meeting_city = 上海
meeting_location = 上海东方明珠塔
meeting_starts_at = 2026-08-22T08:00:00+08:00（若时区已解析）
```

按照当前 M4.2 Frozen v1.2，会议时区缺失属于 G1 blocker。因此，如果系统没有依据受控规则补出时区，期望结果为：

```text
mode = CLARIFY
missing_blocker = meeting_timezone
external_research_calls = 0
```

`traveler_count` 也必须在实际输出中明确出现。只有当 M4.2 合同明确允许从第一人称单数确定性推导 `traveler_count=1` 时，才可以把“我的”作为该字段的来源；否则必须把 `traveler_count` 一并列为 `CLARIFY` 的 blocker。人工验收接口不得替 M4.2 做这个业务决定。

如果项目希望中国大陆会议地点自动确定为 `Asia/Shanghai`，必须先修改并批准 M4.2 的规格规则，不能由人工验收接口默默替换该规则。

### 5.2 BT-ACC-002：完整输入与规划范围

用户输入：

```text
我当前在杭州。下周六（2026年8月22日）早上8点、中国标准时间，我一个人在上海东方明珠塔有一场会议，请规划会前到达的差旅方案。
```

期望的关键事实为：

```text
origin = 杭州
meeting_city = 上海
meeting_location = 上海东方明珠塔
traveler_count = 1
meeting_starts_at = 2026-08-22T08:00:00+08:00
planning_horizon = meeting_arrival_ready
```

在 M4.2 业务边界下，人工接口至少应展示：

```text
geo = REQUIRED
policy = REQUIRED
intercity_transport = REQUIRED
stay = CONDITIONAL
local_transport = REQUIRED
return_scope = EXCLUDED 或 not_planned
activity / place / return_transport = 不得进入主链路
```

M4.2 只验证范围、能力和任务依赖判断；真实政策、航班、酒店、地图查询和最终差旅方案属于后续阶段。

### 5.3 历史案例的保留规则

旧的旅游规划案例不得删除。它们只用于历史合同回归，不再作为商务差旅语义验收的主案例。

M4.1 正式 Golden Dataset 继续保持不可变。需要复用 M4.1 案例时，只引用其 `case_id` 和 Oracle，不复制或改写原始资产。

## 6. 命令合同

以下命令是本规格规定的目标入口；在实现前不得描述为当前仓库已有命令。

### 6.1 固定案例运行

```powershell
venv\Scripts\python.exe -m evaluation.manual_acceptance run --stage M2 --case BT-ACC-001 --mode offline --show full --artifact-dir evaluation/reports/manual/M2/BT-ACC-001
```

需要真实模型时，必须显式指定 Live 模式：

```powershell
venv\Scripts\python.exe -m evaluation.manual_acceptance run --stage M2 --case BT-ACC-001 --mode live --show full --artifact-dir evaluation/reports/manual/M2/BT-ACC-001
```

Live 模式必须显式检查模型、凭证、调用上限、重试策略和预计成本；缺少配置时返回 `BLOCKED`，不得静默切换 Offline、Fake 或默认模型。

### 6.2 探索输入运行

```powershell
venv\Scripts\python.exe -m evaluation.manual_acceptance run --stage M2 --input "我当前在杭州，下周六早上8点我在上海东方明珠塔有一场会议，请规划我的差旅方案。" --mode live --show full --exploratory
```

探索输入只能产生 `OBSERVATION_READY`，不能产生阶段人工通过记录，因为它没有独立固定的期望断言。

### 6.3 人工记录完整性检查

```powershell
venv\Scripts\python.exe -m evaluation.manual_acceptance verify --artifact-dir evaluation/reports/manual/M2/BT-ACC-001
```

该命令只检查运行 Artifact、人工清单、变异结果和独立复核字段是否完整，不替代维护者对业务语义的判断。

## 7. 命令输出状态与状态机

运行器、机器检查、业务断言、人工结论和阶段 Gate 状态必须分开记录。它们不能通过“看起来成功”或人工编辑互相覆盖。

### 7.1 状态域

```text
runner_status：
  OBSERVATION_READY
  BLOCKED
  RUNTIME_FAILURE
  EVALUATOR_ERROR
  NON_ACCEPTANCE_RUN

machine_assertion：
  PASS
  FAIL
  NOT_RUN

mutation_result：
  PASS
  FAIL
  NOT_RUN

independent_review_result：
  PASS
  FAIL
  NOT_RUN

business_assertion：
  PASS
  FAIL
  NOT_SCORABLE
  PENDING

human_decision：
  PENDING
  ACCEPTED
  REJECTED
  BLOCKED

stage_gate_state：
  NOT_STARTED
  RUNNING
  OBSERVATION_READY
  HUMAN_REVIEW_PENDING
  ACCEPTED
  REJECTED
  BLOCKED
```

`business_transition_baseline` 只允许以下值：

```text
CAPTURED_PASS
BASELINE_FAIL
NOT_APPLICABLE
```

`BLOCKED` 不是 `business_transition_baseline` 的合格结果，也不是人工验收通过状态。它只表示当前运行或阶段 Gate 无法完成。

### 7.2 合法状态转移

```text
NOT_STARTED
  → RUNNING
    ├─ 完整真实输出与机器检查齐备 → OBSERVATION_READY
    └─ 缺少运行前条件、真实边界输出或安全条件 → BLOCKED

OBSERVATION_READY
    ├─ EXPECTED/ACTUAL 可独立核对且启动独立复核 → HUMAN_REVIEW_PENDING
    └─ 发现边界输出、Artifact、公开入口或安全条件缺失 → BLOCKED

HUMAN_REVIEW_PENDING
    ├─ 所有 Gate 条件满足 → ACCEPTED
    ├─ 关键语义断言、变异检查或独立复核失败 → REJECTED
    └─ 复核所需材料或运行条件失效 → BLOCKED

BLOCKED ──新建 run_id 并从头运行──→ NOT_STARTED
REJECTED ──修复后新建 run_id 并从头运行──→ NOT_STARTED
ACCEPTED ──实现、案例、配置或期望断言变化后新建 run_id──→ NOT_STARTED
```

以下转移规则是强制性的：

1. `NOT_STARTED → RUNNING`：必须已经冻结案例、期望断言、运行模式和阶段适用性声明；适用性不得在运行失败后补写。
2. `RUNNING → OBSERVATION_READY`：必须生成完整 `ACTUAL`、运行元数据和机器检查结果；缺少真实边界输出时转为 `BLOCKED`。
3. `OBSERVATION_READY → HUMAN_REVIEW_PENDING`：必须能分别查看 `EXPECTED` 与 `ACTUAL`，并启动独立复核。
4. `HUMAN_REVIEW_PENDING → ACCEPTED`：必须同时满足 `machine_assertion=PASS`、人工断言完成、`mutation_result=PASS`、`independent_review_result=PASS`，以及 `business_transition_baseline` 为 `CAPTURED_PASS`、`BASELINE_FAIL` 或预先声明的 `NOT_APPLICABLE`。
5. `HUMAN_REVIEW_PENDING → REJECTED`：任一关键语义断言不成立、变异检查无效或独立复核否定时转为 `REJECTED`。
6. 运行缺少凭证、配置、案例、真实边界输出、Artifact、公开入口或安全条件时，转为 `BLOCKED`；外部调用、评测器或配置异常必须保留对应 `runner_status`，并同时使 `stage_gate_state=BLOCKED`。
7. `BLOCKED` 和 `REJECTED` 都是当前 `run_id` 的终态，不能直接转为 `ACCEPTED`。阻塞解除后必须生成新的 `run_id`，从 `NOT_STARTED` 重新运行；旧 Artifact 的状态不可覆盖。
8. `ACCEPTED` 是当前 `run_id` 的终态。任何实现、案例、配置或期望断言变化都必须创建新的 `run_id`，不能修改旧记录。

### 7.3 Gate 计算规则

`M4.2_IMPLEMENTATION_GATE=OPEN` 当且仅当每个前置阶段同时满足：

```text
historical_contract_acceptance = ACCEPTED
stage_gate_state = ACCEPTED
runner_status = OBSERVATION_READY
machine_assertion = PASS
business_transition_baseline ∈ {CAPTURED_PASS, BASELINE_FAIL, NOT_APPLICABLE}
human_decision = ACCEPTED
mutation_result = PASS
independent_review_result = PASS
没有 BLOCKED、REJECTED、RUNTIME_FAILURE、EVALUATOR_ERROR 或 NON_ACCEPTANCE_RUN
所有适用的固定案例都有 ACTUAL Artifact 和人工复核记录
```

`stage_gate_state` 和实施 Gate 都是由上述字段确定性派生的只读结果，不得由命令参数、人工编辑或报告文本直接写入 `OPEN`。任何一个前置阶段不满足上述条件，`M4.2_IMPLEMENTATION_GATE=CLOSED`。`BASELINE_FAIL` 仅能作为已记录的转型前事实，不能表示业务语义已经通过；`NOT_APPLICABLE` 只能来自运行前冻结的阶段适用性声明，不能用来替代失败运行或缺失接口。

`NOT_APPLICABLE` 只适用于阶段 Spec 和运行前冻结的适用性清单已经明确声明“不处理该业务义务”的阶段或案例；被阶段 Gate 标记为 `mandatory` 的阶段或案例不得使用该值。适用性清单必须由维护者在运行前确认，不能由 Runner、人工复核或失败处理逻辑在运行后生成。

`M4.3_IMPLEMENTATION_GATE=OPEN` 还必须额外满足 M4.2 的 `stage_gate_state=ACCEPTED`。任何 `BLOCKED`、`REJECTED` 或未完成的人工复核都会使 Gate 保持 `CLOSED`。

只有人工记录中的 `human_decision=ACCEPTED` 且上述 Gate 计算结果为 `OPEN`，才表示对应阶段可以进入下一阶段。任何命令退出码为 0、机器检查通过或 Artifact 已生成，都不能单独改变 Gate 状态。

## 8. Artifact 合同

每次固定案例运行至少产生：

```text
evaluation/reports/manual/<stage>/<case_id>/
├── actual.json
├── expected.json
├── observation.md
├── machine-checks.json
├── runtime.json
└── human-review.md
```

### 8.1 `actual.json`

必须来自真实阶段入口的运行结果，不能由断言代码重新拼装。根据阶段不同，至少包含：

```text
M1：typed request、state、WorkflowError
M2：Interpretation、ConstraintSnapshot、ReadinessResult、RouteDecision
M2.1：事件序列、trace、阶段状态、失败链
M3：ProviderResult、Evidence、Candidate、TTL 和失败语义
M4：公开入口路由、TaskGraph、TaskResult、Evidence、Candidate、计划边界
M4.1：CaseResult、Oracle、business_assertion、first_failed_stage、failure_category、metric_values
```

如果阶段没有可观察的真实边界输出，必须返回 `BLOCKED`，不得用摘要、测试日志或人工推测补齐。

### 8.2 `expected.json`

必须在运行前固定，来源可以是用户审查过的人工案例文件或现有不可变 Oracle。禁止根据 `actual.json` 动态生成期望值。

至少包含：

```text
case_id
input
reference_now
expected_stage_behavior
expected_key_fields
expected_failure_or_success_semantics
human_assertions
```

### 8.3 `observation.md`

必须以人可以直接核对的顺序展示：

```text
案例输入
期望判断
实际输出
机器检查
失败阶段与错误类型
调用次数、重试次数和运行模式
代码提交与运行指纹
人工核对清单
```

“全部通过”不能作为唯一内容。报告必须显式展示系统实际理解成了什么以及为什么作出该判断。

### 8.4 `human-review.md`

至少包含：

```text
stage
case_id
run_id
reviewer
reviewed_at
checked_assertions
observed_differences
mutation_result
independent_review_result
decision: ACCEPTED | REJECTED | BLOCKED
reason
```

## 9. 各阶段人工收口要求

### 9.1 M0

人工核对数据集、Fixture、配置指纹、Offline 无网络、失败语义和报告生成结果。M0 不负责解析完整商务差旅语义，因此只需确认商务案例可以被登记、冻结和追踪，不要求 M0 产生会议字段。

M0 的适用性声明为：完整商务差旅语义理解不属于本阶段，该业务义务可记录为运行前冻结的 `NOT_APPLICABLE`；数据集、Fixture、配置、Offline 和失败语义案例属于 M0 的 mandatory 验收内容，不得标记为 `NOT_APPLICABLE`。

### 9.2 M1

人工核对有效和非法类型化请求、Schema 错误、状态转移和 `WorkflowError`。M1 使用阶段自身的类型化投影，不强行要求 M1 理解自然语言会议输入。

M1 的适用性声明为：自然语言会议语义理解不属于本阶段，该业务义务可记录为运行前冻结的 `NOT_APPLICABLE`；类型化请求、Schema 错误、状态转移和 `WorkflowError` 属于 M1 的 mandatory 验收内容，不得标记为 `NOT_APPLICABLE`。

### 9.3 M2

人工核对 BT-ACC-001 和 BT-ACC-002 的：

```text
Interpretation
ConstraintSnapshot
ReadinessResult
RouteDecision
最终交互状态
```

必须能看出系统识别了哪些事实、哪些是约束、哪些仍未知，以及为什么进入 `PLAN` 或 `CLARIFY`。

### 9.4 M2.1

人工核对同一商务案例的事件链：

```text
workflow_started
G0
Interpreter
Constraint
Readiness
Router
workflow_completed 或 workflow_failed
```

事件必须能被人直接查看，不能只在测试内部通过 `capsys` 捕获后丢弃。CLARIFY 必须显示没有启动 Planner 或外部研究任务。

### 9.5 M3

人工核对由商务案例投影出的 Provider、Evidence 和 Candidate 合同，包括来源、时间、TTL、空结果和失败语义。M3 不负责把这些结果组装成最终差旅方案。

### 9.6 M4

人工验收入口必须经过公开交互边界，不能直接构造 `RouteDecision` 或直接调用内部 M4 Use Case 作为最终人工证据。

必须展示：

```text
M2 路由结果
ConstraintSnapshot
TaskGraph
TaskResult
Evidence / Candidate
计划结构、假设、警告和失败状态
```

如果当前代码仍然只展示旧的 `geo + transport` 或只返回单项交通计划，记录为 `BASELINE_FAIL`，不得修饰为差旅规划成功。

### 9.7 M4.1

人工核对评测器是否准确区分：

```text
evaluation_status
business_assertion
run_status
live_status
```

M4.1 可以接受“评测器准确暴露业务失败”，但不能因为评测器运行成功就接受商务差旅语义。

## 10. 变异检查与独立复核

变异检查必须在隔离的临时工作副本或明确的测试变体中执行，不得污染当前基线。

必须满足：

1. 改变一个关键业务字段或关键路径；
2. 重新运行同一固定案例；
3. `ACTUAL` 必须发生可解释变化；
4. 固定断言或人工清单必须明确拒绝变异结果；
5. 变异后仍显示“验收通过”时，ACC-INFRA-1 验收失败。

推荐的最小变异包括：

- M2：交换一个 hard/soft 约束标签或把 `PLAN` 改为 `CLARIFY`；
- M2.1：删除一个关键阶段事件；
- M3：删除 Evidence 引用或伪造空结果为成功；
- M4：删除一个必需 Task 或绕过公开路由；
- M4.1：改变 `first_failed_stage` 或评分结果。

实现代码和基础测试完成后，必须在新的、没有实现过程上下文的会话中复核 `observation.md` 和 `actual.json`。独立复核只判断实际输出、期望断言、关键语义和失败归因是否可信，最终 `ACCEPTED` 仍由项目维护者确认。

## 11. 安全与失败边界

开发期可以展示完整的类型化业务对象和有限的测试输入，但以下内容在任何 Artifact、日志和报告中都禁止出现：

```text
API Key、Token、Password、Authorization、Cookie
完整系统 Prompt 和隐藏指令
供应商完整原始响应
不必要的姓名、电话、邮箱、证件号和支付信息
```

发现敏感字段时，运行必须进入 `EVALUATOR_ERROR`，不能只依赖前端遮罩继续生成“成功”报告。

以下任一情况都不得标记人工验收完成：

- 期望结果由实际结果动态生成；
- 只能看到 `PASS`，看不到关键实际字段；
- 阶段入口被测试 Fake 或内部捷径替代；
- M4 绕过 M2 路由；
- M2.1 事件无法人工查看；
- 上游失败被包装成部分成功；
- 变异后输出不变或仍自动通过；
- Artifact 缺少代码版本、运行模式或案例身份；
- 工作树状态不满足正式验收要求；
- 人工记录缺少明确的 `ACCEPTED`、`REJECTED` 或 `BLOCKED`。

## 12. M4.2 前置门

M4.2 可以继续保持 `Spec Frozen / Plan 待批准`，但在 ACC-INFRA-1 的人工收口完成前不得进入业务代码实现。

进入 M4.2 实现前必须满足：

```text
M0 historical_contract_acceptance = ACCEPTED
M1 historical_contract_acceptance = ACCEPTED
M2 historical_contract_acceptance = ACCEPTED
M2.1 historical_contract_acceptance = ACCEPTED
M3 historical_contract_acceptance = ACCEPTED
M4 historical_contract_acceptance = ACCEPTED
M4.1 historical_contract_acceptance = ACCEPTED

```

上述 M0～M4.1 阶段集合统一引用 §7.3 的 Gate 计算规则；本节不重复定义状态域、字段取值或例外路径。

`BASELINE_FAIL` 仅能作为当前商务转型基线记录，不代表业务成功，也不能替代 `ACCEPTED`。`NOT_APPLICABLE` 必须在运行前由阶段 Spec 和冻结适用性清单确定；mandatory 阶段或案例不得使用该值，且不能在运行失败后补写或掩盖缺少实际输出。任何 `BLOCKED` 都会使 M4.2 前置门保持 `CLOSED`。

## 12.1 未来阶段复用规则

M4.2、M4.3、M5 以及之后的每个阶段 Spec 都必须显式引用总 Spec 的“阶段人工收口”原则和本规格，并至少声明：

- `evaluation.manual_acceptance` 的阶段标识和只读适配器；
- 本阶段必须展示的真实边界输出；
- 本阶段固定案例、独立期望断言和失败语义；
- 阶段特有的 `human-review.md` 人工核对项；
- 进入下一阶段前所需的 `human_decision` 和 Artifact 条件。

后续阶段不得以 Dashboard、生产日志、单一 pytest 汇总或新的私有命令替代统一人工验收入口。若某阶段无法通过统一入口展示真实边界输出，必须标记为 `BLOCKED`，不得借用上一阶段的人工记录。

## 13. 允许修改与完成条件

允许新增本地人工验收命令、只读阶段适配器、人工案例、期望断言、输出序列化、开发期展示通道、人工检查清单和变异检查。必要时可以增加不改变业务行为的只读 Facade。

禁止修改业务判断以适配接口，禁止修改 M4.1 正式资产，禁止用测试 Fake 冒充真实公开路径，禁止借此实现 M4.2、M4.3、M5 或 EVAL-OBS-1 的 Dashboard 能力。

ACC-INFRA-1 完成必须满足：

- M0～M4.1 均有可执行的人工验收入口；
- 每个阶段都有可人工查看的真实边界输出；
- BT-ACC-001 和 BT-ACC-002 已冻结并生成转型前基线；
- `EXPECTED` 与 `ACTUAL` 分离且不可互相生成；
- 关键阶段通过变异检查；
- 独立上下文完成复核；
- 所有阶段均有人工 `ACCEPTED`、`REJECTED` 或 `BLOCKED` 记录；
- 历史验收资产和 M4.1 正式结论未改变。

完成 ACC-INFRA-1 不代表 M4.2 业务语义已经实现，只代表项目重新获得了在阶段边界观察和判断代码的能力。

## 14. 版本记录

| 版本 | 日期 | 变更 |
|---|---|---|
| v0.1 | 2026-08-16 | 建立独立人工验收接口规格；切换商务差旅转型案例；定义历史合同收口、转型基线、命令、Artifact、变异检查和 M4.2 前置门。 |
| v0.2 | 2026-08-16 | 对齐总 Spec 的“阶段人工收口”原则；规定 M4.2 及后续阶段复用统一接口并在自身 Spec 中声明适配器与人工 Gate。 |
| v0.3 | 2026-08-16 | 固化阶段状态机、Gate 计算和 `BLOCKED`/`NOT_APPLICABLE` 的不可绕过规则。 |
| v0.4 | 2026-08-16 | 将运行状态、机器检查、变异检查和独立复核纳入 Gate 派生条件，并清除 M4.2/M4.3 的 `BLOCKED` 放行表述。 |
| v0.5 | 2026-08-17 | 统一 `business_transition_baseline` 的取值域，移除与 §7.1 冲突的 `BLOCKED` 值。 |
