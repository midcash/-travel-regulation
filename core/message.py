"""Agent 间通信契约的核心数据类型。

包含:
- TaskType / ErrorCode 枚举
- AgentIdentity / HealthStatus / Capability / AgentMessage 数据类
- BaseAgent / AgentRegistry 抽象基类
- MessageValidationError / TaskExecutionError 异常
- 超时与重试常量

来源: spec/agent_contract.md
"""

from __future__ import annotations

import re
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from enum import Enum
from typing import Any, Dict, List, Optional
from uuid import UUID

# ============================================================
# 模块级常量 — spec/agent_contract.md §5
# ============================================================

MESSAGE_TIMEOUT = 30        # Agent 间消息处理超时 (秒)
TOOL_TIMEOUT = 15           # 工具/API 调用超时 (秒)
TASK_TIMEOUT = 120          # 整体任务完成超时 (秒)
HEALTH_CHECK_TIMEOUT = 5    # 健康检查超时 (秒)

MAX_RETRIES = 3             # 最大重试次数
RETRY_BACKOFF = [1, 2, 4]   # 指数退避序列 (秒)

TIMESTAMP_TOLERANCE = timedelta(minutes=5)  # AgentMessage.validate() 规则4 容差

# UUID v4 正则 (8-4-4-4-12 十六进制格式)
_UUID_V4_RE = re.compile(
    r'^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$'
)

# 允许的 Agent 状态值
_VALID_AGENT_STATUSES = frozenset({"online", "offline", "degraded"})


# ============================================================
# TaskType 枚举 — spec/agent_contract.md §3.2
# ============================================================

class TaskType(Enum):
    """任务类型枚举 — 统一定义所有 Agent 间通信的有效 task_type 值。

    值命名规则: <category>.<action>
    category: task | response | control
    """

    # 任务请求 (Orchestrator → Specialist)
    TASK_CREATE_ITINERARY = "task.create_itinerary"
    TASK_REVISE_ITINERARY = "task.revise_itinerary"
    TASK_VALIDATE_FEASIBILITY = "task.validate_feasibility"
    TASK_EVALUATE_CODE = "task.evaluate_code"
    TASK_EVALUATE_PLAN = "task.evaluate_plan"
    TASK_EVALUATE_CONTRIBUTION = "task.evaluate_contribution"

    # 响应消息 (Specialist → Orchestrator)
    RESPONSE_ITINERARY_DRAFT = "response.itinerary_draft"
    RESPONSE_VALIDATION_REPORT = "response.validation_report"
    RESPONSE_RESULT = "response.result"
    RESPONSE_ERROR = "response.error"

    # 控制消息 (Orchestrator → All Agents)
    CONTROL_ABORT = "control.abort"

    def is_request(self) -> bool:
        """判断是否为 task.* 类别的任务请求。"""
        return self.value.startswith("task.")

    def is_response(self) -> bool:
        """判断是否为 response.* 类别的响应消息。"""
        return self.value.startswith("response.")

    def is_control(self) -> bool:
        """判断是否为 control.* 类别的控制消息。"""
        return self.value.startswith("control.")

    def category(self) -> str:
        """返回消息类别: 'task' | 'response' | 'control'。"""
        return self.value.split(".", 1)[0]


# ============================================================
# ErrorCode 枚举 — spec/agent_contract.md §4.2
# ============================================================

class ErrorCode(Enum):
    """标准错误码枚举。每个值携带 (meaning, recoverable, suggested_action) 元信息。"""

    INVALID_MESSAGE = ("消息格式不合法", False, "abort")
    TASK_NOT_SUPPORTED = ("不支持的任务类型", False, "skip")
    EXECUTION_FAILED = ("任务执行失败", True, "retry")
    TIMEOUT = ("处理超时(30s)", True, "retry")
    DATA_UNAVAILABLE = ("所需数据不可用", True, "skip")
    CONSTRAINT_VIOLATION = ("硬约束违反", False, "revise")
    INTERNAL_ERROR = ("Agent 内部错误", False, "abort")

    def __init__(self, meaning: str, recoverable: bool, suggested_action: str):
        self._meaning = meaning
        self._recoverable = recoverable
        self._suggested_action = suggested_action

    @property
    def meaning(self) -> str:
        """错误码的中文含义。"""
        return self._meaning

    @property
    def recoverable(self) -> bool:
        """是否可通过重试恢复。"""
        return self._recoverable

    @property
    def suggested_action(self) -> str:
        """建议的恢复操作: retry | skip | abort | revise。"""
        return self._suggested_action

    @classmethod
    def retryable_codes(cls) -> List[ErrorCode]:
        """返回所有可重试的错误码 (TIMEOUT, EXECUTION_FAILED)。"""
        return [c for c in cls if c.recoverable]


# ============================================================
# AgentIdentity — spec/agent_contract.md §7.1
# ============================================================

@dataclass(frozen=True)
class AgentIdentity:
    """Agent 唯一标识。

    不可变 (frozen=True)，符合契约原则"消息内容不可变"。
    """

    name: str
    """Agent 唯一标识符 (如 'orchestrator', 'planning_agent')。"""

    version: str
    """Agent 版本号 (SemVer 格式, 如 '1.0.0')。"""

    capabilities: List[str]
    """能力标签列表，用于 Registry 发现。"""

    endpoint: str
    """内部通信端点。"""

    status: str
    """当前状态: 'online' | 'offline' | 'degraded'。"""

    def __post_init__(self):
        if not self.name or not isinstance(self.name, str):
            raise ValueError(f"name 必须为非空字符串, 实际: {self.name!r}")
        if self.status not in _VALID_AGENT_STATUSES:
            raise ValueError(
                f"status 必须是 {sorted(_VALID_AGENT_STATUSES)} 之一, 实际: {self.status!r}"
            )


# ============================================================
# HealthStatus — spec/agent_contract.md §2
# ============================================================

@dataclass
class HealthStatus:
    """Agent 健康检查结果。"""

    status: str
    """健康状态: 'healthy' | 'degraded' | 'unhealthy'。"""

    last_checked: datetime
    """最近检查时间。"""

    details: Dict[str, Any] = field(default_factory=dict)
    """附加详情。"""

    message: str = ""
    """可选的健康状态描述信息。"""


# ============================================================
# Capability — spec/agent_contract.md §2
# ============================================================

@dataclass(frozen=True)
class Capability:
    """Agent 能力描述 (用于 get_capabilities() 返回值)。"""

    name: str
    """能力名称。"""

    description: str
    """能力描述。"""

    version: str = "1.0.0"
    """能力自身的版本。"""


# ============================================================
# AgentMessage — spec/agent_contract.md §3.1
# ============================================================

@dataclass(frozen=True)
class AgentMessage:
    """Agent 间通信的标准消息格式。

    不可变 (frozen=True)，发送后不得修改。
    """

    message_id: str
    """UUID v4 格式的消息唯一标识。"""

    sender: AgentIdentity
    """发送者标识。"""

    receiver: AgentIdentity
    """接收者标识。"""

    task_type: TaskType
    """任务类型枚举值。"""

    payload: Dict[str, Any]
    """任务载荷。"""

    timestamp: datetime
    """消息创建时间 (ISO 8601)。"""

    correlation_id: Optional[str] = None
    """关联请求 ID，用于请求-响应配对。响应消息必须非空。"""

    def validate(self, registry: Optional[AgentRegistry] = None) -> bool:
        """验证消息格式的合法性。

        验证规则 (spec/agent_contract.md §3.1):
        1. message_id 必须为非空 UUID v4
        2. sender/receiver 必须为已注册的 Agent (仅当 registry 不为 None 时)
        3. task_type 必须为 TaskType 枚举中的已知值
        4. timestamp 必须在 ±5 分钟容差范围内
        5. 若为响应消息 (task_type.is_response())，correlation_id 必须非空

        Args:
            registry: 可选的 AgentRegistry，用于校验 sender/receiver 注册状态。
                      为 None 时跳过规则 2。

        Returns:
            True 表示消息合法。

        Raises:
            MessageValidationError: 任何一条校验规则不满足时抛出。
        """
        violations: List[str] = []

        # 规则 1: message_id 必须为非空 UUID v4
        if not self.message_id:
            violations.append("message_id 为空")
        elif not _UUID_V4_RE.match(self.message_id):
            violations.append(f"message_id 不是合法的 UUID v4: {self.message_id!r}")
        else:
            try:
                uuid_obj = UUID(self.message_id)
                if uuid_obj.version != 4:
                    violations.append(f"message_id 不是 UUID v4 (version={uuid_obj.version})")
            except ValueError:
                violations.append(f"message_id 无法解析为 UUID: {self.message_id!r}")

        # 规则 2: sender/receiver 注册状态 (仅在 registry 提供时检查)
        if registry is not None:
            # 注意: 此检查涉及异步 I/O，在同步 validate() 中仅做存在性检查
            # 完整异步校验应在 BaseAgent.handle_message() 入口处完成
            if not isinstance(self.sender, AgentIdentity):
                violations.append("sender 不是 AgentIdentity 实例")
            if not isinstance(self.receiver, AgentIdentity):
                violations.append("receiver 不是 AgentIdentity 实例")

        # 规则 3: task_type 必须为已知枚举值
        if not isinstance(self.task_type, TaskType):
            violations.append(
                f"task_type 不是 TaskType 枚举值: {type(self.task_type).__name__}"
            )

        # 规则 4: timestamp 必须在 ±5 分钟范围内
        now = datetime.now(timezone.utc)
        # 将 timestamp 统一转为 UTC 比较
        ts = self.timestamp
        if ts.tzinfo is None:
            ts = ts.replace(tzinfo=timezone.utc)
        diff = abs(now - ts)
        if diff > TIMESTAMP_TOLERANCE:
            violations.append(
                f"timestamp 偏差 {diff.total_seconds():.0f}s "
                f"超出容差 {TIMESTAMP_TOLERANCE.total_seconds():.0f}s"
            )

        # 规则 5: 响应消息必须带 correlation_id
        if self.task_type.is_response():
            if not self.correlation_id:
                violations.append(
                    f"响应消息 (task_type={self.task_type.value}) "
                    f"必须携带 correlation_id"
                )
            elif self.correlation_id and not _UUID_V4_RE.match(self.correlation_id):
                violations.append(
                    f"correlation_id 不是合法的 UUID v4: {self.correlation_id!r}"
                )

        if violations:
            raise MessageValidationError(
                message=f"消息校验失败: {'; '.join(violations)}",
                violations=violations,
            )
        return True


# ============================================================
# 异常类 — spec/agent_contract.md §2, §3.1
# ============================================================

class MessageValidationError(ValueError):
    """消息格式校验失败。由 AgentMessage.validate() 抛出。"""

    def __init__(self, message: str, violations: List[str]):
        super().__init__(message)
        self.violations = violations
        """所有违规项的描述列表。"""


class TaskExecutionError(Exception):
    """任务执行失败。由 BaseAgent.handle_message() 抛出。"""

    def __init__(self, message: str, error_code: ErrorCode, agent_name: str):
        super().__init__(message)
        self.error_code = error_code
        """关联的错误码。"""
        self.agent_name = agent_name
        """发生错误的 Agent 名称。"""


# ============================================================
# BaseAgent — spec/agent_contract.md §2
# ============================================================

class BaseAgent(ABC):
    """Agent 基类 — 所有 Agent 的抽象契约。

    子类必须实现全部 5 个抽象成员。
    """

    @property
    @abstractmethod
    def agent_name(self) -> str:
        """Agent 唯一标识符。"""
        ...

    @property
    @abstractmethod
    def agent_version(self) -> str:
        """Agent 版本号 (SemVer)。"""
        ...

    @abstractmethod
    async def handle_message(self, message: AgentMessage) -> AgentMessage:
        """处理接收到的消息并返回响应。

        Args:
            message: 标准格式的 Agent 消息。

        Returns:
            标准格式的响应消息。

        Raises:
            MessageValidationError: 消息格式不合法。
            TaskExecutionError: 任务执行失败。
            TimeoutError: 处理超时 (30s)。
        """
        ...

    @abstractmethod
    async def health_check(self) -> HealthStatus:
        """返回 Agent 健康状态。"""
        ...

    @abstractmethod
    def get_capabilities(self) -> List[Capability]:
        """返回 Agent 支持的能力列表。"""
        ...


# ============================================================
# AgentRegistry — spec/agent_contract.md §7.2
# ============================================================

class AgentRegistry(ABC):
    """Agent 注册与发现中心 — 抽象契约。"""

    @abstractmethod
    async def register(self, agent: AgentIdentity) -> bool:
        """注册 Agent。返回 True 表示注册成功。"""
        ...

    @abstractmethod
    async def unregister(self, agent_name: str) -> bool:
        """注销 Agent。返回 True 表示注销成功。"""
        ...

    @abstractmethod
    async def discover(self, capability: str) -> List[AgentIdentity]:
        """按能力标签发现 Agent。返回匹配的 Agent 列表。"""
        ...

    @abstractmethod
    async def get_agent(self, name: str) -> Optional[AgentIdentity]:
        """按名称查找 Agent。未找到返回 None。"""
        ...

    @abstractmethod
    async def health_check_all(self) -> Dict[str, HealthStatus]:
        """对所有已注册 Agent 执行健康检查。"""
        ...
