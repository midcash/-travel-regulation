# progress/ — 进度跟踪索引

---

## 模块碎片索引

| 模块 | 碎片文件 | 所属阶段 | 状态 |
|------|---------|---------|------|
| core/ (框架内核) | [core.md](core.md) | Phase 0 | 已完成 |
| models/ (数据模型) | [models.md](models.md) | Phase 0 | 已完成 |
| tools/ (工具集) | [tools.md](tools.md) | Phase 0 | 已完成 |
| Orchestrator | [orchestrator.md](orchestrator.md) | Phase 1 | 已完成 |
| Planning Agent | [planning.md](planning.md) | Phase 2 | 已完成 |
| Execution Agent | [execution.md](execution.md) | Phase 2 | 已完成 |
| Evaluation Agent | [evaluation.md](evaluation.md) | Phase 3 | 已完成 |
| tests/ (测试) | [tests.md](tests.md) | Phase 4 | 已完成 |

---

## 总体阶段进度

| 阶段 | 状态 | 开始日期 | 完成日期 |
|------|------|---------|---------|
| Phase 0: 基础设施 (core/, models/, tools/) | 已完成 | 2026-07-05 | 2026-07-06 |
| Phase 1: Orchestrator | 已完成 | 2026-07-06 | 2026-07-06 |
| Phase 2: Planning Agent + Execution Agent | 已完成 | 2026-07-06 | 2026-07-06 |
| Phase 3: Evaluation Agent | 已完成 | 2026-07-06 | 2026-07-06 |
| Phase 4: 集成测试 + 消融实验 | 已完成 | 2026-07-06 | 2026-07-06 |
| Phase 5: API Provider 切换 (DeepSeek + 高德 + 途牛 MCP) | 已完成 | 2026-07-06 | 2026-07-06 |

**状态说明**: 未开始 → 进行中 → 已完成 → 已评估

---

## 准备文件清单 (已完成)

以下规格/约束文件在准备阶段已完成，编码阶段开始后不再单独追踪：

| 目录 | 文件数 | 状态 |
|------|--------|------|
| `spec/` | 6 | 已完成 (2026-07-05) |
| `playbooks/` | 4 | 已完成 (2026-07-05) |
| `evaluation/` | 8 | 已完成 (2026-07-05) |
| `devagents/` | 4 | 已完成 (2026-07-05) |
| 根配置 (CLAUDE.md, PROGRESS.md, VERSION) | 3 | 已完成 (2026-07-05) |

---

## 变更日志

| 日期 | 变更类型 | 涉及文件 | 原因 |
|------|---------|---------|------|
| 2026-07-05 | 创建 | 全部 24 个 .md 文件 | 项目初始化，完成所有准备文件 |
| 2026-07-05 | 重构 | PROGRESS.md → progress/*.md | 拆分为 per-module 碎片，避免并行开发时的合并冲突 |
| 2026-07-05 | 修复 | CLAUDE.md, code_agent.md, gate_definitions.md, agent_contract.md | 约束推演发现5个关键缺口（Chain A/C/D）：Gate 2伪代码缺REJECT、Gate 0/1阈值不一致、Code Agent §6缺性能+测试自检、合约缺消息类型 |
| 2026-07-06 | 实现 | agents/ + 164 tests | Batch 2 全面铺开：4个业务Agent完整实现 + 164 tests (85% cov) |
| 2026-07-06 | 实现 | tests/test_integration.py, tests/test_ablation.py | Batch 3 集成测试+消融实验：41/41 场景全覆盖，LOO+AIS+360°+协同分析 |
| 2026-07-06 | 新增 | progress/lessons.md + CLAUDE.md R5.5 + devagents 约束更新 | 创建跨轮次经验记录机制：Code/Test Agent 写入，Context Agent 读取 |
| 2026-07-06 | 实现 | core/llm_client.py + agents/planning_agent.py + 60 tests | Batch 4: Planning Agent 接入 LLM — LLMClient + 6方法改造，LLM优先→stub降级 |
| 2026-07-06 | 实现 | core/config.py + tools/price|geo|time_checker.py + agents/execution_agent.py + 75 tests | Batch 5: Execution Agent 接入真实 API — AmadeusPriceClient + NominatimClient + MapboxDirectionsClient，全部双轨架构（API优先→stub降级），degraded 标记传播 |
| 2026-07-06 | 实现 | tests/test_real_cases.py + 14 tests | Batch 6: 集成验证 + 真实案例 — 5个真实城市(东京/巴黎/纽约/成都/曼谷)端到端跑通，降级场景+跨领域验证，663 tests 0 regressions |
| 2026-07-06 | 重构 | core/llm_client.py + core/config.py + tools/price|geo|time_checker.py + tests | Phase 5: API Provider 切换 — LLM: Anthropic→DeepSeek (openai SDK), 地图: Mapbox/Nominatim→高德, 价格: Amadeus→途牛 MCP (JSON-RPC 2.0 + SSE 解析), 新增 .env.example, E2E 验证: DeepSeek/高德Geocode/高德Directions/途牛Hotel/途牛Flight 全部 PASS |
| 2026-07-07 | 新增 | evaluation/ (plan_quality_rubric.md 修改 + meta_rubric.md + memory/tool/rag/reasoning/protocol/safety/evolution_quality_rubric.md + system_metrics.md + metrics.md 修改 + quality_criteria.md 修改) + progress/lessons.md | v1.2.0 评估体系升级 — Step 1-10 全部完成: (1) Mode B 评分校准+维度地板规则+JSON锚点 (2-8) 7 个模块 Layer 2 评估量表新建 (9) Mode D 系统级指标+评估体系统一索引 (10) lessons 经验回灌+Change Log 更新。合计新增 8 个 .md 文件，修改 5 个已有文件。只建尺子不改代码。 |
| 2026-07-08 | 实现 | models/ (reasoning.py + check.py + feedback.py + protocol.py + __init__.py) + core/ (prompt_builder.py + prompt_templates/ + self_check.py + message_validator.py + message_schemas/ + message.py + context.py) + playbooks/planner_playbook.md + tests/ (conftest.py + test_real_cases.py + test_api_integration.py) + pytest.ini | v1.2.0 Step 0+R1+R2+P1+P2 并行开发 — Step 0: 4个新数据模型文件 (13 dataclass); R1: PromptBuilder (390行) + 3 YAML/JSON 模板; R2: SelfCheck 规则引擎 (456行, 5项纯计算); P1: MessageValidator (293行) + 9 JSON Schema + VersionPolicy 版本协商; P2: StateMachine ASCII图 + strict_mode + BFS路径 + 死角验证; 测试策略: pytest.ini slow marker + 成都快速e2e + 6条真实API冒烟。424 passed, 19 deselected。 |
| 2026-07-09 | 实现 | agents/orchestrator.py + agents/planning_agent.py + tests/test_models.py + tests/test_orchestrator.py + tests/test_planning_agent.py | v1.2.0 R4 StructuredFeedback — Orchestrator 从 validation/quality 构造问题定位级 RevisionFeedback；Planning revision prompt 注入 format_for_prompt()；复用现有测试文件新增 5 个用例。默认全套 654 passed, 22 deselected。 |
| 2026-07-09 | 实现 | core/message.py + core/message_validator.py + tests/test_message.py + tests/test_message_validator.py + agents/*.py | v1.2.0 P3 ErrorRecovery — MessageValidator.auto_fix() 3 类修复 (dimensions 嵌套→扁平 / correlation_id 生成 / timestamp 修正) + AgentMessage.validate() 集成 auto_fix + 4 Agent handler 适配返回类型。新增 12 tests, 666 passed, 0 regressions。 |

---

## 评估知识更新影响追踪

| 评估知识变更 | 需检查的源文件 | 需检查的被约束文件 | 检查日期 | 状态 |
|-------------|---------------|-------------------|---------|------|
| — | — | — | — | — |

**检查清单**（每次评估知识更新后执行）:
- [ ] `evaluation/` 下的 rubric/gate/metrics/scenarios
- [ ] `playbooks/evaluator_playbook.md` (Mode A/B/C)
- [ ] `spec/evaluator_spec.md`
- [ ] `devagents/code_agent.md` §7 (代码质量约束)
- [ ] `devagents/test_agent.md` §7 (测试质量约束)
- [ ] `devagents/plan_agent.md` §7 (方案合规约束)
