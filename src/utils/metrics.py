"""
Prometheus 指标模块。

定义项目级 Counter / Gauge / Histogram，覆盖 Agent 调用、LLM 调用、Phase 耗时、重试。
所有指标在模块加载时注册。当前阶段值在内存中累积，不暴露 HTTP 端点（待 FastAPI 阶段）。

用法:
    from src.utils.metrics import AGENT_CALLS_TOTAL, LLM_TOKENS_TOTAL

    AGENT_CALLS_TOTAL.labels(agent="planner", status="success").inc()
    LLM_TOKENS_TOTAL.labels(model="deepseek-chat", type="input").inc(amount=300)
"""

from __future__ import annotations

from prometheus_client import Counter, Gauge, Histogram

# ---- Agent 调用指标 ----

AGENT_CALLS_TOTAL = Counter(
    "agent_calls_total",
    "Agent 调用总次数",
    ["agent", "status"],  # status: success / failure
)

AGENT_DURATION_SECONDS = Histogram(
    "agent_duration_seconds",
    "Agent 执行耗时（秒）",
    ["agent"],
    buckets=[0.1, 0.5, 1, 2, 5, 10, 30, 60],
)

# ---- LLM 调用指标 ----

LLM_CALLS_TOTAL = Counter(
    "llm_calls_total",
    "LLM API 调用总次数",
    ["model", "status"],  # status: success / failure
)

LLM_TOKENS_TOTAL = Counter(
    "llm_tokens_total",
    "LLM Token 消耗总量",
    ["model", "type"],  # type: input / output
)

LLM_DURATION_SECONDS = Histogram(
    "llm_duration_seconds",
    "LLM API 调用耗时（秒）",
    ["model"],
    buckets=[1, 2, 5, 10, 20, 30, 60, 120],
)

# ---- Phase 指标 ----

PHASE_DURATION_SECONDS = Histogram(
    "phase_duration_seconds",
    "各 Phase 执行耗时（秒）",
    ["phase"],
    buckets=[0.01, 0.1, 0.5, 1, 2, 5, 10, 30, 60],
)

# ---- 重试指标 ----

RETRY_COUNT_TOTAL = Counter(
    "retry_count_total",
    "重试总次数",
    ["agent", "reason"],
)

# ---- 工作流状态 ----

CURRENT_SESSION_GAUGE = Gauge(
    "current_session_phase",
    "当前活跃会话的阶段",
    ["session_id"],
)
