# System Metrics — Mode D 系统级端到端指标

---

## 1. 概述

本文档定义了 **Mode D 系统级评估指标**——在 Layer 1（代码质量）、Layer 2（业务产出）、Layer 3（Agent 贡献度）之上，新增的端到端系统性能度量层。

**评估层级关系**:
```
Layer 0: 元评估 (Meta Rubric)      → 评估"尺子"自身的质量
Layer 1: 代码质量 (Code Quality)    → 评估开发质量
Layer 2: 业务产出 (Business Output) → 评估方案质量（7 个模块 rubric）
Layer 3: Agent 贡献度 (Contribution)→ 评估架构质量
Mode D:  系统级指标 (System Metrics)→ 评估端到端系统性能
```

**评估频率**: 每批次（≥ 20 个请求）后自动计算，趋势指标每周更新。

---

## 2. 指标定义

### D1. 首次通过率 (First-Pass Rate, FPR)

**定义**: Gate 2 首次评估即 ≥ 80 分的概率。

```
FPR = count(composite_score ≥ 80 on first Gate 2) / total_plans

Range: 0.0 - 1.0
Target: ≥ 0.80
Alert: < 0.50 → Planning Agent 或 Reasoning 模块可能需要优化
Warning: < 0.65 → 建议检查 prompt 模板和 SelfCheck 机制
```

**数据来源**: `GateRunner.gate_log` — 筛选 `gate_id=2` 且 `iteration=1` 的记录

**与 Layer 2 的关系**: FPR 是 Reasoning Quality Rubric 中"修订收敛轮次"指标的系统级聚合。FPR 高 = Planning 首次输出质量高 = 修订轮次低。

---

### D2. 平均迭代轮次 (Average Iterations, AI)

**定义**: 从首次 Planning 到 Gate 2 PASS（或降级）的平均修订轮次。

```
AI = Σ(iterations_per_plan) / total_plans

Range: 0 - 3 (max_iter=3)
Target: ≤ 1.5
Alert: > 2.0 → 修订闭环效率低下
Warning: > 2.5 → 接近系统上限，Planning↔Execution 协作需改进
```

**数据来源**: `GateRunner.gate_log` — 每个 plan_id 的 `gate_id=2` 最大 `iteration` 值

**与 Layer 2 的关系**: AI 直接反映 Reasoning Quality Rubric 中"修订收敛轮次"维度和 Protocol Quality Rubric 中"错误恢复率"维度的系统级表现。

---

### D3. 降级率 (Degradation Rate, DR)

**定义**: API → stub 降级的发生频率（按 tool 独立统计 + 全链路聚合）。

```
DR_tool = degraded_tool_calls / total_tool_calls   (per tool)
DR_full = plans_with_any_degraded_tool / total_plans (full chain)

Range: 0.0 - 1.0
Target: DR_tool ≤ 0.05 (每 tool), DR_full ≤ 0.15
Alert: DR_full > 0.30 → API 稳定性严重不足
Warning: 单个 tool 的 DR_tool > 0.20 → 该 tool 需要专项排查
```

**数据来源**: `ValidationReport.degraded` 标记 + 各 tool 的 `degraded` 传播标记

**与 Layer 2 的关系**: DR 直接反映 Tool Quality Rubric 中"API 可用率"和"降级优雅度"两个维度的系统级表现。

---

### D4. 时间-质量曲线 (Time-Quality Curve, TQC)

**定义**: 方案生成耗时 vs composite_score 的散点分布，用于识别"花更多时间是否换来更高质量"的效率边界。

```
TQC = { (generation_time_seconds_i, composite_score_i) | i = 1..N }

分析维度:
- 效率前沿 (Efficiency Frontier): 在给定时间内能达到的最高质量
- 边际收益递减点: 超过该时间后，额外时间投入的质量提升 < 1 分/秒
- 异常点检测: 耗时异常长但质量低 → 可能陷入重复修订循环
```

**数据来源**: Orchestrator 的 `process_request` 开始/结束时间戳 + Evaluation Agent 的 `composite_score`

**与 Layer 2 的关系**: TQC 是跨维度的综合视图——同时反映 Planning（生成效率）、Execution（校验效率）、Evaluation（评估效率）的整体时间性能。

---

### D5. 成本-质量比 (Cost-of-Quality, CoQ)

**定义**: LLM token 消耗与方案质量的比值。

```
CoQ = total_token_cost / composite_score

total_token_cost = Σ(prompt_tokens × prompt_price + completion_tokens × completion_price)

Range: 取决于模型定价
Target: 由基线测量确定（首次 50 个请求的 CoQ 中位数作为基线）
Alert: CoQ 上升 > 30% vs 基线 → 成本失控
Warning: CoQ 上升 > 15% vs 基线 → 建议检查 prompt 长度是否膨胀
```

**数据来源**: LLM API 响应的 `usage` 字段 + Evaluation Agent 的 `composite_score`

---

## 3. 指标汇总

| 指标ID | 名称 | 缩写 | 公式 | 目标 | 告警阈值 |
|--------|------|------|------|------|---------|
| D1 | 首次通过率 | FPR | count(first_gate2≥80) / total | ≥ 0.80 | < 0.50 |
| D2 | 平均迭代轮次 | AI | Σ(iterations) / total | ≤ 1.5 | > 2.0 |
| D3 | 降级率 | DR | degraded_calls / total_calls | ≤ 0.15 | > 0.30 |
| D4 | 时间-质量曲线 | TQC | {(time, score)} 散点分布 | 边际收益 > 1分/秒 | 异常点占比 > 10% |
| D5 | 成本-质量比 | CoQ | token_cost / score | 保持基线 ± 15% | > 基线 × 1.3 |

---

## 4. Mode D 看板

### 实时指标 (每次批次后更新)
| 指标 | 当前值 | 目标值 | 趋势 |
|------|--------|--------|------|
| FPR | — | ≥ 0.80 | — |
| AI | — | ≤ 1.5 | — |
| DR (全链路) | — | ≤ 0.15 | — |
| DR (price_checker) | — | ≤ 0.05 | — |
| DR (geo_checker) | — | ≤ 0.05 | — |
| DR (time_checker) | — | ≤ 0.05 | — |
| CoQ | — | 基线 ± 15% | — |

### 趋势指标 (每周更新)
| 指标 | 本周 | 上周 | 变化 |
|------|------|------|------|
| FPR | — | — | — |
| AI | — | — | — |
| DR (全链路) | — | — | — |
| CoQ | — | — | — |
| TQC 效率前沿移动 | — | — | — |

---

## 5. 告警规则

| 告警条件 | 严重级别 | 建议行动 |
|---------|---------|---------|
| FPR < 0.50 连续 2 批次 | CRITICAL | 检查 Planning prompt 模板和 Reasoning 模块 |
| AI > 2.5 连续 2 批次 | HIGH | 检查修订闭环和 Planning↔Execution 协作 |
| DR_full > 0.50 | CRITICAL | API 大面积不可用，检查 API key 和网络 |
| 单 tool DR > 0.30 连续 3 批次 | HIGH | 专项排查该 tool 的 API 提供商 |
| CoQ 上升 > 30% vs 基线 | MEDIUM | 检查 prompt 长度和 LLM 调用次数 |
| TQC 异常点 > 20% | MEDIUM | 存在大量"耗时高但质量低"的请求，检查修订震荡 |

---

## 6. 与 Layer 1/2/3 的关联

```
Mode D 指标 ← 聚合自 Layer 1/2/3 的底层指标:
  
  FPR ← Reasoning.Convergence + Reasoning.SelfCheck
  AI  ← Reasoning.Convergence + Protocol.Recovery
  DR  ← Tool.Availability + Tool.Degradation
  TQC ← Planning(生成效率) + Execution(校验效率) + Evaluation(评估效率)
  CoQ ← LLM token 消耗 + Layer 2 composite_score
```

---

## 7. 变更日志

| 版本 | 日期 | 变更 |
|------|------|------|
| 1.0.0 | 2026-07-07 | 初始版本，Mode D 系统级 5 指标（FPR/AI/DR/TQC/CoQ）+ 看板 + 告警规则 + 与 Layer 1/2/3 关联映射 |
