# ADR-002：M2 混合路由与约束优先级

Status: Accepted

Date: 2026-07-30

## Context

M2 需要把用户自然语言转换为可验证约束、澄清 blocker 和下一步交互模式。纯关键词路由无法处理当前计划引用、否定、hard/soft 语义和冲突；完全交给 LLM 又无法保证安全边界、状态引用和失败语义。

## Decision

采用“LLM 解释 + 确定性服务决策”的混合边界：

1. G0 在任何 LLM 调用前执行确定性安全和输入检查；阻断问题直接产生 `WorkflowError`。
2. RequestInterpreter 只返回严格的 `InterpretationResult`，不写状态、不调用工具、不生成旅行事实。
3. ConstraintService 负责类别、日期、币种、人数、否定召回、来源和冲突的归一化，生成新的不可变 `ConstraintSnapshot`。
4. ReadinessEvaluator 根据 Snapshot 和模式判断是否缺少 origin、destination、日期/时长、人数、预算一致性或当前计划引用。
5. InteractionRouter 使用安全优先级、解释结果和 Readiness 结果产生 `RouteDecision`；解释器的 `mode_hint` 是意图信号，不是绕过 blocker 的授权。
6. 用户明确约束优先于用户确认、旅程假设和画像建议；硬约束失败不能被软偏好评分抵消。
7. 所有异常均 fail-fast，M2 不启用 retry、cache、fallback、估算或 partial success。

## Consequences

正面影响：安全阻断和 Schema 校验可复现；澄清问题能够映射到具体 blocker；后续 M3 可直接读取结构化 Snapshot 和 Router 能力；LLM 输出的随机性不会直接改变权限和确定性可行性判断。

代价：需要维护 Interpreter Prompt、领域归一化规则和两套测试；真实 LLM Gate 仍需在固定模型、Prompt、Schema 和预算下重复执行。

## Verification

- 真实模型固定为 `deepseek-v4-flash`；
- M2 Live Gate：9 cases × 2 runs，18 runs，14 network calls，`retry_count=0`；
- Schema、关键字段、hard/soft、否定、澄清 blocker 和安全指标均为 `1.0`；
- 离线 M2 相关测试 120 passed；
- ConstraintService 99%、Router 99%，Interpreter 96%，G0 96%，Readiness 92%。

## Scope boundary

本 ADR 不授权 M3 的外部工具和 Evidence 能力，也不授权 M4 的 Task Graph、规划器或任何外部写操作。
