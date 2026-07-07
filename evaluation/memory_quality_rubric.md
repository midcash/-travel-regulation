# Memory Quality Rubric — 记忆模块质量评分量表

---

## 1. 概述

本文档是 **Layer 2 业务产出评估**中 Memory 模块的专用评分量表。用于评估记忆系统的检索质量、偏好一致性、压缩保真度和跨会话复用能力。

**评估对象**: Memory 四层体系 — UserProfile（用户画像持久化）、SessionMemory（会话工作记忆）、EpisodicMemory（历史方案检索）、MemoryManager（统一读写接口）

**评估时机**: 每次 Memory 模块变更后、每 10 个会话后定期审计

**当前状态**: Memory 模块完全空白（仅有 SharedContext 会话级，无持久化）。此量表用于后续 Memory 模块开发时的评估驱动。

---

## 2. 评分维度与权重

| 维度 | 权重 | 缩写 | 核心问题 |
|------|------|------|---------|
| 检索命中率 (Recall) | 30% | REC | 给定查询，历史相关记忆是否被检索到？ |
| 偏好一致性 (Consistency) | 25% | CON | 用户偏好（素食/不购物等）是否跨会话保持一致？ |
| 压缩保真度 (Fidelity) | 25% | FID | 容量限制下，关键信息是否保留、非关键信息是否被正确裁剪？ |
| 跨会话复用率 (Reuse) | 20% | REU | 新会话中，历史记忆被实际引用的比例？ |

---

## 3. 检索命中率 (Recall) — 权重 30%

### 评分锚点

| 分数 | 描述 | 判定标准 |
|------|------|---------|
| 5 | 精确检索 | recall@5 ≥ 0.95, precision@5 ≥ 0.90, MRR ≥ 0.90 |
| 4 | 良好检索 | recall@5 ≥ 0.85, precision@5 ≥ 0.80, MRR ≥ 0.80 |
| 3 | 基本可用 | recall@5 ≥ 0.70, precision@5 ≥ 0.65, MRR ≥ 0.65 |
| 2 | 检索不足 | recall@5 0.50-0.69 或 precision@5 < 0.65 |
| 1 | 检索失效 | recall@5 < 0.50，大部分相关记忆无法检索 |

### 检查清单
- [ ] recall@5: 前5个结果中包含相关记忆的比例 ≥ 0.85？
- [ ] precision@5: 前5个结果中相关记忆的占比 ≥ 0.80？
- [ ] MRR (Mean Reciprocal Rank): 第一个相关记忆的平均排名倒数 ≥ 0.80？
- [ ] 语义匹配: 同义查询（"东京美食" vs "东京好吃的"）是否能检索到相同结果集？
- [ ] 跨模态: 用户用不同表述描述同一偏好时，检索是否一致？

### 评分指南
```
以 recall@5 为主要依据，precision@5 和 MRR 为辅助:
recall@5 ≥ 0.95 且 precision@5 ≥ 0.90 → 5分
recall@5 ≥ 0.85 且 precision@5 ≥ 0.80 → 4分
recall@5 ≥ 0.70 且 precision@5 ≥ 0.65 → 3分
recall@5 0.50-0.69 → 2分
recall@5 < 0.50 → 1分
```

### 锚点示例

**最低分示例 (1分)** — 明显相关的历史记忆无法检索:
```json
{
  "query": {"user_id": "u_001", "intent": "上次去东京的酒店推荐"},
  "ground_truth": ["session_42_hotel_list", "user_profile_hotel_pref"],
  "retrieval_result": {
    "retrieved_items": ["session_15_weather", "session_08_flight"],
    "recall_at_5": 0.0,
    "precision_at_5": 0.0,
    "mrr": 0.0
  }
}
```

**最高分示例 (5分)** — 精确检索所有相关记忆:
```json
{
  "query": {"user_id": "u_001", "intent": "上次去东京的酒店推荐"},
  "ground_truth": ["session_42_hotel_list", "user_profile_hotel_pref", "session_42_budget"],
  "retrieval_result": {
    "retrieved_items": [
      {"id": "session_42_hotel_list", "score": 0.98, "rank": 1},
      {"id": "user_profile_hotel_pref", "score": 0.95, "rank": 2},
      {"id": "session_42_budget", "score": 0.91, "rank": 3},
      {"id": "session_41_restaurant", "score": 0.72, "rank": 4},
      {"id": "session_40_transport", "score": 0.55, "rank": 5}
    ],
    "recall_at_5": 1.0,
    "precision_at_5": 0.80,
    "mrr": 1.0
  }
}
```

---

## 4. 偏好一致性 (Consistency) — 权重 25%

### 评分锚点

| 分数 | 描述 | 判定标准 |
|------|------|---------|
| 5 | 完全一致 | 所有已记录偏好跨会话 100% 保持一致，无冲突 |
| 4 | 高度一致 | ≥ 95% 偏好保持一致，偶发轻微冲突被自动解决 |
| 3 | 基本一致 | 85-94% 偏好一致，个别冲突需人工介入 |
| 2 | 存在冲突 | 70-84% 偏好一致，多次出现偏好丢失或冲突 |
| 1 | 严重不一致 | < 70% 偏好一致，偏好频繁丢失或被覆盖 |

### 检查清单
- [ ] 用户画像中的偏好是否在所有会话中一致读取？
- [ ] 偏好更新后，旧会话的历史偏好是否被正确覆盖（非并存冲突版本）？
- [ ] 冲突检测: 是否存在两个冲突偏好同时生效（如"素食"和"推荐和牛餐厅"）？
- [ ] 默认值污染: 用户未设置的偏好是否被错误地使用默认值覆盖？
- [ ] 偏好久久性: 用户 3 个月前设置的偏好是否仍然生效？

### 评分指南
```
偏好一致率 (PC_rate) = 一致会话数 / 总会话数:
PC_rate ≥ 99% → 5分
PC_rate 95-98% → 4分
PC_rate 85-94% → 3分
PC_rate 70-84% → 2分
PC_rate < 70% → 1分
```

### 锚点示例

**最低分示例 (1分)** — 偏好频繁丢失和冲突:
```json
{
  "user_id": "u_002",
  "user_profile": {"dietary": "素食", "budget_level": "经济"},
  "session_history": [
    {"session": "s_01", "dietary_applied": "素食", "consistent": true},
    {"session": "s_02", "dietary_applied": null, "consistent": false, "issue": "偏好丢失，推荐了和牛餐厅"},
    {"session": "s_03", "dietary_applied": "无限制", "consistent": false, "issue": "被默认值覆盖"},
    {"session": "s_04", "dietary_applied": "素食", "consistent": true}
  ],
  "consistency_rate": "2/4 (50%)"
}
```

**最高分示例 (5分)** — 偏好跨会话完全一致:
```json
{
  "user_id": "u_003",
  "user_profile": {
    "dietary": {"restrictions": ["素食"], "preferences": ["日料", "意大利菜"]},
    "travel_style": "文化深度",
    "budget_level": "舒适",
    "avoid": ["购物陷阱", "过度商业化的景点"],
    "last_updated": "2026-03-15"
  },
  "session_history": [
    {"session": "s_10", "date": "2026-03-20", "preferences_applied": "5/5", "conflicts": 0},
    {"session": "s_11", "date": "2026-05-12", "preferences_applied": "5/5", "conflicts": 0},
    {"session": "s_12", "date": "2026-07-01", "preferences_applied": "5/5", "conflicts": 0}
  ],
  "consistency_rate": "100% (15/15 preferences consistent across 3 sessions)"
}
```

---

## 5. 压缩保真度 (Fidelity) — 权重 25%

### 评分锚点

| 分数 | 描述 | 判定标准 |
|------|------|---------|
| 5 | 完美保真 | 关键信息 100% 保留，非关键信息被正确识别和裁剪 |
| 4 | 高度保真 | 关键信息保留 ≥ 95%，裁剪准确率 ≥ 90% |
| 3 | 基本保真 | 关键信息保留 85-94%，偶有误裁或冗余保留 |
| 2 | 保真不足 | 关键信息丢失 > 15% 或大量冗余未裁剪 |
| 1 | 严重失真 | 压缩后关键信息丢失 > 30%，记忆基本不可用 |

### 检查清单
- [ ] 关键信息（目的地、预算、日期、偏好）是否在压缩后完整保留？
- [ ] 非关键信息（临时状态、中间草稿、重复内容）是否被正确裁剪？
- [ ] 压缩比是否在目标范围内（如 10:1 压缩后仍可恢复关键事实）？
- [ ] 压缩是否可逆验证（解压后关键信息可校验）？
- [ ] 边界情况: 容量满了之后，最旧的记忆是否按 LRU 正确淘汰？

### 评分指南
```
关键信息保留率 (KIR) = 保留的关键字段数 / 总关键字段数:
KIR = 100% → 5分
KIR ≥ 95% → 4分
KIR 85-94% → 3分
KIR 70-84% → 2分
KIR < 70% → 1分
```

### 锚点示例

**最低分示例 (1分)** — 压缩后关键信息大量丢失:
```json
{
  "session_id": "s_20",
  "original_size_kb": 45.2,
  "compressed_size_kb": 2.1,
  "compression_ratio": "21.5:1",
  "key_information_audit": {
    "destination": {"original": "东京", "retained": "东京", "ok": true},
    "budget": {"original": 15000, "retained": null, "ok": false, "issue": "关键数值丢失"},
    "dates": {"original": "2026-12-20~25", "retained": "2026-12-??", "ok": false, "issue": "日期被截断"},
    "dietary": {"original": "素食", "retained": null, "ok": false, "issue": "偏好丢失"},
    "hotel_choice": {"original": "新宿王子酒店", "retained": null, "ok": false, "issue": "具体选择丢失"}
  },
  "key_info_retention": "1/5 (20%)"
}
```

**最高分示例 (5分)** — 压缩后关键信息完整保留:
```json
{
  "session_id": "s_21",
  "original_size_kb": 52.8,
  "compressed_size_kb": 8.5,
  "compression_ratio": "6.2:1",
  "key_information_audit": {
    "destination": {"original": "京都", "retained": "京都", "ok": true},
    "budget": {"original": 12000, "retained": 12000, "ok": true},
    "dates": {"original": "2026-11-15~20", "retained": "2026-11-15~20", "ok": true},
    "dietary": {"original": ["无限制"], "retained": ["无限制"], "ok": true},
    "selected_hotel": {"original": "京都站前酒店", "retained": "京都站前酒店", "ok": true},
    "top_attractions": {"original": ["金阁寺","伏见稻荷","岚山"], "retained": ["金阁寺","伏见稻荷","岚山"], "ok": true}
  },
  "key_info_retention": "6/6 (100%)",
  "pruned_correctly": ["临时价格查询缓存", "中间draft v1/v2", "重复的交通查询"],
  "pruned_incorrectly": []
}
```

---

## 6. 跨会话复用率 (Reuse) — 权重 20%

### 评分锚点

| 分数 | 描述 | 判定标准 |
|------|------|---------|
| 5 | 高度复用 | ≥ 80% 的新会话引用了历史记忆 |
| 4 | 良好复用 | 60-79% 的新会话引用了历史记忆 |
| 3 | 部分复用 | 40-59% 的新会话引用了历史记忆 |
| 2 | 低复用 | 20-39% 的新会话引用了历史记忆 |
| 1 | 几乎不复用 | < 20% 的新会话引用了历史记忆，记忆形同虚设 |

### 检查清单
- [ ] 复用率: 新会话中 MemoryManager 返回的数据被实际使用的比例？
- [ ] 引用深度: 被引用的记忆是仅用户画像（浅层）还是包含历史方案细节（深层）？
- [ ] 复用价值: 被复用的记忆是否对方案质量有正向贡献？
- [ ] 过期淘汰: 过期/不再相关的记忆是否自动降低权重？

### 评分指南
```
复用率 = 引用历史记忆的会话数 / 总新会话数:
复用率 ≥ 80% → 5分
复用率 60-79% → 4分
复用率 40-59% → 3分
复用率 20-39% → 2分
复用率 < 20% → 1分

额外加分: 深层引用(历史方案细节) > 浅层引用(仅用户画像) → +0.5分
```

### 锚点示例

**最低分示例 (1分)** — 记忆几乎不被使用:
```json
{
  "period": "2026-06-01 ~ 2026-07-01",
  "total_sessions": 25,
  "sessions_with_memory_reuse": 2,
  "reuse_rate": "8%",
  "reuse_breakdown": {
    "user_profile_only": 2,
    "historical_plan_detail": 0,
    "episodic_similar_plan": 0
  },
  "analysis": "仅2次会话引用了用户画像中的语言偏好，历史方案完全未被复用"
}
```

**最高分示例 (5分)** — 记忆深度融入每次新会话:
```json
{
  "period": "2026-06-01 ~ 2026-07-01",
  "total_sessions": 20,
  "sessions_with_memory_reuse": 18,
  "reuse_rate": "90%",
  "reuse_breakdown": {
    "user_profile_only": 5,
    "user_profile_plus_preferences": 8,
    "historical_plan_detail_referenced": 5,
    "episodic_similar_plan_retrieved": 3
  },
  "quality_impact": {
    "avg_score_with_memory": 85.3,
    "avg_score_without_memory": 72.1,
    "delta": "+13.2"
  }
}
```

---

## 7. 综合评分计算

### 计算公式
```python
composite_score = (
    REC_score * 0.30 +
    CON_score * 0.25 +
    FID_score * 0.25 +
    REU_score * 0.20
) * 20
# Range: 20 - 100
```

### 维度地板规则

| 规则ID | 触发条件 | 效果 |
|--------|---------|------|
| FLOOR-REC | REC = 1（recall@5 < 50%，检索基本失效） | composite_score = min(composite_score, 59) |
| FLOOR-CON | CON = 1（偏好一致率 < 70%） | composite_score = min(composite_score, 59) |
| FLOOR-MULTI | ≥ 2 个维度得分 < 2 | composite_score = min(composite_score, 69) |

### 判定矩阵
| 总分 | 判定 | 后续行动 |
|------|------|---------|
| 90-100 | EXCELLENT | Memory 模块质量卓越，可作为参考实现 |
| 80-89 | PASS | 质量达标，可投入生产使用 |
| 70-79 | REVISE (轻) | 针对性优化 2-3 个检索/一致性问题 |
| 60-69 | REVISE (重) | 系统性改进 ≥ 3 个维度 |
| 40-59 | REJECT (可修复) | 重大缺陷（检索失效/偏好严重冲突） |
| 20-39 | REJECT (严重) | Memory 模块基本不可用 |

---

## 8. 评估示例

### 示例 1: 高质量 Memory 系统

**系统概况**: 四层体系完整实现，30 天运行数据
**各维度情况**:
- REC: recall@5=0.93, precision@5=0.88, MRR=0.87 → 4分
- CON: 偏好一致率 97% → 4分
- FID: KIR=100%, 压缩比 6:1 → 5分
- REU: 复用率 85%, 深层引用占 40% → 5分

**地板规则检查**:
```
REC=4 (≥2 ✓), CON=4 (≥2 ✓)
维度 <2 的数量 = 0
→ 无地板规则触发
```

**计算**:
```
(4×0.30 + 4×0.25 + 5×0.25 + 5×0.20) × 20
= (1.20 + 1.00 + 1.25 + 1.00) × 20
= 4.45 × 20
= 89 → PASS
```

### 示例 2: 低质量 Memory 系统

**系统概况**: 仅有 SessionMemory 无持久化，偏好频繁丢失
**各维度情况**:
- REC: recall@5=0.45, 大量相关记忆检索不到 → 1分
- CON: 偏好一致率 60% → 1分
- FID: 无压缩机制，内存溢出导致截断 → 2分
- REU: 复用率 10% → 1分

**地板规则检查**:
```
REC=1 → FLOOR-REC 触发！
CON=1 → FLOOR-CON 触发！
维度 <2 的数量 = 3 (REC/CON/REU) → FLOOR-MULTI 触发！
→ composite_score 上限被多规则限制为 min(score, 59, 59, 69) = 59
```

**计算**:
```
(1×0.30 + 1×0.25 + 2×0.25 + 1×0.20) × 20
= (0.30 + 0.25 + 0.50 + 0.20) × 20
= 1.25 × 20
= 25 → min(25, 59) = 25
→ REJECT (严重)
```

---

## 9. 变更日志

| 版本 | 日期 | 变更 |
|------|------|------|
| 1.0.0 | 2026-07-07 | 初始版本，4维度 Memory 质量量表（检索命中率/偏好一致性/压缩保真度/跨会话复用率）+ 2个计算示例 |
