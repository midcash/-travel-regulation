# 双 LLM 对抗旅行规划 CLI 入口。
from __future__ import annotations

import sys
from collections.abc import Sequence
from uuid import uuid4

from src.application.interaction_facade import TripInteractionFacade, TripInteractionResult
from src.application.use_cases.plan_trip import PlanTripResult, PlanTripUseCase
from src.bootstrap import bootstrap_settings
from src.domain.models.trip_request import TravelerProfile, TripRequest
from src.obs.errors import from_exception
from src.obs.log import configure_logging, get_logger
from src.obs.trace import configure_console_span_exporter

_DEFAULT_PLAN_TRIP_USE_CASE = PlanTripUseCase

logger = get_logger(__name__)


def _print_result(result: PlanTripResult | TripInteractionResult) -> None:
    if isinstance(result, TripInteractionResult):
        _print_interaction_result(result)
        return

    plan_text = result.plan
    rounds = result.rounds
    issues = result.issues_found

    print('\n' + '=' * 60)
    print(plan_text)
    print('=' * 60)

    # 日志只记录计数，避免泄露完整方案或评审文本。
    logger.info(
        'plan_summary',
        rounds=rounds,
        plan_chars=len(plan_text),
        issues_found=len(issues),
    )

    if issues:
        print(f'\n[WARN] 评审发现 {len(issues)} 个问题（已尝试修正）:')
        for issue in issues[:5]:
            print(f'  - {issue[:120]}')
    else:
        print('\n[PASS] 方案通过评审')



def _print_interaction_result(result: TripInteractionResult) -> None:
    """以 CLI 可读形式展示 M2 路由结果，不泄露原始输入。"""
    decision = result.route_decision
    if result.plan_result is not None:
        _print_result(result.plan_result)
        return

    print('\n' + '=' * 60)
    print(f'路由：{decision.mode}')
    print(f'状态：{result.state.status.value}（版本 {result.state.version}）')
    if result.clarification is not None:
        print('\n需要补充的信息：')
        for question in result.clarification.questions:
            print(f'  - {question.question}')
    if result.plan_result is None and result.clarification is None:
        print('当前请求已完成路由，未在 M2 执行外部旅行工具。')
    print('=' * 60)
    logger.info(
        'interaction_summary',
        route_mode=decision.mode,
        state=result.state.status.value,
        state_version=result.state.version,
        blockers=len(result.readiness.blockers),
    )


def main(argv: Sequence[str] | None = None) -> int:
    # 支持命令行参数或内置测试用例。
    arguments = list(sys.argv[1:] if argv is None else argv)
    if arguments:
        user_input = ' '.join(arguments)
    else:
        user_input = (
            '下周二到周四去深圳出差，其中周三下午和晚上有空闲，'
            '预算2000元用于个人休闲，喜欢科技和创意园区。'
        )

    request = _build_cli_request(user_input)
    trace_id = f"cli:{request.trip_id}:{request.request_id}"
    try:
        settings = bootstrap_settings()
        configure_logging(settings.log_level)
        configure_console_span_exporter(settings.console_span_exporter)
        logger.info('start', input_chars=len(user_input), trace_id=trace_id)
        use_case = PlanTripUseCase(settings)
        if isinstance(use_case, _DEFAULT_PLAN_TRIP_USE_CASE):
            result = TripInteractionFacade(
                settings,
                planner=use_case,
            ).execute(request, user_input)
        else:
            # 保留已有测试和外部调用方替换 PLAN Facade 的兼容入口。
            result = use_case.execute(request)
    except Exception as exc:
        failure = from_exception(exc, trace_id=trace_id)
        logger.error('workflow_failed', **failure.event_fields())
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

    M1 尚未实现自然语言解析，因此原始文本作为偏好保留给兼容 Facade，
    由后续阶段的解释器负责提取目的地、日期和约束。
    """
    request_token = uuid4().hex
    return TripRequest(
        request_id=f'cli-request:{request_token}',
        trip_id=f'cli-trip:{request_token}',
        session_id=f'cli-session:{request_token}',
        origin='cli',
        destinations=('cli-request',),
        duration_days=1,
        travelers=TravelerProfile(adults=1),
        preferences=(user_input,),
        raw_input_ref=f'cli-input:{request_token}',
    )


if __name__ == '__main__':
    raise SystemExit(main())
