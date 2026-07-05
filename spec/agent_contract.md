# Agent Contract — Agent 间通信契约

---

## 1. 契约概述

本文档定义了旅游规划编排系统中所有 Agent 之间的通信契约。任何 Agent 与其他 Agent 的交互都必须严格遵循此契约。

**契约原则**:
- 消息格式必须在发送前验证，格式不合规的消息将被拒绝
- 请求-响应必须配对（通过 correlation_id）
- 所有 Agent 必须实现标准错误响应
- 消息内容不可变（发送后不得修改）

---

## 2. BaseAgent 接口契约

所有 Agent 必须继承 `BaseAgent` 并实现以下接口:

```python
class BaseAgent(ABC):
    """Agent 基类，所有 Agent 的抽象契约"""

    @property
    @abstractmethod
    def agent_name(self) -> str:
        """Agent 唯一标识符"""

    @property
    @abstractmethod
    def agent_version(self) -> str:
        """Agent 版本号 (SemVer)"""

    @abstractmethod
    async def handle_message(self, message: AgentMessage) -> AgentMessage:
        """处理接收到的消息并返回响应

        Args:
            message: 标准格式的 Agent 消息

        Returns:
            标准格式的响应消息

        Raises:
            MessageValidationError: 消息格式不合法
            TaskExecutionError: 任务执行失败
            TimeoutError: 处理超时 (30s)
        """

    @abstractmethod
    async def health_check(self) -> HealthStatus:
        """返回 Agent 健康状态"""

    @abstractmethod
    def get_capabilities(self) -> List[Capability]:
        """返回 Agent 支持的能力列表"""
```

---

## 3. 消息契约

### 3.1 AgentMessage 数据模型

```python
@dataclass
class AgentMessage:
    message_id: str          # UUID v4
    sender: AgentIdentity    # 发送者标识
    receiver: AgentIdentity  # 接收者标识
    task_type: TaskType      # 任务类型枚举
    payload: Dict[str, Any]  # 任务载荷
    timestamp: datetime      # ISO 8601
    correlation_id: Optional[str] = None  # 关联请求 ID

    def validate(self) -> bool:
        """验证消息格式的合法性"""
        # 1. message_id 必须为非空 UUID
        # 2. sender/receiver 必须为已注册的 Agent
        # 3. task_type 必须为已知的任务类型
        # 4. timestamp 必须在合理范围内 (±5min)
        # 5. 若为响应消息，correlation_id 必须非空
```

### 3.2 各 Agent 的消息契约

#### Orchestrator → Planning Agent

**请求**: `task.create_itinerary`
```json
{
  "payload": {
    "request_id": "uuid",
    "destination": { "city": "string", "country": "string" },
    "dates": { "arrival": "YYYY-MM-DD", "departure": "YYYY-MM-DD" },
    "budget": { "total": "number", "currency": "string" },
    "travelers": { "adults": "number", "children": "number" },
    "preferences": { ... },
    "constraints": { ... }
  }
}
```

**请求**: `task.revise_itinerary`
```json
{
  "payload": {
    "original_draft_id": "uuid",
    "revision_feedback": [
      { "dimension": "string", "issue": "string", "suggestion": "string", "priority": "string" }
    ]
  }
}
```

**响应**: `response.itinerary_draft` → 见 planner_playbook.md §5

#### Orchestrator → Execution Agent

**请求**: `task.validate_feasibility`
```json
{
  "payload": {
    "draft_id": "uuid",
    "travel_plan_draft": { ... }
  }
}
```

**响应**: `response.validation_report` → 见 executor_playbook.md §5

#### Orchestrator → Evaluation Agent

**请求**: `task.evaluate_code` (Mode A)
```json
{
  "payload": {
    "target_agent": "string",
    "code_files": ["string (paths)"],
    "context": "string (optional)"
  }
}
```

**请求**: `task.evaluate_plan` (Mode B)
```json
{
  "payload": {
    "plan_id": "uuid",
    "travel_plan_draft": { ... },
    "validation_report": { ... }
  }
}
```

**请求**: `task.evaluate_contribution` (Mode C)
```json
{
  "payload": {
    "test_suite_id": "string",
    "test_cases": [{ "input": {...}, "expected_output": {...} }],
    "baseline_config": ["orchestrator", "planning_agent", "execution_agent", "evaluation_agent"]
  }
}
```

**响应**: 见 evaluator_playbook.md §5

#### 通用消息类型

**响应**: `response.result`
```json
{
  "payload": {
    "result_type": "string (itinerary_draft | validation_report | code_quality_report | plan_quality_report | contribution_report)",
    "data": { "... (具体响应内容，见对应 playbook §5)" }
  }
}
```
> 此消息类型是 Orchestrator 接收子 Agent 响应的通用包装。具体 payload 结构由 `result_type` 决定。

**控制**: `control.abort`
```json
{
  "payload": {
    "reason": "user_cancel | fatal_error | timeout",
    "description": "string"
  }
}
```
> 此消息类型用于 Orchestrator 向所有子 Agent 广播中止指令。触发场景: 用户取消、致命错误、全局超时。

---

## 4. 错误处理契约

### 4.1 标准错误响应

所有 Agent 在无法完成任务时必须返回:

```json
{
  "message_id": "uuid",
  "sender": "<agent_name>",
  "receiver": "orchestrator",
  "task_type": "response.error",
  "payload": {
    "error_code": "ERROR_CODE",
    "error_message": "Human-readable description",
    "original_message_id": "uuid",
    "recoverable": true/false,
    "suggested_action": "retry | skip | abort | manual_review"
  },
  "timestamp": "ISO 8601",
  "correlation_id": "uuid"
}
```

### 4.2 标准错误码

| 错误码 | 含义 | 可恢复 | 建议操作 |
|--------|------|--------|---------|
| `INVALID_MESSAGE` | 消息格式不合法 | 否 | abort |
| `TASK_NOT_SUPPORTED` | 不支持的任务类型 | 否 | skip |
| `EXECUTION_FAILED` | 任务执行失败 | 是 | retry |
| `TIMEOUT` | 处理超时 (30s) | 是 | retry |
| `DATA_UNAVAILABLE` | 所需数据不可用 | 是 | skip (降级) |
| `CONSTRAINT_VIOLATION` | 硬约束违反 | 否 | revise |
| `INTERNAL_ERROR` | Agent 内部错误 | 否 | abort |

---

## 5. 超时与重试契约

### 5.1 超时设置

| 操作 | 超时 |
|------|------|
| Agent 间消息处理 | 30s |
| 工具调用 (API) | 15s |
| 整体任务完成 | 120s |
| 健康检查 | 5s |

### 5.2 重试策略

```
重试条件: 错误码 = TIMEOUT | EXECUTION_FAILED
重试次数: 最多 3 次
退避策略: 指数退避 (1s → 2s → 4s)
重试后仍失败: 降级处理或 abort
```

---

## 6. 版本兼容性契约

### 6.1 Agent 版本号

- 格式: SemVer (MAJOR.MINOR.PATCH)
- MAJOR: 契约不兼容的变更
- MINOR: 向后兼容的功能新增
- PATCH: 向后兼容的 bug 修复

### 6.2 兼容性矩阵

| 变更类型 | 消息格式 | Payload 新增字段 | Payload 删除字段 | 处理逻辑 |
|---------|---------|----------------|----------------|---------|
| MAJOR | 可变更 | 可新增/删除 | 可删除 | 不可兼容 |
| MINOR | 不可变更 | 仅可新增(可选) | 不可删除 | 向后兼容 |
| PATCH | 不可变更 | 不可变更 | 不可变更 | 完全兼容 |

---

## 7. Agent 注册与发现

### 7.1 Agent Identity

```python
@dataclass
class AgentIdentity:
    name: str           # 唯一标识符
    version: str        # SemVer
    capabilities: List[str]  # 能力标签
    endpoint: str       # 内部通信端点
    status: str         # online | offline | degraded
```

### 7.2 Registry 契约

```python
class AgentRegistry(ABC):
    @abstractmethod
    async def register(self, agent: AgentIdentity) -> bool: ...

    @abstractmethod
    async def unregister(self, agent_name: str) -> bool: ...

    @abstractmethod
    async def discover(self, capability: str) -> List[AgentIdentity]: ...

    @abstractmethod
    async def get_agent(self, name: str) -> Optional[AgentIdentity]: ...

    @abstractmethod
    async def health_check_all(self) -> Dict[str, HealthStatus]: ...
```

---

## 8. 变更日志

| 版本 | 日期 | 变更 |
|------|------|------|
| 1.0.0 | 2026-07-05 | 初始版本，定义完整 Agent 通信契约 |
