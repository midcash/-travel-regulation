"""M2 ClarificationBuilder：将 G1 blocker 转为最少必要澄清问题。"""

from __future__ import annotations

from collections.abc import Iterable
from hashlib import sha256
from typing import Final

from src.domain.models.clarification import ClarificationQuestion, ClarificationRequest
from src.domain.models.readiness import ReadinessBlocker, ReadinessBlockerCode, ReadinessResult

MAX_CLARIFICATION_QUESTIONS: Final[int] = 3

_QUESTION_TEXT: Final[dict[ReadinessBlockerCode, str]] = {
    ReadinessBlockerCode.MISSING_ORIGIN: "请补充出发地。",
    ReadinessBlockerCode.MISSING_DESTINATION: "请补充目的地。",
    ReadinessBlockerCode.DATE_OR_DURATION_UNDETERMINED: "请补充出行日期范围或旅行天数。",
    ReadinessBlockerCode.DATE_DURATION_CONFLICT: "请确认出行日期范围与旅行天数，二者目前不一致。",
    ReadinessBlockerCode.DATE_RANGE_IN_PAST: "the requested trip dates are earlier than today",
    ReadinessBlockerCode.TRAVELER_COUNT_UNDETERMINED: "请确认出行人数。",
    ReadinessBlockerCode.SPECIAL_POPULATION_UNDETERMINED: (
        "请说明是否有儿童、老人、婴幼儿或无障碍需求。"
    ),
    ReadinessBlockerCode.BUDGET_SEMANTIC_CONFLICT: "请确认预算金额、币种及预算口径。",
    ReadinessBlockerCode.CONSTRAINT_CONFLICT: "请确认互斥约束中需要保留的条件。",
    ReadinessBlockerCode.ACTION_AUTHORIZATION_REQUIRED: "请完成身份认证并确认当前操作已获授权。",
    ReadinessBlockerCode.ACTION_IDENTITY_REQUIRED: "请提供已验证的操作主体身份。",
    ReadinessBlockerCode.CURRENT_PLAN_REQUIRED: "请提供可引用的当前计划。",
    ReadinessBlockerCode.MISSING_MEETING_CITY: "请补充会议城市。",
    ReadinessBlockerCode.MISSING_MEETING_LOCATION: "请补充会议地点。",
    ReadinessBlockerCode.MISSING_MEETING_START: "请补充会议开始日期和时间。",
    ReadinessBlockerCode.MISSING_MEETING_TIMEZONE: "请明确会议时区，系统不会自行推断。",
}


class ClarificationBuilder:
    """只消费 ReadinessResult，不推断额外字段或修改约束状态。"""

    def build(self, result: ReadinessResult) -> ClarificationRequest | None:
        """将 G1 blocker 稳定映射为最多三个澄清问题。

        Args:
            result: ReadinessEvaluator 产生的结构化就绪结果。

        Returns:
            ClarificationRequest | None: 存在 blocker 时返回澄清请求；已就绪时返回 None。

        Raises:
            TypeError: result 不是 ReadinessResult。
            ValueError: blocker 没有对应的确定性问题模板。
        """
        if not isinstance(result, ReadinessResult):
            raise TypeError("result must be a ReadinessResult")
        if result.ready:
            return None

        blockers = _ordered_unique_blockers(result.blockers)
        selected = blockers[:MAX_CLARIFICATION_QUESTIONS]
        questions = tuple(
            _question_for(
                result=result,
                blocker=blocker,
            )
            for blocker in selected
        )
        deferred = tuple(blocker.issue_id for blocker in blockers[MAX_CLARIFICATION_QUESTIONS:])
        return ClarificationRequest(
            trace_id=result.trace_id,
            request_id=result.request_id,
            snapshot_version=result.snapshot_version,
            mode=result.mode,
            questions=questions,
            deferred_blocker_refs=deferred,
        )


def _ordered_unique_blockers(
    blockers: Iterable[ReadinessBlocker],
) -> tuple[ReadinessBlocker, ...]:
    """按阻断优先级排序并去重，保证同一输入重复构建结果一致。"""
    unique: dict[str, ReadinessBlocker] = {}
    for blocker in blockers:
        unique.setdefault(blocker.issue_id, blocker)
    return tuple(
        sorted(
            unique.values(),
            key=lambda item: (item.priority, item.code.value, item.field, item.issue_id),
        )
    )


def _question_for(
    *,
    result: ReadinessResult,
    blocker: ReadinessBlocker,
) -> ClarificationQuestion:
    try:
        question_text = _QUESTION_TEXT[blocker.code]
    except KeyError as exc:
        raise ValueError(
            f"no clarification template for blocker code {blocker.code.value}"
        ) from exc

    digest_input = "|".join(
        (
            result.request_id,
            str(result.snapshot_version),
            result.mode.value,
            blocker.issue_id,
        )
    )
    question_id = f"clarification-{sha256(digest_input.encode()).hexdigest()[:24]}"
    return ClarificationQuestion(
        question_id=question_id,
        blocker_ref=blocker.issue_id,
        code=blocker.code,
        field=blocker.field,
        question=question_text,
        constraint_refs=blocker.constraint_refs,
        conflict_group=blocker.conflict_group,
        priority=blocker.priority,
    )
