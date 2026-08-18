# EVAL-OBS-1：评测基线可视化与观测面提案

> 文档类型：阶段完成后的独立增量提案  
> 依赖基线：M4.1 商务差旅评测基线已完成验收  
> 状态：提案，尚未进入当前核心阶段的实施范围，也不属于 M4.1 完成条件  
> 目标：把已验收评测基线的运行过程改造成可回放、可解释、可插拔的评测观测面。  
> 关系：本提案只消费 M4.1 已交付的评测产物，不修改 M4.1 的 Oracle、评分公式、验收结论或 M4.2 前置条件。
> 使用方式：本文件描述未来增量的机器可验证合同，不宣称对应 Dashboard、API、事件存储或适配器已经完成。是否进入路线图，必须由独立 Plan 和验收门决定。

## 1. 问题定义与设计原则

已验收的 M4.1 评测基线能够证明评测命令是否完成，但仍可进一步解释数据集如何进入各路线、每个阶段输出了什么、失败首先发生在哪里以及最终指标如何由样本推导。因而本提案规划一个只读的 Evaluation Observatory：运行入口负责创建受控评测任务，Runner 负责真实执行，事件层负责结构化记录，Dashboard 负责回放与解释；Dashboard 不得成为第二个 Scorer，也不得改变验收结果。

本提案遵循五项原则：确定性验收仍由现有 Runner、Scorer 和 `stage_acceptance.py` 负责；事件先持久化后推送；未产生事件不等于成功；失败优先于空结果；数据最小化优先于调试便利。所有事件都必须能追溯到 `run_id`、路线、案例、节点、版本和 Artifact，不允许以日志文本作为唯一事实来源。

未来实施时应先验证本提案的机器可验证约定，再使用第 10 节已选定的适配器。事件源、传输、任务运行器、读模型、节点发现和诊断序列化都必须通过稳定接口隔离；替代技术只能以新适配器或新版本接入，不得改写 M4.1 的 Oracle、评分、失败归因、隐私边界或验收状态。任何改变这些语义的扩展，都必须回到对应阶段说明中记录，不能通过 Dashboard 逻辑隐式引入。

## 2. 范围与非目标

### 2.1 本次范围

本提案覆盖未来观测面需要解释的 M4.1 评测链路：

```text
RunSpec 冻结
→ 数据集、Fixture、Policy、Registry 合同校验
→ Component Offline Baseline
→ Stage Integration Offline Baseline
→ Offline Determinism
→ Scorer 与 CaseResult
→ Fingerprint、M4-before、Self-diff
→ Live Semantic Baseline（仅 all 模式）
→ Artifact Manifest
→ 最终验收状态
```

观测面至少提供执行进度、节点输入/输出安全摘要、Oracle 引用、指标结果、失败归属、Artifact 引用、运行配置和解释原理。运行按钮只允许调用预定义的 `offline` 或 `all` 模式，不接受任意 Shell、Python 表达式或前端拼接命令。

### 2.2 非目标

本补充不实现通用日志平台、Token 级流式输出、在线改写 Oracle、自动修复业务失败、缓存回退、备用供应商接管、部分成功伪装、M4-before 覆盖、真实预订/付款动作，以及把 Dashboard 作为 M4.1 业务验收的权威来源。本版选定 SSE 作为观测传输适配器、JSONL 作为规范事件源；派生 Read Model 可以使用数据库，但不得升级为事实源。替代传输、事件源和读模型实现只能通过后续可替换适配器接入。首版必须先拥有与传输协议无关的事件合同和可回放规范事件源。

## 3. 评测输入合同

### 3.1 RunSpec

每次按钮或命令启动先生成不可变 `RunSpec`，然后才允许执行。其逻辑字段如下：

```text
run_id                 全局唯一且不可复用
stage                  固定为 M4.1
mode                   offline | all
requested_routes       component | integration | live_blocking | live_observation
dataset_id/version/hash 数据集身份与内容指纹
case_ids               本次案例集合；顺序稳定
oracle_version         Oracle 版本
fixture_refs/hashes    Fixture 身份与指纹
policy_refs/hashes     Policy bundle 身份与指纹
system_commit          代码提交；未提交时标记为 NON_ACCEPTANCE_RUN
runtime_fingerprint    Provider、Model、URL 指纹、超时、温度、重试等
execution_limits       案例数、Live 次数、Token、时长和成本上限
strict_mode            开发/测试必须为 true
retry_count            普通评测必须为 0
cache_reads            普通评测必须为 false
fallbacks              普通评测必须为 false
partial_success        普通评测必须为 false
requested_at           创建时间
```

`all` 模式必须显式声明模型与凭证是否可用；事件和 Artifact 只记录模型名、配置状态和指纹，不记录密钥。`RunSpec` 冻结后，Runner 不得根据环境变化静默替换数据集、模型、Policy 或执行策略。

### 3.2 案例输入

案例输入来自已审查的 M4.1 JSONL 数据集，并通过现有 `AgentEvalCase` 合同校验。观测层记录 `case_id`、dataset hash、fixed clock、fixture/policy 引用和适用评测视图；自然语言 `input_text` 默认不直接写入事件，只写长度、稳定哈希和脱敏摘要。需要人工复核时，完整原文只能由受控本地 Artifact 权限读取，不得进入普通日志或推送消息。

### 3.3 节点输入

节点之间只传递已校验的 Pydantic 合同或 Artifact 引用。事件中的 `input_artifact_ref` 指向脱敏后、不可变的输入摘要；节点不得把完整 Prompt、完整用户行程、完整供应商响应或凭证作为 `payload` 写入事件。

## 4. 评测输出合同

一次运行至少产生以下不可变产物：

```text
evaluation/reports/M4.1/runs/<run_id>/
├── run.json             RunSpec、运行状态、配置指纹
├── events.jsonl         按 sequence 追加的结构化阶段事件
├── scorecard.json       路线、案例、指标和失败分布
├── report.md            脱敏后的人类报告
└── manifest.json        产物哈希、版本和完整性信息
```

最终输出必须分离以下状态，禁止只返回一个 `PASS`：

```text
evaluation_status       评测器和验收流程是否有效完成
business_assertion      Oracle 是否满足：PASS | FAIL | NOT_SCORABLE
run_status              COMPLETED | EXTERNAL_FAILURE | EVALUATOR_ERROR | NON_ACCEPTANCE_RUN
live_status             未执行、执行成功或 Live 失败状态
```

`evaluation_status=PASS` 不推出 `business_assertion=PASS`；业务基线可以在评测器正确运行时保持 FAIL。上游节点失败时，下游只能产生 `BLOCKED_BY_UPSTREAM` 或 `NOT_RUN`，不得产生空的成功输出。

## 5. 阶段、路线与节点事件

### 5.1 统一事件字段

`EvaluationEvent` 是唯一的跨节点观测合同，至少包含：

```text
event_id              事件唯一标识
run_id                运行身份
route_id              路线身份
case_id               案例身份；运行级事件可为空
node_id               节点身份
node_version          节点实现版本
sequence              run 内单调递增序号
event_type            事件类型
status                事件状态
occurred_at           事件时间
duration_ms           节点完成事件耗时
input_schema_version  输入合同版本
input_artifact_ref    输入安全摘要或 Artifact 引用
output_schema_version 输出合同版本
output_artifact_ref   输出安全摘要或 Artifact 引用
expected_ref          Oracle、数据集或规则引用
metric_refs           指标名称、公式和结果引用
principle_refs        Spec、代码和评测原理引用
failure_packet_ref    失败包引用；无失败时为空
downstream_call_count 下游调用计数
runtime_fingerprint   运行指纹
dataset_fingerprint   数据集指纹
policy_fingerprint    Policy 指纹
view_fixture_fingerprint Fixture 指纹
```

字段必须满足：`sequence` 在单个 `run_id` 内严格递增；同一 `event_id` 不得重复写入；事件可按序重放；服务重启或前端断开不丢失已持久化事件。时间用于展示和审计，顺序以 `sequence` 为准。

### 5.2 事件类型

最小事件集合为：

```text
run_started          RunSpec 已冻结
assets_validated     数据集、Fixture、Policy、Registry 校验完成
route_started        一条评测路线开始
node_started         节点开始执行
node_output          节点输出已校验并生成安全摘要
metric_computed      指标已由确定性 Scorer 计算
node_failed          节点或评测器失败并生成 Failure Packet
node_blocked         节点因上游失败而未运行
route_finished       路线完成，含路线级状态和计数
artifact_written     产物已追加写入并通过哈希校验
acceptance_finished  阶段验收完成，含四类最终状态
run_finished         运行结束，可成功或失败
```

### 5.3 M4.1 节点注册

首批节点清单至少包含：`run_spec`、`dataset_contract`、`case_registry`、`component_offline`、`stage_integration`、`scorer`、`offline_determinism`、`fingerprint`、`m4_before`、`self_diff`、`live_blocking`、`live_observation`、`artifact_manifest`、`stage_acceptance`。每个节点的版本化 Manifest 登记 `node_id`、`node_version`、输入/输出 Schema、拥有指标、允许失败类别、上游/下游、`principle_refs` 和可用路线。

版本化 Node Manifest 是 Runner 与 Dashboard 的共同元数据来源，Manifest Loader 负责 Schema、版本和引用完整性校验。页面不得用节点名称写死流程判断；新增节点只需实现统一 Node Adapter、提交兼容的 Manifest 并产出事件，即可被路线图、节点详情和指标页识别。未注册的事件、Manifest 版本不兼容或声明与实际事件不一致，必须使运行进入 `EVALUATOR_ERROR`，不能静默展示。代码内注册表可以作为 Loader 的内部索引，但不是跨模块元数据的规范来源。

### 5.4 阶段输出最小内容

每个 `node_output` 必须说明实际输出是否可用、输出合同版本、脱敏摘要、Artifact 引用和校验结果。每个 `metric_computed` 必须说明指标名、分子/分母或等价计算原理、Oracle 引用、实际值、是否适用以及评分来源。当前 `StageOutput(stage, status, summary)` 可作为兼容输入，但不能作为完整观测合同；适配器必须把它提升为上述事件，不得伪造缺失字段。

## 6. Failure Packet 合同

### 6.1 结构

所有 `node_failed` 都必须关联一个 `FailurePacket`：

```text
failure_id            失败唯一标识
run_id/route_id/case_id 失败上下文
node_id/node_version  首个失败节点及版本
first_failed_stage    INPUT_CONTRACT、INTERPRETER、SCOPE、ROUTER、...
failure_category      BUSINESS_FAILURE | EXTERNAL_DEPENDENCY_FAILURE |
                      EVALUATOR_ERROR | CONFIGURATION_ERROR
run_status             COMPLETED 之外的实际状态或业务失败状态
error_type/code        稳定错误类型和机器码
safe_summary           脱敏、有限长度的根因摘要
expected_ref/actual_ref 期望与实际摘要引用
affected_metrics      受影响指标
upstream_refs          上游事件或 Artifact 引用
downstream_state       BLOCKED_BY_UPSTREAM | NOT_RUN | CONTINUED_BY_CONTRACT
retryable              是否允许重试；普通 M4.1 运行仍为 0 次重试
downstream_call_count  已发生的下游调用数
trace_id               关联执行追踪身份
occurred_at/duration_ms 时间与耗时
artifact_refs          报告、事件或证据引用
```

### 6.2 归因规则

首个失败阶段由最早违反合同或 Oracle 的节点确定，不得把后续连锁失败覆盖首因。数据集、Policy、Fixture、Schema 或 Scorer 不可用归为 `EVALUATOR_ERROR` 或 `CONFIGURATION_ERROR`；外部 API/LLM 网络、超时、限流归为 `EXTERNAL_DEPENDENCY_FAILURE`；案例期望与实际不符归为 `BUSINESS_FAILURE`。只有拥有充分上下文的节点才能标记失败；否则使用 `EVALUATOR_ERROR` 并说明缺失字段。

Failure Packet 不得把异常堆栈、完整 Prompt 或供应商原始响应直接作为摘要。选择 10.6=A 后，观测层也不得复制原始材料到生成的 Artifact；如需人工复核，只能引用已有的、独立受权限保护的输入源或外部审计系统，Failure Packet 仅保存引用、哈希和安全摘要，不能通过 Dashboard 默认接口返回原始内容。

## 7. 脱敏边界与数据治理

### 7.1 永不写入观测产物

以下内容禁止进入任何生成的观测事件、JSONL、派生 Artifact、Dashboard API、报告和指标标签：API Key、Token、Password、Authorization、Cookie、完整 Prompt、系统指令、完整用户原文、姓名/手机号/邮箱/证件号、完整行程、支付信息、供应商完整原始响应以及 URL 查询参数中的密钥。发现敏感键或敏感值时必须替换为 `[REDACTED]`，不能仅依赖前端隐藏。原始数据集、外部供应商响应或系统错误日志如因其他系统需要保留，不属于本观测层生成物，且不得被观测层复制或拼接进引用对象。

### 7.2 允许写入的最小信息

允许记录稳定身份、长度、枚举、数量、有限长度安全摘要、不可逆哈希、Schema 版本、Artifact 相对引用、时间、耗时、指标值、调用计数和指纹。案例文本默认只保留 `input_hash`、`input_length` 和规则化摘要；城市、日期等业务字段仅在已脱敏且确实支撑评测解释时保留。原始文件必须使用不可变目录、访问控制和明确保留策略。

### 7.3 脱敏验收

测试必须以嵌套字典、列表、异常消息、URL query、报告文本和 Pydantic 序列化结果验证凭证、Prompt、PII 不可逆流；不能只测试界面遮罩。任何脱敏失败都使事件写入失败并将运行标记为 `EVALUATOR_ERROR`，不能继续产生“看似成功”的完整评测。

## 8. 运行、实时推送与回放

按钮行为等价于创建受控 Job：后端生成 `run_id`，冻结 `RunSpec`，启动允许的独立子进程 Runner，并返回 `run_id` 与观测地址。本版以 JSONL 作为规范事件源，以 SSE 作为传输适配器；事件必须先追加并校验，再向客户端发送，推送失败不得中断评测。客户端按 `run_id + after_sequence` 请求或恢复增量，断线重连后可以从最后序号继续回放。Dashboard 读模型由 JSONL 事件投影生成并可删除重建；轮询、WebSocket 或 SQLite 规范事件源只能作为实验适配器，不能在默认路径静默接管。

节点级事件是默认粒度，不推送 LLM Token。实时指标标记为 `in_progress` 或 `partial_observation`，只有 `metric_computed`、`route_finished` 和 `acceptance_finished` 产生的结果才可用于最终展示。未完成运行不得显示最终 PASS；运行中的上游失败必须实时将相关下游置为 `BLOCKED_BY_UPSTREAM`。

## 9. 一致性、幂等与 Artifact 约束

同一 `run_id` 只允许一个执行实例；运行中的同一路线不得重复启动。JSONL 规范事件源采用追加式写入，禁止覆盖已有事件或复用序号；读模型属于可重建投影，不得反向修改事件源。每次运行使用独立目录，正式 `M4-before.json` 保持不可变，按钮不得更新它。事件、scorecard、report 和 manifest 的哈希必须可相互校验；事件汇总的路线计数必须与 `CaseResult`、`StageScorecard` 和最终报告一致，否则运行标记为 `EVALUATOR_ERROR`。

## 10. 已决策的技术选型与可替换实现方案

本节记录项目维护者已经选择的方案及其替换边界。下列选项不会改变 M4.1 的 Golden Dataset、Oracle、评分公式、Failure Packet 语义或四类最终状态；它们只决定事件如何保存、运行如何调度、Dashboard 如何读取以及开发诊断如何开放。每个选择都必须通过接口、版本字段、配置指纹和独立验收保持可替换；实验结果不足以证明替代方案更好时，默认路径不得被实验代码污染。

选择记录格式如下：

```text
decision_id: D-OBS-<编号>
selected_option: <A | B | C>
reason: <选择依据>
decided_by: <维护者>
decided_at: <日期>
```

### 10.1 事件存储方案

**A. JSONL 作为规范事件源（推荐）**：实现最简单，追加写入、文件级回放、差异比较和离线归档都清晰，适合当前 M4.1 单机评测；缺点是复杂过滤、并发读取和跨运行聚合需要额外索引。

**B. SQLite 作为规范事件源**：适合按案例、节点、指标和失败类型查询，支持事务与索引；缺点是需要数据库 Schema、迁移、锁处理和备份约束，增加 M4.1 首版复杂度。

**C. 双写模式**：JSONL 保存不可变原始事件，SQLite 保存查询读模型；可同时满足审计回放和 Dashboard 查询，但存在双写一致性、恢复顺序和存储成本问题。

已选择：`D-OBS-01 = A`。理由：M4.1 以单机、可归档、易 diff 和可回放为首要目标，JSONL 能以最低实现成本提供不可变事件源。替换边界为 `EventStore` 接口；SQLite 或双写实验只能生成独立 `run_id`，并必须证明回放结果与 JSONL 规范源一致。无论选择哪一项，`events` 必须保持追加、可按 `sequence` 回放且不可被 Dashboard 覆盖。

### 10.2 实时事件传输方案

**A. HTTP 轮询（推荐首版）**：前端按 `run_id + after_sequence` 拉取事件，实现简单、调试透明、无需长连接基础设施；代价是存在轮询延迟和额外请求。

**B. SSE**：服务端单向推送，适合评测事件流，浏览器自动重连较简单；代价是需要长连接、代理超时和连接生命周期管理。

**C. WebSocket**：支持双向控制、暂停、取消和交互式操作；代价是协议复杂度、权限边界和状态同步成本更高，M4.1 当前不需要双向通信。

已选择：`D-OBS-02 = B`。理由：评测链路是服务端单向事件流，SSE 能在保持协议简单的同时提供近实时更新和断线重连语义。替换边界为 `EventTransport` 接口；轮询可作为兼容或实验实现，但不是运行时故障回退。无论选择哪一项，事件必须先持久化，再向客户端发送，推送失败不得中断 Runner。

### 10.3 评测任务运行隔离方案

**A. 同进程后台任务**：按钮调用受控 Python Runner，由应用进程中的后台任务执行；开发成本最低，但 Runner 崩溃、阻塞或资源泄漏可能影响观测服务。

**B. 独立子进程（推荐当前阶段）**：后端只传递已校验的 `RunSpec`，子进程调用固定入口，不接受任意 Shell；隔离性和失败边界较好，适合真实 Live 调用，但需要进程生命周期和结果回收管理。

**C. 独立 Job Worker/任务队列**：由队列和 Worker 执行评测，适合多人、多运行和长期任务；需要额外部署、队列可靠性和任务状态治理，不宜作为 M4.1 首个实现前置条件。

已选择：`D-OBS-03 = B`。理由：独立子进程能隔离 Live 调用、Runner 崩溃和资源泄漏，且仍适合当前单机阶段。替换边界为 `EvaluationExecutor` 接口；未来可实验 Job Worker，但不能让前端提交任意命令、Python 代码或未注册 Runner。任何方案都不得允许这些行为。

### 10.4 Dashboard 读模型方案

**A. 直接读取事件并实时聚合**：结构简单、组件少，但每次刷新都需要重新聚合，历史运行较多时性能和一致性较弱。

**B. 事件源加可重建 Read Model（推荐）**：事件是唯一事实源，路线、案例、指标和失败摘要由投影器生成；读模型损坏时可从事件重建，最适合审计和断线恢复，但需要维护投影版本。

**C. 仅保存最终快照**：查询简单，但无法可靠回放中间过程，也无法证明最终指标如何由阶段事件推导，不满足本 Spec 的完整观测目标。

已选择：`D-OBS-04 = B`。理由：事件是审计事实，路线、案例、指标和失败摘要由可重建投影生成，既支持断线恢复，也允许读模型独立演进。替换边界为 `ReadModelProjector` 接口；读模型可以使用 SQLite，但只能是派生存储，损坏后必须能从 JSONL 重建。Dashboard 不得将自身聚合结果反写为评测事实。

### 10.5 事件观测粒度方案

**A. 节点级加案例/指标级事件（推荐）**：观察 `node_started`、`node_output`、`metric_computed` 和失败包，足以解释链路、案例和最终指标，事件量与可读性平衡最佳。

**B. 增加字段级事件**：能够观察单个字段变化，适合调试 Interpreter 或 Schema 映射，但事件数量显著增加，且更容易暴露用户输入。

**C. Token 级 LLM 流式事件**：能够展示模型生成过程，但不能替代结构化评测事件，会增加隐私、成本、噪声和重放复杂度；不建议用于 M4.1。

已选择：`D-OBS-05 = A`。理由：节点、案例和指标级事件已经能够解释链路与验收，能够控制事件量、隐私风险和回放成本。替换边界为 `EventDetailPolicy`；字段级或 Token 级实验不得改变标准事件、评分和验收，且不得默认进入公共观测面。无论选择哪一项，Token 流不能成为评分、失败归因或验收状态的依据。

### 10.6 开发诊断信息开放方案

**A. 全部使用安全摘要（推荐默认）**：事件、报告、API 和 Dashboard 始终只包含脱敏摘要与引用，安全边界最清晰。

**B. 双通道诊断（推荐开发增强方案）**：公共观测面继续写入 `safe_summary`；本地显式开启的开发模式可以生成更详细的诊断 Artifact，但该 Artifact 不进入 JSONL、Dashboard、CI、提交记录或外部接口。

**C. 开发阶段完全不脱敏**：调试信息最完整，但会使本地日志、截图、CI 转储、共享目录和错误上报成为敏感数据泄漏点，不建议采用。

无论选择哪一项，API Key、Token、Password、Authorization、Cookie 和密钥类 URL 参数均不得明文写入任何事件或 Artifact。已选择：`D-OBS-06 = A`。理由：企业项目和共享开发环境中，事件、报告、Dashboard、CI 与截图具有不可控扩散路径，统一安全摘要能提供最稳定的边界。根因不得因此被压缩成无意义的“失败”：`error_code`、首因阶段、结构化 `expected_ref/actual_ref`、受影响指标、上游引用和有限长度 `safe_summary` 必须足以解释可验证根因。若实验表明仍不足，必须提出新的版本化诊断方案并重新验收，不能直接关闭脱敏或写入原始 Prompt、堆栈和供应商响应。

### 10.7 节点注册机制

**A. 代码内显式注册表（推荐 M4.1）**：节点通过 Python 注册函数提供 ID、版本、Schema、指标和原理引用，类型检查和测试最直接；扩展时需要修改注册模块。

**B. 版本化节点 Manifest**：节点元数据写入 JSON/YAML Manifest，Dashboard 和 Runner 读取同一份声明，跨语言或跨项目复用更方便；需要额外 Schema 校验和版本兼容策略。

**C. Python Package Entry Point 插件**：模块可独立安装和发现，扩展性最好；部署、加载失败、安全审查和版本冲突处理复杂，不宜在 M4.1 首版引入。

已选择：`D-OBS-07 = B`。理由：版本化 Manifest 将节点元数据从 Dashboard 和 Runner 代码中解耦，便于未来模块跨项目接入和实验比较。替换边界为 `NodeManifestLoader` 接口；Entry Point 等插件机制只能作为后续实验。节点未注册、版本不匹配或 Schema 不可解析时必须进入 `EVALUATOR_ERROR`，不得静默忽略。

### 10.8 Live 评测启动策略

**A. 仅手动确认后启动（推荐）**：按钮先展示模型、调用上限、预计成本信息和凭证状态，用户确认后才执行 `all`；最符合真实 API 的成本与风险控制。

**B. `offline` 默认，`all` 需显式参数或权限**：普通按钮只运行离线门，Live 通过单独按钮、命令参数或受控权限开启，适合 CI 和本地开发并存。

**C. 每次按钮都运行完整 `all`**：观测链路最完整，但会产生不可预期的模型费用、网络依赖和等待时间，不建议作为默认行为。

已选择：`D-OBS-08 = A`。理由：真实模型调用具有成本、延迟和凭证风险，`all` 必须在展示模型、调用上限、预计成本和凭证状态后由用户明确确认；`offline` 可直接运行，不产生 Live 副作用。替换边界为 `LiveGateAuthorizer` 接口；Live 缺少模型或凭证时必须显式失败，不得回退 Fake、默认模型或离线结果。

### 10.9 选型的固定约束

无论维护者选择何种组合，以下约束不得被选型覆盖：事件 Schema 与 Failure Packet 必须保持版本化；`run_id` 必须幂等；M4-before 必须不可覆盖；事件汇总必须与 Scorer、Scorecard 和最终报告一致；Dashboard 不得修改评测结果；敏感凭证不得明文落盘；所有新增方案都必须通过第 11 节验收并记录迁移代价。替代实现不得以运行时隐式 fallback 接入；必须显式声明 `implementation_id`、`implementation_version`、配置指纹和兼容的合同版本。

### 10.10 可插拔与实验协议

为支持“先实验、后决定”的技术演进，本阶段把可替换性定义为合同要求，而不是未来重构目标。至少保留以下边界：

```text
EventStore             JSONL 规范事件源；未来可替换 SQLite 或其他实现
EventTransport         SSE；未来可替换轮询或 WebSocket
EvaluationExecutor     独立子进程；未来可替换 Job Worker
ReadModelProjector     从事件生成可重建读模型
NodeManifestLoader     加载、校验和版本协商 Node Manifest
DiagnosticSerializer   生成结构化安全摘要和 Failure Packet
LiveGateAuthorizer     执行 Live 启动前的确认、预算和权限检查
```

每个实现必须以 Adapter 形式接入，不能让业务节点依赖具体 JSONL、SSE、SQLite、进程或 Manifest 文件读取细节。每次实验都必须使用相同版本的 Dataset、Oracle、Policy、Fixture、评分器和 `RunSpec` 约束，单独生成 `run_id` 与 `experiment_id`，并记录实现身份、版本、配置指纹、耗时、资源成本、失败分布和回放一致性。实验比较至少回答：是否改变了事件语义、是否改变了最终指标、是否改变了失败归因、是否改善了延迟/可靠性/维护成本，以及迁移是否可逆。

替代实现进入默认路径前，必须先通过合同测试、故障注入、断线/重启恢复、事件重放一致性、脱敏验收和可插拔验收；若实验失败，系统必须显式失败并保留失败包，不得自动切回另一实现伪造成功。节点扩展只需提供 Adapter、版本化 Manifest、输入/输出 Schema、指标与原理引用以及事件生产能力；Dashboard 不得为单个新节点增加专用判断分支。

## 11. 验收方式

验收分为合同、执行、解释、安全和回归五层：

1. **合同验收**：合法 `RunSpec`、`EvaluationEvent`、Node Registry 和 Failure Packet 能通过 Pydantic 校验；缺失必填字段、重复事件、乱序事件、未知节点和错误状态转换必须拒绝。
2. **链路验收**：一次 Offline 运行至少产生从 `run_started` 到 `run_finished` 的完整事件序列；数据集、Registry、Component、Integration、Scorer、Determinism、Fingerprint、M4-before、Self-diff、Artifact 和最终验收节点均可追溯。`all` 模式另验 Live blocking/observation 事件和配置状态。
3. **结果一致性验收**：事件重放得到的路线、案例、失败分布、指标和四类最终状态必须与现有 `stage_acceptance.py`、`scorecard.json`、`M4-before` 一致；观测层不能改变 Runner exit code 或业务断言。
4. **失败验收**：注入输入 Schema、Scorer、外部依赖、超时、空结果、解析失败和上游失败时，必须产生正确 Failure Packet、首因阶段和下游阻断状态；不得产生 fallback、cache、partial success 或强制通过。
5. **安全验收**：凭证、Token、Prompt、PII、完整行程和供应商原始响应在 JSONL、Artifact、报告和 API 输出中均不可见；路径和引用不泄露工作区之外的秘密文件。
6. **幂等与回放验收**：同一运行不能重复启动；事件写入不可覆盖；断线后可按序号恢复；重复消费不会重复计数；正式 M4-before 仍保持原哈希。
7. **可插拔验收**：注册一个测试节点，不改 Dashboard 聚合代码即可出现在路线、节点、失败和原理视图；注销或版本不匹配时必须显式失败。
8. **选型实现验收**：确认 JSONL 是唯一规范事件源、SSE 只负责传输、读模型可从事件重建、Runner 在独立子进程中失败可回收、Node Manifest 可版本校验、公共诊断不泄露原始敏感材料，以及 `all` 未经确认不会启动。
9. **替换实验验收**：以测试替代 Adapter 替换任一已选实现，不修改 Runner、Scorer、Dashboard 业务判断即可运行；实验结果必须能与基线按 `run_id`、`experiment_id` 和实现指纹对比，并在失败时保留 Failure Packet。

验收命令至少包括：

```text
venv/Scripts/python -m pytest tests/unit/evaluation/test_m4_1_observability*.py -q
venv/Scripts/python -m pytest tests/integration/test_m4_1_observability*.py -q
venv/Scripts/python evaluation/run_m4_1_acceptance.py --mode offline
```

Live 只在显式配置模型、密钥和预算后执行，不作为普通测试的隐式前置条件。

## 12. 交付顺序与当前实现限制

实施顺序固定为：先交付事件/失败包/脱敏/JSONL EventStore 合同与测试，再接入独立子进程 Offline Runner，随后接入 SSE、可重建 Read Model 和版本化 Node Manifest，最后接入 Live 确认与运行按钮。任何 UI 先于事件合同都属于不可验收的展示层。

本补充首版不宣称 Dashboard、SSE、FastAPI、独立子进程 Runner、Read Model 或 Node Manifest Loader 已存在；它们只有在对应开发任务完成并通过测试后才可称为已实现。当前 M4.1 原有日志和最终报告继续有效，新增观测层必须作为兼容适配器接入，不能修改既有业务结果来制造可观测性。已选方案是默认实现方向，不等于禁止实验；实验必须通过第 10.10 节的替换约定进行。

## 13. 版本记录

| 版本 | 日期 | 变更 |
|---|---|---|
| v1.0 | 2026-08-14 | 建立 M4.1 评测可观测性补充合同、脱敏边界、Failure Packet 和验收方式 |
| v1.1 | 2026-08-14 | 增加待决策技术选型、方案取舍、推荐默认与选择记录格式 |
| v1.2 | 2026-08-15 | 固化 10.1—10.8 选型为 A、B、B、B、A、A、B、A；增加适配器边界、实验协议和替换验收 |
