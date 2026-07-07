# Tool Quality Rubric — 工具系统质量评分量表

---

## 1. 概述

本文档是 **Layer 2 业务产出评估**中 Tool System 的专用评分量表。用于评估工具系统的 API 可用性、响应延迟、结果准确率和降级优雅度。

**评估对象**: Tool System — ToolRegistry（统一注册/发现）+ MCPClient（标准化调用）+ 4 个独立 checker（price/geo/time/risk）+ 降级策略

**评估时机**: 每次工具模块变更后、每次 API 提供商切换后、每周定期巡检

**当前状态**: tools/ 下 4 个独立 checker（途牛 MCP / 高德地理编码 / 高德路径规划 / 风险 stub），无统一 ToolRegistry，降级策略分散在各 checker 中。

---

## 2. 评分维度与权重

| 维度 | 权重 | 缩写 | 核心问题 |
|------|------|------|---------|
| API 可用率 (Availability) | 30% | AVL | 首次调用成功率、降级触发频率 |
| 响应延迟 (Latency) | 25% | LAT | P50/P99 延迟是否在目标范围内 |
| 结果准确率 (Accuracy) | 25% | ACC | 返回结果与真实值偏差（价格偏差%、坐标偏差 km） |
| 降级优雅度 (Degradation) | 20% | DEG | 降级时 stub 数据质量、降级传播范围（部分 vs 全量） |

---

## 3. API 可用率 (Availability) — 权重 30%

### 评分锚点

| 分数 | 描述 | 判定标准 |
|------|------|---------|
| 5 | 高可用 | 首次调用成功率 ≥ 99%，降级触发 < 1% |
| 4 | 稳定可用 | 首次调用成功率 95-98.9%，偶发降级 |
| 3 | 基本可用 | 首次调用成功率 85-94.9%，降级时有发生 |
| 2 | 不稳定 | 首次调用成功率 70-84.9%，频繁降级 |
| 1 | 严重不可用 | 首次调用成功率 < 70%，大部分请求降级 |

### 检查清单
- [ ] 各 tool 的首次调用成功率是否 ≥ 95%？
- [ ] API key 过期/无效时是否有明确的错误提示（而非静默降级）？
- [ ] 是否有健康检查端点定期探测 API 可达性？
- [ ] 降级触发后是否有自动恢复机制（如 5 分钟后重试 API）？
- [ ] 不同 tool 的降级是否独立（一个 tool 降级不影响其他 tool）？
- [ ] API 调用是否有超时设置（≤ 15s）？

### 评分指南
```
以 24h 窗口内首次调用成功率为主要依据:
成功率 ≥ 99% → 5分
成功率 95-98.9% → 4分
成功率 85-94.9% → 3分
成功率 70-84.9% → 2分
成功率 < 70% → 1分
```

### 锚点示例

**最低分示例 (1分)** — 3 个 tool 全部降级:
```json
{
  "period": "2026-07-07 00:00 ~ 2026-07-08 00:00",
  "tools": {
    "price_checker": {
      "api": "途牛 MCP",
      "calls_attempted": 150,
      "first_call_success": 72,
      "success_rate": "48%",
      "degradation_count": 78,
      "failure_reason": "SSE 解析失败 + apiKey 过期 (参考: lessons.md Batch 5/Phase 5)"
    },
    "geo_checker": {
      "api": "高德 Geocode",
      "calls_attempted": 200,
      "first_call_success": 130,
      "success_rate": "65%",
      "degradation_count": 70
    },
    "time_checker": {
      "api": "高德 Directions",
      "calls_attempted": 180,
      "first_call_success": 100,
      "success_rate": "55.6%",
      "degradation_count": 80
    }
  },
  "overall_availability": "56.2%"
}
```

**最高分示例 (5分)** — 全部 tool 高可用:
```json
{
  "period": "2026-07-07 00:00 ~ 2026-07-08 00:00",
  "tools": {
    "price_checker": {
      "api": "途牛 MCP",
      "calls_attempted": 150,
      "first_call_success": 149,
      "success_rate": "99.3%",
      "degradation_count": 1,
      "auto_recovery_count": 1
    },
    "geo_checker": {
      "api": "高德 Geocode",
      "calls_attempted": 200,
      "first_call_success": 199,
      "success_rate": "99.5%",
      "degradation_count": 1
    },
    "time_checker": {
      "api": "高德 Directions",
      "calls_attempted": 180,
      "first_call_success": 180,
      "success_rate": "100%",
      "degradation_count": 0
    }
  },
  "overall_availability": "99.6%"
}
```

---

## 4. 响应延迟 (Latency) — 权重 25%

### 评分锚点

| 分数 | 描述 | 判定标准 |
|------|------|---------|
| 5 | 极低延迟 | P50 < 200ms, P99 < 1s |
| 4 | 低延迟 | P50 < 500ms, P99 < 2s |
| 3 | 可接受 | P50 < 1s, P99 < 5s |
| 2 | 延迟较高 | P50 1-3s 或 P99 > 5s |
| 1 | 延迟不可接受 | P50 > 3s 或 P99 > 10s |

### 检查清单
- [ ] P50 延迟是否 < 500ms（对实时交互场景）？
- [ ] P99 延迟是否 < 5s（含外部 API 往返）？
- [ ] 是否有超时设置防止无限等待？
- [ ] 并发调用 3 个 tool 时总延迟是否 ≤ 最慢 tool 的延迟（并行执行）？
- [ ] 是否有本地缓存减少重复 API 调用？

### 评分指南
```
以 P50 为主要依据，P99 为辅助:
P50 < 200ms 且 P99 < 1s → 5分
P50 < 500ms 且 P99 < 2s → 4分
P50 < 1s 且 P99 < 5s → 3分
P50 1-3s 或 P99 5-10s → 2分
P50 > 3s 或 P99 > 10s → 1分
```

### 锚点示例

**最低分示例 (1分)** — 严重超时:
```json
{
  "period": "2026-07-07 00:00 ~ 2026-07-08 00:00",
  "latency_stats": {
    "price_checker": {"p50_ms": 4500, "p99_ms": 12000, "timeouts": 15},
    "geo_checker": {"p50_ms": 3200, "p99_ms": 8500, "timeouts": 8},
    "time_checker": {"p50_ms": 5000, "p99_ms": 15000, "timeouts": 22}
  },
  "overall_p50_ms": 4200,
  "overall_p99_ms": 13500,
  "analysis": "途牛 MCP SSE 连接慢 + 高德 API 网络延迟，所有 tool P50 超 3s"
}
```

**最高分示例 (5分)** — 快速响应:
```json
{
  "period": "2026-07-07 00:00 ~ 2026-07-08 00:00",
  "latency_stats": {
    "price_checker": {"p50_ms": 180, "p99_ms": 850, "timeouts": 0},
    "geo_checker": {"p50_ms": 120, "p99_ms": 600, "timeouts": 0},
    "time_checker": {"p50_ms": 150, "p99_ms": 900, "timeouts": 0}
  },
  "overall_p50_ms": 145,
  "overall_p99_ms": 920,
  "cache_hit_rate": "45% (known_cache 预热 20+ 常用坐标)"
}
```

---

## 5. 结果准确率 (Accuracy) — 权重 25%

### 评分锚点

| 分数 | 描述 | 判定标准 |
|------|------|---------|
| 5 | 高度准确 | 价格偏差 < 10%, 坐标偏差 < 1km, 路线时间偏差 < 10% |
| 4 | 基本准确 | 价格偏差 10-15%, 坐标偏差 1-3km |
| 3 | 存在偏差 | 价格偏差 15-20%, 坐标偏差 3-5km |
| 2 | 偏差较大 | 价格偏差 20-30%, 坐标偏差 5-10km |
| 1 | 严重失准 | 价格偏差 > 30%, 坐标偏差 > 10km, 或返回明显错误数据 |

### 检查清单
- [ ] 价格偏差均值 (MPD) 是否 < 15%？
- [ ] 地理编码是否将城市名正确解析到市中心坐标（偏差 < 5km）？
- [ ] 路径规划的距离和预计时间是否与真实情况偏差 < 15%？
- [ ] stub fallback 数据的准确度是否在可接受范围（标注了 `degraded=true`）？
- [ ] 是否有已知的数据质量问题（如途牛酒店价格不含税、高德坐标偏移）被记录？

### 评分指南
```
综合偏差 = (价格偏差% × 0.5 + 坐标偏差评分 × 0.3 + 时间偏差% × 0.2):
综合偏差 < 8% → 5分
综合偏差 8-12% → 4分
综合偏差 12-18% → 3分
综合偏差 18-25% → 2分
综合偏差 > 25% → 1分
```

### 锚点示例

**最低分示例 (1分)** — 价格严重偏差 + stub 数据过时:
```json
{
  "accuracy_audit": {
    "price_check": {
      "sample_size": 50,
      "mean_deviation_pct": 45.0,
      "worst_case": {"item": "东京酒店", "estimated": 300, "market": 1200, "deviation": "75%"}
    },
    "geo_check": {
      "sample_size": 30,
      "mean_coord_deviation_km": 12.5,
      "worst_case": {"query": "浅草", "returned": "埼玉県浅草", "deviation_km": 45}
    },
    "time_check": {
      "sample_size": 20,
      "mean_time_deviation_pct": 35.0
    }
  },
  "stub_data_quality": "使用 2024 年价格数据，未更新"
}
```

**最高分示例 (5分)** — 全部 tool 结果高度准确:
```json
{
  "accuracy_audit": {
    "price_check": {
      "sample_size": 50,
      "mean_deviation_pct": 6.5,
      "api_source": "途牛 MCP 实时价格",
      "currency": "CNY (统一)"
    },
    "geo_check": {
      "sample_size": 30,
      "mean_coord_deviation_km": 0.8,
      "api_source": "高德 Geocode API"
    },
    "time_check": {
      "sample_size": 20,
      "mean_time_deviation_pct": 7.2,
      "api_source": "高德 Directions API"
    }
  }
}
```

---

## 6. 降级优雅度 (Degradation) — 权重 20%

### 评分锚点

| 分数 | 描述 | 判定标准 |
|------|------|---------|
| 5 | 优雅降级 | stub 数据质量接近真实数据（偏差 < 15%），降级仅影响单个 tool，其余 tool 正常 |
| 4 | 良好降级 | stub 数据可用（偏差 15-25%），降级范围可控 |
| 3 | 可接受 | stub 数据基本可用（偏差 25-35%），降级传播有限 |
| 2 | 降级粗糙 | stub 数据偏差 > 35%，或多个 tool 连锁降级 |
| 1 | 降级崩溃 | 降级后数据完全不可用，或降级导致整个请求失败 |

### 检查清单
- [ ] stub 数据是否定期更新（价格数据过期 < 30 天）？
- [ ] 降级传播: 一个 tool 降级是否导致其他 tool 也降级（应隔离）？
- [ ] 降级时 `degraded` 标记是否正确传播到上层（Orchestrator / Evaluation Agent）？
- [ ] stub 数据的中文/英文 key 是否都有覆盖（参考: lessons.md Batch 1 中英文 key 不匹配）？
- [ ] 降级后的方案质量是否仍可接受（composite_score ≥ 60）？

### 评分指南
```
降级质量 = stub准确度(40%) + 降级隔离度(30%) + stub覆盖率(30%):
降级质量 ≥ 90% → 5分
降级质量 75-89% → 4分
降级质量 60-74% → 3分
降级质量 40-59% → 2分
降级质量 < 40% → 1分

> 实战参考: lessons.md Batch 7 — stub 路径下 degraded 断言失败案例: 
  Orchestrator 接入真实 EvaluationAgent 后，stub 草稿得分 < 80 触发 degraded=true，
  E2E 测试预期 degraded=False 被打破。说明降级路径的评分基线需要独立设定。
```

### 锚点示例

**最低分示例 (1分)** — 降级后数据完全不可用:
```json
{
  "degradation_event": {
    "timestamp": "2026-07-07 14:30:00",
    "failed_tool": "price_checker (途牛 MCP)",
    "failure_reason": "SSE 解析异常 + apiKey 过期 (参考: lessons.md Phase 5)",
    "degradation_scope": "全部价格数据降级",
    "stub_data_quality": {
      "coverage": "仅覆盖 3 个城市 (东京/曼谷/巴黎)",
      "freshness_days": 180,
      "accuracy_vs_real": "偏差 > 50%",
      "key_issue": "中文 key 可查但英文 key 返回默认值 (参考: lessons.md Batch 1)"
    },
    "propagation": "price → budget → Gate 1 blocking → 整体方案 REJECT",
    "downstream_impact": "stub 价格偏低导致预算校验通过但实际不可行"
  }
}
```

**最高分示例 (5分)** — 单点降级，其他 tool 正常，stub 质量高:
```json
{
  "degradation_event": {
    "timestamp": "2026-07-07 10:15:00",
    "failed_tool": "risk_checker (天气 API)",
    "failure_reason": "外部天气 API 超时",
    "degradation_scope": "仅天气数据，签证/安全仍正常",
    "stub_data_quality": {
      "coverage": "覆盖全部 20 个热门目的地",
      "freshness_days": 7,
      "accuracy_vs_real": "偏差 < 10% (使用季节平均值)",
      "source": "历史数据聚合 + 季节性调整"
    },
    "propagation": "风险检查 → degraded=true 标记 → 不影响价格/地理/时间校验",
    "downstream_impact": "方案质量下降 < 5 分 (composite_score: 87 → 83)"
  }
}
```

---

## 7. 综合评分计算

### 计算公式
```python
composite_score = (
    AVL_score * 0.30 +
    LAT_score * 0.25 +
    ACC_score * 0.25 +
    DEG_score * 0.20
) * 20
# Range: 20 - 100
```

### 维度地板规则

| 规则ID | 触发条件 | 效果 |
|--------|---------|------|
| FLOOR-AVL | AVL = 1（API 可用率 < 70%） | composite_score = min(composite_score, 59) |
| FLOOR-ACC | ACC = 1（结果偏差 > 25%，数据严重失准） | composite_score = min(composite_score, 59) |
| FLOOR-DEG | DEG = 1（降级崩溃） | composite_score = min(composite_score, 59) |
| FLOOR-MULTI | ≥ 3 个维度得分 < 3 | composite_score = min(composite_score, 69) |

### 判定矩阵
| 总分 | 判定 | 后续行动 |
|------|------|---------|
| 90-100 | EXCELLENT | Tool 系统卓越，可作为 MCP 集成参考 |
| 80-89 | PASS | 质量达标，可投入生产使用 |
| 70-79 | REVISE (轻) | 针对性优化延迟/准确率问题 |
| 60-69 | REVISE (重) | 系统性改进 API 可靠性或降级策略 |
| 40-59 | REJECT (可修复) | API 大面积不可用或降级崩溃 |
| 20-39 | REJECT (严重) | Tool 系统基本失效 |

---

## 8. 评估示例

### 示例 1: 高质量 Tool 系统

**系统概况**: 全部 tool 使用真实 API，known_cache 预热，降级隔离良好
**各维度情况**:
- AVL: 首次调用成功率 99.2% → 5分
- LAT: P50=180ms, P99=900ms → 5分
- ACC: 综合偏差 7.8% → 5分
- DEG: 单 tool 降级不传播，stub 偏差 12% → 4分

**地板规则检查**:
```
AVL=5 (≥2 ✓), ACC=5 (≥2 ✓), DEG=4 (≥2 ✓)
维度 <3 的数量 = 0
→ 无地板规则触发
```

**计算**:
```
(5×0.30 + 5×0.25 + 5×0.25 + 4×0.20) × 20
= (1.50 + 1.25 + 1.25 + 0.80) × 20
= 4.80 × 20
= 96 → EXCELLENT
```

### 示例 2: 低质量 Tool 系统

**系统概况**: 途牛 MCP 频繁降级，高德 API 延迟高，stub 数据过时
**各维度情况**:
- AVL: 成功率 52%，大部分请求降级 → 1分
- LAT: P50=4s, P99=12s → 1分
- ACC: stub 数据偏差 45%，坐标偏差 12km → 1分
- DEG: 3 个 tool 全部降级，stub 覆盖仅 3 个城市 → 1分

**地板规则检查**:
```
AVL=1 → FLOOR-AVL 触发！
ACC=1 → FLOOR-ACC 触发！
DEG=1 → FLOOR-DEG 触发！
维度 <3 的数量 = 4 → FLOOR-MULTI 触发！
→ composite_score 上限 = min(score, 59, 59, 59, 69) = 59
```

**计算**:
```
(1×0.30 + 1×0.25 + 1×0.25 + 1×0.20) × 20
= (0.30 + 0.25 + 0.25 + 0.20) × 20
= 1.00 × 20
= 20 → min(20, 59) = 20
→ REJECT (严重)
```

---

## 9. 变更日志

| 版本 | 日期 | 变更 |
|------|------|------|
| 1.0.0 | 2026-07-07 | 初始版本，4维度 Tool 质量量表（API可用率/响应延迟/结果准确率/降级优雅度）+ 2个计算示例 |
