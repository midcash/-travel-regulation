"""core/message.py 单元测试。

覆盖: TaskType, ErrorCode, AgentIdentity, HealthStatus, Capability,
       AgentMessage.validate(), MessageValidationError, TaskExecutionError,
       BaseAgent, AgentRegistry, 超时常量
"""

import uuid
from datetime import datetime, timedelta, timezone

import pytest

from core.message import (
    HEALTH_CHECK_TIMEOUT,
    MAX_RETRIES,
    MESSAGE_TIMEOUT,
    RETRY_BACKOFF,
    TASK_TIMEOUT,
    TIMESTAMP_TOLERANCE,
    TOOL_TIMEOUT,
    AgentIdentity,
    AgentMessage,
    AgentRegistry,
    BaseAgent,
    Capability,
    ErrorCode,
    HealthStatus,
    MessageValidationError,
    TaskExecutionError,
    TaskType,
)


# ============================================================
# TaskType
# ============================================================

class TestTaskType:
    """TaskType 枚举测试。"""

    def test_all_11_values_exist(self):
        """验证 11 个枚举值全部存在。"""
        values = {t.value for t in TaskType}
        expected_task = {
            "task.create_itinerary", "task.revise_itinerary",
            "task.validate_feasibility", "task.evaluate_code",
            "task.evaluate_plan", "task.evaluate_contribution",
        }
        expected_response = {
            "response.itinerary_draft", "response.validation_report",
            "response.result", "response.error",
        }
        expected_control = {"control.abort"}
        assert expected_task.issubset(values)
        assert expected_response.issubset(values)
        assert expected_control.issubset(values)
        assert len(TaskType) == 11

    def test_is_request_returns_true_for_task_types(self):
        """task.* 类型 is_request() 返回 True。"""
        assert TaskType.TASK_CREATE_ITINERARY.is_request() is True
        assert TaskType.TASK_REVISE_ITINERARY.is_request() is True
        assert TaskType.TASK_VALIDATE_FEASIBILITY.is_request() is True
        assert TaskType.TASK_EVALUATE_CODE.is_request() is True
        assert TaskType.TASK_EVALUATE_PLAN.is_request() is True
        assert TaskType.TASK_EVALUATE_CONTRIBUTION.is_request() is True

    def test_is_request_returns_false_for_non_task_types(self):
        """response.* / control.* 类型 is_request() 返回 False。"""
        assert TaskType.RESPONSE_RESULT.is_request() is False
        assert TaskType.RESPONSE_ERROR.is_request() is False
        assert TaskType.CONTROL_ABORT.is_request() is False

    def test_is_response_returns_true_for_response_types(self):
        """response.* 类型 is_response() 返回 True。"""
        assert TaskType.RESPONSE_ITINERARY_DRAFT.is_response() is True
        assert TaskType.RESPONSE_VALIDATION_REPORT.is_response() is True
        assert TaskType.RESPONSE_RESULT.is_response() is True
        assert TaskType.RESPONSE_ERROR.is_response() is True

    def test_is_response_returns_false_for_non_response_types(self):
        """task.* / control.* 类型 is_response() 返回 False。"""
        assert TaskType.TASK_CREATE_ITINERARY.is_response() is False
        assert TaskType.CONTROL_ABORT.is_response() is False

    def test_is_control_returns_true_for_control_abort(self):
        """CONTROL_ABORT is_control() 返回 True。"""
        assert TaskType.CONTROL_ABORT.is_control() is True

    def test_is_control_returns_false_for_others(self):
        """非 control 类型 is_control() 返回 False。"""
        assert TaskType.TASK_CREATE_ITINERARY.is_control() is False
        assert TaskType.RESPONSE_ERROR.is_control() is False

    def test_category_returns_correct_strings(self):
        """category() 返回正确的类别字符串。"""
        assert TaskType.TASK_CREATE_ITINERARY.category() == "task"
        assert TaskType.RESPONSE_RESULT.category() == "response"
        assert TaskType.CONTROL_ABORT.category() == "control"


# ============================================================
# ErrorCode
# ============================================================

class TestErrorCode:
    """ErrorCode 枚举测试。"""

    def test_all_7_values_exist(self):
        """验证 7 个错误码全部存在。"""
        names = {e.name for e in ErrorCode}
        expected = {
            "INVALID_MESSAGE", "TASK_NOT_SUPPORTED", "EXECUTION_FAILED",
            "TIMEOUT", "DATA_UNAVAILABLE", "CONSTRAINT_VIOLATION", "INTERNAL_ERROR",
        }
        assert names == expected
        assert len(list(ErrorCode)) == 7

    def test_meaning_property_returns_non_empty(self):
        """每个错误码的 meaning 属性为非空字符串。"""
        for ec in ErrorCode:
            assert isinstance(ec.meaning, str)
            assert len(ec.meaning) > 0

    def test_recoverable_correct_values(self):
        """可恢复的错误码: TIMEOUT, EXECUTION_FAILED, DATA_UNAVAILABLE。"""
        assert ErrorCode.TIMEOUT.recoverable is True
        assert ErrorCode.EXECUTION_FAILED.recoverable is True
        assert ErrorCode.DATA_UNAVAILABLE.recoverable is True
        assert ErrorCode.INVALID_MESSAGE.recoverable is False
        assert ErrorCode.CONSTRAINT_VIOLATION.recoverable is False

    def test_suggested_action_valid_values(self):
        """suggested_action 为合法值 (retry/skip/abort/revise)。"""
        valid_actions = {"retry", "skip", "abort", "revise"}
        for ec in ErrorCode:
            assert ec.suggested_action in valid_actions

    def test_retryable_codes_returns_only_recoverable(self):
        """retryable_codes() 只返回 recoverable=True 的错误码。"""
        retryable = ErrorCode.retryable_codes()
        for ec in retryable:
            assert ec.recoverable is True
        assert ErrorCode.TIMEOUT in retryable
        assert ErrorCode.EXECUTION_FAILED in retryable
        assert ErrorCode.DATA_UNAVAILABLE in retryable


# ============================================================
# AgentIdentity
# ============================================================

class TestAgentIdentity:
    """AgentIdentity 数据类测试。"""

    def test_create_valid_identity(self):
        """正常创建 AgentIdentity。"""
        identity = AgentIdentity(
            name="test", version="1.0.0",
            capabilities=["a"], endpoint="test://local", status="online",
        )
        assert identity.name == "test"
        assert identity.version == "1.0.0"
        assert identity.capabilities == ["a"]
        assert identity.endpoint == "test://local"
        assert identity.status == "online"

    def test_all_valid_statuses(self):
        """三种合法状态均可创建: online, offline, degraded。"""
        for status in ("online", "offline", "degraded"):
            identity = AgentIdentity(
                name="x", version="1.0.0",
                capabilities=[], endpoint="", status=status,
            )
            assert identity.status == status

    def test_invalid_status_raises_value_error(self):
        """无效 status 抛出 ValueError。"""
        with pytest.raises(ValueError, match="status"):
            AgentIdentity(
                name="x", version="1.0.0",
                capabilities=[], endpoint="", status="unknown",
            )

    def test_empty_name_raises_value_error(self):
        """空 name 抛出 ValueError。"""
        with pytest.raises(ValueError, match="name"):
            AgentIdentity(
                name="", version="1.0.0",
                capabilities=[], endpoint="", status="online",
            )

    def test_is_frozen(self):
        """AgentIdentity 不可修改 (frozen dataclass)。"""
        identity = AgentIdentity(
            name="x", version="1.0.0",
            capabilities=[], endpoint="", status="online",
        )
        with pytest.raises(Exception):
            identity.name = "y"  # type: ignore[misc]


# ============================================================
# HealthStatus
# ============================================================

class TestHealthStatus:
    """HealthStatus 数据类测试。"""

    def test_create_with_defaults(self):
        """使用默认值创建 HealthStatus。"""
        now = datetime.now(timezone.utc)
        hs = HealthStatus(status="healthy", last_checked=now)
        assert hs.status == "healthy"
        assert hs.last_checked == now
        assert hs.details == {}
        assert hs.message == ""

    def test_create_with_all_fields(self):
        """使用全部字段创建 HealthStatus。"""
        now = datetime.now(timezone.utc)
        hs = HealthStatus(
            status="degraded",
            last_checked=now,
            details={"cpu": 0.9},
            message="high load",
        )
        assert hs.details == {"cpu": 0.9}
        assert hs.message == "high load"


# ============================================================
# Capability
# ============================================================

class TestCapability:
    """Capability 数据类测试。"""

    def test_create_with_defaults(self):
        """默认 version 为 '1.0.0'。"""
        cap = Capability(name="test", description="a test capability")
        assert cap.name == "test"
        assert cap.description == "a test capability"
        assert cap.version == "1.0.0"

    def test_custom_version(self):
        """可指定自定义版本。"""
        cap = Capability(name="test", description="desc", version="2.0.0")
        assert cap.version == "2.0.0"

    def test_is_frozen(self):
        """Capability 不可修改 (frozen dataclass)。"""
        cap = Capability(name="test", description="desc")
        with pytest.raises(Exception):
            cap.name = "new"  # type: ignore[misc]


# ============================================================
# AgentMessage
# ============================================================

class TestAgentMessage:
    """AgentMessage 数据类测试。"""

    def test_create_valid_message(self, sample_message):
        """正常创建请求消息。"""
        assert sample_message.message_id is not None
        assert sample_message.sender is not None
        assert sample_message.receiver is not None
        assert sample_message.task_type == TaskType.TASK_CREATE_ITINERARY
        assert sample_message.payload == {"destination": "Tokyo"}
        assert sample_message.correlation_id is None

    def test_create_response_message(self, sample_response_message):
        """正常创建响应消息 (带 correlation_id)。"""
        assert sample_response_message.correlation_id is not None
        assert sample_response_message.task_type.is_response() is True

    def test_is_frozen(self, sample_message):
        """AgentMessage 不可修改 (frozen dataclass)。"""
        with pytest.raises(Exception):
            sample_message.payload = {}  # type: ignore[misc]

    # --- validate() 规则1: message_id ---

    def test_validate_passes_for_valid_message(self, sample_message):
        """合法消息 validate() 返回 AgentMessage 实例（v1.2.0 P3: 返回类型改为 AgentMessage）。"""
        result = sample_message.validate()
        assert isinstance(result, AgentMessage)
        assert result._auto_fixed is None

    def test_validate_fails_for_empty_message_id(self, sample_identity, sample_identity2):
        """空 message_id 抛出 MessageValidationError。"""
        msg = AgentMessage(
            message_id="",
            sender=sample_identity2,
            receiver=sample_identity,
            task_type=TaskType.TASK_CREATE_ITINERARY,
            payload={},
            timestamp=datetime.now(timezone.utc),
        )
        with pytest.raises(MessageValidationError, match="message_id"):
            msg.validate()

    def test_validate_fails_for_non_uuid_message_id(self, sample_identity, sample_identity2):
        """非 UUID 格式的 message_id 抛出 MessageValidationError。"""
        msg = AgentMessage(
            message_id="not-a-uuid",
            sender=sample_identity2,
            receiver=sample_identity,
            task_type=TaskType.TASK_CREATE_ITINERARY,
            payload={},
            timestamp=datetime.now(timezone.utc),
        )
        with pytest.raises(MessageValidationError, match="message_id"):
            msg.validate()

    def test_validate_fails_for_non_v4_uuid(self, sample_identity, sample_identity2):
        """非 v4 UUID 抛出 MessageValidationError。"""
        # UUID v1 (以 1 开头的时间戳版本)
        msg = AgentMessage(
            message_id="00000000-0000-1000-8000-000000000000",
            sender=sample_identity2,
            receiver=sample_identity,
            task_type=TaskType.TASK_CREATE_ITINERARY,
            payload={},
            timestamp=datetime.now(timezone.utc),
        )
        with pytest.raises(MessageValidationError, match="message_id"):
            msg.validate()

    # --- validate() 规则2: sender/receiver (without registry) ---

    def test_validate_skips_registry_check_when_none(self, sample_identity, sample_identity2):
        """无 registry 时跳过注册检查。"""
        msg = AgentMessage(
            message_id=str(uuid.uuid4()),
            sender=sample_identity2,
            receiver=sample_identity,
            task_type=TaskType.TASK_CREATE_ITINERARY,
            payload={},
            timestamp=datetime.now(timezone.utc),
        )
        assert isinstance(msg.validate(registry=None), AgentMessage)

    # --- validate() 规则3: task_type ---

    def test_validate_not_needed_for_valid_task_type(self, sample_identity, sample_identity2):
        """合法的 TaskType 枚举值通过校验。"""
        for tt in TaskType:
            msg = AgentMessage(
                message_id=str(uuid.uuid4()),
                sender=sample_identity2,
                receiver=sample_identity,
                task_type=tt,
                payload={},
                timestamp=datetime.now(timezone.utc),
                correlation_id=str(uuid.uuid4()) if tt.is_response() else None,
            )
            # 不应抛出异常
            msg.validate()

    # --- validate() 规则4: timestamp ---

    def test_validate_auto_fixes_old_timestamp(self, sample_identity, sample_identity2):
        """v1.2.0 P3: 仅 timestamp 偏差时可自动修复，返回修正后消息。"""
        old_time = datetime.now(timezone.utc) - timedelta(minutes=10)
        msg = AgentMessage(
            message_id=str(uuid.uuid4()),
            sender=sample_identity2,
            receiver=sample_identity,
            task_type=TaskType.TASK_CREATE_ITINERARY,
            payload={},
            timestamp=old_time,
        )
        fixed = msg.validate()
        assert isinstance(fixed, AgentMessage)
        assert fixed._auto_fixed is not None
        assert "timestamp_corrected_to_utc_now" in fixed._auto_fixed
        # 修复后 timestamp 应在容差范围内
        diff = abs(datetime.now(timezone.utc) - fixed.timestamp)
        assert diff < TIMESTAMP_TOLERANCE

    def test_validate_auto_fixes_future_timestamp(self, sample_identity, sample_identity2):
        """v1.2.0 P3: 仅 timestamp 偏差时可自动修复。"""
        future_time = datetime.now(timezone.utc) + timedelta(minutes=10)
        msg = AgentMessage(
            message_id=str(uuid.uuid4()),
            sender=sample_identity2,
            receiver=sample_identity,
            task_type=TaskType.TASK_CREATE_ITINERARY,
            payload={},
            timestamp=future_time,
        )
        fixed = msg.validate()
        assert isinstance(fixed, AgentMessage)
        assert fixed._auto_fixed is not None
        assert "timestamp_corrected_to_utc_now" in fixed._auto_fixed

    def test_validate_passes_for_timestamp_within_tolerance(self, sample_identity, sample_identity2):
        """容差范围内的时间戳通过校验。"""
        within = datetime.now(timezone.utc) - timedelta(minutes=3)
        msg = AgentMessage(
            message_id=str(uuid.uuid4()),
            sender=sample_identity2,
            receiver=sample_identity,
            task_type=TaskType.TASK_CREATE_ITINERARY,
            payload={},
            timestamp=within,
        )
        assert isinstance(msg.validate(), AgentMessage)

    # --- validate() 规则5: correlation_id ---

    def test_validate_auto_fixes_missing_correlation_id(self, sample_identity, sample_identity2):
        """v1.2.0 P3: 仅 correlation_id 缺失时可自动修复。"""
        msg = AgentMessage(
            message_id=str(uuid.uuid4()),
            sender=sample_identity,
            receiver=sample_identity2,
            task_type=TaskType.RESPONSE_RESULT,
            payload={},
            timestamp=datetime.now(timezone.utc),
        )
        fixed = msg.validate()
        assert isinstance(fixed, AgentMessage)
        assert fixed._auto_fixed is not None
        assert "correlation_id_auto_generated" in fixed._auto_fixed
        assert fixed.correlation_id is not None
        # 验证是合法 UUID v4
        assert uuid.UUID(fixed.correlation_id).version == 4

    def test_validate_passes_for_request_without_correlation_id(self, sample_message):
        """请求消息不需要 correlation_id，应通过校验。"""
        assert sample_message.correlation_id is None
        assert isinstance(sample_message.validate(), AgentMessage)

    def test_validate_checks_correlation_id_uuid_format(self, sample_identity, sample_identity2):
        """correlation_id 存在时校验 UUID v4 格式。"""
        msg = AgentMessage(
            message_id=str(uuid.uuid4()),
            sender=sample_identity,
            receiver=sample_identity2,
            task_type=TaskType.RESPONSE_RESULT,
            payload={},
            timestamp=datetime.now(timezone.utc),
            correlation_id="not-a-uuid",
        )
        with pytest.raises(MessageValidationError, match="correlation_id"):
            msg.validate()

    def test_validate_passes_for_response_with_valid_correlation_id(self, sample_response_message):
        """响应消息带合法 correlation_id 通过校验。"""
        assert isinstance(sample_response_message.validate(), AgentMessage)

    # --- 多违规 ---

    def test_validate_collects_multiple_violations(self, sample_identity, sample_identity2):
        """存在多个违规时 violations 列表包含全部违规项。"""
        old_time = datetime.now(timezone.utc) - timedelta(minutes=10)
        msg = AgentMessage(
            message_id="bad-id",
            sender=sample_identity2,
            receiver=sample_identity,
            task_type=TaskType.RESPONSE_RESULT,
            payload={},
            timestamp=old_time,
            correlation_id=None,
        )
        with pytest.raises(MessageValidationError) as exc_info:
            msg.validate()
        # message_id + timestamp + correlation_id = 3 violations
        assert len(exc_info.value.violations) >= 3

    def test_validate_handles_non_string_message_id(self, sample_identity, sample_identity2):
        """非字符串 message_id 不抛出 TypeError (P0 fix R1)。"""
        msg = AgentMessage(
            message_id=12345,  # type: ignore[arg-type]
            sender=sample_identity2,
            receiver=sample_identity,
            task_type=TaskType.TASK_CREATE_ITINERARY,
            payload={},
            timestamp=datetime.now(timezone.utc),
        )
        with pytest.raises(MessageValidationError, match="message_id"):
            msg.validate()

    def test_validate_handles_non_enum_task_type(self, sample_identity, sample_identity2):
        """非 TaskType 枚举 task_type 不抛出 AttributeError (P0 fix R2)。"""
        # 使用 __init__ 绕过 frozen dataclass 限制直接构造非法值
        msg = object.__new__(AgentMessage)
        object.__setattr__(msg, "message_id", str(uuid.uuid4()))
        object.__setattr__(msg, "sender", sample_identity2)
        object.__setattr__(msg, "receiver", sample_identity)
        object.__setattr__(msg, "task_type", "not_an_enum")
        object.__setattr__(msg, "payload", {})
        object.__setattr__(msg, "timestamp", datetime.now(timezone.utc))
        object.__setattr__(msg, "correlation_id", None)
        with pytest.raises(MessageValidationError):
            msg.validate()


# ============================================================
# MessageValidationError
# ============================================================

class TestMessageValidationError:
    """MessageValidationError 异常测试。"""

    def test_violations_stored(self):
        """violations 列表正确存储。"""
        err = MessageValidationError("test", ["v1", "v2"])
        assert err.violations == ["v1", "v2"]
        assert "test" in str(err)

    def test_empty_violations_allowed(self):
        """允许空的 violations 列表。"""
        err = MessageValidationError("test", [])
        assert err.violations == []


# ============================================================
# TaskExecutionError
# ============================================================

class TestTaskExecutionError:
    """TaskExecutionError 异常测试。"""

    def test_error_code_and_agent_name_stored(self):
        """error_code 和 agent_name 正确存储。"""
        err = TaskExecutionError(
            "execution failed",
            error_code=ErrorCode.EXECUTION_FAILED,
            agent_name="test_agent",
        )
        assert err.error_code == ErrorCode.EXECUTION_FAILED
        assert err.agent_name == "test_agent"

    def test_is_exception_subclass(self):
        """TaskExecutionError 是 Exception 的子类。"""
        assert issubclass(TaskExecutionError, Exception)


# ============================================================
# BaseAgent
# ============================================================

class TestBaseAgent:
    """BaseAgent ABC 测试。"""

    def test_cannot_instantiate_directly(self):
        """直接实例化 BaseAgent 抛出 TypeError。"""
        with pytest.raises(TypeError):
            BaseAgent()  # type: ignore[abstract]

    def test_concrete_subclass_can_be_instantiated(self):
        """实现了所有抽象方法的子类可以实例化。"""
        class MyAgent(BaseAgent):
            @property
            def agent_name(self) -> str:
                return "my_agent"

            @property
            def agent_version(self) -> str:
                return "1.0.0"

            async def handle_message(self, message):
                return message

            async def health_check(self):
                return HealthStatus(
                    status="healthy",
                    last_checked=datetime.now(timezone.utc),
                )

            def get_capabilities(self):
                return [Capability(name="test", description="test")]

        agent = MyAgent()
        assert agent.agent_name == "my_agent"
        assert agent.agent_version == "1.0.0"


# ============================================================
# AgentRegistry
# ============================================================

class TestAgentRegistry:
    """AgentRegistry ABC 测试。"""

    def test_cannot_instantiate_directly(self):
        """直接实例化 AgentRegistry 抛出 TypeError。"""
        with pytest.raises(TypeError):
            AgentRegistry()  # type: ignore[abstract]

    def test_concrete_subclass_requires_all_methods(self):
        """缺少任一抽象方法导致 TypeError。"""
        class PartialRegistry(AgentRegistry):
            async def register(self, agent):
                return True

        with pytest.raises(TypeError):
            PartialRegistry()  # type: ignore[abstract]


# ============================================================
# Constants
# ============================================================

class TestConstants:
    """超时与重试常量测试。"""

    def test_timeout_constants(self):
        """超时常量值与 spec 一致。"""
        assert MESSAGE_TIMEOUT == 30
        assert TOOL_TIMEOUT == 15
        assert TASK_TIMEOUT == 120
        assert HEALTH_CHECK_TIMEOUT == 5

    def test_retry_constants(self):
        """重试常量值与 spec 一致。"""
        assert MAX_RETRIES == 3
        assert RETRY_BACKOFF == [1, 2, 4]

    def test_timestamp_tolerance(self):
        """时间戳容差为 5 分钟。"""
        assert TIMESTAMP_TOLERANCE == timedelta(minutes=5)


# ============================================================
# v1.2.0 I1 — protocol_version + auto_fix 测试
# ============================================================


class TestProtocolVersion:
    """AgentMessage protocol_version 字段测试。"""

    def test_protocol_version_defaults_to_1_0(self, sample_message):
        """protocol_version 默认值 "1.0"。"""
        assert sample_message.protocol_version == "1.0"

    def test_protocol_version_preserved(self, sample_identity, sample_identity2):
        """设置 protocol_version="1.2" 后被正确保留。"""
        msg = AgentMessage(
            message_id=str(uuid.uuid4()),
            sender=sample_identity2,
            receiver=sample_identity,
            task_type=TaskType.TASK_CREATE_ITINERARY,
            payload={"destination": "Tokyo"},
            timestamp=datetime.now(timezone.utc),
            protocol_version="1.2",
        )
        assert msg.protocol_version == "1.2"

    def test_auto_fixed_initially_none(self, sample_message):
        """_auto_fixed 初始值为 None。"""
        assert sample_message._auto_fixed is None


class TestAutoFixIntegration:
    """AgentMessage.validate() 内联 auto_fix 集成测试。"""

    def test_validate_returns_same_message_when_no_issues(
        self, sample_identity, sample_identity2
    ):
        """validate() 合法的请求消息 → 返回原消息。"""
        msg = AgentMessage(
            message_id=str(uuid.uuid4()),
            sender=sample_identity2,
            receiver=sample_identity,
            task_type=TaskType.TASK_CREATE_ITINERARY,
            payload={"destination": "Tokyo"},
            timestamp=datetime.now(timezone.utc),
        )
        result = msg.validate()
        assert result is msg or (
            result.message_id == msg.message_id and result._auto_fixed is None
        )

    def test_validate_auto_fixes_old_timestamp(
        self, sample_identity, sample_identity2
    ):
        """旧 timestamp → validate() 自动修复，返回修复后消息。"""
        old_time = datetime.now(timezone.utc) - timedelta(minutes=10)
        msg = AgentMessage(
            message_id=str(uuid.uuid4()),
            sender=sample_identity2,
            receiver=sample_identity,
            task_type=TaskType.TASK_CREATE_ITINERARY,
            payload={"destination": "Tokyo"},
            timestamp=old_time,
        )
        fixed = msg.validate()
        assert fixed._auto_fixed is not None
        assert "timestamp_corrected_to_utc_now" in fixed._auto_fixed

    def test_validate_auto_fixes_missing_correlation_id(
        self, sample_identity, sample_identity2
    ):
        """响应消息缺 correlation_id → validate() 自动生成 UUID。"""
        msg = AgentMessage(
            message_id=str(uuid.uuid4()),
            sender=sample_identity,
            receiver=sample_identity2,
            task_type=TaskType.RESPONSE_RESULT,
            payload={"result": "ok"},
            timestamp=datetime.now(timezone.utc),
        )
        fixed = msg.validate()
        assert fixed._auto_fixed is not None
        assert "correlation_id_auto_generated" in fixed._auto_fixed
        assert fixed.correlation_id is not None

    def test_validate_auto_fixes_both_timestamp_and_correlation(
        self, sample_identity, sample_identity2
    ):
        """同时缺 correlation_id + 旧 timestamp → 两项均修复。"""
        old_time = datetime.now(timezone.utc) - timedelta(minutes=10)
        msg = AgentMessage(
            message_id=str(uuid.uuid4()),
            sender=sample_identity,
            receiver=sample_identity2,
            task_type=TaskType.RESPONSE_RESULT,
            payload={"result": "ok"},
            timestamp=old_time,
        )
        fixed = msg.validate()
        assert fixed._auto_fixed is not None
        fixes = fixed._auto_fixed
        assert "timestamp_corrected_to_utc_now" in fixes
        assert "correlation_id_auto_generated" in fixes
