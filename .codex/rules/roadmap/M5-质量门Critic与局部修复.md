# M5：质量门、Independent Critic、Targeted Repair 与量化 Eval

> 文档状态：Frozen v1.0，可在 M4.3 验收后编写阶段 Plan  
> 本阶段性质：求职核心质量闭环，不扩展业务范围  

## 1. 阶段目标

建立统一 G0～G5 GateRunner，将商务差旅的确定性可行性与语义质量评审分离；Critic 输出带会议、政策、计划项或 Evidence 引用的问题；RepairController 执行有界补证或局部补丁；用 M4.1 冻结差旅评测集量化证明质量闭环收益。M5 完成核心质量闭环并淘汰 legacy 自由文本 L1/L2 主链路。

## 2. 前置条件

- M4.1、M4.2、M4.3 已验收，M4 历史回归继续通过；
- BusinessTripScope、MeetingRequirement、PolicyRule/PolicyEvidence、PreMeetingLodgingRequirement 已冻结；
- M4.3 可生成带通用公司政策、去程、候选级会前住宿、市内交通的结构化 PlanCandidate、EvidenceSnapshot、TaskResult；
- Schedule/Budget 逻辑已有确定性测试；
- 计划项有稳定 ID 和 evidence refs；
- Orchestrator 的失败传播、预算和状态版本已验收；
- M4.1 差旅 Golden Cases/基线及 M4.3 Offline/Live 纵向报告版本可追踪。

## 3. 允许修改范围

- `src/application/gate_runner.py`、`repair_controller.py`；
- `src/domain/services/validators/`；
- `src/agents/critic.py`；
- Validation/Repair 类型化契约；
- Composer 结构化修订入口；
- legacy L1/L2/loop 的迁移或删除；
- `evaluation/` Runner、rubrics、reports、golden tests。

## 4. 禁止事项

- 不实现 G6、外部写操作、事件订阅或反馈学习；
- Critic 不调用供应商工具、不直接改 Plan；
- BLOCKING 不得被总分抵消；
- 非 structural issue 禁止整份重生成；
- 达到轮次上限不视为成功；
- Critic 失败不得跳过 G4；
- 不输出无引用的事实问题；
- 不只展示成功样例或删除退化案例。
- 不新增国际/港澳台、多人、多城市、多会议、城际中转、返程、景点、员工等级或完整 RAG 能力；
- 不引入舱等/席别、汇率、审批流、特殊人群等 M4.3 未冻结字段作为阻断条件；
- 不建设通用 Judge 平台、在线标注平台或自动 Prompt 优化系统。

## 5. GateRunner 协议

```python
class Gate(Protocol):
    @property
    def gate_id(self) -> GateId: ...
    def evaluate(self, context: GateContext) -> GateResult: ...

class GateRunner:
    def run_until_blocked(self, context: GateContext) -> ValidationReport: ...
```

规则：

- G0→G5 固定顺序；
- BLOCKING 立即停止，WARNING 进入报告；
- Gate 异常转换为 WorkflowError；
- 每次运行绑定 plan/evidence/constraint version；
- 修复后重跑受影响 Gate，交付前全量重跑；
- GateResult 只能由 GateRunner 生成，Composer 不可修改。

## 6. Gate 要求

### G0：安全与输入

检查权限、Schema、注入标志、PII 使用范围和危险/越权意图。复用 M2 逻辑并迁入统一接口。

### G1：规划就绪

检查 blocker、约束冲突、Snapshot/Scope 状态和计划引用。至少检查出发地、会议地点、会议时间与时区、人数和影响能力选择的 hard constraints。返程默认不规划，不得作为 blocker；`return_scope` 必须明确。用户可补充的 blocker 进入 CLARIFYING；系统通用政策缺失不向用户追问，留给 G2 作为证据失败。

### G2：证据就绪

检查覆盖率、status、TTL、来源、冲突和关键缺失。每个 required capability 必须有可用 Evidence：通用政策、去程、仅对该候选必需的一晚会前住宿、市内交通和会议地点。关键证据 stale/conflicting/missing 为 BLOCKING，禁止缓存回退或部分交付；某住宿候选失败不得连带淘汰独立可行的无住宿候选。

### G3：确定性可行

至少检查：

- hard constraints；
- 会议日期、时区、最晚到达时间和到达缓冲；
- 直达航班/铁路和最后一段市内交通的时序可行性；
- 每个需要过夜的候选具有唯一的一晚会前住宿需求、正确入住/退房日期和酒店到会议地点通勤；
- 通用政策中的去程总价上限、单晚酒店总价上限、本地交通许可、会议最小提前到达时间和版本适用性；
- 全部金额使用 CNY，检查去程、单晚酒店、本地交通与总额；供应商未承诺的税费不得伪造；
- plan/candidate/evidence 引用完整性。

所有算术和时间逻辑使用纯代码。

### G4：语义与体验

Critic 检查方案是否符合商务差旅语境：缓冲是否解释充分、方案差异是否有意义、政策与个人偏好的冲突是否说明、红眼或过早出发等体验风险是否披露、备选是否真正改变成本/稳健性/舒适度。Critic 不验证实时价格、班次或路况，只判断 Plan 对已验证 Evidence 的使用和解释是否一致。

### G5：交付完整

检查 Delivery Schema、版本/状态、`planning_horizon`、`return_scope`、required night coverage、assumptions、warnings、tradeoffs、alternatives、policy/evidence refs、validation report、金额/时间格式和敏感信息。缺失即失败。

## 7. Critic 契约

```text
CriticReport
  report_id
  plan_version
  rubric_version
  issues[]
  dimension_assessments[]
  evidence_refs[]
```

每个 issue 包含 severity、issue_type、affected_plan_item_ids、constraint/evidence refs、说明和 repair strategy。解析失败、空响应、版本不匹配或事实问题无引用均为 FAILED。

## 8. RepairController

| issue type | 动作 |
|:---|:---|
| evidence_missing/stale | 定向 research task |
| policy_missing/conflicting | 定向政策补证；仍失败则 FAILED 或 CLARIFYING |
| meeting_deadline_miss | 替换去程或市内交通并重算缓冲 |
| lodging_night_uncovered | 为候选唯一会前住宿夜重查酒店并重算通勤/预算 |
| stay_unavailable/policy_violation | 换住宿并重算市内通勤/预算/政策 |
| local_transfer_missing | 定向市内路线 research task |
| budget_over | 替换不违反 hard policy 的边际成本项 |
| preference_gap | Composer 局部 Patch |
| hard_constraint_conflict | 回 CLARIFYING |
| structural_infeasible | 允许生成新骨架 |
| schema_error | 只修格式，不造缺失内容 |

RepairPatch 声明 base version、affected IDs、operations、expected effects、required gates。应用前检查版本，应用后创建新版本，禁止原地修改。

收敛规则：

- 默认最多 2 轮；
- 连续两轮 BLOCKING 集合无减少则 FAILED；
- 同一 issue 连续复现达到阈值则 FAILED；
- 每轮计入调用、时间和成本预算；
- 最终交付前 G0～G5 全量通过。

## 9. 评分与 Eval

hard pass 与质量评分分离，仅 G0～G3 无 BLOCKING 后计算质量向量。质量维度使用 policy、meeting_temporal、budget、comfort、robustness、evidence；若展示综合排序，必须同时给出权重版本和分项。

Runner 按数据集版本输出 JSON 与 Markdown，至少包含：

- `hard_constraint_pass_rate`；
- `meeting_deadline_pass_rate`；
- `policy_compliance_accuracy`；
- `lodging_night_coverage_rate`；
- `local_transfer_coverage_rate`；
- `return_scope_disclosure_rate`；
- `evidence_coverage_rate`；
- `unsupported_fact_rate`；
- `first_pass_success_rate`；
- `repair_success_rate`；
- `repair_scope_precision`；
- `clarification_precision`；
- `p50/p95_latency_ms`；
- `llm_calls/tool_calls/token_usage/cost_per_case`；
- 按 case tag、Gate、Agent/Tool 和错误类型划分的失败分布。

评测纪律：

- 失败定位到 `case_id`、trace 和责任阶段；
- 不同数据集版本只比较共同样例子集；
- 质量提升不得以未解释的成本/延迟失控换取；
- LLM Judge 只评价语义维度，不替代确定性断言；
- 退化案例必须保留并记录修复、接受或阻断结论。


### 9.1 Live Online Eval

M5 必须用真实 LLM 验证 Critic 和 Repair，Fake 只能验证确定性错误路径：

- 使用 6 条开发案例和人工标注缺陷对，覆盖会议迟到、政策冲突、候选所需会前酒店缺失、酒店超限、市内交通缺失、返程范围误报、证据缺失和不可修复问题；其中“可修复问题”和“不可修复问题”两条各重复 2 次；
- 报告至少包含 `schema_pass_rate`、`hard_constraint_pass_rate`、`critic_issue_recall`、`critic_false_positive_rate`、`repair_success_rate`、`blocking_escape_rate`、延迟、Token、成本和失败分类；
- 阈值按 rubric 版本固定，不能用临时删案例或只展示成功样例提高通过率；
- Critic/Repair 的真实调用失败、解析失败、无引用问题或不收敛都阻断 M5；不得跳过 Critic 或切换 Fake 继续；
- 每次 Prompt、模型、Schema、Rubric 或 Gate 逻辑改变都必须重跑该 Online Eval；失败响应脱敏后进入 Offline 回归集。
Live Critic/Repair 单次验收最多 10 次 LLM 调用、`retry_count=0`；存在版本化价格表时估算成本上限为 5 CNY，否则以 Token 与调用数预算阻断。真实工具事实全部使用 M4.3 冻结 Evidence Fixture，M5 不重复消耗供应商调用预算。
Offline Critic/Repair 测试用 Fake 或 Fixture 精确制造无引用、非法 JSON、空响应、超时、错误版本、不收敛和预算耗尽；Live Online Eval 不能替代故障注入，Fake 通过也不能证明真实 Critic/Repair 达到阈值。

真实 API 验收由用户负责手动执行。Codex 不自动调用真实 LLM 或执行 Online Eval，只准备人工标注案例、阈值、命令和脱敏报告格式。用户应通过 `start-local.ps1` 或本阶段明确的等价启动方式加载真实配置；未提供人工执行结果时，Live Online Eval 状态为 `PENDING_MANUAL_ACCEPTANCE`，不得标记 M5 完成。

## 10. Legacy 迁移

- `review/l1.py` 拆入 validators；
- `review/l2.py` 替换为 CriticAgent；
- `engine/loop.py` 退出新 Use Case 主链路；
- 保留一阶段对照测试后移除；
- 删除前用 `rg` 证明生产调用者为零；
- golden tests 比较约束和结构，不固定自然语言。

## 11. 实现顺序

1. Gate/Result/Report 契约；
2. G0/G1；
3. G2；
4. G3 纯代码 validators；
5. Critic Schema/Prompt/Fake；
6. G4/G5；
7. RepairIssueRouter；
8. RepairPatch/版本和收敛；
9. legacy 迁移；
10. M4.1 差旅数据集完整 Pipeline Eval；
11. 真实 LLM Critic/Repair Online Eval；
12. baseline/current 对比和失败分类报告；
13. 独立 Review。

## 12. 测试矩阵

- 每个 Gate：pass、warning、blocking、异常、版本不匹配；
- G3：跨午夜/时区、航班/铁路到达边界、最后一段市内交通、required night 缺失、酒店政策边界、CNY 预算边界和悬空引用；
- Critic：合法、无引用、非法 JSON、空响应、错误版本、注入、超时；
- Repair：每类 issue、最小范围、版本冲突、局部重验、全量终验、无收敛、轮次/预算耗尽；
- E2E：正常参会方案、一次修复后通过、政策/候选所需会前酒店/市内交通证据缺失失败、hard policy conflict 澄清、Critic 异常失败、循环不收敛失败；
- Live Eval：真实 Critic 缺陷检出、修复成功/失败、重复运行波动和成本上限。

新增代码覆盖率 ≥ 90%，确定性 validators ≥ 95%。

## 13. 阶段验收门

- [ ] G0～G5 统一运行并绑定版本；
- [ ] BLOCKING 不被总分抵消；
- [ ] Critic issue 都有 refs；
- [ ] Repair 是版本化局部 Patch；
- [ ] 无收敛和上限耗尽显式 FAILED；
- [ ] legacy L1/L2 退出主链路；
- [ ] 全量 Gate 通过才产生正常 Delivery；
- [ ] M4.1 差旅数据集全部可执行，无原因不明的 `NOT_SUPPORTED`；
- [ ] 首场会议到达时限、政策合规、候选级会前住宿需求和市内交通覆盖均由确定性 Gate 验证；
- [ ] 返程未规划不会被 G5 漏披露；
- [ ] 报告可复现并包含质量、延迟、成本和失败分布；
- [ ] 每个退化案例有处理结论；
- [ ] 用户手动执行的 Live Online Eval 达到 rubric 阈值，报告包含重复运行波动、真实失败和成本；
- [ ] 无 fallback/cache/forced pass/partial success。

## 14. 交付清单

- GateRunner、G0～G5、validators；
- CriticAgent、RepairController、Patch 与收敛检测；
- legacy 迁移和测试；
- 版本化 Pipeline Eval Runner；
- baseline/current 对比、失败分类和案例 Trace 索引；
- M5 ADR：硬 Gate、质量向量、评测阈值和 Repair 边界。

## 15. 版本记录

| 版本 | 日期 | 变更 |
|:---|:---|:---|
| Frozen v1.0 | 2026-08-12 | 按求职 MVP 冻结 G0～G5、带引用 Critic、有界 Targeted Repair 和 6 条 Live 缺陷集；移除舱等、汇率、特殊人群、中转与通用评测平台扩张。 |
