# Orchestrator Specification — 编排器规格

---

## 1. 模块标识

| 属性 | 值 |
|------|-----|
| 模块名称 | Orchestrator |
| Agent 标识 | `orchestrator` |
| 版本 | 1.0.0 |
| 类型 | 主控 Agent |
| 依赖 | Planning Agent, Execution Agent, Evaluation Agent |
| 文件路径 | `agents/orchestrator.py` |

---

## 2. 功能规格

### 2.1 用户需求解析

**函数**: `parse_user_request(raw_text: str) -> StructuredRequest`

**行为**:
1. 从自然语言中提取: 目的地、出发日期、返回日期、预算、人数、偏好标签
2. 对模糊信息进行二义性消解:
   - "下个月" → 当前月份 + 1
   - "两个人" → adults=2
   - "北京" → {city: "北京", country: "中国"}
3. 必填项检查: 目的地 AND 日期 AND 预算 → 缺一则追问用户

**输入**:
```
"我想去东京玩5天，预算1万块，喜欢美食和文化"
```

**输出**:
```json
{
  "destination": { "city": "东京", "country": "日本" },
  "dates": { "arrival": null, "departure": null, "duration_days": 5 },
  "budget": { "total": 10000, "currency": "CNY" },
  "travelers": { "adults": 1, "children": 0 },
  "preferences": { "style": ["food", "culture"], "pace": "moderate" }
}
```
注: dates 为 null 时需追问具体日期

### 2.2 任务分解

**函数**: `decompose_task(request: StructuredRequest) -> TaskQueue`

**行为**:
1. 将需求分解为原子子任务:
   - T1: 交通方案规划
   - T2: 住宿方案规划
   - T3: 每日行程规划
   - T4: 预算方案生成
2. 确定依赖关系: T1 || T2 (无依赖) → T3 (依赖 T1, T2) → T4 (依赖 T1-T3)
3. 构建任务 DAG

**输出**: TaskQueue (拓扑排序的任务列表)

### 2.3 任务路由

**函数**: `route_task(task: Task, registry: AgentRegistry) -> AgentIdentity`

**路由规则**:

| 任务类型 | 目标 Agent | 消息类型 |
|---------|-----------|---------|
| 行程规划 (T1-T4) | planning_agent | task.create_itinerary |
| 可行性验证 | execution_agent | task.validate_feasibility |
| 方案评估 | evaluation_agent | task.evaluate_plan |
| 行程修订 (Gate 2 反馈修订) | planning_agent | task.revise_itinerary |
| 代码评估 | evaluation_agent | task.evaluate_code |
| 贡献度评估 | evaluation_agent | task.evaluate_contribution |

### 2.4 结果整合

**函数**: `assemble_plan(draft: TravelPlanDraft, validation: ValidationReport, quality: PlanQualityReport) -> FinalTravelPlan`

**行为**:
1. 合并 Planning Agent 的草稿 + Execution Agent 的校验修正
2. 应用 Evaluation Agent 的改进建议
3. 检查完整性: 交通 + 住宿 + 每日行程 + 预算 → 缺项自动补占位
4. 生成总览摘要
5. 附加质量报告

### 2.5 修订循环管理

**函数**: `manage_revision_loop(current_plan: TravelPlanDraft, quality_report: PlanQualityReport) -> RevisionDecision`

**决策逻辑**:
```
if quality_report.composite_score >= 80:
    return RevisionDecision.APPROVE
elif iteration_count >= 3:
    return RevisionDecision.DEGRADE  # 降级输出
else:
    return RevisionDecision.REVISE   # 反馈修订
```

---

## 3. 接口规格

### 3.1 公共方法

```python
class Orchestrator(BaseAgent):
    agent_name = "orchestrator"
    agent_version = "1.0.0"

    async def process_request(self, raw_text: str) -> FinalTravelPlan:
        """完整的用户请求处理流程"""

    async def parse_user_request(self, raw_text: str) -> StructuredRequest:
        """解析用户自然语言需求"""

    async def decompose_task(self, request: StructuredRequest) -> TaskQueue:
        """分解需求为原子任务"""

    async def route_task(self, task: Task) -> AgentMessage:
        """路由任务到目标 Agent"""

    async def assemble_plan(self, *args) -> FinalTravelPlan:
        """整合所有 Agent 产出"""

    async def manage_quality_gate(self, gate_id: int, payload: Dict) -> GateResult:
        """执行质量门检查"""

    async def handle_revision(self, quality_report: PlanQualityReport) -> RevisionDecision:
        """决定修订策略"""
```

### 3.2 事件处理

| 事件 | 处理方式 |
|------|---------|
| on_agent_timeout | 重试 (指数退避，最多3次) |
| on_agent_error | 记录日志 + 降级策略 |
| on_gate_failure | 按 Gate 类型处理: 追问/修订/降级 |
| on_user_cancel | 广播 control.abort + 清理 Shared Context |

---

## 4. 状态管理

### 4.1 状态转换

```
IDLE
  → (receive request) → VALIDATING
  → (Gate 0 pass) → DECOMPOSING
  → (tasks ready) → DISPATCHING
  → (all dispatched) → WAITING_PLANNER
  → (draft received) → WAITING_EXECUTOR
  → (validation received) → WAITING_EVALUATOR
  → (quality report received) → DECIDING
  → (PASS) → ASSEMBLING → WAITING_GATE3 → COMPLETED
  → (REVISE) → WAITING_PLANNER (iteration++)
  → (DEGRADE) → ASSEMBLING → COMPLETED_DEGRADED
  → (ERROR) → FAILED
```

### 4.2 Shared Context 操作

Orchestrator 是唯一可以直接写入 Shared Context 的 Agent。子 Agent 只能读取。

**写入操作**:
- `context.set_request(request)` — 写入结构化需求
- `context.set_task_queue(queue)` — 写入任务队列
- `context.set_current_draft(draft)` — 更新当前草稿
- `context.set_validation_report(report)` — 写入校验报告
- `context.set_quality_report(report)` — 写入质量评估
- `context.increment_iteration()` — 迭代计数 +1
- `context.set_status(status)` — 更新状态

**读取操作**:
- `context.get_request()` → StructuredRequest
- `context.get_current_draft()` → TravelPlanDraft
- `context.get_status()` → Status

---

## 5. 约束与边界条件

### 5.1 输入约束
- 用户输入不能为空字符串
- 预算必须 > 0
- 日期必须在未来（不能是过去）
- 目的地必须可识别（有对应地理实体）

### 5.2 处理约束
- 单个请求最多 3 轮 Evaluation → Revision 循环
- 单次请求总处理时间 ≤ 120s
- 并发子任务数 ≤ 5

### 5.3 输出约束
- 最终方案必须包含: 交通、住宿、每日行程、预算明细
- 若降级输出，必须标注 `degraded: true` + 降级原因
- 质量报告必须附加到最终方案中

---

## 6. 测试规格

### 6.1 单元测试覆盖

| 测试场景 | 输入 | 期望输出 |
|---------|------|---------|
| 正常解析 | "去东京5天1万" | StructuredRequest 完整 |
| 缺失日期 | "去东京玩预算1万" | 追问日期 |
| 缺失目的地 | "想出去玩预算1万" | 追问目的地 |
| 缺失预算 | "去东京5天" | 追问预算 |
| 空输入 | "" | 拒绝 + 提示 |
| 过去日期 | "2020-01-01出发去东京" | 拒绝 + 提示 |

### 6.2 集成测试覆盖

| 测试场景 | 期望行为 |
|---------|---------|
| 完整流程 (happy path) | 5步全部走完，Gate 全部通过 |
| Planning 超时 | 重试1次，仍失败则降级 |
| Evaluation 3轮不通过 | 第3轮后降级输出 + 标注 |
| 用户中途取消 | 广播 abort + 清理状态 |
| 硬约束违反 | 退回 Planning 修订，不降级 |

---

## 7. 变更日志

| 版本 | 日期 | 变更 |
|------|------|------|
| 1.0.0 | 2026-07-05 | 初始版本 |
