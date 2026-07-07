# Protocol Quality Rubric — 消息协议质量评分量表

---

## 1. 概述

本文档是 **Layer 2 业务产出评估**中 Protocol 模块的专用评分量表。用于评估 Agent 间通信协议的消息合法性、版本兼容性、错误恢复能力和状态转换正确性。

**评估对象**: Protocol — MessageValidator（JSON Schema 校验）、protocol_version（版本兼容性协商）、FeedbackSchema（标准修订反馈格式）、StateMachine（状态转换可视化 + 测试辅助）

**评估时机**: 每次 Agent 间通信契约变更后、每次新增消息类型后、每 50 次消息交换后定期审计

**当前状态**: spec/agent_contract.md 定义了 AgentMessage + TaskType（11 个值），但无 schema 校验层。lessons.md 中高频出现 dict↔dataclass 转换 bug、dimensions 嵌套 vs 扁平不匹配、状态转换死角（Batch 7 三条桥接问题）。

---

## 2. 评分维度与权重

| 维度 | 权重 | 缩写 | 核心问题 |
|------|------|------|---------|
| 消息合法率 (Validity) | 35% | VAL | schema 校验通过率、格式错误提前拦截率 |
| 版本兼容性 (Compatibility) | 25% | CMP | 跨版本消息收发成功率、版本协商成功率 |
| 错误恢复率 (Recovery) | 25% | RCV | 格式错误后自动修复率、降级通信成功率 |
| 状态转换正确性 (State) | 15% | STA | 非法状态转换发生率、转换链完整性 |

---

## 3. 消息合法率 (Validity) — 权重 35%

### 评分锚点

| 分数 | 描述 | 判定标准 |
|------|------|---------|
| 5 | 完全合法 | 100% 消息通过 schema 校验，格式错误在发送前 100% 被拦截 |
| 4 | 高度合法 | ≥ 99% 消息通过校验，格式错误拦截率 ≥ 95% |
| 3 | 基本合法 | 95-98.9% 消息通过校验，部分格式错误漏到接收方 |
| 2 | 存在较多非法消息 | 90-94.9% 通过校验，格式错误拦截不足 |
| 1 | 大量非法消息 | < 90% 通过校验，缺乏有效的格式校验层 |

### 检查清单
- [ ] 是否有 JSON Schema 校验层在消息发送前和接收后各校验一次？
- [ ] 必填字段（message_id, sender, receiver, task_type, payload）是否 100% 非空？
- [ ] correlation_id 在 response 类型消息中是否强制存在？
- [ ] payload 内嵌套结构（如 dimensions）的 schema 是否明确定义（扁平 vs 嵌套）？
- [ ] 是否存在 dict↔dataclass 转换的数据丢失风险（参考: lessons.md Batch 7 — dimensions 嵌套 vs 扁平不匹配）？
- [ ] 消息大小是否有上限（防止超大 payload 导致 OOM）？

### 评分指南
```
消息合法率 = 通过校验的消息数 / 总发送消息数:
合法率 = 100% → 5分
合法率 99-99.9% → 4分
合法率 95-98.9% → 3分
合法率 90-94.9% → 2分
合法率 < 90% → 1分
```

### 锚点示例

**最低分示例 (1分)** — 大量消息格式错误:
```json
{
  "period": "2026-07-01 ~ 2026-07-07",
  "total_messages": 500,
  "validation_stats": {
    "passed": 420,
    "failed": 80,
    "pass_rate": "84%",
    "common_errors": [
      {"type": "missing_correlation_id", "count": 25, "ref": "lessons.md Batch 3 — response 消息缺 correlation_id"},
      {"type": "dimensions_type_mismatch", "count": 18, "ref": "lessons.md Batch 7 — dimensions 嵌套 dict vs 扁平 number"},
      {"type": "missing_required_field", "count": 15, "fields": ["sender", "task_type"]},
      {"type": "payload_schema_violation", "count": 12},
      {"type": "message_id_duplicate", "count": 10}
    ]
  },
  "intercepted_before_send": 5,
  "interception_rate": "6.3% (5/80)"
}
```

**最高分示例 (5分)** — 全部消息合法:
```json
{
  "period": "2026-07-01 ~ 2026-07-07",
  "total_messages": 500,
  "validation_stats": {
    "passed": 500,
    "failed": 0,
    "pass_rate": "100%",
    "common_errors": []
  },
  "schema_version": "1.1.0",
  "validation_layer": "MessageValidator (JSON Schema draft-07) — 发送前校验 + 接收后校验双重保障"
}
```

---

## 4. 版本兼容性 (Compatibility) — 权重 25%

### 评分锚点

| 分数 | 描述 | 判定标准 |
|------|------|---------|
| 5 | 完全兼容 | 跨版本消息 100% 成功收发，协议升级后旧版 Agent 可正常工作 |
| 4 | 高度兼容 | ≥ 98% 跨版本消息成功，偶发需版本协商 |
| 3 | 基本兼容 | 90-97.9% 跨版本成功，部分新字段导致旧版解析失败 |
| 2 | 兼容性不足 | 70-89.9% 跨版本成功，版本升级频繁导致通信中断 |
| 1 | 不兼容 | < 70% 跨版本成功，协议升级即破坏通信 |

### 检查清单
- [ ] 是否有 protocol_version 字段在消息头中传递？
- [ ] 新增字段是否使用向后兼容的方式（optional with default）？
- [ ] 废弃字段是否有过渡期（标记 deprecated 但保留 ≥ 2 个版本）？
- [ ] 是否有版本协商机制（发送方和接收方协商使用共同支持的最高版本）？
- [ ] Agent 升级协议版本后，未升级的 Agent 是否仍可通信？

### 评分指南
```
跨版本成功率 = 跨版本成功的消息数 / 跨版本消息总数:
成功率 ≥ 99% → 5分
成功率 98-98.9% → 4分
成功率 90-97.9% → 3分
成功率 70-89.9% → 2分
成功率 < 70% → 1分
```

### 锚点示例

**最低分示例 (1分)** — 版本升级即断裂:
```json
{
  "version_compatibility_audit": {
    "current_version": "1.1.0",
    "agents_in_system": {
      "orchestrator": "1.1.0",
      "planning_agent": "1.1.0",
      "execution_agent": "1.0.0",
      "evaluation_agent": "1.0.0"
    },
    "cross_version_stats": {
      "messages_sent": 200,
      "messages_successful": 120,
      "success_rate": "60%",
      "failures": [
        {"from": "orchestrator v1.1.0", "to": "execution_agent v1.0.0", "reason": "新字段 'revision_feedback' 导致旧版 parse 失败"},
        {"from": "orchestrator v1.1.0", "to": "evaluation_agent v1.0.0", "reason": "dimensions 格式从扁平改为嵌套后旧版无法解析"}
      ]
    }
  }
}
```

**最高分示例 (5分)** — 完全兼容:
```json
{
  "version_compatibility_audit": {
    "current_version": "1.1.0",
    "agents_in_system": {
      "orchestrator": "1.1.0",
      "planning_agent": "1.1.0",
      "execution_agent": "1.0.0",
      "evaluation_agent": "1.0.0"
    },
    "cross_version_stats": {
      "messages_sent": 200,
      "messages_successful": 200,
      "success_rate": "100%"
    },
    "compatibility_mechanisms": [
      "新字段全部 optional with default",
      "protocol_version 在消息头中传递，接收方按版本解析",
      "v1.1.0 → v1.0.0 时自动 strip 新字段并记录 warning"
    ]
  }
}
```

---

## 5. 错误恢复率 (Recovery) — 权重 25%

### 评分锚点

| 分数 | 描述 | 判定标准 |
|------|------|---------|
| 5 | 自动恢复 | ≥ 90% 的格式/通信错误被自动修复，无需人工介入 |
| 4 | 大部分自动恢复 | 70-89% 自动修复率 |
| 3 | 部分自动恢复 | 50-69% 自动修复率 |
| 2 | 少量自动恢复 | 20-49% 自动修复率，多数错误需人工处理 |
| 1 | 无恢复能力 | < 20% 自动修复率，任何格式错误都导致通信失败 |

### 检查清单
- [ ] format 错误（如 dimensions 嵌套→扁平）是否能自动转换？
- [ ] 缺失字段（如 correlation_id）是否能自动生成并记录 warning？
- [ ] 消息重试机制: 发送失败后是否有自动重试（含退避策略）？
- [ ] 降级通信: 当主通道失败时是否有备选通信方式？
- [ ] 错误日志是否包含足够的诊断信息（发送方/接收方/消息ID/错误详情）？

### 评分指南
```
自动修复率 = 自动修复的错误数 / 总错误数:
修复率 ≥ 90% → 5分
修复率 70-89% → 4分
修复率 50-69% → 3分
修复率 20-49% → 2分
修复率 < 20% → 1分
```

### 锚点示例

**最低分示例 (1分)** — 无自动恢复:
```json
{
  "period": "2026-07-01 ~ 2026-07-07",
  "total_errors": 45,
  "recovery_stats": {
    "auto_recovered": 5,
    "manual_fix_required": 40,
    "auto_recovery_rate": "11%",
    "common_unrecovered": [
      {"error": "dimensions type mismatch", "auto_fix": false, "reason": "无转换逻辑"},
      {"error": "missing correlation_id", "auto_fix": false, "reason": "未实现自动生成"},
      {"error": "state_transition_illegal", "auto_fix": false, "reason": "状态机直接抛异常"}
    ]
  }
}
```

**最高分示例 (5分)** — 高度自动恢复:
```json
{
  "period": "2026-07-01 ~ 2026-07-07",
  "total_errors": 45,
  "recovery_stats": {
    "auto_recovered": 42,
    "manual_fix_required": 3,
    "auto_recovery_rate": "93.3%",
    "recovery_mechanisms": {
      "dimensions_normalize": "自动检测嵌套/扁平格式并统一转换",
      "correlation_id_auto_gen": "response 消息缺 correlation_id 时自动生成 UUID + warning",
      "state_transition_retry": "非法状态转换 → 尝试合法前置状态链 → 重试",
      "message_retry": "发送失败 → 指数退避重试(3次) → 降级通知"
    }
  }
}
```

---

## 6. 状态转换正确性 (State) — 权重 15%

### 评分锚点

| 分数 | 描述 | 判定标准 |
|------|------|---------|
| 5 | 完全正确 | 0 非法状态转换，状态转换链 100% 覆盖所有业务路径 |
| 4 | 基本正确 | 非法转换 < 0.5%，≥ 95% 业务路径有状态链覆盖 |
| 3 | 存在死角 | 非法转换 0.5-2%，存在 1-2 个未覆盖的转换路径 |
| 2 | 较多死角 | 非法转换 2-5%，多个状态转换路径缺失或 stub 掩盖 |
| 1 | 严重缺陷 | 非法转换 > 5%，状态机存在设计缺陷 |

### 检查清单
- [ ] 状态转换表是否覆盖所有业务路径（正常 + 修订 + 降级 + 异常）？
- [ ] 是否有非法状态转换的实际拦截（非仅文档记录）？
- [ ] stub 路径是否掩盖了状态机死角（参考: lessons.md Batch 7 — stub Gate 2 始终 PASS 掩盖了 REVISING→WAITING_EVALUATOR 非法转换）？
- [ ] 状态转换是否有可视化/日志记录便于调试？
- [ ] 状态机是否支持"重置"或"回滚"到安全状态？

### 评分指南
```
非法转换率 = 非法转换次数 / 总状态转换次数:
非法转换率 = 0% → 5分
非法转换率 < 0.5% → 4分
非法转换率 0.5-2% → 3分
非法转换率 2-5% → 2分
非法转换率 > 5% → 1分
```

### 锚点示例

**最低分示例 (1分)** — 状态机多处缺陷:
```json
{
  "period": "2026-07-01 ~ 2026-07-07",
  "total_transitions": 300,
  "state_audit": {
    "illegal_transitions": 18,
    "illegal_rate": "6%",
    "known_dead_paths": [
      {"from": "REVISING", "to": "WAITING_EVALUATOR", "issue": "非法转换 — 正确路径应为 REVISING→WAITING_PLANNER→WAITING_EXECUTOR→GATE_1→WAITING_EVALUATOR (参考: lessons.md Batch 7)"},
      {"from": "IDLE", "to": "DECIDING", "issue": "非法转换 — 需先经过 VALIDATING (参考: lessons.md Batch 3)"}
    ],
    "stub_masked_paths": [
      "stub Gate 2 始终返回 PASS → REVISING 状态链从未被测试 (参考: lessons.md Batch 7)"
    ],
    "missing_paths": ["REJECTED → 清理 → IDLE", "TIMEOUT → 重试 → WAITING_PLANNER"]
  }
}
```

**最高分示例 (5分)** — 状态机完全正确:
```json
{
  "period": "2026-07-01 ~ 2026-07-07",
  "total_transitions": 300,
  "state_audit": {
    "illegal_transitions": 0,
    "illegal_rate": "0%",
    "all_paths_covered": true,
    "state_paths_verified": [
      "正常路径: IDLE→VALIDATING→WAITING_PLANNER→WAITING_EXECUTOR→GATE_1→WAITING_EVALUATOR→COMPLETED",
      "修订路径: REVISING→WAITING_PLANNER→WAITING_EXECUTOR→GATE_1→WAITING_EVALUATOR (修订后重检)",
      "降级路径: REVISING→...→GATE_2_FAIL(3轮)→DEGRADED→COMPLETED",
      "拒绝路径: 任意→GATE_2_FAIL(score<60)→REJECTED",
      "超时恢复: TIMEOUT→RETRY(≤3)→原状态或DEGRADED"
    ],
    "state_coverage": "100% (5/5 业务路径)"
  }
}
```

---

## 7. 综合评分计算

### 计算公式
```python
composite_score = (
    VAL_score * 0.35 +
    CMP_score * 0.25 +
    RCV_score * 0.25 +
    STA_score * 0.15
) * 20
# Range: 20 - 100
```

### 维度地板规则

| 规则ID | 触发条件 | 效果 |
|--------|---------|------|
| FLOOR-VAL | VAL = 1（消息合法率 < 90%） | composite_score = min(composite_score, 59) |
| FLOOR-STA | STA = 1（非法状态转换 > 5%） | composite_score = min(composite_score, 59) |
| FLOOR-MULTI | ≥ 3 个维度得分 < 3 | composite_score = min(composite_score, 69) |

### 判定矩阵
| 总分 | 判定 | 后续行动 |
|------|------|---------|
| 90-100 | EXCELLENT | 协议质量卓越，可作为 Agent 通信规范参考 |
| 80-89 | PASS | 协议质量达标 |
| 70-79 | REVISE (轻) | 针对性修复 schema 校验或状态转换死角 |
| 60-69 | REVISE (重) | 系统性改进消息格式校验和错误恢复 |
| 40-59 | REJECT (可修复) | 通信可靠性严重不足 |
| 20-39 | REJECT (严重) | 协议基本不可用 |

---

## 8. 评估示例

### 示例 1: 高质量 Protocol

**系统概况**: MessageValidator 双重校验 + 版本协商 + 自动修复
**各维度情况**:
- VAL: 消息合法率 100% → 5分
- CMP: 跨版本成功率 100% → 5分
- RCV: 自动修复率 92% → 5分
- STA: 非法转换率 0% → 5分

**地板规则检查**: 全部 ≥ 2 → 无触发

**计算**:
```
(5×0.35 + 5×0.25 + 5×0.25 + 5×0.15) × 20
= (1.75 + 1.25 + 1.25 + 0.75) × 20
= 5.00 × 20
= 100 → EXCELLENT
```

### 示例 2: 当前 v1.1.0 Protocol 状态（反映 lessons.md 已知问题）

**系统概况**: 无 schema 校验层，dimensions 嵌套/扁平不匹配，状态转换死角，stub 掩盖路径
**各维度情况**:
- VAL: 无校验层，dimensions 类型不匹配频繁 → 2分
- CMP: agent_version 字段存在但未用于版本协商 → 3分
- RCV: 无自动修复，所有格式错误需人工处理 → 1分
- STA: REVISING→WAITING_EVALUATOR 非法路径，stub 掩盖死角 → 2分

**地板规则检查**:
```
VAL=2 (≥2 ✓), STA=2 (≥2 ✓)
RCV=1 触发？RCV 不是地板规则触发维度
维度 <3 = 3 (VAL/RCV/STA) → FLOOR-MULTI 触发！
→ 上限 = min(score, 69) = 69
```

**计算**:
```
(2×0.35 + 3×0.25 + 1×0.25 + 2×0.15) × 20
= (0.70 + 0.75 + 0.25 + 0.30) × 20
= 2.00 × 20
= 40 → min(40, 69) = 40
→ REJECT (可修复)
```

---

## 9. 变更日志

| 版本 | 日期 | 变更 |
|------|------|------|
| 1.0.0 | 2026-07-07 | 初始版本，4维度 Protocol 质量量表（消息合法率/版本兼容性/错误恢复率/状态转换正确性）+ 2个计算示例，低分示例反映 lessons.md 中 Batch 3/7 已知问题 |
