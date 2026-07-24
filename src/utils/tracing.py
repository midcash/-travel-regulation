"""
OpenTelemetry 追踪模块。

配置 TracerProvider + ConsoleSpanExporter，封装 Phase/Agent/LLM 三级 Span 工具函数。
Span 层级自动嵌套（基于 OTel context propagation），无需手动传 parent。

当前阶段：Span 输出到 Console（stderr），不做远端导出。
远期：切换为 OTLPSpanExporter → Arize Phoenix 或 Langfuse。

用法:
    from src.utils.tracing import trace_phase, trace_agent, trace_llm_call

    with trace_phase(4, session_id) as span:
        span.set_attribute("agent", "planner")
        with trace_agent("planner", session_id):
            with trace_llm_call("deepseek-chat") as llm_span:
                llm_span.set_attribute("gen_ai.usage.input_tokens", 300)
"""

from __future__ import annotations

import sys
from contextlib import contextmanager
from typing import Iterator

from opentelemetry import trace
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor, ConsoleSpanExporter
from opentelemetry.sdk.resources import Resource

# ---- 全局配置 ----
_resource = Resource.create({"service.name": "travel-planner-agent"})
_provider = TracerProvider(resource=_resource)
# Span 输出到 stderr，与 stdout 的 structlog 日志分离
_provider.add_span_processor(BatchSpanProcessor(ConsoleSpanExporter(out=sys.stderr)))
trace.set_tracer_provider(_provider)

_tracer = trace.get_tracer(__name__)


@contextmanager
def trace_session(session_id: str) -> Iterator[trace.Span]:
    """创建 Session 根 Span。所有 Phase Span 必须是此 Span 的子节点。

    必须在 orchestrator 最外层调用，确保全流程共享同一个 trace_id。

    Args:
        session_id: 会话 ID。

    Yields:
        根 Span。
    """
    with _tracer.start_as_current_span(
        "session",
        attributes={"session_id": session_id},
    ) as span:
        yield span


@contextmanager
def trace_phase(phase: int, session_id: str) -> Iterator[trace.Span]:
    """创建 Phase 级别的 Span 上下文管理器。

    Args:
        phase: 阶段编号 (1-8)。
        session_id: 会话 ID。

    Yields:
        当前 Span，可调用 span.set_attribute() 追加属性。
    """
    with _tracer.start_as_current_span(
        f"phase_{phase}",
        attributes={"session_id": session_id, "phase": phase},
    ) as span:
        yield span


@contextmanager
def trace_agent(agent_name: str, session_id: str) -> Iterator[trace.Span]:
    """创建 Agent 级别的 Span 上下文管理器。

    Args:
        agent_name: Agent 名称 (planner / knowledge / reviewer)。
        session_id: 会话 ID。

    Yields:
        当前 Span，可调用 span.set_attribute() 追加属性。
    """
    with _tracer.start_as_current_span(
        f"agent.{agent_name}",
        attributes={"agent": agent_name, "session_id": session_id},
    ) as span:
        yield span


@contextmanager
def trace_llm_call(model: str, provider: str = "deepseek") -> Iterator[trace.Span]:
    """创建 LLM 调用级别的 Span 上下文管理器。

    使用 OpenInference gen_ai 语义规范。

    Args:
        model: 模型名 (deepseek-chat / deepseek-v4-flash / ...)。
        provider: LLM 提供商。

    Yields:
        当前 Span，调用方应设置 gen_ai.usage.* 和 gen_ai.response.* 属性。
    """
    with _tracer.start_as_current_span(
        "gen_ai.chat",
        attributes={
            "gen_ai.system": provider,
            "gen_ai.operation.name": "chat",
            "gen_ai.request.model": model,
        },
    ) as span:
        yield span
