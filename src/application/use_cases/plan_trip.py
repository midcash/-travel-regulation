"""通过 Facade 调用 legacy planner 的规划用例。"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Protocol

from pydantic import BaseModel, ConfigDict

from src.config import Settings
from src.domain.errors import WorkflowError
from src.domain.models.enums import ErrorCategory
from src.domain.models.trip_request import TripRequest
from src.domain.models.value_objects import RequestId, SessionId, TripId
from src.engine.loop import PlanningError
from src.engine.loop import plan as legacy_plan
from src.legacy.mapper import LegacyPlanResult, map_legacy_plan_result


class LegacyPlanner(Protocol):
    """Facade 依赖的 legacy planner 最小接口。"""

    def __call__(self, user_input: str, *, settings: Settings) -> Mapping[str, object]:
        """根据兼容输入生成 legacy 结果。"""


class PlanTripResult(BaseModel):
    """规划用例对外暴露的类型化结果。"""

    model_config = ConfigDict(extra="forbid", frozen=True, str_strip_whitespace=True)

    request_id: RequestId
    trip_id: TripId
    session_id: SessionId
    plan: str
    rounds: int
    issues_found: tuple[str, ...]

    @classmethod
    def from_legacy(
        cls,
        request: TripRequest,
        legacy_result: LegacyPlanResult,
    ) -> PlanTripResult:
        """将已校验的 legacy 结果附加请求身份。"""
        return cls(
            request_id=request.request_id,
            trip_id=request.trip_id,
            session_id=request.session_id,
            plan=legacy_result.plan,
            rounds=legacy_result.rounds,
            issues_found=legacy_result.issues_found,
        )


class PlanTripUseCase:
    """以稳定应用层接口封装当前 legacy 规划流程。"""

    def __init__(
        self,
        settings: Settings,
        *,
        planner: LegacyPlanner = legacy_plan,
    ) -> None:
        self._settings = settings
        self._planner = planner

    def execute(
        self,
        request: TripRequest,
        *,
        raw_input: str | None = None,
    ) -> PlanTripResult:
        """执行一次规划并返回严格类型化结果。

        Args:
            request: 已完成 Schema 校验的旅行请求。
            raw_input: 本轮用户原始文本；未提供时使用结构化请求渲染的兼容文本。

        Returns:
            PlanTripResult: 带请求身份和 legacy 结果的类型化结果。

        Raises:
            WorkflowError: legacy 流程失败或返回结果不符合契约。
        """
        legacy_input = (
            raw_input.strip()
            if raw_input is not None
            else render_legacy_request(request)
        )
        if not legacy_input:
            raise WorkflowError(
                _facade_trace_id(request),
                "mapping",
                ErrorCategory.VALIDATION,
                "legacy_input_empty",
                "planning input must not be empty",
                retryable=False,
            )
        try:
            raw_result = self._planner(legacy_input, settings=self._settings)
            legacy_result = map_legacy_plan_result(raw_result)
        except PlanningError as exc:
            raise WorkflowError(
                _facade_trace_id(request),
                exc.stage,
                ErrorCategory.LLM,
                "legacy_planning_failed",
                exc.safe_message,
                retryable=exc.retryable,
                cause=exc,
            ) from exc
        except Exception as exc:
            raise WorkflowError(
                _facade_trace_id(request),
                "mapping",
                ErrorCategory.VALIDATION,
                "legacy_result_invalid",
                "legacy planner returned an invalid result",
                retryable=False,
                cause=exc,
            ) from exc
        return PlanTripResult.from_legacy(request, legacy_result)

    def execute_with_raw_input(
        self,
        request: TripRequest,
        raw_input: str,
    ) -> PlanTripResult:
        """Execute the compatibility planner with validated transient user text."""
        return self.execute(request, raw_input=raw_input)


def render_legacy_request(request: TripRequest) -> str:
    """将结构化请求渲染为 legacy planner 可消费的兼容文本。"""
    date_text = ""
    if request.date_range is not None:
        date_text = (
            f"日期：{request.date_range.start.isoformat()}至{request.date_range.end.isoformat()}"
        )
    elif request.duration_days is not None:
        date_text = f"天数：{request.duration_days}天"

    traveler_text = (
        f"成人{request.travelers.adults}人、儿童{request.travelers.children}人、"
        f"老人{request.travelers.seniors}人"
    )
    parts = [
        f"出发地：{request.origin}",
        f"目的地：{'、'.join(request.destinations)}",
        date_text,
        f"同行人：{traveler_text}",
    ]
    if request.budget is not None:
        budget = request.budget
        if budget.minimum is not None and budget.maximum is not None:
            parts.append(
                f"预算范围：{budget.minimum.amount}-{budget.maximum.amount}"
                f"{budget.minimum.currency}"
            )
        elif budget.maximum is not None:
            parts.append(f"预算上限：{budget.maximum.amount}{budget.maximum.currency}")
        elif budget.target is not None:
            parts.append(f"目标预算：{budget.target.amount}{budget.target.currency}")
    if request.preferences:
        parts.append(f"偏好：{'、'.join(request.preferences)}")
    if request.explicit_exclusions:
        parts.append(f"排除：{'、'.join(request.explicit_exclusions)}")
    return "；".join(part for part in parts if part)


def _facade_trace_id(request: TripRequest) -> str:
    """生成不含用户原文的稳定 Facade trace ID。"""
    return f"facade:{request.trip_id}:{request.request_id}"
