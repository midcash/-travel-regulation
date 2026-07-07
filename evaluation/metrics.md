# Metrics — 量化评估指标总览

---

## 1. 概述

本文档汇总了 TravelPlan Orchestrator 项目中所有量化评估指标的**定义、计算公式、目标值和告警阈值**。所有指标均可通过 Evaluation Agent 自动计算。

---

## 2. 指标体系总览

```
                    ┌──────────────────┐
                    │   量化指标体系     │
                    └────────┬─────────┘
           ┌─────────────────┼─────────────────┬─────────────────┐
           ▼                 ▼                  ▼                  ▼
    ┌─────────────┐  ┌─────────────┐  ┌────────────────┐  ┌─────────────┐
    │ Layer 1      │  │ Layer 2      │  │ Layer 3         │  │ Mode D       │
    │ 代码质量指标  │  │ 业务产出指标  │  │ Agent 贡献度指标 │  │ 系统级指标    │
    └─────────────┘  └─────────────┘  └────────────────┘  └─────────────┘
```

---

## 3. Layer 1: 代码质量指标

### M1.1 代码质量总分 (Code Quality Score)
```
CQS = Σ(dimension_score_i × weight_i)
where dimensions = {正确性:0.30, 健壮性:0.25, 可读性:0.20, 性能:0.15, 安全性:0.10}

Range: 1.0 - 5.0
Target: ≥ 4.0
Alert: < 3.0 → NEEDS_REVISION
```

### M1.2 测试覆盖率 (Test Coverage)
```
Coverage = (tested_lines / total_lines) × 100%

Target: ≥ 70%
Alert: < 50%
```

### M1.3 代码复杂度 (Cyclomatic Complexity)
```
CC = E - N + 2P  (边数 - 节点数 + 2×连通分量数)

Target: per-function CC ≤ 10
Alert: per-function CC > 15
```

### M1.4 安全漏洞数 (Security Vulnerabilities)
```
Count of identified security issues

Target: 0
Alert: > 0 → immediate fix required
```

---

## 4. Layer 2: 业务产出指标

### M2.1 综合质量得分 (Composite Quality Score)
```
CQS = (completeness×0.25 + feasibility×0.25 + constraint_sat×0.25
       + experience×0.15 + accuracy×0.10) × 20

Range: 0 - 100
Target: ≥ 80
Alert: < 60 → REJECT
```

### M2.2 完整性指数 (Completeness Index)
```
CI = covered_sections / total_required_sections
where sections = {transportation, accommodation, daily_itinerary, meals, budget}

Range: 0.0 - 1.0 (映射到 1-5 分)
Target: 1.0 (5/5)
Alert: < 0.6 (≤ 3/5)
```

### M2.3 可行性指数 (Feasibility Index)
```
FI = 1 - (blocking_issues / total_checks)

Range: 0.0 - 1.0
Target: 1.0 (0 blocking issues)
Acceptable: ≥ 0.8
Alert: < 0.5
```

### M2.4 约束满足率 (Constraint Satisfaction Rate)
```
CSR_hard = satisfied_hard_constraints / total_hard_constraints
CSR_soft = satisfied_soft_constraints / total_soft_constraints

Target: CSR_hard = 100%, CSR_soft ≥ 70%
Alert: CSR_hard < 100% → blocking
```

### M2.5 偏好匹配率 (Preference Match Rate)
```
PMR = matched_preference_items / total_preferences

Range: 0.0 - 1.0
Target: ≥ 0.70
Alert: < 0.50
```

### M2.6 价格偏差均值 (Mean Price Deviation)
```
MPD = (1/n) × Σ(|estimated_i - market_i| / market_i)

Range: 0.0 - ∞ (%)
Target: ≤ 10%
Alert: > 30%
```

### M2.7 首次通过率 (First-Pass Rate)
```
FPR = plans_passing_gate2_on_first_attempt / total_plans

Range: 0.0 - 1.0
Target: ≥ 0.80
Alert: < 0.50 (Planning Agent 可能需要优化)
```

### M2.8 平均迭代次数 (Average Iterations)
```
AI = Σ(iterations_per_plan) / total_plans

Target: ≤ 1.5
Alert: > 2.5 (流程效率低下)
```

---

## 5. Layer 3: Agent 贡献度指标

### M3.1 边际贡献 (Marginal Contribution)
```
MC_i = S_full - S_no_i

其中 S 为 Layer 2 的 composite_score
正值 = 正向贡献，负值 = 移除该 agent 后反而更好

Target: MC_i > 0 for all i
Alert: MC_i ≤ 0 → free_rider 嫌疑
```

### M3.2 贡献率 (Contribution Rate)
```
CR_i = MC_i / ΣMC_j × 100%

Target: 各 agent CR 在 20%-50% 之间 (均衡)
Alert: 某 agent CR < 10% → 可考虑优化或移除
```

### M3.3 Agent 重要性得分 (Agent Importance Score)
```
AIS_i = mean(peer_ratings_received_i)

Range: 1.0 - 5.0
Target: ≥ 3.5 for all agents
Alert: < 2.5 → 该 agent 产出被其他 agent 评价为低质量
```

### M3.4 协同增益 (Synergy Gain)
```
SG = S_full - max(S_best_single_agent)

正值 (> 0): 1+1 > 2 (正协同)
零值 (= 0): 没有额外增益
负值 (< 0): 协作比独立还差 (负协同)

Target: > 0
Alert: ≤ 0 → Agent 协作存在问题
```

### M3.5 协同效率 (Synergy Efficiency)
```
SE = S_full / (S_planner_alone + S_executor_alone) × 100%

Range: 0% - 100%+
Target: > 80% (强协同)
Acceptable: 50% - 80% (中等协同)
Alert: < 50% (弱协同，存在冲突)
```

### M3.6 成本-质量比 (Cost-of-Quality)
```
CoQ = total_llm_calls / composite_score

越低越好
Target: 由基线测量确定（首次全量配置的 CoQ 作为基线）
Alert: CoQ 上升 > 30% vs 基线
```

### M3.7 Pareto 最优判定
```
一个配置是 Pareto 最优的，如果不存在另一个配置在
"质量更高"且"成本更低"两个维度上同时优于它

用途: 辅助选择性价比最优的 agent 配置
```

### M3.8 评分一致性指数 (Inter-Rater Reliability)
```
IRR = 1 - (observed_variance / max_possible_variance)

用于 Mode A 和 Mode B 的多评估者一致性检查
Range: 0.0 - 1.0
Target: ≥ 0.80
Alert: < 0.60 → 评分标准需要重新校准
```

### M3.9 360° 偏差指数 (360° Bias Index)
```
BI_i = Self_i - (Peer_i + Supervisory_i) / 2

Range: -4.0 - +4.0
Target: -0.5 ≤ BI ≤ 0.5 (aligned)
Alert: |BI| > 1.0 持续 → 自我认知偏差
```

---

## 6. Layer 2 模块级评估指标索引

以下 8 个模块各有独立的 Layer 2 评估量表（rubric），定义了各自的维度、权重、评分锚点和判定矩阵：

| 模块 | Rubric 文件 | 维度数 | 核心评估面 |
|------|-----------|--------|-----------|
| Plan (方案) | [plan_quality_rubric.md](plan_quality_rubric.md) | 5 | COM/FEA/CON/EXP/ACC |
| Memory (记忆) | [memory_quality_rubric.md](memory_quality_rubric.md) | 4 | Recall/Consistency/Fidelity/Reuse |
| Tool (工具) | [tool_quality_rubric.md](tool_quality_rubric.md) | 4 | Availability/Latency/Accuracy/Degradation |
| RAG (检索) | [rag_quality_rubric.md](rag_quality_rubric.md) | 4 | Precision/Freshness/Speed/Coverage |
| Reasoning (推理) | [reasoning_quality_rubric.md](reasoning_quality_rubric.md) | 5 | Constraint/Hallucination/SelfCheck/Convergence/Traceability |
| Protocol (协议) | [protocol_quality_rubric.md](protocol_quality_rubric.md) | 4 | Validity/Compatibility/Recovery/State |
| Safety (安全) | [safety_quality_rubric.md](safety_quality_rubric.md) | 4 | Block Rate/False Positive/Injection/PII |
| Evolution (进化) | [evolution_quality_rubric.md](evolution_quality_rubric.md) | 4 | Success/Recurrence/Auto-fix/Growth |

---

## 7. Mode D: 系统级指标

Mode D 定义了 5 个端到端系统级指标，详见 [system_metrics.md](system_metrics.md)：

| 指标ID | 名称 | 缩写 | 目标 | 告警 |
|--------|------|------|------|------|
| D1 | 首次通过率 | FPR | ≥ 0.80 | < 0.50 |
| D2 | 平均迭代轮次 | AI | ≤ 1.5 | > 2.0 |
| D3 | 降级率 | DR | ≤ 0.15 | > 0.30 |
| D4 | 时间-质量曲线 | TQC | 边际收益 > 1分/秒 | 异常点 > 10% |
| D5 | 成本-质量比 | CoQ | 保持基线 ± 15% | > 基线 × 1.3 |

---

## 8. 指标看板 (Dashboard)

### 8.1 实时指标 (每次任务后更新)
| 指标 | 当前值 | 目标值 | 趋势 |
|------|--------|--------|------|
| Composite Quality Score | — | ≥ 80 | — |
| First-Pass Rate | — | ≥ 80% | — |
| Average Iterations | — | ≤ 1.5 | — |
| Blocking Issues (avg) | — | 0 | — |

### 8.2 趋势指标 (每周更新)
| 指标 | 本周 | 上周 | 变化 |
|------|------|------|------|
| Planner CR | — | — | — |
| Executor CR | — | — | — |
| Evaluator CR | — | — | — |
| Synergy Efficiency | — | — | — |
| CoQ | — | — | — |

### 8.3 告警指标 (实时监控)
| 告警条件 | 严重级别 |
|---------|---------|
| CQS < 60 (连续3次) | CRITICAL |
| FPR < 50% | HIGH |
| 任一 agent CR 下降 > 10% | HIGH |
| CoQ 上升 > 30% | MEDIUM |
| BI > 1.0 持续 | LOW |
| SE < 50% | MEDIUM |

---

## 9. 指标计算示例

### 示例: 某次旅行方案评估

**输入数据**:
- completeness: 4 (缺少1个次要元素)
- feasibility: 5 (0 blocking)
- constraint_sat: 4 (软约束 85%)
- experience: 4
- accuracy: 3 (价格偏差 18%)

**计算**:
```
CQS = (4×0.25 + 5×0.25 + 4×0.25 + 4×0.15 + 3×0.10) × 20
    = (1.00 + 1.25 + 1.00 + 0.60 + 0.30) × 20
    = 4.15 × 20
    = 83
```

**判定**: ≥ 80 → PASS

---

## 10. 变更日志

| 版本 | 日期 | 变更 |
|------|------|------|
| 1.0.0 | 2026-07-05 | 初始版本，三层指标体系的完整定义 |
| 1.1.0 | 2026-07-07 | Step 9 评估体系统一索引: (a) §2 指标体系总览追加 Mode D 层 (b) §6 新增 Layer 2 模块级评估指标索引（7 个 rubric 文件引用）(c) §7 新增 Mode D 系统级指标汇总（5 指标）(d) 章节重新编号 |
