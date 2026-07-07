# Evolution Quality Rubric — 自进化引擎质量评分量表

---

## 1. 概述

本文档是 **Layer 2 业务产出评估**中 Evolution 模块的专用评分量表。用于评估自进化引擎的学习能力——Skill 成功率趋势、错误复现控制、自动化修复率和知识增长率。

**评估对象**: Evolution — SkillManager（playbook 自动创建/修补 + 效果追踪）+ NudgeEngine（定期后台 review → 自动触发 Memory/Skill 更新）

**评估时机**: Evolution 模块开发完成后、每 10 个 session 后定期审计、每次 playbook 自动修补后

**当前状态**: Evolution 模块完全空白。仅有 lessons.md 手工记录经验，无自动化闭环。此量表用于后续 Evolution 模块开发时的评估驱动。

**参考**: Hermes 3-session 学习案例 — Skill 创建 → Skill 修补 → 零错误。目标: 同一场景多次执行的错误数应单调递减，同一错误不应在 2 轮以上复现。

---

## 2. 评分维度与权重

| 维度 | 权重 | 缩写 | 核心问题 |
|------|------|------|---------|
| Skill 成功率趋势 (Success) | 30% | SUC | 同一场景多次执行的错误数变化（应单调递减） |
| 错误复现率 (Recurrence) | 25% | REC | 同一错误在多轮中重复出现的频率（应快速归零） |
| 自动化修复率 (Auto-fix) | 25% | ATF | 由 NudgeEngine 自动修补的比例（vs 需人工介入） |
| 知识增长率 (Growth) | 20% | GRW | Skill/playbook 数量、Memory 条目数的增长趋势 |

---

## 3. Skill 成功率趋势 (Success) — 权重 30%

### 评分锚点

| 分数 | 描述 | 判定标准 |
|------|------|---------|
| 5 | 持续改善 | 最近 10 个 session 的错误数单调递减，最终趋近 0 |
| 4 | 明显改善 | 错误数下降 ≥ 50%，趋势向下 |
| 3 | 缓慢改善 | 错误数下降 20-49%，趋势不明确 |
| 2 | 基本无改善 | 错误数下降 < 20%，或波动无趋势 |
| 1 | 恶化 | 错误数增加，学习机制反而引入新问题 |

### 检查清单
- [ ] 同一场景类型（如"东京 5 天文化之旅"）最近 5 次执行的错误数是否呈下降趋势？
- [ ] 错误下降趋势是否具有统计显著性（非随机波动）？
- [ ] 新场景类型的"冷启动"错误数是否在 3 个 session 内降至接近已知场景水平？
- [ ] 是否存在"遗忘"现象——曾经修复的问题在后续 session 中重新出现？
- [ ] 成功率提升是否可归因于 Evolution 机制（非 LLM 随机性）？

### 评分指南
```
错误数变化率 = (最近5次平均错误数 - 最初5次平均错误数) / 最初5次平均错误数:
变化率 ≤ -80% → 5分
变化率 -50% ~ -79% → 4分
变化率 -20% ~ -49% → 3分
变化率 0% ~ -19% → 2分
变化率 > 0%（恶化）→ 1分
```

### 锚点示例

**最低分示例 (1分)** — 错误数反而增加:
```json
{
  "scenario_type": "东京 5天 文化+美食",
  "sessions_tracked": 15,
  "error_trend": {
    "sessions_1_to_5": {"avg_errors": 4.2},
    "sessions_6_to_10": {"avg_errors": 5.8},
    "sessions_11_to_15": {"avg_errors": 7.1},
    "trend": "上升 (+69%)",
    "root_cause": "自动修补引入了不兼容的 playbook 规则，导致新类型错误"
  },
  "analysis": "SkillManager 创建的修补规则与已有规则冲突，每次修补解决 1 个问题但引入 2 个新问题"
}
```

**最高分示例 (5分)** — 错误数单调递减至零:
```json
{
  "scenario_type": "东京 5天 文化+美食",
  "sessions_tracked": 15,
  "error_trend": {
    "sessions_1_to_5": {"avg_errors": 4.2, "typical_errors": ["景点重复", "预算失配", "幻觉餐厅", "交通时间不合理"]},
    "sessions_6_to_10": {"avg_errors": 1.4, "typical_errors": ["预算轻微偏差"]},
    "sessions_11_to_15": {"avg_errors": 0.2, "typical_errors": []},
    "trend": "下降 (-95.2%)",
    "improvements_applied": [
      "Session 3 → playbook 规则: 景点不重复检查",
      "Session 5 → playbook 规则: 单餐花费 ≤ 日均 meal 预算 × 1.5",
      "Session 7 → playbook 规则: 所有推荐需高德 POI 验证"
    ]
  },
  "analysis": "3 个 session 完成冷启动 → 错误数单调递减 → session 12 后稳定零错误"
}
```

---

## 4. 错误复现率 (Recurrence) — 权重 25%

### 评分锚点

| 分数 | 描述 | 判定标准 |
|------|------|---------|
| 5 | 零复现 | 同一错误修复后 0 次复现 |
| 4 | 极少复现 | 复现率 < 5%，偶发边界条件触发 |
| 3 | 偶有复现 | 复现率 5-15% |
| 2 | 频繁复现 | 复现率 15-30%，修复不够彻底 |
| 1 | 反复复现 | 复现率 > 30%，同一错误反复出现，学习机制失效 |

### 检查清单
- [ ] 已记录到 lessons.md 的问题是否在后续 session 中仍有出现？
- [ ] 同一错误复现时，是否有"为何上次修复未生效"的根因分析？
- [ ] 错误修复是否包含回归测试（确保修复后不再出现）？
- [ ] 是否存在"表面修复"——改了症状但根因仍在（如改了 prompt 措辞但未改底层逻辑）？
- [ ] 复现的间隔是否在变长（即使偶有复现，但频率在降低）？

### 评分指南
```
复现率 = 修复后再次出现的错误数 / 总修复错误数:
复现率 = 0% → 5分
复现率 0.1-5% → 4分
复现率 5-15% → 3分
复现率 15-30% → 2分
复现率 > 30% → 1分

> 特殊规则: 错误复现率 > 50% 且持续 3 轮以上 → SUC 维度上限 = 2
```

### 锚点示例

**最低分示例 (1分)** — 错误反复出现:
```json
{
  "period": "2026-06-01 ~ 2026-07-07",
  "total_errors_fixed": 30,
  "recurrence_audit": {
    "errors_recurred": 16,
    "recurrence_rate": "53.3%",
    "top_recurring": [
      {"error": "景点重复(浅草寺 Day1+Day4)", "fixed_in": "session_03", "recurred_in": ["session_07", "session_12", "session_15"], "recur_count": 3},
      {"error": "餐费超预算", "fixed_in": "session_02", "recurred_in": ["session_05", "session_09", "session_14"], "recur_count": 3},
      {"error": "幻觉推荐(不存在餐厅)", "fixed_in": "session_04", "recurred_in": ["session_08", "session_13"], "recur_count": 2}
    ],
    "root_cause": "修复仅调整 prompt 措辞(软建议)，未改为结构化硬约束，LLM 在不同上下文中重新产生相同错误"
  }
}
```

**最高分示例 (5分)** — 零复现:
```json
{
  "period": "2026-06-01 ~ 2026-07-07",
  "total_errors_fixed": 30,
  "recurrence_audit": {
    "errors_recurred": 0,
    "recurrence_rate": "0%",
    "fix_quality": {
      "structural_fixes": 25,
      "prompt_fixes": 5,
      "with_regression_test": 30
    },
    "analysis": "所有修复均附带回归测试，修复方式优先使用结构化约束(规则引擎)而非 prompt 软建议"
  }
}
```

---

## 5. 自动化修复率 (Auto-fix) — 权重 25%

### 评分锚点

| 分数 | 描述 | 判定标准 |
|------|------|---------|
| 5 | 高度自动化 | ≥ 80% 的问题由 NudgeEngine 自动修补，人工仅审查 |
| 4 | 大部分自动化 | 60-79% 自动修补率 |
| 3 | 部分自动化 | 40-59% 自动修补率 |
| 2 | 少量自动化 | 20-39% 自动修补率，多数需人工编写修复 |
| 1 | 几乎全手动 | < 20% 自动修补率，Evolution 形同虚设 |

### 检查清单
- [ ] NudgeEngine 是否能自动检测问题模式（如"景点重复"的共性特征）？
- [ ] NudgeEngine 是否能自动生成 playbook 修补规则（非仅报告问题）？
- [ ] 自动生成的修补规则是否经过安全/合理性校验后才生效（非直接应用）？
- [ ] 人工介入的比例是否在逐渐降低（自动化率在提升）？
- [ ] 自动修补失败时是否有回滚机制？

### 评分指南
```
自动修复率 = 自动修补的问题数 / 总发现问题数:
自动修复率 ≥ 80% → 5分
自动修复率 60-79% → 4分
自动修复率 40-59% → 3分
自动修复率 20-39% → 2分
自动修复率 < 20% → 1分

> 特殊规则: Auto-fix rate < 10% 持续 10+ sessions → composite_score 上限 = 69（Evolution 未真正"自进化"）
```

### 锚点示例

**最低分示例 (1分)** — 几乎全靠人工:
```json
{
  "period": "2026-07-01 ~ 2026-07-31",
  "total_issues_detected": 50,
  "auto_fix_audit": {
    "auto_patched_by_nudge": 5,
    "manual_fix_required": 45,
    "auto_fix_rate": "10%",
    "auto_fixable_but_manual": [
      "景点重复 → 可自动生成'去重检查'规则，但实际人工编写",
      "预算超限 → 可自动调整预算模板参数，但实际人工调整",
      "幻觉餐厅 → 可自动添加 POI 校验步骤，但实际人工添加"
    ],
    "blocker": "NudgeEngine 只能检测和报告问题，不能自动生成修补规则"
  }
}
```

**最高分示例 (5分)** — 高度自动化:
```json
{
  "period": "2026-07-01 ~ 2026-07-31",
  "total_issues_detected": 50,
  "auto_fix_audit": {
    "auto_patched_by_nudge": 42,
    "manual_fix_required": 8,
    "auto_fix_rate": "84%",
    "auto_fix_breakdown": {
      "pattern_detection": 42,
      "rule_generation": 42,
      "auto_validated": 38,
      "rejected_by_validation": 4,
      "applied_successfully": 38
    },
    "manual_cases": [
      "全新类型问题(无历史模式可匹配) → 需人工定义修复策略",
      "多模块联动问题 → 需人工协调"
    ],
    "trend": "auto_fix_rate 从上月 72% 提升至本月 84%，NudgeEngine 模式库持续扩展"
  }
}
```

---

## 6. 知识增长率 (Growth) — 权重 20%

### 评分锚点

| 分数 | 描述 | 判定标准 |
|------|------|---------|
| 5 | 健康增长 | 知识条目月增长 5-15%（稳步增长不过快膨胀），质量验证率 ≥ 90% |
| 4 | 正常增长 | 月增长 3-5% 或 15-25%，大部分知识经过验证 |
| 3 | 缓慢增长 | 月增长 1-3%，或增长快但验证不足 |
| 2 | 停滞 | 月增长 < 1%，知识库几乎不更新 |
| 1 | 衰退 | 知识条目负增长（过期条目被删除但无新条目补充） |

### 检查清单
- [ ] Skill/playbook 数量是否有持续增长趋势？
- [ ] Memory 条目数是否随 session 数线性增长（非停滞）？
- [ ] 新增知识的质量验证率 ≥ 80%（非垃圾条目充数）？
- [ ] 是否有定期清理机制（过期/无效知识被淘汰）？
- [ ] 知识增长率是否与使用频率匹配（高频场景知识增长 > 低频场景）？

### 评分指南
```
知识增长率 = (本月新增有效条目 - 本月淘汰条目) / 月初总条目数:
增长率 5-15% → 5分
增长率 3-5% 或 15-25% → 4分
增长率 1-3% → 3分
增长率 0-1% → 2分
增长率 < 0% → 1分

> 特殊规则: 增长率 = 0 持续 10+ sessions → GRW 维度上限 = 2（知识停滞）
```

### 锚点示例

**最低分示例 (1分)** — 知识衰退:
```json
{
  "period": "2026-07-01 ~ 2026-07-31",
  "knowledge_audit": {
    "start_of_month": {"skills": 15, "playbook_rules": 42, "memory_entries": 500},
    "new_valid_entries": 3,
    "expired_entries_removed": 25,
    "end_of_month": {"skills": 14, "playbook_rules": 38, "memory_entries": 478},
    "growth_rate": "-4.6%",
    "issue": "过期清理正常运行，但新知识生成停滞——NudgeEngine 未触发新知识创建"
  }
}
```

**最高分示例 (5分)** — 健康增长:
```json
{
  "period": "2026-07-01 ~ 2026-07-31",
  "knowledge_audit": {
    "start_of_month": {"skills": 15, "playbook_rules": 42, "memory_entries": 500},
    "new_valid_entries": {"skills": 2, "playbook_rules": 5, "memory_entries": 45},
    "expired_entries_removed": 8,
    "end_of_month": {"skills": 17, "playbook_rules": 47, "memory_entries": 537},
    "growth_rate": "+8.2%",
    "quality_stats": {
      "new_entries_validated": 49,
      "new_entries_rejected": 3,
      "validation_rate": "94.2%"
    },
    "growth_by_frequency": {
      "high_freq_scenarios": "+12%",
      "medium_freq_scenarios": "+7%",
      "low_freq_scenarios": "+3%"
    }
  }
}
```

---

## 7. 综合评分计算

### 计算公式
```python
composite_score = (
    SUC_score * 0.30 +
    REC_score * 0.25 +
    ATF_score * 0.25 +
    GRW_score * 0.20
) * 20
# Range: 20 - 100
```

### 进化地板规则 (Evolution Floor Rules)

| 规则ID | 触发条件 | 效果 |
|--------|---------|------|
| FLOOR-SUC | SUC = 1（错误数恶化而非改善） | composite_score = min(composite_score, 59) |
| FLOOR-REC | REC = 1 且复发率 > 50% 持续 3+ 轮 | composite_score = min(composite_score, 59) |
| FLOOR-ATF | ATF = 1 且 auto-fix rate < 10% 持续 10+ sessions | composite_score = min(composite_score, 69) |
| FLOOR-GRW | GRW = 1 且增长率 = 0 持续 10+ sessions | composite_score = min(composite_score, 69) |
| FLOOR-MULTI | ≥ 2 个维度得分 < 2 | composite_score = min(composite_score, 69) |

> **进化特殊性**: Evolution 维度的地板规则引入了"持续条件"——单一 session 的低分不触发地板，需要问题持续多轮才判定为系统性失效。这体现了 Evolution 的长期性特征。

### 判定矩阵
| 总分 | 判定 | 后续行动 |
|------|------|---------|
| 90-100 | EXCELLENT | 自进化引擎卓越，已实现有效的自动学习闭环 |
| 80-89 | PASS | 自进化机制正常运转 |
| 70-79 | REVISE (轻) | 针对性优化特定维度的学习能力 |
| 60-69 | REVISE (重) | 系统性改进 NudgeEngine 检测/修补逻辑 |
| 40-59 | REJECT (可修复) | 学习机制基本失效 |
| 20-39 | REJECT (严重) | 自进化引擎形同虚设 |

---

## 8. 评估示例

### 示例 1: 高效自进化引擎 (参考 Hermes 3-session 学习)

**系统概况**: NudgeEngine 自动检测+修补，错误单调递减，3 session 内收敛
**各维度情况**:
- SUC: 错误数下降 92%，趋近 0 → 5分
- REC: 修复后零复现 → 5分
- ATF: 自动修复率 82% → 5分
- GRW: 知识月增长 10%，验证率 95% → 5分

**地板规则检查**: 全部 ≥ 2 → 无触发

**计算**:
```
(5×0.30 + 5×0.25 + 5×0.25 + 5×0.20) × 20
= (1.50 + 1.25 + 1.25 + 1.00) × 20
= 5.00 × 20
= 100 → EXCELLENT
```

### 示例 2: 失效的自进化引擎（反映当前手工 lessons.md 状态）

**系统概况**: 仅手工记录 lessons，无自动检测/修补，错误重复出现
**各维度情况**:
- SUC: 无自动学习，错误数无改善趋势 → 2分（因为 lessons 手工经验仍有微弱改善）
- REC: 同一问题反复出现（景点重复在 Batch 2/4/6 多次出现）→ 2分
- ATF: 自动修复率 0%（全手工）→ 1分
- GRW: 知识月增长 < 1%（仅手工追加 lessons）→ 2分

**地板规则检查**:
```
ATF=1, auto-fix_rate=0% → 持续多轮 → FLOOR-ATF 触发！
GRW=2 (增长率 < 1% 持续) → GRW < 1 不触发 FLOOR-GRW
维度 <2 = 1 (ATF) → <2 个 → 不触发 FLOOR-MULTI
→ 上限 = min(score, 69) = 69
```

**计算**:
```
(2×0.30 + 2×0.25 + 1×0.25 + 2×0.20) × 20
= (0.60 + 0.50 + 0.25 + 0.40) × 20
= 1.75 × 20
= 35 → min(35, 69) = 35
→ REJECT (严重)
```

> **解读**: 手工 lessons.md 仅能"记录"问题但不能"自动学习"。Evolution 维度的核心是自动化闭环——当前 0% 自动修复率使 Evolution 维度形同虚设。这是合理的：Evolution 模块尚未开发，手工经验记录不属于"自进化"范畴。

---

## 9. 变更日志

| 版本 | 日期 | 变更 |
|------|------|------|
| 1.0.0 | 2026-07-07 | 初始版本，4维度 Evolution 质量量表（Skill成功率趋势/错误复现率/自动化修复率/知识增长率）+ 持续条件地板规则 + 2个计算示例 |
