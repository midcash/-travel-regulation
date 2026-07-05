# Evaluation Agent Specification — 评估器规格

---

## 1. 模块标识

| 属性 | 值 |
|------|-----|
| 模块名称 | Evaluation Agent |
| Agent 标识 | `evaluation_agent` |
| 版本 | 1.0.0 |
| 类型 | 子 Agent (Specialist) — 质量中枢 |
| 上游 | Orchestrator |
| 下游 | 无 (评估结果通过 Orchestrator 反馈) |
| 文件路径 | `agents/evaluation_agent.py` |

---

## 2. 功能规格

Evaluation Agent 是三合一评估中枢，支持三种工作模式:

### 2.1 Mode A: 代码质量评估 (开发期)

**函数**: `evaluate_code(target_agent: str, code_files: List[str]) -> CodeQualityReport`

**评估维度与权重**:

| 维度 | 权重 | 1分 | 3分 | 5分 |
|------|------|-----|-----|-----|
| 正确性 | 30% | 逻辑错误，多数 case 失败 | 核心逻辑正确，有边界遗漏 | 逻辑完备，覆盖所有边界 |
| 健壮性 | 25% | 无异常处理 | 有异常处理但不完整 | 完整的异常处理 + 降级策略 |
| 可读性 | 20% | 命名混乱，无注释 | 基本清晰，部分命名可优化 | 命名规范，关键逻辑有注释 |
| 性能 | 15% | 明显性能问题 (O(n²)可优化场景) | 基本合理 | 优化的算法和资源使用 |
| 安全性 | 10% | 明显安全漏洞 | 基本安全但个别风险 | 安全最佳实践全覆盖 |

**评分计算**: `total_score = Σ(dimension_score × weight)`

**判定**:
- total_score ≥ 4.0: PASS
- 3.0 ≤ total_score < 4.0: PASS_WITH_SUGGESTIONS
- total_score < 3.0: NEEDS_REVISION

### 2.2 Mode B: 业务产出评估 (运行时)

**函数**: `evaluate_plan(draft: TravelPlanDraft, validation: ValidationReport) -> PlanQualityReport`

**评估维度与权重**:

| 维度 | 权重 | 评分方法 |
|------|------|---------|
| 完整性 | 25% | 交通+住宿+行程+餐饮+预算 → 全有=5，缺1=4，缺2=3，缺3+=2 |
| 可行性 | 25% | 引用 ValidationReport: 0 blocking=5，1-2=3，3+=1 |
| 约束满足度 | 25% | 硬约束100%=5，90%+=4，80%+=3，<80%=2 |
| 体验质量 | 15% | 节奏+多样性+个性化: 主观评分 1-5 |
| 信息准确度 | 10% | 价格偏差均值: <10%=5，10-20%=4，20-30%=3，>30%=2 |

**综合得分**: `composite_score = Σ(dimension_score × weight) × 20` → 映射到 0-100

**判定**:
- composite_score ≥ 80: PASS
- 60 ≤ composite_score < 80: REVISE (反馈具体改进点)
- composite_score < 60: REJECT (需重新规划)

### 2.3 Mode C: Agent 贡献度评估 (消融实验)

**函数**: `evaluate_contribution(test_suite: TestSuite, baseline: List[str]) -> ContributionReport`

#### C1: LOO 消融实验

**步骤**:
1. 在 baseline 配置 (所有 agent 就位) 下运行测试套件 → 记录基线得分 `S_full`
2. 移除 Planning Agent → 重跑测试 → 记录 `S_no_planner`
3. 移除 Execution Agent → 重跑测试 → 记录 `S_no_executor`
4. 移除 Evaluation Agent → 重跑测试 → 记录 `S_no_evaluator`
5. 计算边际贡献: `MC_i = S_full - S_no_i`
6. 计算贡献率: `CR_i = MC_i / (MC_planner + MC_executor + MC_evaluator) × 100%`

#### C2: Agent Importance Score

**步骤**:
1. 每个 agent 对其他 agent 的产出评分 (1-5)
2. 汇总评分矩阵:
   ```
              → Planner  → Executor → Evaluator
   Planner       —          4           3
   Executor      5          —           4
   Evaluator     4          5           —
   ```
3. 每个 agent 的 Importance Score = 收到评分的均值
4. 排名 + 打标签:
   - 贡献率 > 50% 且 Importance Score 最高 → `veto` (不可替代)
   - 贡献率 > 30% 且 Importance Score 最低 → `bottleneck` (高负载低评价)
   - 贡献率 < 10% → `free_rider` (可优化或移除)
   - 其他 → `standard`

#### C3: 360° 三角评估

**步骤**:
1. **Self**: 每个 agent 自我评分 (1-5)
2. **Peer**: 下游 agent 评分上游 agent (1-5)
3. **Supervisory**: Orchestrator 评分所有子 agent (1-5)
4. 计算偏差: `bias = Self - (Peer + Supervisory) / 2`
   - bias > 0.5: `overconfident`
   - bias < -0.5: `underconfident`
   - -0.5 ≤ bias ≤ 0.5: `aligned`

#### C4: 协同效应分析

**步骤**:
1. 测量 Planning Agent 独立评分 `S_p_alone`
2. 测量 Execution Agent 独立评分 `S_e_alone`
3. 计算:
   - 协同增益: `Synergy = S_full - max(S_p_alone, S_e_alone)`
   - 协同效率: `Efficiency = S_full / (S_p_alone + S_e_alone) × 100%`
4. 判定:
   - Efficiency > 80%: 强协同
   - 50% < Efficiency ≤ 80%: 中等协同
   - Efficiency ≤ 50%: 弱协同（存在 Agent 间冲突）

#### C5: 成本-质量分析

**步骤**:
1. 统计每种配置的 LLM 调用次数
2. 计算 Cost-of-Quality: `CoQ = LLM调用次数 / 综合质量得分`
3. 识别 Pareto 最优配置（质量高且成本低的配置）

---

## 3. 接口规格

### 3.1 公共方法

```python
class EvaluationAgent(BaseAgent):
    agent_name = "evaluation_agent"
    agent_version = "1.0.0"

    async def handle_message(self, message: AgentMessage) -> AgentMessage:
        """消息处理入口，根据 task_type 路由到 Mode A/B/C"""

    # Mode A: 代码质量评估
    async def evaluate_code(self, target_agent: str, code_files: List[str]) -> CodeQualityReport:
        """评估 Agent 代码质量"""

    async def score_correctness(self, code: str, spec: str) -> DimensionScore: ...
    async def score_robustness(self, code: str) -> DimensionScore: ...
    async def score_readability(self, code: str) -> DimensionScore: ...
    async def score_performance(self, code: str) -> DimensionScore: ...
    async def score_security(self, code: str) -> DimensionScore: ...

    # Mode B: 业务产出评估
    async def evaluate_plan(self, draft: TravelPlanDraft, validation: ValidationReport) -> PlanQualityReport:
        """评估旅行方案质量"""

    async def score_completeness(self, draft: TravelPlanDraft) -> DimensionScore: ...
    async def score_feasibility(self, validation: ValidationReport) -> DimensionScore: ...
    async def score_constraints(self, draft: TravelPlanDraft, request: StructuredRequest) -> DimensionScore: ...
    async def score_experience(self, draft: TravelPlanDraft) -> DimensionScore: ...
    async def score_accuracy(self, validation: ValidationReport) -> DimensionScore: ...

    # Mode C: Agent 贡献度评估
    async def evaluate_contribution(self, test_suite: TestSuite, baseline: List[str]) -> ContributionReport:
        """评估 Agent 贡献度 (消融实验)"""

    async def run_ablation(self, test_suite: TestSuite, configs: List[List[str]]) -> AblationResults: ...
    async def compute_importance_scores(self, rating_matrix: Dict) -> List[ImportanceScore]: ...
    async def run_360_assessment(self, agents: List[str]) -> List[Assessment360]: ...
    async def analyze_synergy(self, results: AblationResults) -> SynergyReport: ...
    async def compute_cost_quality(self, config_stats: List[ConfigStats]) -> CostQualityMatrix: ...
```

---

## 4. 数据约束

### 4.1 评分一致性约束
- 同一维度在不同评估中应使用相同的评分标准
- 评估结果记录到日志，支持跨时间的评分基线校准
- 连续 5 次评分的标准差 > 1.0 → 触发评分漂移告警

### 4.2 反馈质量约束
- 每个 issue 必须附带可操作的改进建议（不能只说"不够好"）
- 反馈建议不能与 spec 冲突
- 反馈优先级: high > medium > low，按优先级组织

### 4.3 消融实验约束
- 测试套件 ≥ 5 个用例（样本量过小则置信度不足）
- 每种配置至少运行 3 次取均值（减少随机性）
- 消融结果必须记录样本量和置信区间

---

## 5. 约束与边界条件

### 5.1 输入约束
- Mode A: code_files 不能为空
- Mode B: draft 必须通过 Gate 1 校验
- Mode C: test_suite 至少包含 5 个测试用例

### 5.2 处理约束
- 不得对同一方案重复评估（幂等性检查: 同一 plan_id + 同一 draft 内容 → 返回缓存结果）
- 贡献度评估在每次重大变更后必须重跑（不可复用旧结果）
- 评估过程不得修改被评估对象

### 5.3 输出约束
- 评估报告必须包含: 各维度得分 + 综合得分 + 判定 + 改进建议
- 贡献度报告必须包含: LOO 矩阵 + 重要性排名 + 360° 对比 + 协同分析 + 成本矩阵

---

## 6. 测试规格

### 6.1 Mode A 测试

| 测试场景 | 期望输出 |
|---------|---------|
| 优秀代码 (所有维度5分) | total_score ≥ 4.5, PASS |
| 有安全漏洞的代码 | security ≤ 2, suggestions 包含修复建议 |
| 不可读代码 (单字母变量) | readability ≤ 2, NEEDS_REVISION |
| 空文件 | 返回 error (INVALID_INPUT) |

### 6.2 Mode B 测试

| 测试场景 | 期望输出 |
|---------|---------|
| 完美方案 | composite_score ≥ 90, PASS |
| 缺住宿的方案 | completeness ≤ 3, 反馈含"缺失住宿" |
| 硬约束违反的方案 | constraint_satisfaction ≤ 3, REVISE/REJECT |
| 体验差的方案 (每天12h暴走) | experience_quality ≤ 3 |

### 6.3 Mode C 测试

| 测试场景 | 期望输出 |
|---------|---------|
| 3个agent贡献均衡 | CR 各 ≈ 33% |
| Planning为瓶颈 | MC_planner 最大, 标签为 bottleneck |
| 某agent可移除 | CR ≈ 0%, 标签为 free_rider |
| 强协同 | synergy_efficiency > 80% |

---

## 7. 性能规格

| 指标 | 目标值 |
|------|--------|
| Mode A: 单文件评估 | ≤ 10s |
| Mode B: 单方案评估 | ≤ 15s |
| Mode C: 完整消融实验 (5用例×7配置) | ≤ 120s |
| 评估缓存命中 | ≤ 1s |

---

## 8. 变更日志

| 版本 | 日期 | 变更 |
|------|------|------|
| 1.0.0 | 2026-07-05 | 初始版本，包含 Mode A/B/C 三层评估 |
