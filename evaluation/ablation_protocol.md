# Ablation Protocol — 消融实验协议

---

## 1. 概述

本文档定义了 **Layer 3 Agent 贡献度评估**中消融实验的完整执行协议。Evaluation Agent 在 Mode C 下按照此协议执行消融实验和贡献度归因分析。

**核心原则** (来自 "Agents that Matter", ICLR 2026):
> 结构性 LOO 移除 ≠ LLM 内省判断。必须真正移除 Agent 并重跑任务，而非让 LLM 猜测。

---

## 2. 实验设计

### 2.1 实验配置矩阵

每次消融实验需测试以下 7 种配置:

| 配置 ID | 配置组成 | 用途 |
|---------|---------|------|
| C_full | Orchestrator + Planner + Executor + Evaluator | 基线 |
| C_no_planner | Orchestrator + Executor + Evaluator | 测量 Planner 贡献 |
| C_no_executor | Orchestrator + Planner + Evaluator | 测量 Executor 贡献 |
| C_no_evaluator | Orchestrator + Planner + Executor | 测量 Evaluator 贡献 |
| C_planner_only | Orchestrator + Planner | 测量 Planner 独立能力 |
| C_executor_only | Orchestrator + Executor | 测量 Executor 独立能力 |
| C_orch_only | Orchestrator only | 测量 Orchestrator 裸能力 |

### 2.2 测试用例要求

- **最小样本量**: ≥ 5 个测试用例
- **推荐样本量**: ≥ 10 个测试用例（统计显著性）
- **用例来源**: `evaluation/test_scenarios.md` 中的端到端测试场景
- **用例覆盖**: 必须包含标准用例 + 边界用例 + 异常用例

### 2.3 重复次数

- 每种配置对每个测试用例运行 **3 次**，取均值
- 目的: 减少 LLM 输出的随机性影响
- 记录每次运行的得分，计算均值 ± 标准差

---

## 3. LOO 消融实验

### 3.1 执行步骤

```
Step 1: 准备测试套件
  - 从 test_scenarios.md 选取 ≥ 5 个用例
  - 记录每个用例的输入和 ground truth (如有)

Step 2: 运行基线 (C_full)
  - 对每个测试用例，使用完整 agent 配置运行 3 次
  - 记录 composite_score (Layer 2)，取均值 → S_full_i
  - 计算 S_full = mean(S_full_i for all test cases)

Step 3: 逐一移除 Agent
  For each agent in [Planner, Executor, Evaluator]:
    a. 从配置中移除该 agent
    b. Orchestrator 跳过该 agent 的路由
    c. 缺失的功能: 若移除 Planner → 使用空模板; 若移除 Executor → 跳过校验; 若移除 Evaluator → 跳过评估
    d. 对每个测试用例运行 3 次 → S_no_X_i
    e. 计算 S_no_X = mean(S_no_X_i for all test cases)

Step 4: 计算边际贡献
  For each agent X:
    MC_X = S_full - S_no_X
    CR_X = MC_X / (MC_planner + MC_executor + MC_evaluator) × 100%

Step 5: 统计检验
  - 对每个 MC 进行 t-test (paired)
  - 若 p > 0.05 → MC 不显著，标注 "NS" (Not Significant)
```

### 3.2 输出格式

```json
{
  "experiment_id": "uuid",
  "test_suite": "e2e_basic",
  "sample_size": 5,
  "repetitions_per_config": 3,
  "results": {
    "full": { "mean_score": 85.2, "std": 3.1, "config": ["orchestrator", "planning_agent", "execution_agent", "evaluation_agent"] },
    "ablations": [
      {
        "removed_agent": "planning_agent",
        "mean_score": 52.3, "std": 8.7,
        "marginal_contribution": 32.9,
        "contribution_rate_pct": 48.2,
        "significant": true,
        "p_value": 0.002,
        "label": "veto"
      },
      {
        "removed_agent": "execution_agent",
        "mean_score": 58.1, "std": 6.4,
        "marginal_contribution": 27.1,
        "contribution_rate_pct": 39.7,
        "significant": true,
        "p_value": 0.005,
        "label": "bottleneck"
      },
      {
        "removed_agent": "evaluation_agent",
        "mean_score": 76.9, "std": 4.2,
        "marginal_contribution": 8.3,
        "contribution_rate_pct": 12.1,
        "significant": true,
        "p_value": 0.03,
        "label": "standard"
      }
    ]
  }
}
```

### 3.3 特殊情况处理

**情况 1: MC ≤ 0 (移除后反而更好)**
→ 标记为 `free_rider`，建议检查该 agent 是否产生负面干扰

**情况 2: 移除后系统崩溃 (S_no_X 无法计算)**
→ MC_X = S_full（全部得分归因于该 agent），标记为 `veto`

**情况 3: MC 不显著 (p > 0.05)**
→ 标注 "NS"，贡献率视为 0%，可能是样本量不足

---

## 4. Agent Importance Score (Peer Rating)

### 4.1 执行步骤

```
Step 1: 收集评分矩阵
  每个 agent 对其他 agent 的上次产出进行评分 (1-5):
  - Planner 评价 Executor 和 Evaluator 的上次产出
  - Executor 评价 Planner 和 Evaluator 的上次产出
  - Evaluator 评价 Planner 和 Executor 的上次产出

Step 2: 汇总评分
  For each agent X:
    ratings = [所有其他 agent 对 X 的评分]
    AIS_X = mean(ratings)
    std_X = std(ratings)

Step 3: 排名与标签
  - 按 AIS 降序排列
  - 结合 LOO 结果打标签
```

### 4.2 评分矩阵示例

```
评分者 → 被评者
              Planner  Executor  Evaluator
Planner          —        4         3
Executor         5        —         4
Evaluator        4        5         —
─────────────────────────────────────────
收到评分        [5,4]    [4,5]     [3,4]
AIS             4.5      4.5       3.5
排名             1        1         3
```

### 4.3 评分指南 (给 Agent 的评分标准)

评价其他 Agent 的产出时，使用以下标准:

| 分数 | 含义 |
|------|------|
| 5 | 产出优秀，可直接使用，无需修改 |
| 4 | 产出良好，有少量可改进之处 |
| 3 | 产出可用，但需要一定修订 |
| 2 | 产出有较多问题，修订工作量大 |
| 1 | 产出不可用，基本需要重做 |

---

## 5. 360° 三角评估

### 5.1 执行步骤

```
Step 1: Self 评估
  每个 agent 对自己的产出进行自评 (1-5)

Step 2: Peer 评估
  使用 Agent Importance Score 中的 peer rating 作为 Peer 评分
  Peer_X = AIS_X (来自 §4)

Step 3: Supervisory 评估
  Orchestrator 对所有子 agent 进行评分 (1-5)
  或者使用独立的人工评审

Step 4: 偏差分析
  For each agent X:
    bias_X = Self_X - (Peer_X + Supervisory_X) / 2
```

### 5.2 偏差判定

| bias 范围 | 判定 | 含义 |
|-----------|------|------|
| bias > 1.0 | overconfident (严重) | 自我认知显著偏高 |
| 0.5 < bias ≤ 1.0 | overconfident (轻度) | 自我认知略偏高 |
| -0.5 ≤ bias ≤ 0.5 | aligned | 自我认知与外部评价一致 |
| -1.0 ≤ bias < -0.5 | underconfident (轻度) | 自我认知略偏低 |
| bias < -1.0 | underconfident (严重) | 自我认知显著偏低 |

### 5.3 输出示例

```json
{
  "360_assessment": [
    {
      "agent": "planning_agent",
      "self_score": 4.5,
      "peer_score": 4.0,
      "supervisory_score": 4.0,
      "bias": 0.5,
      "verdict": "aligned"
    },
    {
      "agent": "execution_agent",
      "self_score": 4.0,
      "peer_score": 4.5,
      "supervisory_score": 4.5,
      "bias": -0.5,
      "verdict": "aligned"
    },
    {
      "agent": "evaluation_agent",
      "self_score": 5.0,
      "peer_score": 3.5,
      "supervisory_score": 3.5,
      "bias": 1.5,
      "verdict": "overconfident"
    }
  ]
}
```

---

## 6. 协同效应分析

### 6.1 执行步骤

```
Step 1: 提取独立评分
  S_planner_alone = C_planner_only 的 mean_score
  S_executor_alone = C_executor_only 的 mean_score

Step 2: 提取协作评分
  S_full = C_full 的 mean_score

Step 3: 计算协同指标
  synergy_gain = S_full - max(S_planner_alone, S_executor_alone)
  synergy_efficiency = S_full / (S_planner_alone + S_executor_alone) × 100%

Step 4: 判定
  if synergy_gain > 0 and synergy_efficiency > 80%:
      verdict = "strong_synergy"
  elif synergy_gain > 0:
      verdict = "moderate_synergy"
  else:
      verdict = "weak_or_negative_synergy"
```

### 6.2 判定矩阵

| synergy_gain | synergy_efficiency | 判定 |
|-------------|-------------------|------|
| > 0 | > 80% | strong_synergy |
| > 0 | 50-80% | moderate_synergy |
| > 0 | < 50% | weak_synergy |
| ≤ 0 | any | negative_synergy (Agent 互相干扰) |

---

## 7. 成本-质量分析

### 7.1 执行步骤

```
Step 1: 统计每种配置的资源消耗
  For each config:
    total_llm_calls = Σ(llm_calls_per_agent)
    total_tokens = Σ(tokens_per_agent)
    记录质量得分 S_config

Step 2: 计算 Cost-of-Quality
  For each config:
    CoQ = total_llm_calls / S_config
    (也可用 total_tokens 替代 total_llm_calls)

Step 3: 识别 Pareto 前沿
  在 (质量得分, 成本) 二维平面上:
  - Pareto 最优 = 不存在其他配置在质量和成本两个维度上都优于它
  - 绘制 Pareto 前沿曲线
```

### 7.2 输出示例

```json
{
  "cost_quality": [
    { "config": "full",           "llm_calls": 30, "tokens": 45000, "score": 85.2, "coq": 0.352, "pareto_optimal": false },
    { "config": "no_evaluator",   "llm_calls": 24, "tokens": 36000, "score": 76.9, "coq": 0.312, "pareto_optimal": true  },
    { "config": "no_executor",    "llm_calls": 22, "tokens": 32000, "score": 58.1, "coq": 0.379, "pareto_optimal": false },
    { "config": "no_planner",     "llm_calls": 20, "tokens": 29000, "score": 52.3, "coq": 0.382, "pareto_optimal": false },
    { "config": "planner_only",   "llm_calls": 18, "tokens": 27000, "score": 62.0, "coq": 0.290, "pareto_optimal": true  },
    { "config": "executor_only",  "llm_calls": 16, "tokens": 24000, "score": 55.0, "coq": 0.291, "pareto_optimal": false },
    { "config": "orch_only",      "llm_calls": 12, "tokens": 18000, "score": 45.0, "coq": 0.267, "pareto_optimal": true  }
  ]
}
```

---

## 8. 实验报告模板

每次消融实验完成后，生成以下报告:

```markdown
# Agent 贡献度评估报告

## 实验信息
- 日期: YYYY-MM-DD
- 测试套件: <suite_name>
- 样本量: N 个用例 × 3 次重复

## 1. LOO 消融结果
| Agent | 基线得分 | 移除后得分 | MC | CR% | 标签 |
|-------|---------|-----------|-----|-----|------|
| Planner | 85.2 | 52.3 | 32.9 | 48.2% | veto |
| Executor | 85.2 | 58.1 | 27.1 | 39.7% | bottleneck |
| Evaluator | 85.2 | 76.9 | 8.3 | 12.1% | standard |

## 2. Agent 重要性排名
| 排名 | Agent | AIS | 标签 |
|------|-------|-----|------|
| 1 | Executor | 4.5 | bottleneck |
| 2 | Planner | 4.0 | veto |
| 3 | Evaluator | 3.5 | standard |

## 3. 360° 评估
| Agent | Self | Peer | Supervisory | Bias | 判定 |
|-------|------|------|-------------|------|------|
| Planner | 4.5 | 4.0 | 4.0 | +0.5 | aligned |
| Executor | 4.0 | 4.5 | 4.5 | -0.5 | aligned |
| Evaluator | 5.0 | 3.5 | 3.5 | +1.5 | overconfident |

## 4. 协同效应
- Synergy Gain: +23.2 (正协同)
- Synergy Efficiency: 72.8% (中等协同)

## 5. 成本-质量
- Pareto 最优配置: no_evaluator (CoQ=0.312)
- 全量 vs 最优: 质量 +10.8%, 成本 +25%

## 6. 建议
1. Planner 是 veto player，不可移除
2. Evaluator 贡献度偏低 (12.1%)，考虑优化其 playbook
3. Evaluator 存在 overconfident 偏差 (bias=+1.5)，需校准
4. 若对成本敏感，可考虑 no_evaluator 配置 (仅牺牲 9.7% 质量，节省 20% 成本)
```

---

## 9. 执行频率

| 触发条件 | 频率 |
|---------|------|
| 每次重大架构变更 | 强制执行 |
| 每次 Agent playbook 更新 | 强制执行 |
| 定期回归 (无变更时) | 每周 1 次 |
| 异常检测触发 | Agent CR 下降 > 10% 时 |

---

## 10. 变更日志

| 版本 | 日期 | 变更 |
|------|------|------|
| 1.0.0 | 2026-07-05 | 初始版本，完整 LOO + AIS + 360° + 协同 + 成本分析协议 |
