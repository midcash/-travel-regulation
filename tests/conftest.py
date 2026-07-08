"""共享 pytest fixtures — Phase 4 Batch 3 扩展。"""

import os
import uuid
from datetime import date, datetime, timedelta, timezone

import pytest


def pytest_configure(config):
    """注册自定义 marker。"""
    config.addinivalue_line(
        "markers",
        "slow: 耗时测试（真实 API 调用或完整 e2e pipeline），"
        "默认跳过。手动运行: pytest -m slow"
    )


@pytest.fixture(autouse=True)
def _disable_real_apis(monkeypatch):
    """强制测试环境使用 stub 路径，避免意外触发真实 API 调用。

    在测试期间 UNSET 所有真实 API 的环境变量，使 LLMClient/AmapClient/TuniuClient
    降级为不可用状态，Agent 自动回退 stub 路径。

    需要真实 API 的测试（如 test_real_cases.py 的慢速用例）应在测试内部
    显式设置环境变量，并标记为 @pytest.mark.slow。
    """
    for key in ("DEEPSEEK_API_KEY", "AMAP_API_KEY", "TUNIU_API_KEY"):
        monkeypatch.delenv(key, raising=False)

from core.message import (
    AgentIdentity,
    AgentMessage,
    Capability,
    ErrorCode,
    TaskType,
)
from core.context import ContextStatus, SharedContext
from models.request import (
    Budget,
    DateRange,
    Destination,
    Preferences,
    StructuredRequest,
    Travelers,
)


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


# ============================================================
# Phase 4 Batch 3 — Integration & Ablation test fixtures
# ============================================================

@pytest.fixture
def sample_destination():
    """创建一个标准 Destination (东京)。"""
    return Destination(city="东京", country="日本")


@pytest.fixture
def sample_daterange():
    """创建一个标准 DateRange (5天)。"""
    return DateRange(
        arrival="2026-12-20",
        departure="2026-12-25",
        duration_days=5,
    )


@pytest.fixture
def sample_budget():
    """创建一个标准 Budget (15000 CNY)。"""
    return Budget(total=15000, currency="CNY")


@pytest.fixture
def sample_travelers():
    """创建标准 Travelers (2 adults)。"""
    return Travelers(adults=2, children=0)


@pytest.fixture
def sample_preferences():
    """创建标准 Preferences (food + culture, moderate pace)。"""
    return Preferences(style=["food", "culture"], pace="moderate")


@pytest.fixture
def sample_request(sample_destination, sample_daterange, sample_budget, sample_travelers, sample_preferences):
    """创建一个完整的 StructuredRequest (东京5天)。"""
    return StructuredRequest(
        destination=sample_destination,
        dates=sample_daterange,
        budget=sample_budget,
        travelers=sample_travelers,
        preferences=sample_preferences,
        request_id=str(uuid.uuid4()),
    )


@pytest.fixture
def ablation_test_suite():
    """创建消融实验标准测试套件 (10 个用例, protocol §2.2)。"""
    test_configs = [
        (5, 15000, "东京"), (3, 8000, "曼谷"), (7, 30000, "巴黎"),
        (1, 500, "广州"), (14, 50000, "罗马"), (4, 6000, "成都"),
        (6, 12000, "首尔"), (2, 3000, "杭州"), (10, 40000, "伦敦"),
        (3, 10000, "新加坡"),
    ]
    return [
        {
            "id": f"TC-{i+1:03d}",
            "input": f"去{city}{days}天，预算{budget}元",
            "expected_score_min": 70,
        }
        for i, (days, budget, city) in enumerate(test_configs)
    ]


@pytest.fixture
def baseline_config():
    """标准全量 Agent 配置。"""
    return ["orchestrator", "planning_agent", "execution_agent", "evaluation_agent"]


@pytest.fixture
def ablation_configs():
    """7 种消融实验配置 (ablation_protocol.md §2.1)。"""
    return {
        "C_full":            ["orchestrator", "planning_agent", "execution_agent", "evaluation_agent"],
        "C_no_planner":      ["orchestrator", "execution_agent", "evaluation_agent"],
        "C_no_executor":     ["orchestrator", "planning_agent", "evaluation_agent"],
        "C_no_evaluator":    ["orchestrator", "planning_agent", "execution_agent"],
        "C_planner_only":    ["orchestrator", "planning_agent"],
        "C_executor_only":   ["orchestrator", "execution_agent"],
        "C_orch_only":       ["orchestrator"],
    }
