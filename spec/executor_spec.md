# Execution Agent Specification — 执行器规格

---

## 1. 模块标识

| 属性 | 值 |
|------|-----|
| 模块名称 | Execution Agent |
| Agent 标识 | `execution_agent` |
| 版本 | 1.0.0 |
| 类型 | 子 Agent (Specialist) |
| 上游 | Orchestrator |
| 下游 | Evaluation Agent (通过 Orchestrator) |
| 文件路径 | `agents/execution_agent.py` |

---

## 2. 功能规格

### 2.1 可行性验证

**函数**: `validate_feasibility(draft: TravelPlanDraft) -> ValidationReport`

**行为**:
按以下顺序执行 5 项校验，前一项失败不影响后续项执行（汇集所有问题）:

1. **价格校验**: 逐项比对预估价格与市场行情
2. **时间校验**: 检查每日行程时间合理性
3. **地理校验**: 验证路线逻辑性
4. **硬约束校验**: 检查预算上限、日期范围等
5. **风险识别**: 识别天气、安全、证件等风险

### 2.2 价格校验

**函数**: `check_prices(draft: TravelPlanDraft) -> PriceCheckResult`

**校验规则**:
- 偏差率 = |预估价 - 市场中位数| / 市场中位数
- 偏差率 ≤ 10%: 正常 (severity: low)
- 偏差率 10%-30%: 注意 (severity: medium)
- 偏差率 > 30%: 异常 (severity: high)
- 累计异常项 ≥ 3 项 → price_check 整体标记为 failed

**优先级**: 大交通 > 住宿 > 景点门票 > 餐饮

### 2.3 时间校验

**函数**: `check_time(draft: TravelPlanDraft) -> TimeCheckResult`

**校验规则**:
- 每日活动总时间 = Σ(活动时长) + Σ(交通中转时间)
- 中转时间默认 30min (同区域) / 60min (跨区域)
- 总时间 > 12h → conflict (severity: high)
- 总时间 10-12h → warning (severity: low)
- 景点开放时间与安排时间冲突 → conflict (severity: high)
- 用餐时间被活动占用 → warning (severity: medium)

### 2.4 地理校验

**函数**: `check_geography(draft: TravelPlanDraft) -> GeographyCheckResult`

**校验规则**:
- 绘制每日活动地理分布
- 计算理论最优路径长度
- 实际路线长度 / 最优路径长度 > 1.5 → detour (绕路)
- 单程交通 > 3h → 需要有特别说明
- 如发现更优分组 → 输出 optimized_route 建议

### 2.5 硬约束校验

**函数**: `check_constraints(draft: TravelPlanDraft, request: StructuredRequest) -> ConstraintCheckResult`

**硬约束 (违反即 blocking)**:
- 总预算 > 用户预算上限 → blocking
- 日期超出用户指定范围 → blocking
- 人数配置不匹配 → blocking
- 推荐了用户排除的类型/区域 → blocking

**软约束 (违反为 warning)**:
- 偏好的风格未体现 → warning
- 偏好的 pace 不匹配 → warning
- 饮食限制未完全满足 → warning

### 2.6 风险识别

**函数**: `identify_risks(draft: TravelPlanDraft) -> List[RiskAlert]`

**检查维度**:
- 天气风险: 台风季、高温、暴雨、大雪
- 安全风险: 高风险区域、常见骗局、交通安全
- 证件风险: 签证要求、护照有效期 (≥ 6个月)
- 健康风险: 疫苗要求、高原反应、蚊虫疾病

---

## 3. 接口规格

### 3.1 公共方法

```python
class ExecutionAgent(BaseAgent):
    agent_name = "execution_agent"
    agent_version = "1.0.0"

    async def handle_message(self, message: AgentMessage) -> AgentMessage:
        """消息处理入口"""

    async def validate_feasibility(self, draft: TravelPlanDraft) -> ValidationReport:
        """执行完整可行性验证"""

    async def check_prices(self, draft: TravelPlanDraft) -> PriceCheckResult:
        """价格合理性校验"""

    async def check_time(self, draft: TravelPlanDraft) -> TimeCheckResult:
        """时间可行性校验"""

    async def check_geography(self, draft: TravelPlanDraft) -> GeographyCheckResult:
        """地理逻辑校验"""

    async def check_constraints(self, draft: TravelPlanDraft, request: StructuredRequest) -> ConstraintCheckResult:
        """硬约束/软约束校验"""

    async def identify_risks(self, draft: TravelPlanDraft) -> List[RiskAlert]:
        """风险识别"""

    async def estimate_market_price(self, item_type: str, location: str, date: str) -> PriceRange:
        """查询市场行情价"""
```

---

## 4. 数据约束

### 4.1 ValidationReport 约束
- `overall_status` 判定逻辑:
  - blocking_issues 非空 → `infeasible`
  - blocking_issues 为空 且 warnings 非空 → `feasible_with_warnings`
  - 两者皆空 → `feasible`
- 每个 blocking_issue 必须包含 `fix_suggestion`
- 每个 warning 必须包含 `suggestion`

### 4.2 价格数据约束
- 所有价格必须标注货币单位
- 必须注明价格来源类型: `api | cache | estimated`
- 缓存数据必须标注数据日期

---

## 5. 约束与边界条件

### 5.1 输入约束
- TravelPlanDraft 必须包含完整的 transportation / accommodation / daily_itinerary / budget_allocation
- 必须可追溯到原始 StructuredRequest（用于硬约束校验）

### 5.2 处理约束
- 严格执行硬约束，不得因任何原因放松
- 价格校验参考市场行情，不得仅凭 LLM 内部知识
- 风险提示必须基于当季实际情况

### 5.3 输出约束
- 校验报告必须是结构化的（blocking_issues 和 warnings 明确分离）
- 每个问题必须有 severity 标记

---

## 6. 测试规格

### 6.1 单元测试

| 测试场景 | 输入 | 期望输出 |
|---------|------|---------|
| 正常通过 | 价格合理+时间OK+路线合理 | feasible, 0 blocking |
| 价格异常 | 机票价格市场价的2倍 | 1 anomaly (high), price_score < 70 |
| 超时日程 | 某天活动总计15h | 1 conflict (high) |
| 绕路 | A→B→C 但 B 距 A/C > 50km | 1 detour found |
| 预算超支 | 总费用 > 预算120% | 1 blocking_issue |
| 日期超范围 | 实际行程比请求多1天 | 1 blocking_issue |
| 综合问题 | 价格异常 + 超时 + 绕路 | 各类问题独立收集，不互相影响 |

### 6.2 边界测试

| 测试场景 | 期望行为 |
|---------|---------|
| 空行程 | 返回 error (INVALID_INPUT) |
| 所有API不可用 | 使用规则引擎 + 标注"离线模式" |
| 超大型行程 (>30天) | 抽样校验 (每5天抽1天) + 标注 |
| 价格缓存过期 (>7天) | 标注 confidence: "low" |
| 硬约束违反 + 软约束违反 | blocking 阻断，warnings 提示但不阻断 |

---

## 7. 性能规格

| 指标 | 目标值 |
|------|--------|
| 单次完整校验 | ≤ 20s |
| 单次价格查询 | ≤ 3s |
| 地理计算 | ≤ 2s |
| 风险查询 | ≤ 3s |

---

## 8. 变更日志

| 版本 | 日期 | 变更 |
|------|------|------|
| 1.0.0 | 2026-07-05 | 初始版本 |
