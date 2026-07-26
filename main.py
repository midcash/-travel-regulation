# 双 LLM 对抗旅行规划 CLI 入口。
from __future__ import annotations

import sys
from collections.abc import Sequence

from src.bootstrap import bootstrap_settings
from src.engine.loop import plan
from src.obs.log import get_logger

logger = get_logger(__name__)


def _print_result(result: dict) -> None:
    plan_text = result['plan']
    rounds = result['rounds']
    issues = result.get('issues_found', [])

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
        result = plan(user_input, settings=settings)
    except Exception as exc:
        logger.error(
            'plan_failed',
            error_type=type(exc).__name__,
            stage=getattr(exc, 'stage', 'unknown'),
        )
        return 1
    _print_result(result)
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
