# Reasoning Quality Rubric — 推理模块质量评分量表

---

## 1. 概述

本文档是 **Layer 2 业务产出评估**中 Reasoning 模块的专用评分量表。用于评估 LLM 推理链的约束满足率、幻觉控制、自检能力、修订收敛速度和推理可追溯性。

**评估对象**: Reasoning — PromptBuilder（分层 prompt 组装 + 硬约束注入）、SelfCheck（Planning 输出前轻量自检）、StructuredFeedback（修订反馈结构化）、ChainOfThought（分步推理链）

**评估时机**: 每次 Planning Agent 变更后、每次 prompt 模板修改后、每 20 个方案生成后定期审计

**当前状态**: Planning Agent 1314 行，6 个 LLM 方法。e2e 实测发现 3 个 Reasoning 层面的问题：(1) 景点重复 — prompt 缺少"景点不重复"约束 (2) 预算失配 — 个别餐厅远超 meal 预算 (3) 修订闭环不完整 — Gate 2 反馈未被充分传达给 Planning。

---

## 2. 评分维度与权重

| 维度 | 权重 | 缩写 | 核心问题 |
|------|------|------|---------|
| 约束满足率 (Constraint) | 30% | CNS | 硬约束满足率、软约束匹配率 |
| 幻觉率 (Hallucination) | 20% | HAL | 虚构地点/价格的比例 |
| 自检通过率 (SelfCheck) | 15% | SFC | Planning 自检首次通过率 vs Execution 退回率 |
| 修订收敛轮次 (Convergence) | 20% | CVG | 从首次 Gate 2 不通过到 PASS 的平均修订轮次 |
| 推理可追溯性 (Traceability) | 15% | TRC | 每步推理是否有中间产出可校验（vs 黑盒一次生成） |

---

## 3. 约束满足率 (Constraint) — 权重 30%

### 评分锚点

| 分数 | 描述 | 判定标准 |
|------|------|---------|
| 5 | 完美满足 | 硬约束 100% 满足 + 软约束 ≥ 95% 满足 + 隐式约束（景点不重复、预算合理分配）全部满足 |
| 4 | 高度满足 | 硬约束 100%，软约束 85-94%，偶有隐式约束轻微违规 |
| 3 | 基本满足 | 硬约束 100%，软约束 75-84% |
| 2 | 存在违反 | 硬约束 < 100% 或软约束 < 75%，或多项隐式约束违规 |
| 1 | 多处违反 | 多项硬约束违反，方案基本不符合用户要求 |

### 检查清单
- [ ] 硬约束: 预算/日期/人数是否 100% 满足？
- [ ] 软约束: 偏好风格/节奏/住宿类型是否 ≥ 85% 匹配？
- [ ] 隐式约束: 景点是否无重复？每日花费是否在合理范围内？
- [ ] Prompt 注入: 硬约束是否通过 prompt 模板强制注入（而非仅建议）？
- [ ] 约束传播: Planning → Execution 往返时，约束条件是否保持完整？

### 评分指南
```
以硬约束满足为门槛，软约束满足为调档:
硬约束 < 100% → 直接 2 分或以下
硬约束 = 100%:
  软约束 ≥ 95% 且隐式约束全部满足 → 5分
  软约束 85-94% → 4分
  软约束 75-84% → 3分
  软约束 < 75% → 2分
```

### 锚点示例

**最低分示例 (1分)** — 多条约束违反:
```json
{
  "plan_id": "draft_001",
  "user_request": {"budget": 15000, "travelers": 2, "dietary": "素食"},
  "constraint_audit": {
    "hard_constraints": {
      "budget_within_limit": false,
      "detail": "总花费 18500 超出预算 23%",
      "date_match": true,
      "travelers_match": true
    },
    "soft_constraints": {
      "dietary_satisfied": false,
      "detail": "推荐了 3 家和牛餐厅，用户为素食者",
      "style_match": false,
      "pace_match": true
    },
    "implicit_constraints": {
      "no_duplicate_attractions": false,
      "detail": "浅草寺 Day1 和 Day4 各出现 1 次",
      "daily_budget_balanced": false,
      "detail": "Day 2 晚餐 8000 日元 = 日均 meal 预算的 3 倍"
    }
  },
  "hard_pass": "2/4 (50%)",
  "soft_pass": "2/4 (50%)"
}
```

**最高分示例 (5分)** — 全部约束完美满足:
```json
{
  "plan_id": "draft_002",
  "user_request": {"budget": 12000, "travelers": 2, "preferences": ["文化", "美食"], "dietary": "无限制"},
  "constraint_audit": {
    "hard_constraints": {
      "budget_within_limit": true,
      "total_spent": 11200,
      "date_match": true,
      "travelers_match": true,
      "no_excluded": true
    },
    "soft_constraints": {
      "style_match": true,
      "pace_match": true,
      "accommodation_match": true,
      "dietary_satisfied": true
    },
    "implicit_constraints": {
      "no_duplicate_attractions": true,
      "daily_budget_balanced": true,
      "max_daily_spend_ratio": 1.3
    }
  },
  "hard_pass": "4/4 (100%)",
  "soft_pass": "4/4 (100%)"
}
```

---

## 4. 幻觉率 (Hallucination) — 权重 20%

### 评分锚点

| 分数 | 描述 | 判定标准 |
|------|------|---------|
| 5 | 零幻觉 | 所有推荐地点/价格可通过 API/知识库验证，0 虚构 |
| 4 | 极少幻觉 | 虚构率 < 2%，仅个别冷门信息无法验证 |
| 3 | 偶有幻觉 | 虚构率 2-5%，少量不存在的地点或偏差明显的价格 |
| 2 | 较多幻觉 | 虚构率 5-15%，多次出现无法验证的推荐 |
| 1 | 严重幻觉 | 虚构率 > 15%，大量推荐无法在真实世界查证 |

### 检查清单
- [ ] 景点名称是否可在高德 POI 或 Wikipedia 中查证？
- [ ] 酒店名称和价格是否与途牛 MCP 返回数据一致？
- [ ] 餐厅推荐是否真实存在（非 LLM 编造）？
- [ ] 价格数字是否在合理范围（非随机生成的数字）？
- [ ] 是否有"编造的地名"（如"东京幸福大酒店"实际不存在）？

### 评分指南
```
虚构率 = 无法验证的推荐项数 / 总推荐项数:
虚构率 = 0% → 5分
虚构率 0.1-2% → 4分
虚构率 2-5% → 3分
虚构率 5-15% → 2分
虚构率 > 15% → 1分
```

### 锚点示例

**最低分示例 (1分)** — 大量虚构内容:
```json
{
  "plan_id": "draft_003",
  "total_recommendations": 40,
  "hallucination_audit": {
    "fabricated_items": [
      {"name": "东京天空温泉酒店", "issue": "不存在此酒店", "type": "accommodation"},
      {"name": "涩谷无敌景观餐厅", "issue": "LLM 编造的名称", "type": "restaurant"},
      {"name": "新宿神秘博物馆", "issue": "不存在此景点", "type": "attraction"},
      {"name": "银座隐藏酒吧", "issue": "名称过于模糊无法验证", "type": "restaurant"},
      {"name": "浅草秘密花园", "issue": "不存在", "type": "attraction"},
      {"name": "东京湾直升机 tour", "issue": "价格编造: 标价 500 元实际 3000+", "type": "activity"}
    ],
    "fabrication_rate": "15% (6/40)",
    "unverifiable_rate": "10% (4/40)",
    "combined_issue_rate": "25%"
  }
}
```

**最高分示例 (5分)** — 零幻觉:
```json
{
  "plan_id": "draft_004",
  "total_recommendations": 45,
  "hallucination_audit": {
    "fabricated_items": [],
    "unverifiable_items": [],
    "verified_via_api": 38,
    "verified_via_knowledge_base": 7,
    "fabrication_rate": "0%",
    "notes": "所有推荐均可在高德 POI + 途牛 MCP 中查证"
  }
}
```

---

## 5. 自检通过率 (SelfCheck) — 权重 15%

### 评分锚点

| 分数 | 描述 | 判定标准 |
|------|------|---------|
| 5 | 高效自检 | SelfCheck 首次拦截率 ≥ 80%（问题在 Planning 内部发现并修复，未被 Execution 退回） |
| 4 | 良好自检 | SelfCheck 首次拦截率 60-79% |
| 3 | 基本自检 | SelfCheck 首次拦截率 40-59% |
| 2 | 自检不足 | SelfCheck 首次拦截率 20-39%，大部分问题依赖 Execution 发现 |
| 1 | 自检缺失 | 无 SelfCheck 机制，或拦截率 < 20%，Planning 输出后几乎所有问题由 Execution 发现 |

### 检查清单
- [ ] Planning 是否在输出前执行了结构化的 SelfCheck（非依赖 LLM 自我评价）？
- [ ] SelfCheck 的检查项是否覆盖: 景点重复、预算合理性、天数匹配、偏好满足？
- [ ] SelfCheck 发现的问题是否被实际修正后再输出（非仅标记）？
- [ ] SelfCheck 通过率 vs Execution 退回率是否有监控？

### 评分指南
```
SelfCheck 拦截率 = SelfCheck 发现并修复的问题数 / 总问题数:
拦截率 ≥ 80% → 5分
拦截率 60-79% → 4分
拦截率 40-59% → 3分
拦截率 20-39% → 2分
拦截率 < 20% → 1分
```

### 锚点示例

**最低分示例 (1分)** — 无自检，全部依赖 Execution:
```json
{
  "period": "2026-07-01 ~ 2026-07-07",
  "plans_generated": 20,
  "selfcheck_stats": {
    "mechanism": "无 — LLM 直接输出，不做结构化检查",
    "issues_found_by_selfcheck": 0,
    "issues_found_by_execution": 45,
    "interception_rate": "0%"
  },
  "execution_rejections": {
    "attraction_duplicate": 12,
    "budget_overflow": 10,
    "date_mismatch": 5,
    "dietary_violation": 8
  }
}
```

**最高分示例 (5分)** — SelfCheck 高效拦截:
```json
{
  "period": "2026-07-01 ~ 2026-07-07",
  "plans_generated": 20,
  "selfcheck_stats": {
    "mechanism": "规则引擎 + LLM 辅助: 景点去重检查 / 预算分配合理性 / 偏好匹配度",
    "issues_found_by_selfcheck": 38,
    "issues_fixed_before_output": 38,
    "issues_found_by_execution": 7,
    "interception_rate": "84.4% (38/45)"
  },
  "execution_rejections": {
    "attraction_duplicate": 0,
    "budget_overflow": 2,
    "date_mismatch": 1,
    "dietary_violation": 4
  }
}
```

---

## 6. 修订收敛轮次 (Convergence) — 权重 20%

### 评分锚点

| 分数 | 描述 | 判定标准 |
|------|------|---------|
| 5 | 快速收敛 | 平均修订 0-1 轮即 PASS Gate 2 |
| 4 | 正常收敛 | 平均 1.0-1.5 轮 |
| 3 | 偏慢收敛 | 平均 1.5-2.0 轮 |
| 2 | 收敛困难 | 平均 2.0-2.5 轮，或 > 20% 的方案达 3 轮上限 |
| 1 | 不收敛 | 平均 > 2.5 轮，或 > 30% 的方案达 3 轮上限后降级 |

### 检查清单
- [ ] 平均修订轮次是否 ≤ 1.5？
- [ ] 是否有 ≥ 80% 的方案在 2 轮内 PASS？
- [ ] 修订反馈是否结构化（具体指出问题位置和期望修改）？
- [ ] 修订后的方案是否确实改进了被指出的问题（非"假修订"）？
- [ ] 是否存在"修订震荡"——修订后新问题出现、旧问题复现？

### 评分指南
```
平均轮次 ≤ 1.0 → 5分
平均轮次 1.0-1.5 → 4分
平均轮次 1.5-2.0 → 3分
平均轮次 2.0-2.5 → 2分
平均轮次 > 2.5 → 1分
```

### 锚点示例

**最低分示例 (1分)** — 反复修订不收敛:
```json
{
  "period": "2026-07-01 ~ 2026-07-07",
  "total_plans": 15,
  "convergence_stats": {
    "avg_iterations": 2.8,
    "pass_in_1_round": 0,
    "pass_in_2_rounds": 3,
    "pass_in_3_rounds": 5,
    "degraded_after_3": 7,
    "degraded_rate": "46.7%"
  },
  "common_issues": [
    "修订只改了表面文字，未修正底层问题",
    "修订 A 问题 → 引入 B 问题 → 修订 B → A 复现（修订震荡）",
    "反馈格式为自然语言，Planning 解析不稳定"
  ]
}
```

**最高分示例 (5分)** — 快速收敛:
```json
{
  "period": "2026-07-01 ~ 2026-07-07",
  "total_plans": 20,
  "convergence_stats": {
    "avg_iterations": 0.6,
    "pass_in_1_round": 12,
    "pass_in_2_rounds": 7,
    "pass_in_3_rounds": 1,
    "degraded_after_3": 0,
    "degraded_rate": "0%"
  },
  "feedback_format": "结构化 JSON: {dimension, issue, location, expected_fix}",
  "notes": "Planning 正确解析结构化反馈，修订后问题解决率 95%"
}
```

---

## 7. 推理可追溯性 (Traceability) — 权重 15%

### 评分锚点

| 分数 | 描述 | 判定标准 |
|------|------|---------|
| 5 | 完全可追溯 | 每步推理有独立中间产出（目的地分析 → 景点筛选 → 日程编排 → 预算分配），每步可独立校验 |
| 4 | 大部分可追溯 | ≥ 80% 的决策有中间推理步骤记录 |
| 3 | 部分可追溯 | 50-79% 的决策可追溯到推理步骤 |
| 2 | 少量可追溯 | 仅最终输出，少量中间步骤可见 |
| 1 | 黑盒输出 | 仅有一次性的最终输出，中间推理完全不可见 |

### 检查清单
- [ ] Planning 是否输出了 CoT (Chain of Thought) 推理步骤？
- [ ] 每个景点的选择理由是否被记录（非仅名称列表）？
- [ ] 预算分配的逻辑（为什么给交通 40%）是否被记录？
- [ ] 修订决策: 收到反馈后修改了什么、为什么这样改？
- [ ] 推理链是否可被外部审计（Evaluation Agent 可逐步骤验证）？

### 评分指南
```
可追溯率 = 有推理记录的决策数 / 总决策数:
可追溯率 ≥ 95% → 5分
可追溯率 80-94% → 4分
可追溯率 50-79% → 3分
可追溯率 20-49% → 2分
可追溯率 < 20% → 1分
```

### 锚点示例

**最低分示例 (1分)** — 黑盒输出:
```json
{
  "plan_id": "draft_005",
  "output_mode": "单次生成 — 无中间推理步骤",
  "traceability": {
    "destination_selection_reason": null,
    "attraction_ranking_logic": null,
    "budget_allocation_rationale": null,
    "schedule_arrangement_logic": null,
    "revision_decision_log": null
  },
  "auditable_decisions": "0/25 (0%)",
  "risk": "如果输出有问题，无法定位是哪个推理步骤出错"
}
```

**最高分示例 (5分)** — 完整推理链:
```json
{
  "plan_id": "draft_006",
  "output_mode": "CoT 分步推理，每步独立记录",
  "traceability": {
    "step_1_destination_analysis": {
      "output": "东京 12 月: 平均气温 5-12°C, 日照 9.5h, 红叶季结束/灯光秀开始",
      "source": "知识库 + LLM 推理"
    },
    "step_2_attraction_selection": {
      "output": "从 45 个候选景点筛选至 10 个: 考虑季节适宜度 + 用户偏好(文化+美食) + 地理聚类",
      "reasoning": "排除夏季限定的活动，优先室内+室外混合以应对冬季天气"
    },
    "step_3_schedule_arrangement": {
      "output": "Day1 新宿/涩谷 → Day2 浅草/晴空塔 → Day3 明治神宫/原宿 → Day4 台场 → Day5 自由探索",
      "reasoning": "地理聚类减少交通时间，Day1 到达日安排轻松，Day3 最密集匹配体力峰值"
    },
    "step_4_budget_allocation": {
      "output": "交通 52% / 住宿 27% / 餐饮 12% / 活动 6% / 缓冲 3%",
      "reasoning": "国际机票占大头，当地用 JR Pass 控制成本，住宿选择中档商务酒店"
    },
    "step_5_revision_response": {
      "feedback_received": "Day 2 晚餐 8000 日元超 meal 预算 3 倍",
      "change_made": "替换为同区域 2500 日元居酒屋套餐",
      "reasoning": "保持地理位置便利的同时控制成本到预算 1.2 倍以内"
    }
  },
  "auditable_decisions": "25/25 (100%)"
}
```

---

## 8. 综合评分计算

### 计算公式
```python
composite_score = (
    CNS_score * 0.30 +
    HAL_score * 0.20 +
    SFC_score * 0.15 +
    CVG_score * 0.20 +
    TRC_score * 0.15
) * 20
# Range: 20 - 100
```

### 维度地板规则

| 规则ID | 触发条件 | 效果 |
|--------|---------|------|
| FLOOR-CNS | CNS = 1（多项硬约束违反） | composite_score = min(composite_score, 59) |
| FLOOR-HAL | HAL = 1（幻觉率 > 15%） | composite_score = min(composite_score, 59) |
| FLOOR-CVG | CVG = 1（修订不收敛，> 30% 降级） | composite_score = min(composite_score, 69) |
| FLOOR-MULTI | ≥ 3 个维度得分 < 3 | composite_score = min(composite_score, 69) |

### 判定矩阵
| 总分 | 判定 | 后续行动 |
|------|------|---------|
| 90-100 | EXCELLENT | 推理质量卓越，可作为 prompt 模板参考 |
| 80-89 | PASS | 推理质量达标 |
| 70-79 | REVISE (轻) | 针对性优化特定约束或幻觉问题 |
| 60-69 | REVISE (重) | 系统性改进 prompt 模板和 SelfCheck 机制 |
| 40-59 | REJECT (可修复) | 推理质量严重影响方案可用性 |
| 20-39 | REJECT (严重) | 推理基本不可用 |

---

## 9. 评估示例

### 示例 1: 高质量推理

**系统概况**: prompt 含硬约束注入 + SelfCheck + CoT 分步推理
**各维度情况**:
- CNS: 硬约束 100%, 软约束 92%, 隐式约束全满足 → 4分
- HAL: 虚构率 0.5% → 4分
- SFC: SelfCheck 拦截率 82% → 5分
- CVG: 平均 0.8 轮 → 5分
- TRC: 可追溯率 95% → 5分

**地板规则检查**: CNS=4 (≥2 ✓), HAL=4 (≥2 ✓), CVG=5 (≥2 ✓) → 无触发

**计算**:
```
(4×0.30 + 4×0.20 + 5×0.15 + 5×0.20 + 5×0.15) × 20
= (1.20 + 0.80 + 0.75 + 1.00 + 0.75) × 20
= 4.50 × 20
= 90 → EXCELLENT
```

### 示例 2: 低质量推理

**系统概况**: 黑盒一次生成，无 SelfCheck，幻觉严重，修订不收敛（反映当前 v1.1.0 e2e 实测问题）
**各维度情况**:
- CNS: 硬约束 100%, 软约束 60%, 景点重复+预算失配 → 2分
- HAL: 虚构率 8% → 2分
- SFC: 无 SelfCheck，拦截率 0% → 1分
- CVG: 平均 2.6 轮，40% 降级 → 1分
- TRC: 黑盒输出，可追溯率 5% → 1分

**地板规则检查**:
```
CVG=1 → FLOOR-CVG 触发！
维度 <3 = 4 (CNS/HAL/SFC/TRC) → FLOOR-MULTI 触发！
→ 上限 = min(score, 69, 69) = 69
```

**计算**:
```
(2×0.30 + 2×0.20 + 1×0.15 + 1×0.20 + 1×0.15) × 20
= (0.60 + 0.40 + 0.15 + 0.20 + 0.15) × 20
= 1.50 × 20
= 30 → min(30, 69) = 30
→ REJECT (严重)
```

---

## 10. 变更日志

| 版本 | 日期 | 变更 |
|------|------|------|
| 1.0.0 | 2026-07-07 | 初始版本，5维度 Reasoning 质量量表（约束满足率/幻觉率/自检通过率/修订收敛轮次/推理可追溯性）+ 2个计算示例 |
