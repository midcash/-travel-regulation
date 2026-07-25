# Test Scenarios — 测试场景集

---

## 1. 概述

本文档定义了 TravelPlan Orchestrator 的完整测试场景集。测试场景覆盖正常流程、边界情况、异常情况和消融实验，用于验证系统功能完整性和质量门有效性。

> **当前项目映射**: 当前分支 Agent 为 Orchestrator → KnowledgeAgent → PlannerAgent → ReviewerAgent。Gate 逻辑内嵌在 orchestrator LLM prompt 中（无独立 GateRunner）。标注 `[FUTURE]` 的测试场景依赖尚未实现的组件（GateRunner/SharedContext/消息 Schema），留作后续参考。

---

## 2. 端到端测试场景 (Happy Path)

### TS-E2E-001: 标准旅行规划
```
输入:
  "我想去日本东京旅游，12月20号出发，12月25号返回，2个人，
   预算总共15000元，喜欢美食和文化体验，住宿舒适型"

期望输出:
  - Gate 0: PASS (所有必填项完整)
  - PlannerAgent 产出包含: 往返交通 + 5晚住宿 + 5天行程 + 每日3餐 + 预算分配
  - KnowledgeAgent: feasible, 0 blocking_issues
  - Gate 1: PASS
  - ReviewerAgent: composite_score ≥ 80
  - Gate 2: PASS
  - Gate 3: PASS
  - 最终方案包含完整的 travel plan JSON
```

### TS-E2E-002: 短途旅行 (1天)
```
输入:
  "去广州玩1天，预算500块，喜欢美食"

期望输出:
  - 1天行程，活动总数 ≤ 5（时间限制）
  - 无住宿推荐（不过夜）
  - 预算在 450-500 之间
  - 所有 Gate 通过
```

### TS-E2E-003: 长途旅行 (14天)
```
输入:
  "去欧洲法国意大利，14天，预算5万，喜欢文化艺术历史"

期望输出:
  - 按城市拆分: 如巴黎7天 + 罗马7天
  - 城市间交通方案
  - 每5-7天有相对轻松的一天
  - 所有 Gate 通过
```

### TS-E2E-004: 有饮食限制
```
输入:
  "去曼谷5天，预算8000，素食者，喜欢寺庙和按摩"

期望输出:
  - 所有餐厅推荐均为素食/蔬食
  - 景点偏向寺庙类
  - 约束满足度 = 5 (硬约束满足)
```

### TS-E2E-005: 有排除项
```
输入:
  "去香港3天，预算6000，不要购物行程，喜欢户外和自然"

期望输出:
  - 行程中无购物类活动
  - 景点偏向自然/户外类 (如徒步径、离岛)
  - 约束满足度 = 5
```

---

## 3. 边界测试场景

### TS-EDGE-001: 极低预算
```
输入: "去北京3天，预算500元"

期望:
  - 推荐青旅/民宿 (低端住宿)
  - 推荐免费景点
  - 餐饮推荐经济型
  - Knowledge 可能标记 warnings (预算紧张)
  - 不应标记为 infeasible (只要总价 ≤ 500)
```

### TS-EDGE-002: 极高预算
```
输入: "去马尔代夫7天，预算20万，要最奢华的体验"

期望:
  - 推荐高端度假村、水上别墅
  - 推荐私人包机/商务舱
  - 活动推荐高端 (私人游艇、潜水)
```

### TS-EDGE-003: 多人出行
```
输入: "去三亚5天，6个人（4大人2小孩），预算3万，亲子游"

期望:
  - 推荐家庭房/套房
  - 推荐亲子友好景点
  - 餐饮考虑儿童友好
  - 活动安排不密集
```

### TS-EDGE-004: 无偏好标签
```
输入: "去成都4天，预算5000"

期望:
  - 使用默认 moderate 节奏
  - 混合风格（文化+美食+休闲）
  - 不应报错
```

### TS-EDGE-005: 当天出发
```
输入: "今天出发去杭州2天，预算2000"

期望:
  - 日期校验通过 (今天 = 合法)
  - 可能标记风险: "出发日期紧迫，部分预订可能受限"
```

---

## 4. 异常测试场景

### TS-ERR-001: 缺失目的地
```
输入: "想去玩5天，预算1万"

期望:
  - Gate 0: FAIL
  - 追问: "请问您想去哪个目的地？"
```

### TS-ERR-002: 缺失日期
```
输入: "去东京，预算1万"

期望:
  - Gate 0: FAIL
  - 追问: "请问您的出发和返回日期是？"
```

### TS-ERR-003: 缺失预算
```
输入: "去东京5天"

期望:
  - Gate 0: FAIL
  - 追问: "请问您的预算范围是？"
```

### TS-ERR-004: 过去日期
```
输入: "去东京5天，2020年1月1日出发，预算1万"

期望:
  - Gate 0: FAIL
  - 拒绝: "出发日期不能是过去的日期"
```

### TS-ERR-005: 返回日期早于出发
```
输入: "去东京，12月25日出发，12月20日返回，预算1万"

期望:
  - Gate 0: FAIL
  - 拒绝: "返回日期不能早于出发日期"
```

### TS-ERR-006: 空输入
```
输入: ""

期望:
  - 立即拒绝
  - 返回: "请输入您的旅行需求"
```

### TS-ERR-007: 无意义输入
```
输入: "asdfghjkl"

期望:
  - 尝试解析失败
  - 返回: "无法理解您的需求，请使用自然语言描述"
```

---

## 5. 质量门测试场景

### TS-GATE-001: Gate 1 硬约束违反
```
场景: Planning 产出预算超出上限 120%

期望:
  - KnowledgeAgent: blocking_issue (硬约束违反)
  - Gate 1: FAIL
  - Orchestrator: 退回 Planning 修订
```

### TS-GATE-002: Gate 2 一次修订通过
```
场景: 第一版得分 72 (REVISE)

期望:
  - Gate 2 第一轮: FAIL
  - Planning 收到反馈并修订
  - 第二版评分 ≥ 80
  - Gate 2 第二轮: PASS
```

### TS-GATE-003: Gate 2 三轮后降级
```
场景: 连续3版都 < 80

期望:
  - 第3轮修订后仍 < 80
  - Gate 2: 强制 PASS + degraded: true
  - 最终方案标注 degraded_reason + 未满足项清单
```

### TS-GATE-004: Gate 3 格式修复
```
场景: 最终方案缺少某字段

期望:
  - Gate 3: FAIL (格式错误)
  - 自动补占位符 + auto_filled: true
  - 重新检查 → PASS
```

### TS-GATE-005: Gate 3 预算超支拒绝
```
场景: 最终方案预算 breakdown 之和 > total_budget

期望:
  - Gate 3: FAIL (预算超支)
  - 不可自动修复
  - 标记为 FAILED + 人工介入
```

---

## 6. 消融实验测试场景 [FUTURE]

> 以下测试依赖完整的消融实验框架（LOO/Peer-rating/协同分析），当前项目 ReviewerAgent 尚未实现，暂不可执行。

### TS-ABLATION-001: LOO 完整消融
```
测试套件: TS-E2E-001 到 TS-E2E-005 (5个用例)

配置:
  1. Full (Orch + Plan + Exec + Eval) → S_full
  2. w/o PlannerAgent → S_no_planner
  3. w/o KnowledgeAgent → S_no_knowledge
  4. w/o ReviewerAgent → S_no_reviewer

期望输出:
  - 各配置得分可比较
  - MC_planner > 0 (Planner 有正向贡献)
  - MC_executor > 0 (Executor 有正向贡献)
  - 贡献率分布合理 (无 agent CR = 0)
```

### TS-ABLATION-002: Agent Importance Score
```
场景: 端到端测试后，各 agent 互评

期望:
  - 评分矩阵完整 (无缺失评分)
  - 评分方差 ≤ 1.5 (评分一致性)
  - 有明确的排名
```

### TS-ABLATION-003: 360° 评估一致性
```
场景: Self-Peer-Supervisory 三方评分

期望:
  - 三方偏差 ≤ 1.0 (评分基本一致)
  - 无 agent bias > 1.0 (无严重认知偏差)
```

### TS-ABLATION-004: 协同效应
```
场景: 独立 vs 协作对比

期望:
  - S_full ≥ max(S_planner_alone, S_executor_alone) (协作不差于最强单 agent)
  - synergy_efficiency > 50% (至少有中等协同)
```

---

## 7. 性能测试场景 [FUTURE]

> 以下测试依赖系统稳定运行及性能基准数据，当前阶段暂不可执行。

### TS-PERF-001: 标准耗时
```
场景: 标准5天行程，完整流程

期望:
  - 总耗时 ≤ 60s
  - Agent 间通信 ≤ 5s/次
```

### TS-PERF-002: 并行处理
```
场景: 3个用户请求同时到达

期望:
  - 3个请求均正常完成
  - 无死锁或资源争抢
  - 互不干扰
```

### TS-PERF-003: 大型行程
```
场景: 30天多城市行程

期望:
  - 能正常完成 (不超时)
  - Execution 采用抽样校验
  - 总耗时 ≤ 120s
```

---

## 8. 编排器错误恢复测试场景 [FUTURE]

> 以下测试依赖 GateRunner/SharedContext/control.abort 等消息 Schema 组件，当前 orchestrator 为简化 LLM 驱动循环，尚未实现。留作状态机优化时的参考。

### TS-ORCH-001: PlannerAgent 超时恢复
```
场景: PlannerAgent 首次调用超时，第1次重试成功

期望:
  - 第1次调用 30s 后超时
  - Orchestrator 按指数退避 1s 后重试
  - 第1次重试成功，流程继续
  - 最终方案正常产出
```

### TS-ORCH-002: Agent 超时耗尽重试
```
场景: KnowledgeAgent 连续 3 次重试全部超时

期望:
  - 3 次重试均在 30s 后超时（间隔 1s→2s→4s）
  - 重试耗尽后标记 KnowledgeAgent 调用失败
  - Orchestrator 降级输出: 跳过可行性验证，标注 degraded
  - 最终方案标注"可行性未验证"
```

### TS-ORCH-003: 评估超时跳过
```
场景: ReviewerAgent (Mode B) 超时

期望:
  - 超时后不阻塞流程
  - Orchestrator 跳过质量评估，直接进入 Gate 3
  - 最终方案标注"质量评估未完成"
  - degraded: true
```

### TS-ORCH-004: PlannerAgent 返回错误(有部分产物)
```
场景: PlannerAgent 返回错误但有部分草稿

期望:
  - Orchestrator 检测到错误响应 (response.error)
  - partial_draft 非空 → 使用部分草稿
  - 缺失部分由默认模板填充 + auto_filled: true
  - 标注"部分内容需人工完善"
```

### TS-ORCH-005: Agent 返回空错误(无产物)
```
场景: KnowledgeAgent 返回错误且 body 为空

期望:
  - Orchestrator 检测到错误响应且无有效 payload
  - 错误信息传播到用户
  - 不产出虚假方案
  - GateRunner 记录失败原因
```

### TS-ORCH-006: 多 Agent 复合错误
```
场景: Planning 和 Execution 均返回错误

期望:
  - Orchestrator 不提前退出，收集所有错误
  - 汇总错误列表到最终响应
  - 不产出方案，返回聚合错误信息
```

### TS-ORCH-007: 用户在 Planning 阶段取消
```
场景: 用户在 PlannerAgent 执行中发送取消指令

期望:
  - Orchestrator 收到 control.abort (reason: user_cancel)
  - 广播 abort 到所有子 Agent
  - 清理 SharedContext，释放资源
  - 返回"已取消"确认
```

### TS-ORCH-008: 用户在 Execution 阶段取消
```
场景: 用户在 KnowledgeAgent 执行中取消

期望:
  - Orchestrator 广播 abort
  - 保存当前部分产物到日志（供后续恢复）
  - 5s 内完成清理
  - 返回"已取消"+"已保存部分草稿"
```

### TS-ORCH-009: 用户在 Evaluation 阶段取消
```
场景: 用户在 ReviewerAgent 执行中取消

期望:
  - Orchestrator 广播 abort
  - 询问用户: 保留当前草稿 / 丢弃
  - 保留 → 跳过评估直接 Gate 3 + degraded
  - 丢弃 → 完全清理
```

---

## 9. KnowledgeAgent 核心检查函数测试场景 [FUTURE]

> 以下测试针对 KnowledgeAgent 内部的细粒度检查函数（price/time/geography），当前 KnowledgeAgent 使用 LLM function-calling 自主编排而非独立检查函数，后续重构时可作为单元测试参考。

### TS-EXEC-001: check_prices 正常通过
```
场景: 4项价格 (机票/酒店/餐饮/门票) 均在市场价 10% 偏差内

期望:
  - price_score ≥ 90
  - 0 个 price_anomalies
  - overall_status: "passed"
```

### TS-EXEC-002: check_prices 边界告警
```
场景: 酒店价格偏离市场价恰好 30% (中/高阈值边界)

期望:
  - price_score 在 60-70 之间
  - 1 个 price_anomaly (severity: "medium")
  - overall_status: "passed_with_warnings"
  - 不产生 blocking_issue
```

### TS-EXEC-003: check_prices 触发阻断
```
场景: 4项中3项价格偏离超过 30%

期望:
  - price_score < 50
  - 3 个 price_anomalies (含 severity: "high")
  - overall_status: "failed"
  - 产生 blocking_issue: "多项价格严重偏离市场价，预算可行性存疑"
```

### TS-EXEC-004: check_time 正常通过
```
场景: 5天行程，每天总活动+交通 ≤ 10h，无时间冲突

期望:
  - 0 个 time_conflicts
  - 0 个 time_warnings
  - overall_time_status: "passed"
  - 不产生 blocking_issue
```

### TS-EXEC-005: check_time 边界告警
```
场景: 某天总活动时间恰好 12h (告警阈值，未到冲突)

期望:
  - 0 个 time_conflicts
  - 1 个 time_warning: "第X天总时长接近上限(12h)"
  - overall_time_status: "passed_with_warnings"
```

### TS-EXEC-006: check_time 触发阻断
```
场景: 某天活动时间超过 12h + 午餐时段两个活动重叠

期望:
  - 2 个 time_conflicts (超时 + 午餐冲突)
  - overall_time_status: "failed"
  - 产生 blocking_issue: "第X天存在时间冲突"
```

### TS-EXEC-007: check_geography 正常通过
```
场景: 东京线性路线 (浅草→上野→秋叶原→新宿→涩谷)，绕路比 1.14 (< 1.5)

期望:
  - detour_ratio < 1.5
  - 0 个 geography_warnings
  - overall_geo_status: "passed"
```

### TS-EXEC-008: check_geography 边界告警
```
场景: 路线绕路比恰好 1.5 (告警阈值)

期望:
  - detour_ratio = 1.5
  - 1 个 geography_warning: "路线绕路比达到上限(1.5)"
  - overall_geo_status: "passed_with_warnings"
```

### TS-EXEC-009: check_geography 触发阻断
```
场景: 路线绕路比 2.0 + 包含 3.5h 未标注交通方式的长途转移

期望:
  - detour_ratio > 1.5
  - 1 个 geography_warning (绕路) + 1 个 blocking (未标注长途)
  - overall_geo_status: "failed"
  - 产生 blocking_issue: "存在地理逻辑不可行的路线段"
```

---

## 10. 回归测试套件

### 最小回归集 (每次提交必跑) [FUTURE — 待测试框架搭建]
- TS-E2E-001 (标准流程)
- TS-ERR-001 (缺失目的地)
- TS-GATE-001 (硬约束违反)

> 注: TS-ORCH-* 和 TS-EXEC-* 场景依赖尚未实现的组件，暂不纳入当前回归集。

### 完整回归集 (每次发布前必跑) [FUTURE]
- 所有 TS-E2E-* (5个)
- 所有 TS-EDGE-* (5个)
- 所有 TS-ERR-* (7个)
- 所有 TS-GATE-* (5个)

### 消融回归集 (每次架构变更必跑)
- 所有 TS-ABLATION-* (4个)

---

## 11. 变更日志

| 版本 | 日期 | 变更 |
|------|------|------|
| 1.0.0 | 2026-07-05 | 初始版本，41个测试场景（含 §8 编排器错误恢复 9个 + §9 执行 Agent 核心检查函数 9个） |
