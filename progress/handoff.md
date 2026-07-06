# Handoff — v1.1.0 交接文档

> **版本**: v1.1.0 (tag 已发布) | **分支**: `feat/api-integration` | **日期**: 2026-07-06
> **状态**: API 全链路已跑通，可投产验证

---

## 1. 项目概要

旅游规划多 Agent 编排系统，**一主多从 (Orchestrator-Specialist)** 架构。

```
用户输入 → Orchestrator → Planning Agent (DeepSeek LLM) → Execution Agent (高德+途牛) → Evaluation Agent (Mode B) → FinalTravelPlan
```

## 2. 当前版本交付物

| 交付项 | 状态 | 关键指标 |
|--------|------|----------|
| v1.1.0 tag | 已发布到 GitHub | `035c2d4` (batch 7 bridge) + `637a3e2` (actual v1.1.0) |
| 全链路 e2e | 已验证 | 东京 5 天, score 82.0, degraded=false, 1 轮 PASS |
| 测试套件 | 661 passed, 0 regressions | 14 个测试文件, 41 场景全覆盖 |
| API Provider | DeepSeek + 高德 + 途牛 MCP | 双轨架构 (API→stub 降级) |
| Orchestrator→Agent 桥接 | Batch 7 完成 | 3 stub 替换为真实 Agent 调用 |
| README.md | 已创建 | feat/api-integration, 下次合并到 main |

## 3. API 配置

| 服务 | 环境变量 | 状态 | 用途 |
|------|---------|------|------|
| DeepSeek LLM | `DEEPSEEK_API_KEY` + `DEEPSEEK_MODEL=deepseek-chat` | 已配置 (.env) | 行程/景点/餐厅/住宿生成 |
| 高德地图 | `AMAP_API_KEY` | 已配置 (.env) | 地理编码 + 路径规划 + 交通时间 |
| 途牛 MCP | `TUNIU_API_KEY` | 已配置 (.env) | 酒店/机票/门票价格 (JSON-RPC 2.0) |

**密钥文件**: `.env` (gitignored), 模板见 `.env.example`
**依赖**: `requirements.txt` — openai>=1.0.0, python-dotenv>=1.0, pytest>=7.0

## 4. Agent 集群现状

### 4.1 Orchestrator (`agents/orchestrator.py`, 1146 行, version 1.1.0)

- 用户输入解析 (NL → StructuredRequest)
- 任务分解 (4-task DAG)
- Quality Gate 0→1→2→3
- **v1.1.0**: 真正调用 PlanningAgent / ExecutionAgent / EvaluationAgent，不再用 stub
- 桥接层: `_dict_to_draft()` / `_draft_to_dict()` / `_dict_to_validation()` 做 dict↔dataclass 转换
- 降级: Agent 异常时自动回退到原始 stub

### 4.2 Planning Agent (`agents/planning_agent.py`, 1314 行, version 1.1.0)

- 6 个 LLM 方法: research_destination / search_attractions / search_accommodations / search_restaurants / create_itinerary / allocate_budget + revise_itinerary
- LLM 调用: DeepSeek Chat via openai SDK (AsyncOpenAI, base_url=api.deepseek.com)
- 双轨: LLM 可用 → 真实生成; LLM 失败 → `_llm_or_stub()` → stub fallback
- 6 种异常处理: TimeoutError / RateLimitError / ParseError / EmptyResponse / SchemaValidation / unknown

### 4.3 Execution Agent (`agents/execution_agent.py`, 586 行, version 1.0.0)

- 5 项校验: price / time / geography / constraint / risk
- 价格: `tools/price_checker.py` → 途牛 MCP (JSON-RPC 2.0 / SSE) → stub fallback
- 地理: `tools/geo_checker.py` → 高德地理编码 API → Haversine fallback
- 时间: `tools/time_checker.py` → 高德路径规划 API → Haversine fallback
- 风险: `tools/risk_checker.py` — 天气/签证/安全 (stub)

### 4.4 Evaluation Agent (`agents/evaluation_agent.py`, version 1.0.0)

- Mode A: 代码质量评估 (5维度, 1-5分制)
- Mode B: 业务产出评估 (5维度加权, 0-100分制)
- Mode C: Agent 贡献度评估 (消融实验 LOO)
- Mode B 权重: completeness 0.25 / feasibility 0.25 / constraint_sat 0.25 / experience 0.15 / accuracy 0.10

## 5. e2e 实测分析 (东京 5 天, 2026-07-06)

```
输入: 日本东京5天, 2026-12-20→2026-12-25, 2人, 15000元, 美食+文化
输出: score=82.0, degraded=false, iter=1
```

**维度得分**:

| 维度 | 得分 | 分析 |
|------|------|------|
| completeness | 5.0 | 交通/住宿/行程/预算 结构完整 |
| feasibility | 3 | ExecutionAgent 检出 2 个阻断问题, 修订未消除 |
| constraint_satisfaction | 5.0 | 天数/人数/偏好 全部满足 |
| experience_quality | 3 | 5天仅覆盖 5 个不同景点, 部分天次花费过高 |
| information_accuracy | 4 | 酒店/餐厅/景点信息真实, 未满分 |

**识别的问题**:

1. **景点重复** (高优): LLM prompt 缺少"景点不重复"约束 → 浅草寺/明治神宫各出现 2 次
2. **预算失配** (中优): 个别餐厅远超 meal 预算 → 修订循环未强制修正
3. **修订闭环不完整**: Gate 2 识别问题 → Planning 修订 → 但重新校验后 feasibility 仍是 3

## 6. 下一步优化方向

### 优先级排序（推荐）

| 优先级 | 方向 | 当前问题 | 预期收益 |
|--------|------|---------|----------|
| P0 | Planning 推理优化 | 景点重复 / prompt 约束不足 | 单城市 score → 90+ |
| P0 | Planning↔Execution 协作 | 修订未强制消除阻断问题 | Gate 2→修订→重检 闭环 |
| P1 | Tool 稳定化 | Tuniu/高德偶发降级 | 减少 stub fallback |
| P1 | Memory 跨会话 | 每次对话全新上下文 | 用户偏好复用 |
| P2 | 多城市/多日 | 新功能 | 跨城交通/路由 |

### 具体改进点

**A. Planning prompt 硬约束**:
- `search_attractions`: 增加 "每天景点不可重复"
- `_build_itinerary_with_llm`: 增加 "每日总花费 ≤ total_budget / days"
- `allocate_budget`: 考虑真实物价水平而非固定比例

**B. 协作闭环**:
- `_run_planning_cycle`: Gate 2 要求修订时, 将 feasibility 维度反馈传给 PlanningAgent
- `_call_revision`: 传递具体问题（如 "Day 2 晚餐 8000日元 超预算 2 倍"）

## 7. 文件速查

| 类别 | 文件 | 行数 | 职责 |
|------|------|------|------|
| Agent | `agents/orchestrator.py` | 1146 | 主控编排 + Agent 桥接 |
| Agent | `agents/planning_agent.py` | 1314 | LLM 行程生成 (6方法) |
| Agent | `agents/execution_agent.py` | 586 | API 可行性验证 (5校验) |
| Agent | `agents/evaluation_agent.py` | ~350 | 质量评估 Mode A/B/C |
| 核心 | `core/llm_client.py` | 404 | DeepSeek LLM 客户端 |
| 核心 | `core/config.py` | 146 | API 配置中心 |
| 核心 | `core/gate_runner.py` | ~400 | Quality Gate 0-3 |
| 核心 | `core/orchestration_engine.py` | ~500 | 任务DAG/路由/组装/重试 |
| 工具 | `tools/price_checker.py` | ~550 | 途牛 MCP 价格 |
| 工具 | `tools/geo_checker.py` | ~370 | 高德地理编码 |
| 工具 | `tools/time_checker.py` | ~380 | 高德路径规划 |
| 工具 | `tools/risk_checker.py` | ~200 | 天气/签证/安全 |
| 测试 | `tests/test_real_cases.py` | ~400 | 5城市 e2e (14 tests) |
| 测试 | `tests/test_api_integration.py` | ~650 | API 集成 (75 tests) |
| 规格 | `spec/orchestrator_spec.md` | — | 编排器规格 |
| 规格 | `spec/agent_contract.md` | — | Agent 通信契约 |
| 进度 | `progress/lessons.md` | — | 跨轮次经验 (Batch 1-7 + Phase 5) |

## 8. 测试快速入口

```bash
# 全部
venv/Scripts/python.exe -m pytest tests/ -v

# 最小回归 (每次提交)
venv/Scripts/python.exe -m pytest tests/test_gate_runner.py tests/test_integration.py -v

# e2e 真实案例
venv/Scripts/python.exe -m pytest tests/test_real_cases.py -v

# 单 Agent
venv/Scripts/python.exe -m pytest tests/test_orchestrator.py -v
```

## 9. 开发工作流

```
R1 Context → R2 Plan → R3 Execute → R4 Test → R5 Verify → R5.5 Lessons
```

**约束文档**: `devagents/context_agent.md`, `devagents/plan_agent.md`, `devagents/code_agent.md`, `devagents/test_agent.md`
**进度回写**: `progress/<module>.md` — 同步状态 + spec commit + 任务历史
**经验记录**: `progress/lessons.md` — R5.5 写入, commit hash 追溯
**Commit 格式**: `[module] type: 描述` (见 `.gitmessage`)

## 10. Git 里程碑

| Tag | 描述 |
|-----|------|
| v1.0.0 | 基础框架 (4 Agent + stub 数据) |
| **v1.1.0** | **API 全链路接入 (DeepSeek + 高德 + 途牛)** |
| v1.2.0 | (计划) Agent 能力优化 |

---

> **给下一个 Agent**: 项目当前处于"API 刚跑通"的状态。单城市 e2e 可行但质量不够稳定 (82分)。重点投入 Planning 推理优化 + 协作闭环。所有 API key 在 `.env` 中可用。讨论升级方案时请参考 §6 的优先级排序。
