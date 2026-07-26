"""领域工作流错误及其安全序列化。"""

from __future__ import annotations

from collections.abc import Sequence

from pydantic import BaseModel, ConfigDict, Field

from src.domain.models.enums import ErrorCategory
from src.domain.models.value_objects import StableId, TraceId


class WorkflowErrorPayload(BaseModel):
    """可安全暴露给调用方的工作流错误字段。"""

    model_config = ConfigDict(extra="forbid", frozen=True, str_strip_whitespace=True)

    trace_id: TraceId
    stage: str = Field(min_length=1, max_length=64)
    category: ErrorCategory
    code: str = Field(min_length=1, max_length=64)
    safe_message: str = Field(min_length=1, max_length=512)
    upstream_refs: tuple[StableId, ...] = ()
    retryable: bool = False


class WorkflowError(RuntimeError):
    """携带失败阶段和安全摘要的工作流异常。"""

    def __init__(
        self,
        trace_id: TraceId,
        stage: str,
        category: ErrorCategory,
        code: str,
        safe_message: str,
        *,
        upstream_refs: Sequence[StableId] = (),
        retryable: bool = False,
        cause: BaseException | None = None,
    ) -> None:
        self.payload = WorkflowErrorPayload(
            trace_id=trace_id,
            stage=stage,
            category=category,
            code=code,
            safe_message=safe_message,
            upstream_refs=tuple(upstream_refs),
            retryable=retryable,
        )
        self.cause = cause
        super().__init__(self.payload.safe_message)

    @property
    def trace_id(self) -> TraceId:
        """返回关联的 trace ID。"""
        return self.payload.trace_id

    @property
    def stage(self) -> str:
        """返回失败阶段。"""
        return self.payload.stage

    @property
    def category(self) -> ErrorCategory:
        """返回错误分类。"""
        return self.payload.category

    @property
    def retryable(self) -> bool:
        """返回是否允许由上层重试。"""
        return self.payload.retryable

    def public_payload(self) -> WorkflowErrorPayload:
        """返回不包含内部 cause 的不可变错误载荷。"""
        return self.payload
