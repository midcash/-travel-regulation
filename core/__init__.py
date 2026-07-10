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
from core.gate_runner import (
    BlockingIssue,
    GateResult,
    GateRunner,
    Warning_,
)
from core.orchestration_engine import (
    AgentRouter,
    ResultAssembler,
    RetryManager,
    RouteRule,
    Task,
    TaskDAG,
    TaskStatus,
)
from core.task_decomposer import (
    TaskDecomposer,
    _check_cycles,
    _check_orphans,
)
from core.llm_client import (
    DEFAULT_MODEL,
    ENV_API_KEY,
    LLM_TIMEOUT,
    LLMClient,
    LLMEmptyResponseError,
    LLMError,
    LLMParseError,
    LLMRateLimitError,
    LLMSchemaValidationError,
    LLMTimeoutError,
)

__version__ = "1.1.0-dev"

__all__ = [
    # 枚举
    "ErrorCode",
    "TaskType",
    "ContextStatus",
    "TaskStatus",
    # 数据类
    "AgentIdentity",
    "AgentMessage",
    "Capability",
    "HealthStatus",
    "LogEntry",
    "Task",
    # 核心类
    "SharedContext",
    "TaskDAG",
    "AgentRouter",
    "RetryManager",
    "ResultAssembler",
    "GateRunner",
    "TaskDecomposer",
    # Gate 相关
    "BlockingIssue",
    "GateResult",
    "RouteRule",
    "Warning_",
    # 抽象基类
    "AgentRegistry",
    "BaseAgent",
    # 异常
    "MessageValidationError",
    "TaskExecutionError",
    "LLMError",
    "LLMTimeoutError",
    "LLMRateLimitError",
    "LLMParseError",
    "LLMEmptyResponseError",
    "LLMSchemaValidationError",
    # 常量
    "HEALTH_CHECK_TIMEOUT",
    "MAX_RETRIES",
    "MESSAGE_TIMEOUT",
    "RETRY_BACKOFF",
    "TASK_TIMEOUT",
    "TIMESTAMP_TOLERANCE",
    "TOOL_TIMEOUT",
    "LLM_TIMEOUT",
    "DEFAULT_MODEL",
    "ENV_API_KEY",
    # LLM 客户端
    "LLMClient",
    # 校验函数
    "_check_cycles",
    "_check_orphans",
]
