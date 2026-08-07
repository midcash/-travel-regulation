# 旅行规划 CLI 入口。
from __future__ import annotations

import sys
from collections.abc import Sequence
from typing import TypeAlias, cast
from uuid import uuid4

from src.application.fake_provider_workflow import FakeProviderWorkflowResult
from src.application.interaction_facade import TripInteractionFacade, TripInteractionResult
from src.application.use_cases.m4_plan import M4PlanUseCase
from src.application.use_cases.plan_trip import PlanTripResult, PlanTripUseCase
from src.bootstrap import bootstrap_settings
from src.config import Settings
from src.domain.models.trip_request import TravelerProfile, TripRequest
from src.infrastructure.persistence.in_memory import InMemoryStateRepository
from src.obs.errors import from_exception
from src.obs.log import configure_logging, get_logger
from src.obs.trace import configure_console_span_exporter
from src.ports.state_repository import StateRepository

_DEFAULT_PLAN_TRIP_USE_CASE = PlanTripUseCase

logger = get_logger(__name__)
PlanResult: TypeAlias = PlanTripResult | FakeProviderWorkflowResult


def _print_result(result: PlanResult | TripInteractionResult) -> None:
    """在展示边界输出 legacy 或 M4 的安全摘要。"""
    if isinstance(result, TripInteractionResult):
        _print_interaction_result(result)
        return
    if isinstance(result, FakeProviderWorkflowResult):
        _print_m4_result(result)
        return

    plan_text = result.plan
    rounds = result.rounds
    issues = result.issues_found

    print("\n" + "=" * 60)
    print(plan_text)
    print("=" * 60)

    # 日志只记录计数，避免泄露完整方案或评审文本。
    logger.info(
        "plan_summary",
        rounds=rounds,
        plan_chars=len(plan_text),
        issues_found=len(issues),
    )

    if issues:
        print(f"\n[WARN] 评审发现 {len(issues)} 个问题（已尝试修正）：")
        for issue in issues[:5]:
            print(f"  - {issue[:120]}")
    else:
        print("\n[PASS] 方案通过评审")


def _print_m4_result(result: FakeProviderWorkflowResult) -> None:
    """输出 M4 结构化结果，不冒充已经完成 M5 质量门。"""
    budget = result.budget.budget_breakdown.total
    print("\n" + "=" * 60)
    print("[M4] 结构化规划完成")
    print(f"方案：{result.schedule.variant}")
    print(f"候选数：{len(result.candidate_pool.candidates)}")
    print(f"排程项：{len(result.schedule.plan.items)}")
    print(f"预算：{budget.amount} {budget.currency}")
    print(f"状态：{result.orchestration.state.status.value}")
    print(f"trace_id：{result.trace_id}")
    print("说明：M4 已完成研究、候选、排程和预算；M5 质量门尚未执行。")
    print("=" * 60)
    logger.info(
        "m4_plan_summary",
        candidate_count=len(result.candidate_pool.candidates),
        schedule_item_count=len(result.schedule.plan.items),
        budget_amount=str(budget.amount),
        budget_currency=budget.currency,
        plan_variant=result.schedule.variant,
    )


def _print_interaction_result(result: TripInteractionResult) -> None:
    """以 CLI 可读形式展示 M2 路由结果，不泄露原始输入。"""
    decision = result.route_decision
    if result.plan_result is not None:
        _print_result(result.plan_result)
        return

    print("\n" + "=" * 60)
    print(f"路由：{decision.mode}")
    print(f"状态：{result.state.status.value}（版本 {result.state.version}）")
    if result.clarification is not None:
        print("\n需要补充的信息：")
        for question in result.clarification.questions:
            print(f"  - {question.question}")
    if result.plan_result is None and result.clarification is None:
        print("当前请求已完成路由，未在 M4 执行外部旅行工具。")
    print("=" * 60)
    logger.info(
        "interaction_summary",
        route_mode=decision.mode,
        state=result.state.status.value,
        state_version=result.state.version,
        blockers=len(result.readiness.blockers),
    )


def _build_cli_plan_executor(
    settings: Settings,
    *,
    state_repository: StateRepository,
) -> M4PlanUseCase | PlanTripUseCase:
    """按显式配置创建当前 CLI Use Case，不自动 fallback。"""
    if settings.workflow_use_case == "legacy":
        logger.warning("legacy_use_case_selected", workflow_use_case="legacy")
        return PlanTripUseCase(settings)
    return M4PlanUseCase.from_settings(
        settings,
        state_repository=state_repository,
    )


def main(argv: Sequence[str] | None = None) -> int:
    # 支持命令行参数或内置测试用例。
    arguments = list(sys.argv[1:] if argv is None else argv)
    if arguments:
        user_input = " ".join(arguments)
    else:
        user_input = (
            "下周二到周四去深圳出差，其中周三下午和晚上有空闲，"
            "预算2000元用于个人休闲，喜欢科技和创意园区。"
        )

    request = _build_cli_request(user_input)
    trace_id = f"cli:{request.trip_id}:{request.request_id}"
    try:
        settings = bootstrap_settings()
        configure_logging(settings.log_level)
        configure_console_span_exporter(settings.console_span_exporter)
        logger.info(
            "start",
            input_chars=len(user_input),
            trace_id=trace_id,
            workflow_use_case=settings.workflow_use_case,
        )
        state_repository = InMemoryStateRepository()
        result: PlanResult | TripInteractionResult
        use_case = _build_cli_plan_executor(
            settings,
            state_repository=state_repository,
        )
        if settings.workflow_use_case == "legacy" and not isinstance(
            use_case, _DEFAULT_PLAN_TRIP_USE_CASE
        ):
            # 保留已有测试和外部调用方替换 legacy Use Case 的兼容入口。
            result = cast(PlanTripUseCase, use_case).execute(request)
        else:
            result = TripInteractionFacade(
                settings,
                planner=use_case,
                state_repository=state_repository,
            ).execute(request, user_input)
    except Exception as exc:
        failure = from_exception(exc, trace_id=trace_id)
        logger.error("workflow_failed", **failure.event_fields())
        print(
            "工作流失败："
            f"trace_id={failure.payload.trace_id} "
            f"stage={failure.payload.stage} "
            f"code={failure.payload.code} "
            f"message={failure.payload.safe_message}",
            file=sys.stderr,
        )
        return 1
    _print_result(result)
    return 0


def _build_cli_request(user_input: str) -> TripRequest:
    """将 CLI 原始文本封装为 M1 所需的最小结构化请求。

    M2 解释器负责从原始文本提取目的地、日期和约束；CLI 不猜测缺失日期。
    """
    request_token = uuid4().hex
    return TripRequest(
        request_id=f"cli-request:{request_token}",
        trip_id=f"cli-trip:{request_token}",
        session_id=f"cli-session:{request_token}",
        origin="cli",
        destinations=("cli-request",),
        duration_days=1,
        travelers=TravelerProfile(adults=1),
        preferences=(user_input,),
        raw_input_ref=f"cli-input:{request_token}",
    )


if __name__ == "__main__":
    raise SystemExit(main())
