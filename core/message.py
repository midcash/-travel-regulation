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
from uuid import UUID, uuid4

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

# ============================================================
# 协议版本化常量 — v1.2.0
# ============================================================

PROTOCOL_VERSION = "1.2"
"""当前系统支持的协议版本 (MAJOR.MINOR 格式)。"""


class VersionPolicy:
    """协议版本兼容性策略。

    兼容性规则:
    - 同 MAJOR.MINOR → full (完全兼容)
    - 同 MAJOR, 不同 MINOR → adapt (忽略未知字段 / 使用默认值)
    - 不同 MAJOR → reject (不兼容)
    """

    @staticmethod
    def server_version() -> str:
        """返回当前服务端协议版本。"""
        return PROTOCOL_VERSION

    @staticmethod
    def check(
        client_version: str, server_version: str = PROTOCOL_VERSION
    ) -> "CompatibilityResult":
        """检查客户端版本与服务器版本的兼容性。

        Args:
            client_version: 客户端协议版本 (MAJOR.MINOR 格式)。
            server_version: 服务端协议版本，默认使用当前 PROTOCOL_VERSION。

        Returns:
            CompatibilityResult (来自 models.protocol)。
        """
        # 延迟导入避免循环依赖
        from models.protocol import CompatibilityResult

        try:
            client_major, client_minor = VersionPolicy._parse(client_version)
            server_major, server_minor = VersionPolicy._parse(server_version)
        except ValueError as e:
            return CompatibilityResult.reject()

        if client_major != server_major:
            # 主版本不同 → 不可兼容
            return CompatibilityResult.reject()

        if client_minor == server_minor:
            # 完全一致
            return CompatibilityResult.full(server_version)

        # 同 MAJOR, 不同 MINOR → 可适配
        return CompatibilityResult.adapt(server_version)

    @staticmethod
    def negotiate(
        client_versions: List[str], server_version: str = PROTOCOL_VERSION
    ) -> Optional[str]:
        """多版本协商：返回双方共同支持的最高版本。

        在客户端支持的版本列表中，找出与服务端兼容且不超过服务端版本的最高版本。

        Args:
            client_versions: 客户端支持的版本列表 (降序)。
            server_version: 服务端协议版本。

        Returns:
            协商后的版本号字符串。如无兼容版本返回 None。

        Example:
            negotiate(["1.2", "1.1"], "1.1") → "1.1"
            negotiate(["1.0"], "1.2") → "1.0"
        """
        try:
            server_tuple = VersionPolicy._parse(server_version)
        except ValueError:
            return None

        best: Optional[str] = None
        best_tuple: Optional[tuple] = None

        for cv in client_versions:
            result = VersionPolicy.check(cv, server_version)
            if not result.compatible:
                continue
            try:
                cv_tuple = VersionPolicy._parse(cv)
            except ValueError:
                continue
            # 协商版本不能超过服务端版本
            if cv_tuple > server_tuple:
                continue
            if best_tuple is None or cv_tuple > best_tuple:
                best_tuple = cv_tuple
                best = cv

        return best

    @staticmethod
    def _parse(version: str) -> tuple:
        """解析 'MAJOR.MINOR' → (major_int, minor_int)。

        Args:
            version: 版本号字符串。

        Returns:
            (major, minor) 元组。

        Raises:
            ValueError: 版本格式不合法。
        """
        if not version or not isinstance(version, str):
            raise ValueError(f"版本号必须为非空字符串, 实际: {version!r}")

        parts = version.strip().split(".")
        if len(parts) != 2:
            raise ValueError(
                f"版本号格式必须为 MAJOR.MINOR, 实际: {version!r}"
            )

        try:
            major = int(parts[0])
            minor = int(parts[1])
        except ValueError:
            raise ValueError(f"版本号各部分必须为整数, 实际: {version!r}")

        if major < 0 or minor < 0:
            raise ValueError(f"版本号不能为负数, 实际: {version!r}")

        return (major, minor)


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

    protocol_version: str = "1.0"
    """协议版本号 (MAJOR.MINOR 格式)。v1.1.0 及之前默认为 "1.0"，新消息应设为当前 PROTOCOL_VERSION。"""

    correlation_id: Optional[str] = None
    """关联请求 ID，用于请求-响应配对。响应消息必须非空。"""

    _auto_fixed: Optional[List[str]] = None
    """自动修复记录（v1.2.0 P3 ErrorRecovery）。
    None = 未经过 auto_fix；非空 list = 已应用的修复操作描述列表。
    由 MessageValidator.auto_fix() 或 AgentMessage.validate() 内部填充。"""

    # ----------------------------------------------------------
    # 可自动修复的违规类型标识 (v1.2.0 P3 ErrorRecovery)
    # ----------------------------------------------------------

    _FIXABLE_TIMESTAMP = "timestamp 偏差"
    _FIXABLE_CORRELATION = "必须携带 correlation_id"

    def validate(self, registry: Optional[AgentRegistry] = None) -> "AgentMessage":
        """验证消息格式的合法性，尝试自动修复可修复的问题。

        验证规则 (spec/agent_contract.md §3.1):
        1. message_id 必须为非空 UUID v4
        2. sender/receiver 必须为已注册的 Agent (仅当 registry 不为 None 时)
        3. task_type 必须为 TaskType 枚举中的已知值
        4. timestamp 必须在 ±5 分钟容差范围内
        5. 若为响应消息 (task_type.is_response())，correlation_id 必须非空

        v1.2.0 P3 ErrorRecovery: 若违规仅包含可自动修复项（timestamp 偏差、
        correlation_id 缺失），则自动修复并返回新消息实例，而非抛出异常。

        Args:
            registry: 可选的 AgentRegistry，用于校验 sender/receiver 注册状态。
                      为 None 时跳过规则 2。

        Returns:
            合法的 AgentMessage（可能是修复后的新实例）。

        Raises:
            MessageValidationError: 存在不可自动修复的违规项时抛出。
        """
        violations: List[str] = []
        fixable_violations: List[str] = []

        # 规则 0: protocol_version 必须存在且为非空字符串
        if not self.protocol_version or not isinstance(self.protocol_version, str):
            violations.append(
                f"protocol_version 必须为非空字符串, "
                f"实际: {self.protocol_version!r}"
            )

        # 规则 1: message_id 必须为非空 UUID v4
        if not self.message_id:
            violations.append("message_id 为空")
        elif not isinstance(self.message_id, str):
            violations.append(
                f"message_id 必须是字符串类型, 实际: {type(self.message_id).__name__}"
            )
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
        ts = self.timestamp
        if ts.tzinfo is None:
            ts = ts.replace(tzinfo=timezone.utc)
        diff = abs(now - ts)
        if diff > TIMESTAMP_TOLERANCE:
            ts_violation = (
                f"timestamp 偏差 {diff.total_seconds():.0f}s "
                f"超出容差 {TIMESTAMP_TOLERANCE.total_seconds():.0f}s"
            )
            fixable_violations.append(ts_violation)

        # 规则 5: 响应消息必须带 correlation_id
        if isinstance(self.task_type, TaskType) and self.task_type.is_response():
            if not self.correlation_id:
                corr_violation = (
                    f"响应消息 (task_type={self.task_type.value}) "
                    f"必须携带 correlation_id"
                )
                fixable_violations.append(corr_violation)
            elif self.correlation_id and not isinstance(self.correlation_id, str):
                violations.append(
                    f"correlation_id 必须是字符串类型, "
                    f"实际: {type(self.correlation_id).__name__}"
                )
            elif self.correlation_id and not _UUID_V4_RE.match(self.correlation_id):
                violations.append(
                    f"correlation_id 不是合法的 UUID v4: {self.correlation_id!r}"
                )

        # v1.2.0 P3: 尝试自动修复
        if violations or fixable_violations:
            # 如果存在不可修复的违规 → 直接抛异常
            if violations:
                all_violations = violations + fixable_violations
                raise MessageValidationError(
                    message=f"消息校验失败: {'; '.join(all_violations)}",
                    violations=all_violations,
                )

            # 仅剩可修复项 → 自动修复
            return self._apply_auto_fix(fixable_violations)

        return self

    def _apply_auto_fix(self, fixable_violations: List[str]) -> "AgentMessage":
        """对可修复的违规项自动修复，返回新 AgentMessage 实例。

        修复项:
        - timestamp 偏差 → 修正为当前 UTC 时间
        - correlation_id 缺失 (响应消息) → 自动生成 UUID v4

        Args:
            fixable_violations: 可修复的违规描述列表。

        Returns:
            修复后的新 AgentMessage 实例（_auto_fixed 字段记录修复操作）。
        """
        import logging
        logger = logging.getLogger(__name__)
        fixes_applied: List[str] = []

        fixed_timestamp = self.timestamp
        fixed_correlation_id = self.correlation_id

        for v in fixable_violations:
            if v.startswith(self._FIXABLE_TIMESTAMP):
                fixed_timestamp = datetime.now(timezone.utc)
                fixes_applied.append("timestamp_corrected_to_utc_now")
                logger.warning(
                    "auto_fix: message=%s timestamp 已修正为当前 UTC 时间",
                    self.message_id,
                )
            elif self._FIXABLE_CORRELATION in v:
                fixed_correlation_id = str(uuid4())
                fixes_applied.append("correlation_id_auto_generated")
                logger.warning(
                    "auto_fix: message=%s correlation_id 已自动生成 UUID v4",
                    self.message_id,
                )

        # 使用 object.__setattr__ 绕过 frozen 创建新实例
        return AgentMessage(
            message_id=self.message_id,
            sender=self.sender,
            receiver=self.receiver,
            task_type=self.task_type,
            payload=self.payload,
            timestamp=fixed_timestamp,
            protocol_version=self.protocol_version,
            correlation_id=fixed_correlation_id,
            _auto_fixed=fixes_applied,
        )


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
