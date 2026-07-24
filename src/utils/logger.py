"""
结构化日志模块。

基于 structlog，配置 JSON 渲染器，自动注入 OpenTelemetry trace_id/span_id。
替代所有 print() 调用。

用法:
    from src.utils.logger import get_logger
    logger = get_logger(__name__)
    logger.info("agent_started", agent="planner", session_id="default")
"""

from __future__ import annotations

import sys

import structlog

# 强制 stdout 使用 UTF-8 编码（Windows GBK 终端导致中文乱码）
if sys.stdout.encoding != "utf-8":
    sys.stdout.reconfigure(encoding="utf-8")


def _add_otel_context(
    logger: structlog.types.BindableLogger,
    method_name: str,
    event_dict: dict,
) -> dict:
    """向每条日志注入当前 OTel span 的 trace_id 和 span_id。

    若 OTel 未配置（无 TracerProvider），span.is_recording() 返回 False，
    跳过注入，不影响日志输出。
    """
    try:
        from opentelemetry import trace
    except ImportError:
        return event_dict

    span = trace.get_current_span()
    if span.is_recording():
        ctx = span.get_span_context()
        event_dict["trace_id"] = format(ctx.trace_id, "032x")
        event_dict["span_id"] = format(ctx.span_id, "016x")
    return event_dict


structlog.configure(
    processors=[
        structlog.stdlib.add_log_level,
        _add_otel_context,
        structlog.processors.TimeStamper(fmt="iso"),
        structlog.processors.JSONRenderer(ensure_ascii=False),
    ],
    wrapper_class=structlog.stdlib.BoundLogger,
    cache_logger_on_first_use=True,
)


def get_logger(name: str = __name__) -> structlog.stdlib.BoundLogger:
    """获取结构化 logger 实例。

    Args:
        name: logger 名称，通常传 __name__。

    Returns:
        配置好的 BoundLogger，所有日志以 JSON 格式输出到 stdout。
    """
    return structlog.get_logger(name)
