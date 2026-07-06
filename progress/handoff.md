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
| **v1.2.0** | **评估体系全面升级 (进行中)** |

---

## 11. v1.2.0 执行计划 — 评估体系升级

> **目标**: 建立覆盖全模块的评估量表体系，支撑后续评估驱动开发。
> **原则**: 只建尺子不改代码。所有产出为 evaluation/ 下的 .md 量表文件，不修改 agents/ 下的业务代码。
> **总依赖**: 无。以下所有步骤均不依赖新模块代码，以目标架构设计意图为锚点。

---

### Step 1: Mode B 评分校准 + 元评估基础

**目标**: 修复现有唯一已知 bug，建立"尺子的尺子"。

**背景**: 
- `evaluation/plan_quality_rubric.md` 示例 2 中 completeness=2.5 → 总分 65.5，但判定矩阵说 <60 才是 REJECT。completeness 2.5（缺住宿+行程+交通）按公式算出的分与实际判定不符。
- 需要为每个维度添加"最低分/最高分 JSON 示例"作为锚点，消除"评估者不同则分数不同"的问题。

**需读取的文件**:
- `evaluation/plan_quality_rubric.md`（完整）
- `evaluation/quality_criteria.md`（Layer 2 部分）
- `evaluation/gate_definitions.md`（Gate 2 部分）
- `progress/lessons.md`（搜索 "plan_quality_rubric" 和 "Mode B" 和 "65.5" 和 "score" 和 "completeness" 相关内容）

**需创建/修改的文件**:
- `evaluation/plan_quality_rubric.md` — 修改：为 5 个维度各补充一个最低分 JSON 示例和一个最高分 JSON 示例；修复 §9 示例 2 或公式使其自洽
- `evaluation/meta_rubric.md` — 新建：元评估量表。定义评估体系自身的质量标准（rubric 稳定性、锚点校准度、覆盖率、评分一致性），包含 3 维度 × 5 级锚点 + 判定矩阵

**验收标准**:
- `plan_quality_rubric.md` 中两个示例各自带入公式计算，结果与判定矩阵一致（偏差 ≤ 1 分）
- `meta_rubric.md` 包含 ≤3 个维度的评分锚点 + 计算公式 + 判定矩阵
- 两个文件版本号更新为 1.1.0，变更日志追加

---

### Step 2: Memory Quality Rubric

**目标**: 建立记忆模块的 Layer 2 评估量表。

**背景**:
- v1.2.0 目标架构定义 Memory 为四层体系：UserProfile（用户画像持久化）、SessionMemory（会话工作记忆）、EpisodicMemory（历史方案检索）、MemoryManager（统一读写接口）
- 当前系统仅有 SharedContext（会话级，无持久化），Memory 模块完全空白
- 此量表用于后续 Memory 模块开发时的评估驱动

**评估维度建议** (4个):
| 维度 | 权重 | 核心指标 |
|------|------|---------|
| 检索命中率 (Recall) | 30% | 给定查询，历史相关记忆是否被检索到 |
| 偏好一致性 (Consistency) | 25% | 用户偏好（素食/不购物等）是否跨会话保持一致 |
| 压缩保真度 (Fidelity) | 25% | 容量限制下，关键信息是否保留、非关键信息是否被正确裁剪 |
| 跨会话复用率 (Reuse) | 20% | 新会话中，历史记忆被实际引用的比例 |

**需读取的文件**:
- `evaluation/plan_quality_rubric.md`（作为格式参考模板）
- `evaluation/quality_criteria.md`（Layer 2 规范）
- `progress/handoff.md` §11（本文件，了解 Memory 目标架构）

**需创建的文件**:
- `evaluation/memory_quality_rubric.md` — 新建。4 维度 × 5 级锚点 + 加权公式 + 判定矩阵 + 2 个计算示例

**验收标准**:
- 4 个维度各含 5 级评分锚点（1-5分），每级有明确的判定标准
- 含加权计算公式和 0-100 分判定矩阵
- 含 2 个完整的计算示例（一个高分方案、一个低分方案）
- 版本 1.0.0，变更日志初始化

---

### Step 3: Tool Quality Rubric

**目标**: 建立工具系统的 Layer 2 评估量表。

**背景**:
- v1.2.0 目标架构定义 Tool System 为 MCP 标准化工具注册/发现/调用体系（ToolRegistry + MCPClient）
- 当前 tools/ 下 4 个独立 checker，无统一注册/发现/降级策略
- lessons.md 中大量问题与工具降级、API 不可用相关（Batch 5 途牛 SSE 解析、高德 key 管理、Batch 6 降级路径验证）

**评估维度建议** (4个):
| 维度 | 权重 | 核心指标 |
|------|------|---------|
| API 可用率 (Availability) | 30% | 首次调用成功率、降级触发频率 |
| 响应延迟 (Latency) | 25% | P50/P99 延迟是否在目标范围内 |
| 结果准确率 (Accuracy) | 25% | 返回结果与真实值偏差（价格偏差%、坐标偏差km） |
| 降级优雅度 (Degradation) | 20% | 降级时 stub 数据质量、降级传播范围（部分 vs 全量） |

**需读取的文件**:
- `evaluation/plan_quality_rubric.md`（格式模板）
- `tools/price_checker.py`（了解途牛 MCP 当前实现）
- `tools/geo_checker.py`（了解高德 API 当前实现）
- `progress/lessons.md` Batch 5 + Batch 6 部分
- `progress/handoff.md` §11

**需创建的文件**:
- `evaluation/tool_quality_rubric.md` — 新建

**验收标准**: 同 Step 2（4 维度 × 5 级锚点 + 公式 + 判定矩阵 + 2 示例）

---

### Step 4: RAG Quality Rubric

**目标**: 建立知识检索模块的 Layer 2 评估量表。

**背景**:
- v1.2.0 目标架构定义 RAGEngine：目的地知识库 + 历史方案检索 + 实时价格缓存
- 当前系统无 RAG 模块，LLM 完全依赖自身训练数据
- 评估维度需覆盖检索质量和知识质量两个子维度

**评估维度建议** (4个):
| 维度 | 权重 | 核心指标 |
|------|------|---------|
| 检索精度 (Precision) | 30% | recall@5 / precision@5 / MRR |
| 知识新鲜度 (Freshness) | 25% | 价格数据距今天数、景点信息最后更新时间 |
| 检索延迟 (Speed) | 20% | 单次检索 P50/P99 延迟 |
| 知识覆盖度 (Coverage) | 25% | 目的地覆盖率、信息完整度（名称/位置/价格/评价） |

**需读取的文件**:
- `evaluation/plan_quality_rubric.md`（格式模板）
- `progress/handoff.md` §11

**需创建的文件**:
- `evaluation/rag_quality_rubric.md` — 新建

**验收标准**: 同 Step 2

---

### Step 5: Reasoning Quality Rubric

**目标**: 建立推理模块的 Layer 2 评估量表。

**背景**:
- v1.2.0 目标架构定义 Reasoning 包含：PromptBuilder（分层 prompt 组装 + 硬约束注入）、SelfCheck（Planning 输出前轻量自检）、StructuredFeedback（修订反馈结构化）、ChainOfThought（分步推理链）
- 当前 Planning Agent 1314 行，6 个 LLM 方法，但 prompt 约束不足（景点重复、预算失配）、修订反馈非结构化
- handoff.md §6 e2e 实测 3 个问题直接对应 Reasoning 维度

**评估维度建议** (5个):
| 维度 | 权重 | 核心指标 |
|------|------|---------|
| 约束满足率 (Constraint) | 30% | 硬约束满足率、软约束匹配率（复用 CON 维度逻辑） |
| 幻觉率 (Hallucination) | 20% | 虚构地点/价格的比例 |
| 自检通过率 (SelfCheck) | 15% | Planning 自检首次通过率 vs 被 Execution 退回率 |
| 修订收敛轮次 (Convergence) | 20% | 从首次 Gate 2 不通过到 PASS 的平均修订轮次 |
| 推理可追溯性 (Traceability) | 15% | 每步推理是否有中间产出可校验（vs 黑盒一次生成） |

**需读取的文件**:
- `evaluation/plan_quality_rubric.md`（格式模板，特别注意 CON 维度复用）
- `agents/planning_agent.py`（了解当前 LLM 调用方式）
- `playbooks/planner_playbook.md`（了解 SOP 和 prompt 模板）
- `progress/handoff.md` §6（e2e 实测问题）
- `progress/lessons.md` Batch 4（Planning LLM 接入经验）

**需创建的文件**:
- `evaluation/reasoning_quality_rubric.md` — 新建

**验收标准**: 同 Step 2

---

### Step 6: Protocol Quality Rubric

**目标**: 建立消息协议的 Layer 2 评估量表。

**背景**:
- v1.2.0 目标架构定义 Protocol 包含：MessageValidator（JSON Schema 校验）、protocol_version（版本兼容性协商）、FeedbackSchema（标准修订反馈格式）、StateMachine（状态转换可视化 + 测试辅助）
- 当前 spec/agent_contract.md 定义了 AgentMessage + TaskType（11 个值），但无 schema 校验层
- lessons.md 中高频出现 dict↔dataclass 转换 bug、dimensions 嵌套 vs 扁平不匹配、状态转换死角（Batch 7 三条桥接问题）

**评估维度建议** (4个):
| 维度 | 权重 | 核心指标 |
|------|------|---------|
| 消息合法率 (Validity) | 35% | schema 校验通过率、格式错误提前拦截率 |
| 版本兼容性 (Compatibility) | 25% | 跨版本消息收发成功率、版本协商成功率 |
| 错误恢复率 (Recovery) | 25% | 格式错误后自动修复率、降级通信成功率 |
| 状态转换正确性 (State) | 15% | 非法状态转换发生率、转换链完整性 |

**需读取的文件**:
- `spec/agent_contract.md`（当前消息契约）
- `core/message.py`（AgentMessage 实现）
- `progress/lessons.md` 搜索 "接口不匹配" + "状态" + "dimensions" + "to_dict" + "桥接"
- `evaluation/plan_quality_rubric.md`（格式模板）

**需创建的文件**:
- `evaluation/protocol_quality_rubric.md` — 新建

**验收标准**: 同 Step 2

---

### Step 7: Safety Quality Rubric

**目标**: 建立安全围栏的 Layer 2 评估量表。

**背景**:
- v1.2.0 目标架构定义 SafetyGuard：内容安全过滤 + prompt injection 检测 + PII 处理 + 预算硬上限
- 当前系统仅在 Gate 0-3 做业务质量校验，无安全层面设计
- Hermes Agent 的安全边界设计可作为参考：Memory 内容扫描、Skill 安全扫描 + 自动回滚、Secret 脱敏、PII 脱敏

**评估维度建议** (4个):
| 维度 | 权重 | 核心指标 |
|------|------|---------|
| 有害内容拦截率 (Block Rate) | 30% | 危险建议（如推荐高危区域）被正确拦截的比例 |
| 误拦截率 (False Positive) | 25% | 正常内容被错误拦截的比例 |
| 注入检测率 (Injection) | 25% | prompt injection / 越狱尝试的检出率 |
| PII 保护 (Privacy) | 20% | 敏感信息（API key、用户真实姓名）的脱敏覆盖率 |

**需读取的文件**:
- `evaluation/plan_quality_rubric.md`（格式模板）
- `evaluation/code_quality_rubric.md` §7（SEC 维度，参考安全评分思路）

**需创建的文件**:
- `evaluation/safety_quality_rubric.md` — 新建

**验收标准**: 同 Step 2

---

### Step 8: Evolution Quality Rubric

**目标**: 建立自进化引擎的 Layer 2 评估量表。

**背景**:
- v1.2.0 目标架构定义 Evolution：SkillManager（playbook 自动创建/修补 + 效果追踪）+ NudgeEngine（定期后台 review → 自动触发 Memory/Skill 更新）
- 借鉴 Hermes 的 3-session 学习案例：Skill 创建 → Skill 修补 → 零错误
- 当前仅 lessons.md 手工记录经验，无自动化闭环

**评估维度建议** (4个):
| 维度 | 权重 | 核心指标 |
|------|------|---------|
| Skill 成功率趋势 (Success) | 30% | 同一场景多次执行的错误数变化（应单调递减） |
| 错误复现率 (Recurrence) | 25% | 同一错误在多轮中重复出现的频率（应快速归零） |
| 自动化修复率 (Auto-fix) | 25% | 由 NudgeEngine 自动修补的比例（vs 需人工介入） |
| 知识增长率 (Growth) | 20% | Skill/playbook 数量、Memory 条目数的增长趋势 |

**需读取的文件**:
- `evaluation/plan_quality_rubric.md`（格式模板）
- `progress/lessons.md`（了解当前经验记录机制）
- `progress/handoff.md` §11

**需创建的文件**:
- `evaluation/evolution_quality_rubric.md` — 新建

**验收标准**: 同 Step 2

---

### Step 9: Mode D 系统级指标 + 评估体系统一索引

**目标**: 新增系统级评估层，统一索引所有评估文件。

**背景**:
- 当前系统只有 Mode A/B/C 三层，缺系统级端到端指标
- v1.2.0 新增 7 个模块量表后，evaluation/ 目录从 8 个文件膨胀到 16 个，需要统一导航

**需创建/修改的文件**:
- `evaluation/system_metrics.md` — 新建。Mode D 系统级指标定义：
  - 首次通过率 (FPR)：Gate 2 首次即 ≥80 的概率
  - 平均迭代轮次 (AI)：从首次 Planning 到 Gate 2 PASS 的平均轮次
  - 降级率 (Degradation Rate)：API → stub 降级的发生频率
  - 时间-质量曲线 (TQC)：生成时间 vs composite_score 的散点分布
  - 成本-质量比 (CoQ)：token_cost / composite_score
- `evaluation/metrics.md` — 修改：追加 Mode D 4 项指标到汇总表；追加 Step 2-8 新建的 7 个 rubric 文件引用
- `evaluation/quality_criteria.md` — 修改：§1 三层体系更新为四层体系（Layer 0 元评估 + Layer 1-3 + Mode D）；追加 Layer 2 子维度表（7 模块 × 对应 rubric 文件）

**验收标准**:
- `system_metrics.md` 包含 ≤5 个指标的完整定义（公式 + 目标值 + 告警阈值）
- `metrics.md` 汇总表新增 Mode D 行 + 7 个新 rubric 引用
- `quality_criteria.md` 层级描述更新为四层
- 三个文件版本号更新

---

### Step 10: lessons.md 经验回灌 + Change Log 更新

**目标**: 将 66 条开发经验中与评估直接相关的条目系统回灌到对应 rubric，确保新量表锚点有实战数据支撑。同步更新所有变更日志和进度文件。

**背景**:
- lessons.md 中至少 10 条与评估量表相关：
  - Batch 2: `evaluate_plan` "低质量草稿"预期 <60 但实际 65.5（评分公式校准）
  - Batch 2: `score_completeness` `transportation.to_dict()` 空交通未被检测（锚点定义不精确）
  - Batch 5: 途牛 MCP SSE 解析 fail → API 可用率锚点
  - Batch 6: 552 vs 649 测试数统计失误 → 数据准确度锚点
  - Batch 7: dimensions 嵌套 vs 扁平不匹配 → Protocol 消息合法率锚点
  - Batch 7: stub 路径 degraded 断言失败 → Tool 降级优雅度锚点

**需读取的文件**:
- `progress/lessons.md`（完整，搜索 "评估" "score" "得分" "评分" "rubric" "Mode B" "degraded" "stub" "dimensions" "completeness" "feasibility"）

**需修改的文件**:
- `evaluation/plan_quality_rubric.md` — 在 §3 completeness 评分指南中增加 "transportation.to_dict() 非空≠有交通方案" 的判定提醒
- `evaluation/tool_quality_rubric.md`（Step 3 产出）— 在 Degradation 维度锚点中引用 Batch 7 stub degraded 案例
- `evaluation/protocol_quality_rubric.md`（Step 6 产出）— 在 Validity 维度锚点中引用 dimensions 嵌套 vs 扁平案例
- `progress/lessons.md` — 在复盘索引表追加 Batch 8 行（v1.2.0 评估体系升级）
- `progress/README.md` — 变更日志追加 v1.2.0 评估体系升级条目
- `PROGRESS.md` — 更新模块状态，新增 evaluation/ 模块的 v1.2.0 状态

**验收标准**:
- 至少 5 条 lessons 被引用到对应 rubric 的锚点描述中（以脚注或"实战案例"形式）
- `progress/lessons.md` 复盘索引表有 Batch 8 条目
- `progress/README.md` 变更日志有 v1.2.0 条目
- 所有被修改文件版本号更新

---

### 依赖关系

```
Step 1 (校准+元评估)
  │
  ├──→ Step 2 (Memory) ──┐
  ├──→ Step 3 (Tool)     │
  ├──→ Step 4 (RAG)      │
  ├──→ Step 5 (Reasoning) ├──→ Step 9 (Mode D + 索引)
  ├──→ Step 6 (Protocol)  │         │
  ├──→ Step 7 (Safety)    │         ▼
  └──→ Step 8 (Evolution) │    Step 10 (经验回灌 + Change Log)
                           │         │
                           └─────────┘
                             (Step 10 需读取 Step 3/6 产出)
```

- Step 1 必须先完成（为后续提供格式模板 + 元评估标准）
- Step 2-8 互相独立，可并行执行
- Step 9 依赖 Step 2-8 全部完成（需引用 7 个新 rubric）
- Step 10 依赖 Step 1-9 全部完成（需回灌到各 rubric + 统一更新日志）

---

### 执行约定

1. **每个 Step 只产出 .md 文件**，不修改 agents/ 下的业务代码
2. **每个 Step 完成后必须更新所创建/修改文件的版本号和变更日志**
3. **rubric 文件统一格式**：(a) 概述 (b) 评分维度与权重表 (c) 逐维度评分锚点（5级）(d) 检查清单 (e) 评分指南 (f) 综合公式 (g) 判定矩阵 (h) 2个计算示例 (i) 变更日志
4. **提交粒度**: 每个 Step 一个 commit，格式 `[evaluation] feat: Step N — 描述`
5. **执行前先读**: 每个 Step 启动时必须先读取 Step 1 产出的 `meta_rubric.md` 作为质量标准

---

> **给下一个 Agent**: 项目 v1.1.0 API 已跑通 (score 82)。v1.2.0 的目标不是修代码，而是建立完整的评估量表体系——为 Memory / Tool / RAG / Reasoning / Protocol / Safety / Evolution 七大模块各建一个 Layer 2 rubric，让后续开发有尺可量。本文件 §11 包含 10 个 Step 的完整执行计划，从 Step 1 开始逐步骤执行，每个 Step 独立可交付。
