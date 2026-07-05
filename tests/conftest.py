"""共享 pytest fixtures。"""

import uuid
from datetime import datetime, timedelta, timezone

import pytest

from core.message import (
    AgentIdentity,
    AgentMessage,
    Capability,
    ErrorCode,
    TaskType,
)
from core.context import ContextStatus, SharedContext


@pytest.fixture
def sample_identity():
    """创建一个示例 AgentIdentity。"""
    return AgentIdentity(
        name="test_agent",
        version="1.0.0",
        capabilities=["test", "validate"],
        endpoint="test://local",
        status="online",
    )


@pytest.fixture
def sample_identity2():
    """创建第二个示例 AgentIdentity (用于 sender/receiver 配对)。"""
    return AgentIdentity(
        name="orchestrator",
        version="1.0.0",
        capabilities=["orchestrate"],
        endpoint="orch://local",
        status="online",
    )


@pytest.fixture
def sample_message(sample_identity, sample_identity2):
    """创建一个合法的请求 AgentMessage。"""
    return AgentMessage(
        message_id=str(uuid.uuid4()),
        sender=sample_identity2,
        receiver=sample_identity,
        task_type=TaskType.TASK_CREATE_ITINERARY,
        payload={"destination": "Tokyo"},
        timestamp=datetime.now(timezone.utc),
    )


@pytest.fixture
def sample_response_message(sample_identity, sample_identity2):
    """创建一个合法的响应 AgentMessage。"""
    return AgentMessage(
        message_id=str(uuid.uuid4()),
        sender=sample_identity,
        receiver=sample_identity2,
        task_type=TaskType.RESPONSE_RESULT,
        payload={"result_type": "itinerary_draft", "data": {}},
        timestamp=datetime.now(timezone.utc),
        correlation_id=str(uuid.uuid4()),
    )


@pytest.fixture
def sample_context():
    """创建一个初始状态的 SharedContext。"""
    return SharedContext()


@pytest.fixture
def populated_context():
    """创建一个已填充部分数据的 SharedContext。"""
    ctx = SharedContext()
    ctx.set_request({"destination": "Tokyo", "budget": 5000})
    ctx.set_status(ContextStatus.VALIDATING)
    ctx.set_status(ContextStatus.DECOMPOSING)
    ctx.add_log("INFO", "context initialized", "orchestrator")
    return ctx
