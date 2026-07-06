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
