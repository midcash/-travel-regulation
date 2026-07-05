# Contribution Metrics — Agent 贡献度量化指标

---

## 1. 概述

本文档定义了 **Layer 3 Agent 贡献度评估**中的所有量化指标，包括计算公式、解释、目标值和告警阈值。这些指标通过消融实验自动计算，用于持续监控多 Agent 系统的架构健康度。

---

## 2. 核心指标

### 2.1 边际贡献 (MC — Marginal Contribution)

```
定义: MC_i = S_full - S_no_i
其中:
  S_full = 完整配置下的平均综合质量得分
  S_no_i = 移除 agent i 后的平均综合质量得分

单位: 得分点 (composite_score 的绝对变化)
范围: [-100, +100]
解释:
  MC > 0: Agent i 有正向贡献 (移除后质量下降)
  MC = 0: Agent i 无影响
  MC < 0: Agent i 有负向贡献 (移除后质量反而提升)

目标: MC_i > 0 for all i
告警: MC_i ≤ 0 → free_rider 或 negative contributor

计算要求:
  - 样本量 ≥ 5 个测试用例
  - 每配置每用例 ≥ 3 次重复
  - 需要 t-test 显著性检验 (p < 0.05)
```

### 2.2 贡献率 (CR — Contribution Rate)

```
定义: CR_i = MC_i / ΣMC_j × 100%

范围: 0% - 100%
解释:
  所有 agent 的 CR 之和 = 100%
  CR 反映了各 agent 在整体质量提升中的相对贡献

期望分布: 均衡分布 (各 agent 20%-50%)
告警:
  CR < 10%: free_rider (贡献过低)
  CR > 60%: single_point_of_failure (过度依赖单一 agent)
  CR 下降 > 10% (vs 上次评估): 性能退化告警
```

### 2.3 Agent 重要性得分 (AIS — Agent Importance Score)

```
定义: AIS_i = mean(所有其他 agent 对 agent i 的评分)
评分范围: 1-5

解释:
  AIS 反映了 agent i 的产出在同行中的口碑
  AIS 高 = 其他 agent 认为该 agent 的产出质量高、有用
  AIS 低 = 其他 agent 认为该 agent 的产出需要大量修订

目标: AIS ≥ 3.5 for all agents
告警: AIS < 2.5 → 该 agent 产出被同行评价为低质量

注意事项:
  - 评分方差过大 (std > 1.5) 时需要仲裁
  - AIS 与 MC 不一定正相关 (veto agent 可能 MC 高但 AIS 低)
```

### 2.4 协同增益 (SG — Synergy Gain)

```
定义: SG = S_full - max(S_best_single_agent)

其中 S_best_single_agent = max(S_planner_alone, S_executor_alone)

解释:
  SG > 0: 正协同 — 协作产出优于任一 agent 独立运作 (1+1 > 2)
  SG = 0: 无额外增益 — 协作没有比最强单 agent 更好
  SG < 0: 负协同 — 协作反而比独立运作更差 (agent 间冲突)

目标: SG > 0
告警: SG ≤ 0 → Agent 协作存在问题，需排查通信/接口冲突
```

### 2.5 协同效率 (SE — Synergy Efficiency)

```
定义: SE = S_full / (S_planner_alone + S_executor_alone) × 100%

解释:
  理想上限 (100%) 意味着协作产出 = 各 agent 独立产出之和
  实际上限通常 < 100%，因为存在信息冗余和协调开销

判定:
  SE > 80%: 强协同 — 协作效率高
  SE 50-80%: 中等协同 — 有协调开销但在可接受范围
  SE < 50%: 弱协同 — 协调开销过大，可能需要简化 agent 间依赖

目标: SE > 50%
告警: SE 下降 > 20% (vs 上次评估) → 协同退化告警
```

### 2.6 成本-质量比 (CoQ — Cost-of-Quality)

```
定义: CoQ = total_llm_calls / composite_score

其中:
  total_llm_calls = 该配置下所有 agent 的 LLM API 调用总次数
  composite_score = Layer 2 综合质量得分

单位: 调用次数/质量分
解释:
  CoQ 越低越好 — 用更少的 LLM 调用获得更高的质量
  不同配置的 CoQ 可横向比较性价比

基线: 首次全量配置 (C_full) 的 CoQ 作为基线
告警: CoQ 上升 > 30% (vs 基线) → 成本失控告警

变体:
  CoQ_tokens = total_tokens / composite_score (基于 token 消费)
  CoQ_latency = total_time_seconds / composite_score (基于延迟)
```

### 2.7 Pareto 效率 (PE — Pareto Efficiency)

```
定义: 一个配置是 Pareto 最优的，当且仅当不存在另一个配置在
      (质量, 成本) 两个维度上同时严格优于它

解释:
  Pareto 前沿 = 所有 Pareto 最优配置的集合
  非 Pareto 最优的配置 = 存在某个配置在更低的成本下获得相同或更高的质量

用途: 辅助选择性价比最优的 agent 配置
```

### 2.8 360° 偏差指数 (BI — Bias Index)

```
定义: BI_i = Self_i - (Peer_i + Supervisory_i) / 2

范围: [-4.0, +4.0]
解释:
  BI > 0: 自我认知偏高 (overconfident)
  BI < 0: 自我认知偏低 (underconfident)
  BI ≈ 0: 自我认知与外部评价一致 (aligned)

目标: -0.5 ≤ BI ≤ 0.5
告警: |BI| > 1.0 持续 → 自我认知偏差需要干预
```

### 2.9 Agent 标签 (Agent Label)

| 标签 | 条件 | 含义 | 建议行动 |
|------|------|------|---------|
| `veto` | MC 占比 > 50% 或 移除后系统不可用 | 不可替代的核心 agent | 确保高可用，不可移除 |
| `bottleneck` | CR > 30% 且 AIS 最低 | 高负载但产出质量不被认可 | 优化 playbook，增加资源 |
| `standard` | 10% ≤ CR ≤ 50% | 正常贡献 | 保持监控 |
| `free_rider` | CR < 10% 或 MC ≤ 0 | 贡献极低或为负 | 评估是否移除或重构 |
| `overconfident` | BI > 0.5 | 自我认知偏高 | 用数据校准自我评估 |
| `underconfident` | BI < -0.5 | 自我认知偏低 | 提升信心，展示其贡献价值 |

---

## 3. 衍生指标

### 3.1 系统均衡度 (System Balance)

```
定义: SB = 1 - (max(CR) - min(CR)) / 100

范围: 0.0 - 1.0
解释:
  SB = 1.0: 所有 agent 贡献完全均衡
  SB = 0.0: 极端不均衡 (一个 agent 贡献 100%，其他为 0)

目标: SB ≥ 0.7
告警: SB < 0.5 → 系统过度依赖个别 agent
```

### 3.2 稳定性指数 (Stability Index)

```
定义: SI = 1 - |CR_current - CR_previous| / CR_previous

范围: 0.0 - 1.0
解释:
  SI = 1.0: 贡献率完全不变
  SI = 0.0: 贡献率变化 100%

目标: SI ≥ 0.9 (每次评估之间)
告警: SI < 0.8 → 系统架构不稳定，贡献率波动大
```

### 3.3 冗余度 (Redundancy)

```
定义: R = 1 - max(CR) / 100

范围: 0.0 - 1.0
解释:
  R = 0.0: 无冗余 — 所有贡献集中在单一 agent
  R = 0.67 (3 agent 均衡时): 良好冗余
  R 越高越好

目标: R ≥ 0.5
告警: R < 0.3 → 单点故障风险高
```

---

## 4. 指标趋势追踪

### 4.1 追踪维度

| 指标 | 追踪频率 | 趋势方向 | 告警阈值 |
|------|---------|---------|---------|
| MC | 每次消融 | 上升 | 下降 > 10 分 |
| CR | 每次消融 | 均衡 | 变化 > 10% |
| AIS | 每次消融 | 上升 | 下降 > 1.0 |
| SG | 每次消融 | 上升 | 下降 > 10 分 |
| SE | 每次消融 | 上升 | 下降 > 20% |
| CoQ | 每次消融 | 下降 | 上升 > 30% |
| BI | 每次消融 | 趋近 0 | \|BI\| > 1.0 持续 |
| SB | 每次消融 | 上升 | < 0.5 |

### 4.2 趋势分析规则

```
连续 2 次: 任一 agent CR 下降 > 5%
  → 发出 LOW 级别告警，记录观察

连续 3 次: 同一 agent CR 下降
  → 发出 MEDIUM 级别告警，建议检查 agent playbook

CR 突然下降 > 20% (单次)
  → 发出 HIGH 级别告警，可能引入重大回归

SG 从正变负
  → 发出 CRITICAL 级别告警，可能存在 agent 间冲突
```

---

## 5. 指标看板示例

### Agent 贡献度趋势 (最近 4 周)

```
Week     Planner CR    Executor CR    Evaluator CR    SB     SE
W23      45%           38%            17%             0.72   75%
W24      46%           39%            15%             0.69   73%
W25      48%           40%            12%             0.64   70%
W26      50%           41%             9%             0.59   67%  ← Evaluator CR 持续下降

告警: Evaluator CR 连续下降 (17%→9%), 触发 MEDIUM 告警
建议: 检查 evaluator_playbook.md 是否近期有不利变更
```

---

## 6. 变更日志

| 版本 | 日期 | 变更 |
|------|------|------|
| 1.0.0 | 2026-07-05 | 初始版本，8 个核心指标 + 3 个衍生指标完整定义 |
