# core/ — 进度跟踪

**所属阶段**: Phase 0: 基础设施

---

## 文档-代码同步状态

| spec 文件 | spec commit | 对应代码 | 同步状态 | 备注 |
|-----------|-------------|---------|---------|------|
| `spec/agent_contract.md` | a79ba76 | `core/message.py` | 已完成 | AgentMessage / TaskType / ErrorCode / BaseAgent |
| `spec/agent_contract.md` | a79ba76 | `core/context.py` | 已完成 | SharedContext 黑板实现 |
| `spec/system_spec.md` | a79ba76 | `core/context.py` | 已完成 | 状态机 / 持久化 |
| `spec/orchestrator_spec.md` | a79ba76 | `core/context.py` | 已完成 | 15状态枚举 / 状态转换校验 |
| `spec/orchestrator_spec.md` | HEAD | `core/orchestration_engine.py` | 已完成 | TaskDAG / AgentRouter / RetryManager / ResultAssembler |
| `evaluation/gate_definitions.md` | HEAD | `core/gate_runner.py` | 已完成 | GateRunner(Gate 0-3) / GateResult / BlockingIssue / Warning |
| `evaluation/reasoning_quality_rubric.md` | 3af481f | `core/prompt_builder.py` | 已完成 | v1.2.0 R1: PromptBuilder 分层组装 |
| `evaluation/reasoning_quality_rubric.md` | 0936c68 | `core/self_check.py` | 已完成 | v1.2.0 R2: SelfCheck 规则引擎 |
| `evaluation/protocol_quality_rubric.md` | 28a20bd | `core/message_validator.py` | 已完成 | v1.2.0 P1: MessageValidator + 9 Schema |
| `spec/agent_contract.md` | 28a20bd | `core/message.py` | 已完成 | v1.2.0 P1: VersionPolicy + protocol_version |
| `evaluation/protocol_quality_rubric.md` | 8727e26 | `core/context.py` | 已完成 | v1.2.0 P2: ASCII图 + strict_mode + BFS路径 |
| `evaluation/reasoning_quality_rubric.md` | e4a7b07 | `core/cot_pipeline.py` | 已完成 | v1.2.0 R3: CoTPipeline 4步推理链 + wiring收尾 |

## 任务历史

| 日期 | 任务 | 状态 | 备注 |
|------|------|------|------|
| 2026-07-05 | 实现 core/message.py | 已完成 | AgentMessage/TaskType/ErrorCode/AgentIdentity/BaseAgent/AgentRegistry，426行 |
| 2026-07-05 | 实现 core/context.py | 已完成 | ContextStatus(15状态)/LogEntry/SharedContext黑板/to_dict/from_dict，387行 |
| 2026-07-05 | 实现 core/__init__.py | 已完成 | 完整公共API导出 + __version__ |
| 2026-07-05 | 编写 tests/test_message.py | 已完成 | 80+ 测试，覆盖全部5条validate规则/枚举/数据类/ABC |
| 2026-07-05 | 编写 tests/test_context.py | 已完成 | 50+ 测试，覆盖状态转换/日志/序列化/生命周期 |
| 2026-07-05 | Mode A 代码质量评估 | 已完成 | 评分 3.85→P0修复，覆盖率达到96% |
| 2026-07-05 | P0 健壮性修复 | 已完成 | validate()对非字符串message_id和非枚举task_type不再崩溃 |
| 2026-07-06 | 实现 core/gate_runner.py | 已完成 | GateRunner全部4个Gate、GateResult/BlockingIssue/Warning，208行 |
| 2026-07-06 | 实现 core/orchestration_engine.py | 已完成 | TaskDAG/AgentRouter/RetryManager/ResultAssembler，214行 |
| 2026-07-06 | 更新 core/__init__.py | 已完成 | 导出gate_runner + orchestration_engine全部公共API |
| 2026-07-06 | 编写 tests/test_gate_runner.py | 已完成 | 55 tests，覆盖Gate 0-3全部判定分支 |
| 2026-07-06 | 编写 tests/test_orchestration_engine.py | 已完成 | 44 tests，覆盖TaskDAG/路由/重试/整合 |
| 2026-07-06 | Phase 5: LLM 切换 Anthropic→DeepSeek | 已完成 | llm_client.py: openai SDK (AsyncOpenAI) + base_url→api.deepseek.com + DEEPSEEK_API_KEY; 公共API不变 |
| 2026-07-06 | Phase 5: API 配置重构 | 已完成 | config.py: Mapbox→高德(amap_api_key), Amadeus→途牛(tuniu_api_key), auth_headers()→auth_params(), 新增 tuniu_mcp_hotel/flight/ticket 三端点 |
| 2026-07-07 | v1.2.0 Step 0: 数据模型集中定义 | 已完成 | models/reasoning.py + check.py + feedback.py + protocol.py (eb74644) |
| 2026-07-07 | v1.2.0 R1: PromptBuilder + YAML模板 | 已完成 | core/prompt_builder.py (390行) + 3模板文件 + planner_playbook.md §2更新 (3af481f) |
| 2026-07-07 | v1.2.0 R2: SelfCheck规则引擎 | 已完成 | core/self_check.py (456行)，5项纯计算检查 (0936c68) |
| 2026-07-07 | v1.2.0 P1: MessageValidator + 版本化 | 已完成 | core/message_validator.py (293行) + 9 JSON Schema + VersionPolicy (28a20bd) |
| 2026-07-07 | v1.2.0 P2: StateMachine完善 | 已完成 | ASCII状态图 + strict_mode + force_status() + BFS路径 (8727e26) |
| 2026-07-07 | v1.2.0 测试策略优化 | 已完成 | pytest.ini slow marker + 6条真实API冒烟 + 成都快速e2e (3ba9fae) |
| 2026-07-08 | v1.2.0 R3: CoTPipeline + wiring收尾 | 已完成 | core/cot_pipeline.py (1005行) + orchestrator wiring (e4a7b07) |
