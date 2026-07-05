# Planning Agent Specification — 规划器规格

---

## 1. 模块标识

| 属性 | 值 |
|------|-----|
| 模块名称 | Planning Agent |
| Agent 标识 | `planning_agent` |
| 版本 | 1.0.0 |
| 类型 | 子 Agent (Specialist) |
| 上游 | Orchestrator |
| 下游 | Execution Agent (通过 Orchestrator) |
| 文件路径 | `agents/planning_agent.py` |

---

## 2. 功能规格

### 2.1 行程生成

**函数**: `create_itinerary(request: StructuredRequest) -> TravelPlanDraft`

**行为**:
1. 根据目的地进行景点、住宿、餐饮研究
2. 将景点按地理位置分组
3. 编排每日时间表（早/中/晚三个时段）
4. 为每餐推荐餐厅
5. 分配预算到各分项

**约束**:
- 每天至少 2 个主要活动
- 每天至少 3 餐推荐
- 住宿选项 ≥ 2 个
- 景点间距离 ≤ 30km（同一天内）
- 每日活动+交通总时间 ≤ 12 小时
- 预算在总额的 90%-100% 之间

### 2.2 行程修订

**函数**: `revise_itinerary(draft: TravelPlanDraft, feedback: List[RevisionFeedback]) -> TravelPlanDraft`

**行为**:
1. 提取反馈中标记的具体问题
2. 仅修改被指出的问题部分
3. 保持未指出的部分不变（最小化变更范围）
4. 标记修订项为 `revised: true`
5. revision 版本号 +1

**修订原则**:
- 聚焦原则: 只修被指出的问题
- 不退化原则: 修订不得降低未指出的部分的评分
- 透明原则: 修订内容明确标注

---

## 3. 接口规格

### 3.1 公共方法

```python
class PlanningAgent(BaseAgent):
    agent_name = "planning_agent"
    agent_version = "1.0.0"

    async def handle_message(self, message: AgentMessage) -> AgentMessage:
        """消息处理入口 (由 BaseAgent 框架调用)"""

    async def create_itinerary(self, request: StructuredRequest) -> TravelPlanDraft:
        """生成新的旅行行程草稿"""

    async def revise_itinerary(self, draft: TravelPlanDraft, feedback: List[RevisionFeedback]) -> TravelPlanDraft:
        """基于评估反馈修订行程"""

    async def research_destination(self, destination: Destination) -> DestinationInfo:
        """研究目的地信息（景点、交通、住宿市场）"""

    async def search_attractions(self, destination: Destination, preferences: Preferences) -> List[Attraction]:
        """搜索符合偏好的景点"""

    async def search_accommodations(self, destination: Destination, budget: Budget, style: str) -> List[Accommodation]:
        """搜索符合预算和风格的住宿"""

    async def search_restaurants(self, location: str, preferences: DietaryPreferences) -> List[Restaurant]:
        """搜索符合饮食偏好的餐厅"""

    async def optimize_daily_schedule(self, attractions: List[Attraction], day_index: int) -> DaySchedule:
        """优化单日行程安排"""

    async def allocate_budget(self, plan: TravelPlanDraft, total_budget: float) -> BudgetAllocation:
        """分配预算到各分项"""
```

---

## 4. 数据约束

### 4.1 景点推荐约束
- 每个景点必须包含: 名称、位置、类型、建议时长、预估价格、推荐理由
- 景点类型枚举: `nature | culture | entertainment | food | shopping | sports | relaxation`
- 推荐理由必须具体（≥ 10 字），不能是泛泛的"值得一去"

### 4.2 餐厅推荐约束
- 每个餐厅必须包含: 名称、位置、菜系、人均价格、与景点的距离
- 必须考虑用户的饮食限制（如素食、清真等）
- 一日三餐必须覆盖不同的菜系或风格（避免单调）

### 4.3 住宿推荐约束
- 至少 2 个选项（不同价位或风格）
- 每个住宿必须包含: 名称、位置、类型、每晚价格、距离市中心距离、亮点
- 位置应便于出行（距主要景点聚集区 ≤ 10km 或地铁沿线）

---

## 5. 约束与边界条件

### 5.1 输入约束
- StructuredRequest 必须通过 Gate 0 校验
- 预算 > 0
- 天数 ≥ 1

### 5.2 处理约束
- 不允许虚构地点（名称、位置、价格必须可查证）
- 不允许推荐用户排除的类型
- 不允许忽略饮食限制

### 5.3 输出约束
- 每日行程必须完整（morning + afternoon + evening）
- 每餐必须有推荐
- 总预算不得超出用户预算上限

---

## 6. 测试规格

### 6.1 单元测试

| 测试场景 | 输入 | 期望输出 |
|---------|------|---------|
| 正常生成 | 东京5天1万预算 | TravelPlanDraft 完整 |
| 预算紧张 | 东京5天3000预算 | 降低住宿档次，标注成本优化 |
| 偏好匹配 | 偏好"美食"+"文化" | 景点和餐厅推荐偏向美食文化 |
| 饮食限制 | 素食限制 | 所有餐厅推荐均为素食 |
| 排除项 | 排除"购物"类型 | 行程中无购物类活动 |
| 修订 | 反馈指出第3天太满 | 仅修改第3天，其他天不变 |
| 空偏好 | 无偏好标签 | 默认 moderate 节奏，混合风格 |

### 6.2 边界测试

| 测试场景 | 期望行为 |
|---------|---------|
| 1天行程 | 密集安排但不超 12h |
| 30天行程 | 合理分段，每5-7天安排休息日 |
| 预算为 0 | 返回 error (INVALID_INPUT) |
| 未知目的地 | 尝试模糊匹配，失败则返回 error |
| 所有餐厅不匹配饮食限制 | 扩大搜索范围 + 标注 |

---

## 7. 性能规格

| 指标 | 目标值 |
|------|--------|
| 单次行程生成 | ≤ 30s |
| 单次修订 | ≤ 15s |
| 景点搜索 | ≤ 5s |
| 住宿搜索 | ≤ 5s |
| 日程优化 | ≤ 3s |

---

## 8. 变更日志

| 版本 | 日期 | 变更 |
|------|------|------|
| 1.0.0 | 2026-07-05 | 初始版本 |
