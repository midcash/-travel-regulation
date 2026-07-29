# 双 LLM 对抗旅行规划 CLI 入口。
from __future__ import annotations

import sys
from collections.abc import Sequence
from uuid import uuid4

from src.application.use_cases.plan_trip import PlanTripResult, PlanTripUseCase
from src.bootstrap import bootstrap_settings
from src.domain.models.trip_request import TravelerProfile, TripRequest
from src.obs.log import get_logger

logger = get_logger(__name__)


def _print_result(result: PlanTripResult) -> None:
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
        print(f'\n⚠ 评审发现 {len(issues)} 个问题（已尝试修正）:')
        for issue in issues[:5]:
            print(f'  - {issue[:120]}')
    else:
        print('\n✅ 方案通过评审')


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

    logger.info('start', input_chars=len(user_input))
    try:
        settings = bootstrap_settings()
        request = _build_cli_request(user_input)
        result = PlanTripUseCase(settings).execute(request)
    except Exception as exc:
        logger.error(
            'plan_failed',
            error_type=type(exc).__name__,
            stage=getattr(exc, 'stage', 'unknown'),
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
