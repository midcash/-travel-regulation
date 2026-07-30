# M2 Handoff

Stage: M2

Delivered: `RequestInterpreter`、G0/G1 预检与就绪评估、`ConstraintService`、澄清 blocker 计算、混合 `InteractionRouter`，以及 M2 离线和真实 LLM Gate。

Contracts: `InterpretationResult` Schema 版本 `1.0`；Prompt 版本 `m2-request-interpreter-v2`。解释输出必须经过 Pydantic 校验，约束在 `ConstraintService` 中归一化后才能进入 Readiness 和 Router。

Routing: Interpreter 的 `mode_hint` 表达用户意图；ReadinessEvaluator 判断必填字段、冲突和当前计划引用是否就绪；InteractionRouter 按 G0、ACTION、REFINE/REPLAN、CLARIFY、ANSWER/COMPARE/PLAN 的优先级产生下一步模式。LLM 不直接写 TripState，也不调用外部工具。

Security: G0 在 LLM 前执行输入、认证、PII、危险动作、越权、Prompt Injection 和非法日期检查。原始中文 Prompt Injection 用例已由 G0 规则修复并加入回归；没有通过改写用例来掩盖缺陷。

Tests: 默认离线测试 314 passed；M2 相关定向测试 120 passed；新增代码覆盖率满足阶段阈值；真实 Gate 18 runs、14 network calls、2 runs/case、retry 0，脱敏证据位于 `evaluation/reports/M2-live-interpreter.json`。

Failure policy: LLM 配置、超时、非法 JSON、Schema 不匹配、约束归一化失败和路由不确定性均显式失败；没有缓存、估算、备用供应商、默认 PLAN、重试或部分成功。

Next stage prerequisites: M3 可直接读取 `ConstraintSnapshot`、`RouteDecision.required_capabilities` 和结构化解释结果，接入 Tool Adapter、Evidence Registry 和 Candidate Pool。M3 不得绕过 G0、ConstraintService、Readiness 或 Router，也不得把实时事实写入解释结果。

Out of scope: 外部地图/酒店/航班/门票/天气调用、Evidence TTL、Candidate、Task Graph、混合规划、Critic、Repair、Action、SQLite、缓存、重试、fallback、付款和预订。

Current implementation limitations: 当前 Live Gate 使用固定最小 TripState 证明 REFINE/REPLAN 的计划引用路径，但尚未实现真实计划版本持久化或事件驱动重规划；这些属于后续阶段能力，不应在 M2 中伪装为已完成。
