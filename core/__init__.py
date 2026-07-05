"""core 包 — 基础设施层。

包含 Agent 间通信的消息协议、共享上下文黑板、编排引擎和质量门执行器。
"""

from core.message import (
    # 枚举
    ErrorCode,
    TaskType,
    # 数据类
    AgentIdentity,
    AgentMessage,
    Capability,
    HealthStatus,
    # 抽象基类
    AgentRegistry,
    BaseAgent,
    # 异常
    MessageValidationError,
    TaskExecutionError,
    # 常量
    HEALTH_CHECK_TIMEOUT,
    MAX_RETRIES,
    MESSAGE_TIMEOUT,
    RETRY_BACKOFF,
    TASK_TIMEOUT,
    TIMESTAMP_TOLERANCE,
    TOOL_TIMEOUT,
)
from core.context import (
    ContextStatus,
    LogEntry,
    SharedContext,
)

__version__ = "1.0.0-dev"

__all__ = [
    # 枚举
    "ErrorCode",
    "TaskType",
    "ContextStatus",
    # 数据类
    "AgentIdentity",
    "AgentMessage",
    "Capability",
    "HealthStatus",
    "LogEntry",
    # 核心类
    "SharedContext",
    # 抽象基类
    "AgentRegistry",
    "BaseAgent",
    # 异常
    "MessageValidationError",
    "TaskExecutionError",
    # 常量
    "HEALTH_CHECK_TIMEOUT",
    "MAX_RETRIES",
    "MESSAGE_TIMEOUT",
    "RETRY_BACKOFF",
    "TASK_TIMEOUT",
    "TIMESTAMP_TOLERANCE",
    "TOOL_TIMEOUT",
]
