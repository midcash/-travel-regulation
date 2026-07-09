# Handoff — v1.2.0 交接文档

> **版本**: v1.2.0 (开发中) | **分支**: `feat/api-integration` | **日期**: 2026-07-07
> **状态**: 评估体系已完成 → Reasoning + Protocol 方案已修订，待开工 (10 Step, 详见 §12 v2)

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
| **v1.2.0** | **Reasoning + Protocol 完整开发 (进行中)** |

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
Step 1 (校准+元评估) ← 必须先完成
  │
  ├──→ Step 2 (Memory)     ──┐   Step 2-8 各自产出不同文件:
  ├──→ Step 3 (Tool)         │   memory / tool / rag / reasoning /
  ├──→ Step 4 (RAG)          │   protocol / safety / evolution
  ├──→ Step 5 (Reasoning)    │   七个 rubric 文件互不重叠
  ├──→ Step 6 (Protocol)     │
  ├──→ Step 7 (Safety)       │
  └──→ Step 8 (Evolution)   ─┘
           │
           ▼
    Step 9 (Mode D + 索引) ← 需引用 Step 2-8 全部产出
           │
           ▼
    Step 10 (经验回灌 + Change Log) ← 需读取 Step 3/6 产出
```

- Step 1 必须先完成（为后续提供格式模板 `meta_rubric.md` + 元评估标准）
- **Step 2-8 互相独立，可并行启动多个 Agent 同时执行**：每个 Step 写入不同的 evaluation/ 文件，无合并冲突
- Step 9 依赖 Step 2-8 全部完成（需引用 7 个新 rubric 文件路径）
- Step 10 依赖 Step 1-9 全部完成（需回灌到各 rubric + 统一更新日志）

### Step 2-8 并行执行说明

Step 2-8 标记为"可并行"，指的是**开发并行**——多个 Agent 可以同时开始工作，因为：

1. **无数据依赖**：Step 2-8 只依赖 Step 1 产出的 `meta_rubric.md`（格式模板），7 个 Step 之间互不依赖
2. **无文件冲突**：每个 Step 写入一个独立的 rubric 文件，文件名不重叠

| Step | 产出文件 | 互不重叠 |
|------|---------|---------|
| 2 | `evaluation/memory_quality_rubric.md` | ✓ |
| 3 | `evaluation/tool_quality_rubric.md` | ✓ |
| 4 | `evaluation/rag_quality_rubric.md` | ✓ |
| 5 | `evaluation/reasoning_quality_rubric.md` | ✓ |
| 6 | `evaluation/protocol_quality_rubric.md` | ✓ |
| 7 | `evaluation/safety_quality_rubric.md` | ✓ |
| 8 | `evaluation/evolution_quality_rubric.md` | ✓ |

**并行执行流程**：
1. 主 Agent 确认 Step 1 已完成（`meta_rubric.md` 存在）
2. 主 Agent 同时启动 7 个 Agent，各分配一个 Step
3. 每个 Agent 独立读取 handoff.md §11 + `meta_rubric.md` → 产出自己的 rubric 文件
4. 每个 Agent 完成后独立 commit + push（按完成顺序，git 层面串行但不冲突）
5. 7 个 Agent 全部完成后，主 Agent 检查 → 进入 Step 9

**为什么"一个 Step 一个 commit"与并行不冲突**：每个 commit 只修改一个不同文件，git 在合并时零冲突。Agent 完成的先后顺序不影响最终结果——7 个 commit 可以以任意顺序 rebase。

---

### 执行约定

1. **每个 Step 只产出 .md 文件**，不修改 agents/ 下的业务代码
2. **每个 Step 完成后必须更新所创建/修改文件的版本号和变更日志**
3. **rubric 文件统一格式**：(a) 概述 (b) 评分维度与权重表 (c) 逐维度评分锚点（5级）(d) 检查清单 (e) 评分指南 (f) 综合公式 (g) 判定矩阵 (h) 2个计算示例 (i) 变更日志
4. **提交粒度**: 每个 Step 一个 commit，格式 `[evaluation] feat: Step N — 描述`
5. **执行前先读**: 每个 Step 启动时必须先读取 Step 1 产出的 `meta_rubric.md` 作为质量标准
6. **并行约束**: Step 2-8 的 Agent 启动前，主 Agent 必须确认 Step 1 已完成且 `evaluation/meta_rubric.md` 存在于仓库中

---

> **§11 状态**: 已完成。10 个 Step 全部交付 (commit `0279a58`)，17 个 evaluation/ 文件就位。

---

## 12. v1.2.0 实现计划 — Reasoning + Protocol 完整开发 (v2 修订版)

> **目标**: 完整实现 Reasoning 和 Protocol 两个模块，使单城市 e2e 得分从 82 → 90+。
> **原则**: 评估驱动开发。每个 Step 启动前用对应 rubric 对现状打分 → 实现后复评 → Δscore 记录到 commit message。
> **总依赖**: §11 评估体系已完成（所有 rubric 文件可用）。
> **v2 修订**: 14 Step → 10 Step。合并 R1+R2 和 P1+P2，删除 R6（lessons 自动学习，脆弱的 markdown 解析留到 v1.3.0），P4（Spec 升级）改为持续行为（每个 Step 涉及的 spec 改动同步完成，I2 做全局一致性检查）。新增 Phase 0 数据模型先行定义。
> 
> **进度**: 已完成 7/10 Step (Step 0 + R1 + R2 + R3 + P1 + P2 + 测试优化)。剩余: R4 (Feedback) → P3 (ErrorRecovery) → I1 (集成测试) → I2 (E2E 回归)。

---

### 设计原则

v1.2.0 的 Reasoning + Protocol 改造遵循四个核心设计原则：

| 原则 | 解释 | Reasoning 体现 | Protocol 体现 |
|------|------|---------------|--------------|
| **关注点分离** | "说什么"和"怎么说"解耦 | PromptBuilder 组装逻辑 vs YAML 模板内容 | Schema 定义 vs 校验逻辑 |
| **管线化** | 黑盒函数 → 透明管线，每步有独立产出 | CoT 4步: research→select→compose→selfcheck | 校验→兼容性→恢复 流水线 |
| **纵深防御** | 多道防线，不做单一故障点 | SelfCheck(轻量)→Execution(完整)→Feedback(精准) | 发前校验+收后校验 双重保障 |
| **协议即契约** | 靠代码强制执行，而非靠约定和信任 | — | Schema + 版本协商 + 自动修复 |

---

### 两个模块的完整版图

**Reasoning 模块**（4 个子系统）:

| 子系统 | 职责 | 当前状态 |
|--------|------|---------|
| PromptBuilder | 分层 prompt 组装 (Stable/Context/Volatile) + 硬约束注入 + 物价知识注入。**纯文本引擎，不调任何 API。** | 不存在 — prompt 硬编码在 planning_agent.py:79-127 的 f-string 中 |
| ChainOfThought | 研究→筛选→编排→自检 4 步推理链，每步有独立中间产出可校验 | 不存在 — 一次 LLM call 出全部结果 |
| SelfCheck | Planning 输出前规则引擎自检（预算/地理/重复/完整度）。**纯计算，不调 LLM，不调 API。** | 不存在 — 完全依赖 Execution Agent 的事后校验 |
| StructuredFeedback | 修订反馈标准化，逐条注入 revision prompt | 不存在 — 反馈传的是总分而非具体问题 |

> **PromptBuilder 与现有 API 驱动的关系**: PromptBuilder 是纯文本组装引擎，不调任何 API。它与调用 DeepSeek LLM 的 `LLMClient` 职责不同——前者负责"组装说什么"，后者负责"调用 LLM 生成内容"。`price_knowledge.json` 提供的是 LLM 生成时的软参考（"东京午餐大约多少钱"），不是硬校验（"这家酒店今天价格多少"），硬校验由 Execution Agent + 途牛 MCP 负责。因此 price_knowledge.json 不需要 API 驱动。

**Protocol 模块**（4 个子系统）:

| 子系统 | 职责 | 当前状态 |
|--------|------|---------|
| MessageValidator | JSON Schema 校验，发前+收时双重校验，strict_mode 可配 | 不存在 — AgentMessage.validate() 仅检查字段非空 |
| ProtocolVersioning | protocol_version 字段 + 兼容性矩阵 + 版本协商 | 不存在 — spec 定义了 MAJOR/MINOR/PATCH 但代码未实现 |
| StateMachine | 状态转换可视化 + strict_mode 开关 + force_status() 测试辅助 + 死角修复 | 部分存在 — ContextStatus 15 状态已定义，`_VALID_TRANSITIONS` 已实现大部分路径 |
| ErrorRecovery | 格式错误自动修复（dimensions 嵌套→扁平、correlation_id 缺失、timestamp 飘移），修复边界严格受控 | 不存在 — 任何格式错误都导致通信失败 |

---

### Phase 0: 数据模型先行定义 (1 Step)

#### Step 0: 新数据模型定义 ✅ 已完成 — `eb74644`

**目标**: 在编码前集中定义所有新数据模型。接口先行，实现对齐接口。

**背景**:
- R3 CoT 改造需要 `DestinationResearch`、`CandidatePool` 作为中间产出类型
- R4 SelfCheck 需要 `SelfCheckIssue`、`SelfCheckResult` 定义检查结果格式
- R5 StructuredFeedback 需要 `RevisionFeedback` 替代当前裸 dict
- P3 StateMachine 需要 `CompatibilityResult` 定义版本协商结果
- 这些类型散落在多个 Step 的"需创建的文件"中，集中定义可避免接口不一致

**需创建的文件**:
- `models/reasoning.py` — 新建。Reasoning 模块数据模型：
  ```python
  @dataclass
  class DestinationResearch:
      """CoT Step 1 产出：目的地分析"""
      currency: str
      language: str
      timezone: str
      best_season: str
      popular_districts: List[str]
      transport_summary: str
      seasonal_notes: str
      price_level: str              # "高" | "中" | "低"

  @dataclass
  class CandidatePool:
      """CoT Step 2 产出：筛选后的候选池"""
      attractions: List[Attraction]
      accommodations: List[Accommodation]
      restaurants: List[Restaurant]
      selection_rationale: str
      excluded: List[str]

  @dataclass
  class CoTResult:
      """推理管线完整产出"""
      draft: TravelPlanDraft
      research: DestinationResearch
      candidates: CandidatePool
      selfcheck: SelfCheckResult
      attempts: int                # compose→selfcheck 循环次数
      latency_ms: int              # 总延迟
      token_count: int             # 总 token 消耗

  @dataclass
  class StepTrace:
      """单步推理追踪 (用于 TRC 可追溯性评分)"""
      step_name: str
      input_summary: str
      output_summary: str
      duration_ms: int
      token_count: int
  ```

- `models/check.py` — 新建。SelfCheck 数据模型：
  ```python
  class IssueType(Enum):
      BUDGET_OVERSPEND = "budget_overspend"
      GEO_DISTANCE = "geo_distance"
      DUPLICATE_ATTRACTION = "duplicate_attraction"
      MISSING_MEAL = "missing_meal"
      MISSING_ACTIVITY = "missing_activity"
      STYLE_MISMATCH = "style_mismatch"
      EXCLUDED_TYPE = "excluded_type"

  @dataclass
  class SelfCheckIssue:
      type: IssueType
      location: str                # "day_2.dinner" | "day_3.morning"
      actual_value: Any
      expected: str                # "≤ 1500 CNY" | "≤ 30km"
      severity: str                # "blocking" | "warning"

  @dataclass
  class SelfCheckResult:
      passed: bool
      issues: List[SelfCheckIssue]
  ```

- `models/feedback.py` — 新建。修订反馈数据模型：
  ```python
  @dataclass
  class RevisionFeedback:
      """发给 LLM 的结构化修订指令 (替代当前裸 dict)"""
      issue: SelfCheckIssue
      suggestion: str              # "替换为同区域预算内的居酒屋, 如 xxx"
      priority: str                # "blocking" | "warning"
      source: str                  # "self_check" | "execution_agent" | "evaluation_agent"

      def to_dict(self) -> Dict[str, Any]: ...
      def from_dict(cls, data: Dict[str, Any]) -> RevisionFeedback: ...
      def format_for_prompt(self) -> str:
          """转为 LLM 可精确执行的修订指令"""
  ```

- `models/protocol.py` — 新建。Protocol 模块数据模型：
  ```python
  @dataclass
  class ValidationResult:
      valid: bool
      errors: List[SchemaError]
      warnings: List[str]

  @dataclass
  class SchemaError:
      field_path: str              # "payload.dimensions.completeness"
      expected: str                # "number"
      actual: str                  # "dict"
      message: str

  @dataclass
  class CompatibilityResult:
      compatible: bool
      level: str                   # "full" | "adapt" | "reject"
      adapt_rules: List[str]       # ["ignore unknown fields", ...]
      negotiated_version: Optional[str] = None
  ```

**需读取的文件**:
- `models/plan.py`（TravelPlanDraft 结构）
- `models/entities.py`（Attraction / Accommodation / Restaurant 结构）
- `models/request.py`（StructuredRequest 结构）
- `core/message.py`（AgentMessage 结构）

**验收标准**:
- 4 个新 model 文件创建完成，所有 dataclass 通过 `@dataclass` 装饰
- `RevisionFeedback.format_for_prompt()` 的输入/输出格式明确
- 类型之间引用正确（如 `RevisionFeedback.issue` 引用 `SelfCheckIssue`）
- 版本号 1.0.0

---

### Phase R: Reasoning 完整开发 (4 Steps，原 6→4)

> **变更说明**: R1+R2 合并（模板是 PromptBuilder 的内容，分开没有独立价值）。R6 删除（解析 markdown 表格过于脆弱，留到 v1.3.0）。

---

#### R1: PromptBuilder + 模板 (原 R1+R2 合并) ✅ 已完成 — `3af481f`

**目标**: 建立可复用的 prompt 组装基础设施 + 写好模板内容，替代 planning_agent.py 中的硬编码 f-string。

**背景**:
- 当前 `planning_agent.py:79-127` 把模板定义和 prompt 组装混在一起（`_SYSTEM_RESEARCH = "..."` 然后用 f-string 拼接）
- 修改 prompt 需要改 Python 代码 → 非开发者无法调优 prompt

**需创建的文件**:
- `core/prompt_builder.py` — 新建。PromptBuilder 类：
  - `assemble(request, step, feedback=None, iteration=0) -> str` — 组装完整 prompt
  - `_build_stable()` — agent identity + core rules + 硬约束（每次不变）
  - `_build_context(request)` — 目的地/预算/偏好 + 物价参考（per-request）
  - `_build_volatile(feedback, iteration)` — 修订反馈 + 当前轮次（per-turn, 可选）
  - `inject_hard_constraints(constraints) -> str` — 从 StructuredRequest.constraints 提取 → MUST/MUST_NOT 语句

- `core/prompt_templates/` 目录 — 新建：
  - `planner_stable.yaml` — agent identity + core rules + hard constraints + CoT + SelfCheck:
    ```yaml
    identity: "你是一个资深旅游规划师..."
    core_rules:
      - "只推荐真实存在的地点，不得虚构"
      - "所有价格标注币种和金额"
    hard_constraints:
      - "MUST: 同一景点不可在不同天次重复出现"
      - "MUST: 每日总花费 ≤ total_budget / days × 1.1"
      - "MUST: 同一天内任意两景点直线距离 ≤ 30km"
      - "MUST_NOT: 不得推荐 excluded_types 中的活动类型"
    chain_of_thought:
      step_1: "先分析目的地基本信息：季节、汇率、热门区域..."
      step_2: "基于目的地分析结果筛选景点/住宿/餐厅..."
      step_3: "按地理聚类编排每日行程，同时分配预算..."
      step_4: "输出前自查：逐项检查约束满足情况..."
    self_check:
      - "景点是否有重复？"
      - "每日花费是否在预算内？"
      - "每天是否有 ≥ 2 个活动 + ≥ 2 餐？"
    ```
  - `planner_context.yaml` — 6 个 LLM 方法各自对应的 context 模板段落
  - `price_knowledge.json` — 5 城市 × 4 类别（餐饮/住宿/交通/门票）均价。**v1.2.0 MVP 用静态数据，非 API 驱动。** 硬校验由 Execution Agent + 途牛 MCP 负责，此处只提供 LLM 生成的软参考

**需修改的文件**:
- `playbooks/planner_playbook.md` — 修改 §2：
  - 新增 "硬约束 (Hard Constraints)" section
  - 新增 "推理链 (Chain of Thought)" section
  - 新增 "自检 (Self Check)" section

**需读取的文件**:
- `agents/planning_agent.py`（当前 prompt 硬编码方式，79-127 行）
- `playbooks/planner_playbook.md`（SOP 和 prompt 模板）
- `models/request.py`（StructuredRequest 结构）
- `models/reasoning.py`（Step 0 产出 — DestinationResearch / CandidatePool / CoTResult / StepTrace）
- `evaluation/reasoning_quality_rubric.md`（CNS 约束满足率 + TRC 推理可追溯性）
- `progress/handoff.md` §6（e2e 实测 3 个问题）
- `spec/planner_spec.md`（约束条件 §2.1, §4, §5）

**验收标准**:
- `PromptBuilder.assemble(request, step="research")` 返回非空 prompt 字符串
- 硬约束注入: 输入含 `excluded_types: ["赌博"]` → prompt 包含 "MUST_NOT: 不得推荐赌博类型的活动"
- 物价注入: 输入 destination=东京 → prompt 包含 "东京午餐均价 1000-1500 日元"
- `planner_stable.yaml` 包含 identity + core_rules + hard_constraints + chain_of_thought + self_check 五个 section
- `planner_context.yaml` 包含 6 个方法的独立模板段落
- `price_knowledge.json` 包含 5 城市 × 4 类别的均价数据
- `planner_playbook.md` §2 包含 CoT + SelfCheck + 硬约束 三个新增 section
- 修改模板文件不需要改 .py 文件

---

#### R2: SelfCheck (原 R4 提前) ✅ 已完成 — `0936c68`

**目标**: 将 Execution Agent 的部分校验逻辑前移为 Planning 的规则引擎自检。**纯计算，不调任何 API/LLM，始终可用。**

**背景**: 当前 Planning 输出不经自检直接发给 Execution → Execution 检出问题 → 整个修订循环重跑。如果 Planning 能在输出前自行发现并修正最基础的约束违反（预算/地理/重复），可以大幅减少无效修订轮次。

**检查项**:
1. 预算检查: 每日总花费 ≤ total_budget / days × 1.1（允许 10% 浮动）— `severity: blocking`
2. 地理检查: 同天任意两个景点间直线距离 ≤ 30km（Haversine）— `severity: warning`（直线距离 ≠ 实际交通时间）
3. 重复检查: 同一景点不出现超过 1 天 — `severity: blocking`
4. 完整度检查: 每天 ≥ 2 个活动 + ≥ 2 餐推荐 — `severity: warning`（出行/到达日可能例外）
5. 硬约束检查: 未推荐 excluded_types 中的类型、偏好风格匹配率 ≥ 50% — `severity: blocking`

**需创建的文件**:
- `core/self_check.py` — 新建。SelfCheck 类：
  - `check(draft: TravelPlanDraft, request: StructuredRequest) -> SelfCheckResult` — 返回通过/失败 + 问题列表
  - 每个检查项独立方法: `_check_budget()`, `_check_geo()`, `_check_duplication()`, `_check_completeness()`, `_check_constraints()`
  - 使用 `models/check.py` (Step 0) 中定义的 `SelfCheckIssue` / `SelfCheckResult` / `IssueType`

**需读取的文件**:
- `models/check.py`（Step 0 产出 — SelfCheckIssue / SelfCheckResult / IssueType）
- `agents/execution_agent.py`（参考现有 5 项校验的实现逻辑）
- `tools/geo_checker.py`（参考 Haversine 公式实现）
- `models/plan.py`（TravelPlanDraft 结构）
- `models/request.py`（StructuredRequest 结构）
- `evaluation/reasoning_quality_rubric.md`（SFC 自检通过率维度）

**验收标准**:
- 正常 draft（所有项合规）→ `SelfCheckResult.passed = True`, `issues = []`
- 违规 draft（景点重复）→ `passed = False`, issues 含 `DUPLICATE_ATTRACTION` 类型 + 具体景点名
- 违规 draft（单日花费超预算 2x）→ `passed = False`, issues 含超支金额 + 期望范围
- `_check_geo()` 使用 Haversine 公式，不依赖外部 API
- 地理检查 issue 的 severity 为 "warning"（非 "blocking"）
- 单元测试覆盖 ≥ 3 种违规场景

---

#### R3: Planning Agent — Chain-of-Thought 改造 (原 R3) ✅ 已完成 — `da41b39` + `e4a7b07`

**目标**: 将 Planning Agent 的 6 个 LLM 方法从"单次调用的黑盒"改为"分步推理的透明链"。

**背景**: 当前 `create_itinerary` 内部串行调用 6 个方法但不传递推理上下文，后一步不知道前一步的推理结论。e2e 实测 score 82, reasoning_quality_rubric TRC 维度仅 1 分。

**改造方案**:
- 新增 `CoTPipeline` 类 (`core/cot_pipeline.py`) — 编排 4 步推理链，不耦合在 PlanningAgent 内部
- 4 步推理链:
  1. `_step_research(request)` — 目的地研究 → `DestinationResearch`
  2. `_step_select(research)` — 景点/住宿/餐饮筛选 → `CandidatePool`
  3. `_step_compose(selection)` — 日程编排 + 预算分配 → `TravelPlanDraft`
  4. `_step_selfcheck(draft)` — 调用 SelfCheck (R2) → 不通过则回到步骤 3（最多 2 次自我修正）
- 每步的中间产出通过返回值传递（**不写入 SharedContext**，子 Agent 不是写入者）
- PlanningAgent 保留 `create_itinerary` 作为兼容入口（内部调用 CoTPipeline）
- 降级策略: 4 步中任一步 LLM 调用失败 → 整链回退 stub（不混合 LLM+stub）

**CoT 延迟/成本风险**:
- 4 次 LLM 调用替代 1 次，延迟和 token 消耗约 4x
- `CoTResult` 必须记录 `latency_ms` + `token_count` 用于后续 v1.3.0 优化
- 验收标准: 单方案生成 ≤ 3x 当前 `create_itinerary` 延迟

**需创建的文件**:
- `core/cot_pipeline.py` — 新建。CoTPipeline 类：
  - `async execute(request: StructuredRequest) -> CoTResult`
  - `MAX_SELFCHECK_RETRIES = 2`
  - 依赖注入: PromptBuilder + LLMClient + SelfChecker
  - 每步记录 `StepTrace` (输入/输出/延迟/token) 到 `CoTResult.trace`

**需修改的文件**:
- `agents/planning_agent.py` — 改造：
  - `create_itinerary` 改为调用 `CoTPipeline.execute()`
  - 6 个现有 LLM 方法的 prompt 来源从硬编码 f-string 改为 PromptBuilder
  - `__init__` 新增 `prompt_builder` 和 `self_checker` 可选参数
- `agents/orchestrator.py` — **wiring（v2 修订新增）**：
  - `_init_agents()` 创建 `PromptBuilder()` + `SelfChecker()` 实例并注入 PlanningAgent
  - 仅在 `self._llm_client.available` 时注入（LLM 不可用时 CoT 无意义）

**需读取的文件**:
- `agents/planning_agent.py`（完整，1314 行）
- `core/llm_client.py`（LLMClient 接口）
- `core/prompt_builder.py`（R1 产出）
- `core/self_check.py`（R2 产出）
- `models/reasoning.py`（Step 0 产出 — DestinationResearch / CandidatePool / CoTResult / StepTrace）
- `models/check.py`（Step 0 产出 — SelfCheckIssue / SelfCheckResult）
- `evaluation/reasoning_quality_rubric.md`（TRC 推理可追溯性 + CVG 修订收敛轮次）

**验收标准**:
- `CoTPipeline.execute()` 返回 `CoTResult`（含 draft + research + candidates + selfcheck + trace）
- `CoTResult.trace` 包含 4 步或以上的 `StepTrace`（每步有 input_summary + output_summary + duration_ms + token_count）
- `CoTResult.latency_ms` ≤ 3x 当前 `create_itinerary` 延迟
- `CoTResult.attempts` ≥ 1（正常情况 1, 自检不通过时为 2-3）
- 所有 LLM prompt 通过 PromptBuilder 获取，planning_agent.py 无硬编码 f-string
- 任一步 LLM 调用失败 → 整链回退 stub（CoTResult 含 degraded flag）
- 现有 661 tests 全部通过

---

#### R4: StructuredFeedback — 修订反馈标准化 (原 R5) ✅ 已完成 — `待提交`

**目标**: 将修订反馈从"传总分/维度分"升级为"传具体问题定位 + 期望修正值"。

**背景**: handoff §6 问题 3 — Gate 2 检出 feasibility=3，但传到 Planning 的 revision 信息是"feasibility 维度得分低"，而非具体的"Day 2 晚餐 8000 日元超出 3000 日元预算 2.6 倍"。修订后 feasibility 仍是 3。

**需修改的文件**:
- `agents/orchestrator.py` — `_call_revision()` 改造：
  - 从 `ValidationReport.blocking_issues` + `EvaluationReport.dimensions` 中提取具体问题
  - 逐条构造 `RevisionFeedback`（使用 `models/feedback.py` Step 0 定义的类型）
  - 调用 `feedback.format_for_prompt()` 注入 revision prompt
  - **import 变更**: 当前从 `models/entities` import `RevisionFeedback`（维度级），需改为从 `models/feedback` import（问题定位级）。两者字段不同：
    - `entities.RevisionFeedback`: `dimension + issue + suggestion + priority`（通用维度反馈）
    - `feedback.RevisionFeedback`: `issue: SelfCheckIssue + suggestion + priority + source`（精确定位反馈）
- `agents/planning_agent.py` — `revise_itinerary()` 改造：
  - 参数从 `List[dict]` 改为 `List[feedback.RevisionFeedback]`
  - 在 revision prompt 中逐条注入 `format_for_prompt()` 输出

**需读取的文件**:
- `models/feedback.py`（Step 0 产出 — RevisionFeedback）
- `models/check.py`（Step 0 产出 — SelfCheckIssue / IssueType）
- `agents/orchestrator.py` `_call_revision()` 和 `_run_planning_cycle()` 方法
- `agents/planning_agent.py` `revise_itinerary()` 方法
- `models/validation.py`（ValidationReport 结构）
- `models/quality.py`（PlanQualityReport 结构）
- `evaluation/reasoning_quality_rubric.md`（CVG 修订收敛轮次）

**验收标准**:
- Execution 检出 "Day 2 晚餐超预算" → Orchestrator 构造 `RevisionFeedback(issue=SelfCheckIssue(type=BUDGET_OVERSPEND, ...), suggestion="替换为同区域 2500 日元居酒屋", source="execution_agent")`
- `RevisionFeedback.format_for_prompt()` 返回包含 `[BLOCKING] day_2.dinner: 当前=8000, 期望=≤1500. 建议: 替换为...`
- Planning revision 后 Day 2 晚餐花费 ≤ 1500
- 单元测试: 3 种 IssueType 的 feedback → `format_for_prompt()` 输出正确

---

### Phase P: Protocol 完整开发 (3 Steps，原 5→3)

> **变更说明**: P1+P2 合并（校验+版本是同一消息入口层）。P4（Spec 升级）改为持续行为（每个 Step 涉及的 spec 改动同步完成，I2 做全局一致性检查）。

---

#### P1: MessageValidator + 版本化 (原 P1+P2 合并) ✅ 已完成 — `28a20bd`

**目标**: 消息收发两端均经过 schema + 版本兼容性双重校验。

**需创建的文件**:
- `core/message_validator.py` — 新建。MessageValidator 类：
  - `validate(message: AgentMessage) -> ValidationResult` — schema 校验 + 版本兼容性检查
  - `register_schema(task_type: TaskType, schema: dict)` — 注册消息类型 schema
  - `strict_mode: bool` — True → 非法消息抛 `MessageValidationError`; False → 返回 warnings
  - 使用 `models/protocol.py` (Step 0) 中定义的 `ValidationResult` / `SchemaError`

- `core/message_schemas/` 目录 — 新建。9 个 JSON Schema 文件（每个 TaskType 一个）：
  - `task.create_itinerary.schema.json` — 含 `dimensions` 必须为扁平 number 的约束
  - `task.revise_itinerary.schema.json`
  - `task.validate_feasibility.schema.json`
  - `task.evaluate_plan.schema.json`
  - `response.itinerary_draft.schema.json`
  - `response.validation_report.schema.json`
  - `response.result.schema.json`
  - `response.error.schema.json`
  - `control.abort.schema.json`

**需修改的文件**:
- `core/message.py` — 修改：
  - `AgentMessage` 新增字段 `protocol_version: str = "1.0"`
  - 新增 `PROTOCOL_VERSION = "1.2"` 模块常量
  - 新增 `VersionPolicy` 类（兼容性矩阵 + 协商逻辑）：
    ```
    同 MAJOR.MINOR → full
    同 MAJOR, newer MINOR → adapt (忽略未知字段)
    不同 MAJOR → reject
    ```
  - 新增 `negotiate(client_vers, server_vers) -> Optional[str]` — 版本协商：返回双方共同支持的最高版本
  - `AgentMessage.validate()` 改为委托给 MessageValidator

**需读取的文件**:
- `models/protocol.py`（Step 0 产出 — ValidationResult / SchemaError / CompatibilityResult）
- `spec/agent_contract.md` §3（每种消息的 payload schema）、§6（版本兼容性契约）
- `core/message.py`（当前 AgentMessage 实现）
- `evaluation/protocol_quality_rubric.md`（VAL 消息合法率 + CMP 版本兼容性）

**验收标准**:
- 合法 `task.create_itinerary` 消息 → `ValidationResult.valid = True`
- 非法消息（缺少 destination.city）→ `ValidationResult.valid = False` + error 指出缺失字段
- `strict_mode=True` 时非法消息抛 `MessageValidationError`
- v1.2 → v1.2: compatible=full; v1.3 → v1.2: compatible=adapt; v2.0 → v1.2: compatible=reject
- `negotiate(["1.2", "1.1"], ["1.1"])` → "1.1"
- `protocol_version` 字段包含在所有新创建的消息中
- 所有 9 个 JSON Schema 文件定义完整

---

#### P2: StateMachine 完善 — 可视化 + 测试辅助 (原 P3) ✅ 已完成 — `8727e26`

**目标**: 确认并修复状态转换死角（如存在），提供开发和测试辅助工具。

> **注意**: 当前 `core/context.py:117-174` 的 `_VALID_TRANSITIONS` 中 `REVISING → WAITING_PLANNER` (line 158) 和 `WAITING_PLANNER → WAITING_EXECUTOR` (line 134) 均已是合法转换。开工前必须先验证"死角"是否真的存在——可能死角在 orchestrator 的实际调用时序 (orchestrator.py:693-701) 而非状态机本身。

**需修改的文件**:
- `core/context.py` — 修改 SharedContext：
  - docstring 中新增**完整状态转换图**（ASCII 图，15 状态 × 所有合法转换）
  - 新增 `strict_mode: bool = True` 开关 → False 时跳过状态校验（测试/调试用）
  - 新增 `force_status(status: ContextStatus)` 方法 → 仅在 `strict_mode=False` 时可用
  - 新增 `get_legal_transitions(status) -> Set[ContextStatus]` 类方法
  - 新增 `get_transition_path(from_status, to_status) -> List[ContextStatus]` → BFS 最短路
  - `set_status()` 错误消息改进: 从 "非法状态转换" 改为 "非法状态转换 IDLE→DECIDING，合法目标: [VALIDATING, FAILED]"

**需读取的文件**:
- `core/context.py`（完整）
- `agents/orchestrator.py:693-701`（修订路径的 set_status 调用时序）
- `progress/lessons.md`（搜索 "状态" + "REVISING" + "IDLE" + "stub 掩盖"）
- `spec/orchestrator_spec.md` §4.1（状态机定义）
- `evaluation/protocol_quality_rubric.md`（STA 状态转换正确性维度）

**验收标准**:
- `get_legal_transitions(IDLE)` 返回 `{VALIDATING, FAILED}`
- `get_transition_path(REVISING, WAITING_EVALUATOR)` 返回完整路径（BFS 结果）
- `strict_mode=False` 时 `force_status(DECIDING)` 成功；`strict_mode=True` 时抛异常
- 错误消息格式: "非法状态转换 {from}→{to}，合法目标: [...]"
- 如发现死角：补全转换路径 + 修复 orchestrator 调用时序
- 如未发现死角：在 commit message 中注明"已验证，当前 _VALID_TRANSITIONS 无死角"

---

#### P3: ErrorRecovery — 格式错误自动修复 (原 P5)

**目标**: 当消息格式有轻微错误时，尝试自动修复而非直接拒绝。

**背景**: lessons.md 中 11 条"接口不匹配"类问题。如果 MessageValidator 能自动修复常见的格式错误，可以显著减少人工排查。

**修复边界**: 仅修复可安全推断的格式问题；内容缺失/类型根本错误不修复。

| 错误类型 | 修复策略 | 是否安全 |
|---------|---------|---------|
| dimensions 嵌套 dict → 扁平 | `{"completeness": {"score": 5}}` → `{"completeness": 5}` | ✅ 可推断 |
| correlation_id 缺失 | 自动生成 UUID + warning | ✅ 可推断 |
| timestamp 超出容差 | 修正为当前时间 + warning | ✅ 可推断 |
| payload 为空 | 不修复，返回 None | ❌ 不可推断 |
| 必填字段缺失 | 不修复，返回 None | ❌ 不可推断 |

**需修改的文件**:
- `core/message_validator.py` — 新增 `auto_fix(message, validation_result) -> Optional[AgentMessage]`:
  - 修复后附带 `_auto_fixed: List[str]` 元数据字段
  - 修复后消息需通过二次校验（MessageValidator）
  - 所有修复操作记录 warning 日志
- `core/message.py` — **集成点（v2 修订新增）**：
  - `AgentMessage.validate()` 调用 MessageValidator.validate() 后，若失败则调用 auto_fix() 尝试修复
  - 修复成功 → 返回修复后 message + warning 日志
  - 修复失败 → 保持原有 MessageValidationError 抛出行为

**需读取的文件**:
- `core/message_validator.py`（P1 产出）
- `models/protocol.py`（Step 0 产出 — ValidationResult）
- `progress/lessons.md`（搜索 "接口不匹配" + "dimensions" + "to_dict" + "correlation_id"）
- `evaluation/protocol_quality_rubric.md`（RCV 错误恢复率维度）

**验收标准**:
- dimensions 嵌套 dict → 自动提取 score 为扁平值 → 返回修复后 message + `_auto_fixed` 标记
- correlation_id 缺失 → 自动生成 UUID → 返回修复后 message
- payload 为空 → 不修复，返回 None
- 修复后 message 通过 MessageValidator 二次校验
- 单元测试覆盖上述 3 种场景

---

### Phase I: 集成验证 (2 Steps，原 3→2)

> **变更说明**: I2+I3 合并（E2E 回归和 Handoff 收尾是同一阶段的工作）。P4（Spec 升级）在此阶段做全局一致性检查（每个 Step 涉及的 spec 改动应已在该 Step 中同步完成）。

---

#### I1: 集成测试

**目标**: Reasoning + Protocol 模块的联合测试。

**需创建/修改的文件**:
- `tests/test_reasoning.py` — 新建：PromptBuilder + SelfCheck + StructuredFeedback + CoTPipeline 的单元测试 (≥ 30 tests)
- `tests/test_protocol.py` — 新建：MessageValidator + VersionPolicy + StateMachine + ErrorRecovery 的单元测试 (≥ 25 tests)
- `tests/test_integration.py` — 追加：CoT → SelfCheck → StructuredFeedback → Revision 全链路测试 (≥ 5 tests)
- `tests/test_real_cases.py` — 追加：东京/巴黎/成都 3 城市 CoT e2e 真实测试 (≥ 3 tests)

**验收标准**:
- 新增测试 ≥ 60 个
- 现有 661 tests 全部通过（零回归）
- 全链路测试覆盖完整流程

---

#### I2: E2E 回归验证 + Spec 同步 + Handoff 收尾 (原 I2+I3 合并)

**目标**: 完整的评估驱动验证 + spec 一致性检查 + 进度文件更新 + 发布 v1.2.0 tag。

**操作**:
1. 运行东京 5 天 e2e（handoff.md §5 相同输入）
2. 用 `reasoning_quality_rubric.md` 对 Planning 产出打分
3. 用 `protocol_quality_rubric.md` 对消息链路打分
4. 用 `plan_quality_rubric.md` 对最终方案打分（对比 v1.1.0 基线 82.0）
5. 用 `system_metrics.md` Mode D 指标记录 FPR / AI / DR
6. Spec 全局一致性检查：确保 `spec/agent_contract.md`、`spec/orchestrator_spec.md`、`spec/system_spec.md` 与代码实现一致

**需修改的文件**:
- `progress/handoff.md` — 更新 §1 status → "已完成", §12 追加实际 commit hash + Δscore, §10 v1.2.0 → "已完成"
- 涉及 spec 的文件（如有未同步的改动）
- `progress/README.md` — 变更日志追加 v1.2.0 条目
- `progress/lessons.md` — 复盘索引追加 Batch 9（≥ 3 条）
- `PROGRESS.md` — 更新 Planning Agent / core/ 模块状态
- `README.md` — 版本徽章 1.1.0 → 1.2.0

**验收标准**:
- `plan_quality_rubric.md` composite_score ≥ 88（从 82.0 提升 ≥ 6 分）
- `reasoning_quality_rubric.md` 约束满足率维度 ≥ 4（景点重复 → 0，修订收敛 ≤ 2 轮）
- `protocol_quality_rubric.md` 消息合法率维度 ≥ 4（零 dict 转换 bug）
- CoT 中间产出全部可追溯（每步有 `StepTrace` 日志）
- Codebase 与 spec/ 文件无差异（spec 一致性检查通过）
- 所有进度文件同步到 v1.2.0 完成状态
- `lessons.md` 有 Batch 9 条目

---

### 依赖关系

```
Phase 0: Step 0 (数据模型) ← 必须先完成
           │
           ├──────────────────────────────────┐
           ▼                                  ▼
Phase R (Reasoning, 4 Steps)        Phase P (Protocol, 3 Steps)
════════════════════════            ════════════════════════

R1: PromptBuilder + 模板              P1: MessageValidator + 版本化
  │                                     │
  ├─→ R2: SelfCheck (可并行 R1)         ├─→ P2: StateMachine (可并行 P1)
  │     │                               │     │
  │     └─────────────────┐             │     └──────────────┐
  ▼                       ▼             ▼                    ▼
R3: CoT 改造               │      P3: ErrorRecovery           │
  │                       │             │                    │
  └─→ R4: Feedback ───────┘             └────────────────────┘
        │                                    │
        └────────────┬───────────────────────┘
                     ▼
              Phase I (集成, 2 Steps)
                     │
              I1: 集成测试
                     │
              I2: E2E 回归 + Spec 同步 + Handoff 收尾
```

**关键依赖**:
- **Step 0 → 所有 Step**: Step 0 定义数据模型，所有后续 Step 引用
- **R1 → R3**: R3 的 CoTPipeline 依赖 PromptBuilder 获取 prompt
- **R2 → R3**: R3 的 `_step_selfcheck()` 调用 R2 的 SelfChecker
- **R2 + R3 → R4**: R4 的 RevisionFeedback 复用 R2 的 `SelfCheckIssue`
- **P1 → P3**: P3 的 ErrorRecovery 依赖 MessageValidator 的 `ValidationResult`
- **Phase R ∥ Phase P**: 两个 Phase 可并行启动，集成点在 R4 ↔ P3 的 RevisionFeedback 格式（使用 Step 0 的 `models/feedback.py` 统一类型）

**并行机会**:
- Step 0 完成后，R1 + R2 + P1 + P2 可 4 路并行启动
- R2 完成后，R1+R2 合并处的 Agent 可接手 R3

---

### 执行约定

1. **接口先行**: Step 0 必须先完成。所有后续 Step 引用的数据类型在 Step 0 中定义
2. **评估驱动**: 每个 Step 完成后用对应 rubric 自评，commit message 中记录 Δscore
3. **测试不退化**: 任何 Step 完成后必须保持 661 tests 全绿
4. **spec 同步**: 每个 Step 涉及的 spec 改动同步完成，不集中到后续 Step。I2 仅做全局一致性检查
5. **commit 格式**: `[module] feat: Step N — 描述 (Δscore: +X)`
6. **每个 Step 修改 ≤ 3 个核心文件**，避免一个 commit 改太多文件导致 review 困难
7. **PromptBuilder 不调 API**: PromptBuilder 是纯文本引擎，不依赖任何外部服务
8. **SelfChecker 不调 API/LLM**: SelfChecker 是纯规则引擎，Haversine 公式本地计算
9. **CoT 降级策略**: 4 步中任一步 LLM 失败 → 整链回退 stub（不混合 LLM+stub）
10. **wiring 完备原则 (v2 修订新增)**: 每个 Step 在"需修改的文件"中必须列出调用链上所有需修改的文件。特别是 `agents/orchestrator.py::_init_agents()` 作为全局集中 wiring 点，任何 Agent 新增构造函数参数（如 Step R3 的 `prompt_builder`/`self_checker`）都必须同步修改 `_init_agents()` 完成注入。不得假设"上游模块会自动获得新依赖"。

---

### v2 修订记录

| 变更 | 原 (§12 v1) | 新 (§12 v2) | 理由 |
|------|------------|------------|------|
| 新增 Phase 0 | 无 | Step 0: 数据模型集中定义 | 接口先行，避免跨 Step 类型不一致 |
| R1+R2 合并 | 分开两个 Step | R1: PromptBuilder + 模板 | 模板是 PromptBuilder 的内容，分开没有独立价值 |
| R4 提前 | R4 在 R3 之后 | R2 (原 R4) 可在 R1 之后立即启动 | SelfChecker 是纯计算模块，不依赖 CoT |
| R6 删除 | PromptBuilder 从 lessons 自动学习 | 删除，留到 v1.3.0 | 解析 markdown 表格过于脆弱，66 条 lessons 大多是开发 bug 而非 prompt 约束 |
| P1+P2 合并 | 分开两个 Step | P1: MessageValidator + 版本化 | 校验+版本是同一消息入口层 |
| P4 → 持续行为 | 独立 Step | 每个 Step 同步改 spec，I2 做全局一致性检查 | spec 差异累积到最后容易遗漏 |
| I2+I3 合并 | 分开两个 Step | I2: E2E + Spec + Handoff 收尾 | 同一阶段的收尾工作 |
| CoT 降级策略 | 未提及 | 整链回退 stub（不混合 LLM+stub） | 4 步中任一步失败，后续步骤缺少推理上下文 |
| CoT 性能指标 | 无 | `CoTResult.latency_ms` + `token_count` | 4x LLM 调用的代价必须可度量 |
| 地理检查 severity | 未区分 | blocking vs warning | Haversine 直线距离 ≠ 实际交通时间，不应 blocking |
| 版本协商 | 仅检查兼容性 | 新增 `negotiate()` 多版本协商 | 只检查不协商无法解决版本不匹配 |
| P3 开工前验证 | 直接开工 | 先验证死角是否真的存在 | 当前 `_VALID_TRANSITIONS` 中 `REVISING → WAITING_PLANNER` 已是合法转换 |
| R3 wiring | 未提及 | `orchestrator.py::_init_agents()` 注入 PromptBuilder + SelfChecker | CoT 路径因 `_init_agents()` 未传依赖而永远不可达 |
| R4 import | 未提及 | `orchestrator.py` 需从 `models/entities.RevisionFeedback` 切换为 `models/feedback.RevisionFeedback` | 两个 RevisionFeedback 字段不同，不可混用 |
| P3 wiring | 未提及 | `message.py::validate()` 集成 auto_fix 调用 | auto_fix 方法写了但无调用者 |
| 执行约定§10 | 无 | wiring 完备原则：任何 Agent 新增构造参数 → 必须改 `_init_agents()` | 防止 Step 产出死代码 |

---

> **给下一个 Agent**: 
> 
> 评估体系 (evaluation/) 已全部就位，Reasoning + Protocol 两个 rubric 已定义好质量标准。
> 
> v1.2.0 的目标是实现 Reasoning (PromptBuilder + CoT + SelfCheck + StructuredFeedback) 和 Protocol (MessageValidator + 版本化 + StateMachine + ErrorRecovery) 的完整开发，使 e2e 得分从 82 → 90+。
> 
> **本文件 §12 v2 为 10 Step (Step 0 + R1-R4 + P1-P3 + I1-I2)**。当前 R4 已完成，P3/I1/I2 仍待开发；I2 完成后才达到 v1.2.0。
> 
> **首先执行 Step 0（数据模型定义）**——接口先行，所有后续 Step 引用 Step 0 定义的类型。Step 0 完成后，R1 + R2 + P1 + P2 可 4 路并行启动。
