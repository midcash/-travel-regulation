# Plan Quality Rubric — 旅行方案质量评分量表

---

## 1. 概述

本文档是 **Layer 2 业务产出评估**的详细评分量表。ReviewerAgent 使用此量表对旅行规划方案进行评分。

> **当前项目映射**: 此量表直接用作 ReviewerAgent 的 system prompt 评分标准。KnowledgeAgent 负责可行性验证（替代原 Execution Agent），ReviewerAgent 负责质量评审（替代原 Evaluation Agent）。

---

## 2. 评分维度与权重

| 维度 | 权重 | 缩写 | 来源 |
|------|------|------|------|
| 完整性 (Completeness) | 25% | COM | 直接评估 TravelPlanDraft |
| 可行性 (Feasibility) | 25% | FEA | 引用 KnowledgeAgent 的可行性验证结果 |
| 约束满足度 (Constraint Satisfaction) | 25% | CON | 对比原始用户需求 |
| 体验质量 (Experience Quality) | 15% | EXP | 主观评估 + 规则检查 |
| 信息准确度 (Information Accuracy) | 10% | ACC | 引用 KnowledgeAgent 的价格校验 |

---

## 3. 完整性 (Completeness) — 权重 25%

### 评分锚点

| 分数 | 描述 | 判定标准 |
|------|------|---------|
| 5 | 完整 | 全部5个必需模块完整: 交通(往返+当地) + 住宿(≥2选项) + 每日行程(每天≥2活动) + 餐饮(每天3餐) + 预算明细 |
| 4 | 基本完整 | 5个模块齐全，但个别模块有轻微缺失（如某餐缺推荐、住宿仅1个选项） |
| 3 | 部分缺失 | 缺少1个模块，或2个以上模块有轻微缺失 |
| 2 | 明显缺失 | 缺少2个以上模块 |
| 1 | 严重不完整 | 仅有框架，缺少实质内容（如仅有目的地和日期，无具体行程） |

### 检查清单
- [ ] transportation: 是否有往返交通方案？
- [ ] transportation: 是否有当地交通建议？
- [ ] accommodation: 是否 ≥ 2 个选项？
- [ ] daily_itinerary: 每天是否 ≥ 2 个活动？
- [ ] daily_itinerary: 每天是否 ≥ 2 餐推荐？
- [ ] budget_breakdown: 是否包含所有分项（交通/住宿/活动/餐饮/缓冲）？

### 评分指南
```
每项缺失扣 0.5 分（从 5 分起扣，最低 1 分）
6/6 ✓ = 5分
5/6 ✓ = 4分
4/6 ✓ = 3分
2-3/6 ✓ = 2分
0-1/6 ✓ = 1分
```

> **注意**: 判定交通方案是否为空时，不能仅依赖 `transportation.to_dict()` 返回非空结构。必须检查 `outbound` / `return_trip` / `local` 中至少有一个包含实质性交通信息（如航班号、车次、路线描述）。空 dict 占位 ≠ 有交通方案。（参考: lessons.md Batch 2 — score_completeness 空交通检测遗漏）

### 锚点示例

**最低分示例 (1分)** — 仅有目的地和日期，无实质内容:
```json
{
  "destination": {"city": "东京", "country": "日本"},
  "dates": {"arrival": "2026-12-20", "departure": "2026-12-25"},
  "transportation": {"outbound": {}, "return_trip": {}, "local": {}},
  "accommodation": [],
  "daily_itinerary": [
    {"day": 1, "activities": [], "meals": {"breakfast": {}, "lunch": {}, "dinner": {}}}
  ],
  "budget_breakdown": {}
}
```

**最高分示例 (5分)** — 5大模块齐全，每项充实:
```json
{
  "destination": {"city": "东京", "country": "日本"},
  "dates": {"arrival": "2026-12-20", "departure": "2026-12-25"},
  "transportation": {
    "outbound": {"type": "flight", "route": "北京→东京", "flight_no": "CA925", "duration": "3h30m", "price": 3500},
    "return_trip": {"type": "flight", "route": "东京→北京", "flight_no": "CA926", "duration": "4h", "price": 3500},
    "local": {"type": "地铁+JR", "description": "Suica卡+JR Pass 7日券", "estimated_cost": 800}
  },
  "accommodation": [
    {"name": "新宿王子酒店", "location": "新宿", "price_per_night": 800, "rating": 4.2},
    {"name": "浅草雷门酒店", "location": "浅草", "price_per_night": 600, "rating": 4.0}
  ],
  "daily_itinerary": [
    {
      "day": 1,
      "activities": [{"name": "浅草寺", "duration": "2h"}, {"name": "晴空塔", "duration": "2h"}],
      "meals": {
        "breakfast": {"name": "酒店自助", "cost": 0},
        "lunch": {"name": "一兰拉面 浅草店", "cost": 60},
        "dinner": {"name": "居酒屋 鳥貴族", "cost": 150}
      }
    }
  ],
  "budget_breakdown": {"transportation": 7800, "accommodation": 4000, "activities": 1500, "meals": 2000, "buffer": 700}
}
```

---

## 4. 可行性 (Feasibility) — 权重 25%

### 评分锚点

| 分数 | 描述 | 判定标准 |
|------|------|---------|
| 5 | 完全可行 | blocking_issues = 0 且 warnings = 0 |
| 4 | 可行（少量警告） | blocking_issues = 0 且 warnings ≤ 2 |
| 3 | 基本可行（较多警告） | blocking_issues = 0 且 warnings > 2 |
| 2 | 存在阻断问题 | blocking_issues = 1-2 |
| 1 | 严重不可行 | blocking_issues ≥ 3 |

### 检查要点 (引用 KnowledgeAgent 验证结果)
- [ ] blocking_issues 数量
- [ ] price anomalies 数量和 severity
- [ ] time conflicts 数量
- [ ] detours found 数量
- [ ] risk alerts 数量和 severity

### 评分指南
```
直接引用 KnowledgeAgent 的验证结果:
- blocking_count = 0 且 warning_count = 0 → 5分
- blocking_count = 0 且 warning_count ≤ 2 → 4分
- blocking_count = 0 且 warning_count > 2 → 3分
- blocking_count = 1-2 → 2分
- blocking_count ≥ 3 → 1分
```

### 锚点示例

**最低分示例 (1分)** — 3个阻断问题，方案基本不可行:
```json
{
  "validation_report": {
    "summary": {"blocking_count": 3, "warning_count": 5},
    "blocking_issues": [
      {"constraint": "budget", "severity": "high", "detail": "总花费 18500 超出预算 15000 达 23%"},
      {"constraint": "geography", "severity": "high", "detail": "Day 3 大阪→东京→大阪 当日往返不可行"},
      {"constraint": "time", "severity": "high", "detail": "Day 5 航班 10:00 与上午行程冲突"}
    ],
    "price_check": {"mean_deviation_pct": 35.0},
    "time_check": {"conflicts_found": 2},
    "geo_check": {"detours_found": 1}
  }
}
```

**最高分示例 (5分)** — 零阻断 + 零警告:
```json
{
  "validation_report": {
    "summary": {"blocking_count": 0, "warning_count": 0},
    "blocking_issues": [],
    "price_check": {"mean_deviation_pct": 6.5, "anomalies": []},
    "time_check": {"conflicts_found": 0},
    "geo_check": {"detours_found": 0},
    "risk_check": {"alerts": [], "weather_ok": true, "visa_ok": true}
  }
}
```

---

## 5. 约束满足度 (Constraint Satisfaction) — 权重 25%

### 评分锚点

| 分数 | 描述 | 判定标准 |
|------|------|---------|
| 5 | 完美满足 | 硬约束 100% 满足 + 软约束 ≥ 90% 满足 |
| 4 | 高度满足 | 硬约束 100% 满足 + 软约束 80-89% 满足 |
| 3 | 基本满足 | 硬约束 100% 满足 + 软约束 70-79% 满足 |
| 2 | 存在违反 | 硬约束 < 100% 或软约束 < 70% |
| 1 | 多处违反 | 多项硬约束违反 |

### 硬约束检查清单
- [ ] 总预算 ≤ 用户预算上限
- [ ] 出发日期 = 用户指定日期
- [ ] 返回日期 = 用户指定日期
- [ ] 人数配置正确
- [ ] 未推荐用户排除的类型/区域

### 软约束检查清单
- [ ] 偏好风格匹配（如"美食"→ 有特色餐饮推荐）
- [ ] 节奏偏好匹配（如"休闲"→ 每天活动不过密）
- [ ] 住宿类型匹配（如"舒适"→ 非青旅/非奢华）
- [ ] 饮食限制满足（如素食→ 所有餐厅推荐为素食）
- [ ] 无障碍需求满足

### 评分指南
```
硬约束检查:
  全部通过 → 满分基数 5
  1项违反 → 直接 2 分
  2+项违反 → 直接 1 分

软约束检查 (在硬约束满分基础上):
  每项未满足扣 0.4 分
  CSR_soft = 满足数/总数
  CSR_soft ≥ 90% → 5分
  CSR_soft 80-89% → 4分
  CSR_soft 70-79% → 3分
  CSR_soft < 70% → 2分
```

### 锚点示例

**最低分示例 (1分)** — 预算超支 + 日期错误 + 未考虑饮食限制:
```json
{
  "user_request": {
    "destination": "曼谷", "budget": 3000, "travelers": 2,
    "dates": {"arrival": "2026-08-15", "departure": "2026-08-18"},
    "preferences": ["美食"], "dietary": {"restrictions": ["素食"]}
  },
  "constraint_check": {
    "hard_constraints": {
      "budget_within_limit": false,
      "arrival_date_match": false,
      "departure_date_match": true,
      "travelers_match": true,
      "no_excluded_types": true
    },
    "soft_constraints": {
      "style_match": false,
      "pace_match": true,
      "accommodation_type_match": true,
      "dietary_satisfied": false,
      "accessibility_satisfied": true
    },
    "hard_pass_rate": "3/5 (60%)",
    "soft_pass_rate": "3/5 (60%)"
  }
}
```

**最高分示例 (5分)** — 全部硬约束满足 + 软约束 100%:
```json
{
  "user_request": {
    "destination": "京都", "budget": 12000, "travelers": 2,
    "dates": {"arrival": "2026-11-15", "departure": "2026-11-20"},
    "preferences": ["文化", "美食"], "dietary": {"restrictions": []}
  },
  "constraint_check": {
    "hard_constraints": {
      "budget_within_limit": true,
      "arrival_date_match": true,
      "departure_date_match": true,
      "travelers_match": true,
      "no_excluded_types": true
    },
    "soft_constraints": {
      "style_match": true,
      "pace_match": true,
      "accommodation_type_match": true,
      "dietary_satisfied": true,
      "accessibility_satisfied": true
    },
    "hard_pass_rate": "5/5 (100%)",
    "soft_pass_rate": "5/5 (100%)"
  }
}
```

---

## 6. 体验质量 (Experience Quality) — 权重 15%

### 评分锚点

| 分数 | 描述 | 判定标准 |
|------|------|---------|
| 5 | 卓越体验 | 节奏合理 + 活动多样(≥3种类型) + 高度个性化(≥80%偏好匹配) + 有惊喜元素 |
| 4 | 良好体验 | 三项中两项优秀，一项良好。整体体验舒适。 |
| 3 | 一般体验 | 三项中一项优秀，其他及格。无明显亮点但可接受。 |
| 2 | 体验较差 | 节奏失衡或活动单调。个性化不足。 |
| 1 | 体验糟糕 | 明显不考虑用户体验。如每天满负荷、无休息日、所有活动同质化。 |

### 检查要点
- [ ] 节奏合理性: 每日活动总时间 ≤ 10h，有休息缓冲
- [ ] 多样性: 活动类型 ≥ 3 种
- [ ] 个性化: 偏好标签匹配率 ≥ 70%
- [ ] 节奏变化: 不是每天相同节奏（有轻重缓急）
- [ ] 特色体验: 是否有"只有当地才有的"独特活动

### 评分指南
```
5分: 5/5 检查要点 ✓
4分: 4/5 检查要点 ✓
3分: 3/5 检查要点 ✓
2分: 2/5 检查要点 ✓
1分: 0-1/5 检查要点 ✓
```

### 锚点示例

**最低分示例 (1分)** — 天天同质化、满负荷运转、无个性化:
```json
{
  "experience_profile": {
    "daily_activity_hours": [12, 13, 11, 12, 12],
    "activity_types": ["购物", "购物"],
    "preference_match_rate": 0.10,
    "pace_variance": "无变化 — 每天高强度",
    "unique_experiences": [],
    "issues": [
      "所有天次均为购物行程，活动类型仅1种",
      "每日活动超12小时，无休息缓冲",
      "用户偏好'文化+美食'，但方案中0个文化景点、0家特色餐厅"
    ]
  }
}
```

**最高分示例 (5分)** — 节奏合理、活动多样、高度个性化、有惊喜:
```json
{
  "experience_profile": {
    "daily_activity_hours": [7, 8, 6, 9, 5],
    "activity_types": ["历史古迹", "美食体验", "自然风光", "手作体验", "温泉"],
    "preference_match_rate": 0.90,
    "pace_variance": "轻重交替 — Day1密集/Day3轻松/Day5半天",
    "unique_experiences": [
      "筑地市场金枪鱼拍卖参观（需凌晨4点排队）",
      "箱根露天温泉 + 富士山景观",
      "浅草和服体验 + 专业摄影师跟拍"
    ],
    "highlights": "最后一天安排半天自由探索，不塞满行程"
  }
}
```

---

## 7. 信息准确度 (Information Accuracy) — 权重 10%

### 评分锚点

| 分数 | 描述 | 判定标准 |
|------|------|---------|
| 5 | 高度准确 | 价格偏差均值 < 10%，无虚构信息 |
| 4 | 基本准确 | 价格偏差均值 10-15% |
| 3 | 存在偏差 | 价格偏差均值 15-20% |
| 2 | 偏差较大 | 价格偏差均值 20-30% |
| 1 | 严重失实 | 价格偏差均值 > 30% 或存在虚构的地点/活动 |

### 检查要点 (引用 KnowledgeAgent 价格校验)
- [ ] MPD (价格偏差均值): 来自 KnowledgeAgent 的 price_check 结果
- [ ] 虚构检查: 所有推荐项是否可在真实世界查证
- [ ] 货币一致性: 所有价格是否使用相同货币单位
- [ ] 时效性: 价格数据是否与出行日期匹配（非过期数据）

### 评分指南
```
以 MPD 为主要依据:
MPD < 10% → 5分
MPD 10-15% → 4分
MPD 15-20% → 3分
MPD 20-30% → 2分
MPD > 30% → 1分

额外扣分:
- 发现虚构地点 → 直接 1 分
- 货币不统一 → 扣 1 分
- 价格数据过期(>30天) → 扣 1 分
```

### 锚点示例

**最低分示例 (1分)** — 价格偏差严重 + 虚构景点:
```json
{
  "accuracy_profile": {
    "mean_price_deviation_pct": 42.0,
    "price_checks": [
      {"item": "酒店", "estimated": 300, "market": 1200, "deviation_pct": 75.0},
      {"item": "午餐", "estimated": 20, "market": 80, "deviation_pct": 75.0}
    ],
    "fabricated_items": [
      {"name": "东京幻想乐园", "reason": "不存在于此地址的虚构景点"}
    ],
    "currency_consistency": false,
    "data_freshness_days": 180
  }
}
```

**最高分示例 (5分)** — 价格高度准确 + 信息真实:
```json
{
  "accuracy_profile": {
    "mean_price_deviation_pct": 5.2,
    "price_checks": [
      {"item": "酒店", "estimated": 850, "market": 880, "deviation_pct": 3.4},
      {"item": "机票", "estimated": 3200, "market": 3350, "deviation_pct": 4.5},
      {"item": "景点门票", "estimated": 150, "market": 160, "deviation_pct": 6.3}
    ],
    "fabricated_items": [],
    "currency_consistency": true,
    "data_freshness_days": 3
  }
}
```

---

## 8. 综合评分计算

### 计算公式
```python
composite_score = (
    COM_score * 0.25 +
    FEA_score * 0.25 +
    CON_score * 0.25 +
    EXP_score * 0.15 +
    ACC_score * 0.10
) * 20
# Range: 20 - 100
```

### 维度地板规则 (Dimension Floor Rule)

在应用判定矩阵之前，先检查维度地板规则。任一维度触发地板规则时，composite_score 上限被强制锁定，防止高权重维度"掩盖"致命缺陷。

| 规则ID | 触发条件 | 效果 |
|--------|---------|------|
| FLOOR-COM | COM < 2（缺住宿+行程+交通中至少2项） | composite_score = min(composite_score, 59) |
| FLOOR-FEA | FEA = 1（blocking_issues ≥ 3） | composite_score = min(composite_score, 59) |
| FLOOR-CON | CON = 1（多项硬约束违反） | composite_score = min(composite_score, 59) |
| FLOOR-ACC | ACC = 1（MPD > 30% 或虚构地点） | composite_score = min(composite_score, 59) |
| FLOOR-MULTI | ≥ 3 个维度得分 < 3 | composite_score = min(composite_score, 69) |

> **设计意图**: 即使其他维度得分很高，一个致命缺陷（如内容严重缺失、价格全部虚构）也应将方案拉至 REJECT 或 REVISE (重) 区间。这解决了"completeness=2.5 但总分 65.5 只是 REVISE (重) 而非 REJECT"的评分过松问题。

### 判定矩阵
| 总分 | 判定 | 后续行动 |
|------|------|---------|
| 90-100 | EXCELLENT | 直接输出，可作为优质案例 |
| 80-89 | PASS | 直接输出 |
| 70-79 | REVISE (轻) | 针对性修订 2-3 个具体问题 |
| 60-69 | REVISE (重) | 修订 ≥ 3 个具体问题 |
| 40-59 | REJECT (可修复) | 重大缺陷，需重新规划 |
| 20-39 | REJECT (严重) | 基本不可用，从头重新规划 |

---

## 9. 评估示例

### 示例 1: 高质量方案

**方案概况**: 东京5天，预算15000，2人，美食+文化
**各维度情况**:
- COM: 全部6项齐全 → 5分
- FEA: blocking=0, warnings=1 → 4分
- CON: 硬约束全过，软约束85% → 4分
- EXP: 节奏合理+3种活动类型+80%偏好匹配 → 4分
- ACC: MPD=8% → 5分

**地板规则检查**:
```
COM=5 (≥2 ✓), FEA=4 (≥2 ✓), CON=4 (≥2 ✓), ACC=5 (≥2 ✓)
维度 <3 的数量 = 0 (<3 ✓)
→ 无地板规则触发
```

**计算**:
```
(5×0.25 + 4×0.25 + 4×0.25 + 4×0.15 + 5×0.10) × 20
= (1.25 + 1.00 + 1.00 + 0.60 + 0.50) × 20
= 4.35 × 20
= 87 → PASS
```

### 示例 2: 维度地板触发 — 内容严重缺失

**方案概况**: 曼谷3天，预算5000，2人，无特殊偏好
**各维度情况**:
- COM: 缺住宿+行程+交通，仅1分（对应 handoff §6 中 completeness=2.5 的改进场景）
- FEA: 仅有价格警告，blocking=0, warnings=2 → 4分
- CON: 硬约束全过，软约束80% → 4分
- EXP: 节奏尚可，活动较少 → 3分
- ACC: MPD=12% → 4分

**地板规则检查**:
```
COM=1 (<2 → FLOOR-COM 触发！)
→ composite_score 上限被强制锁定为 59
```

**计算**:
```
(1×0.25 + 4×0.25 + 4×0.25 + 3×0.15 + 4×0.10) × 20
= (0.25 + 1.00 + 1.00 + 0.45 + 0.40) × 20
= 3.10 × 20
= 62 → 但 FLOOR-COM 触发 → min(62, 59) = 59
→ REJECT (可修复)
```

> **对比**: 若无地板规则，此方案得分 62 → REVISE (重)。但"缺住宿+行程+交通"是致命缺陷，不应仅靠高可行性/约束分"掩盖"。地板规则将其正确拉至 REJECT。

### 示例 3: 多维度低分 — FLOOR-MULTI 触发

**方案概况**: 巴黎4天，预算8000，1人，艺术+历史
**各维度情况**:
- COM: 缺当地交通+住宿仅1选项 → 3分
- FEA: blocking=0, warnings=4 → 3分
- CON: 硬约束1项违反(预算) → 2分
- EXP: 仅2种活动类型，个性化不足 → 2分
- ACC: MPD=18% → 3分

**地板规则检查**:
```
COM=3 (≥2 ✓), FEA=3 (≥2 ✓), CON=2 (≥2 ✓), ACC=3 (≥2 ✓)
维度 <3 的数量 = 2 (CON=2, EXP=2) → <3, 不触发 FLOOR-MULTI
→ 无地板规则触发
```

**计算**:
```
(3×0.25 + 3×0.25 + 2×0.25 + 2×0.15 + 3×0.10) × 20
= (0.75 + 0.75 + 0.50 + 0.30 + 0.30) × 20
= 2.60 × 20
= 52 → REJECT (可修复)
```

---

## 10. 变更日志

| 版本 | 日期 | 变更 |
|------|------|------|
| 1.0.0 | 2026-07-05 | 初始版本，5维度完整评分量表附带计算示例 |
| 1.1.0 | 2026-07-07 | Step 1 评分校准: (a) 5个维度各新增最低分/最高分 JSON 锚点示例 (b) §8 新增维度地板规则 (FLOOR-COM/FEA/CON/ACC/MULTI) 防止维度分掩盖致命缺陷 (c) §9 示例更新: 示例2 改为展示 FLOOR-COM 触发场景, 新增示例3 多维度低分场景 (d) §3 评分指南追加 transportation.to_dict() 空值判定提醒 |
