"""双 LLM 对抗旅行规划 — CLI 入口。"""
from __future__ import annotations

import sys

from src.engine.loop import plan
from src.obs.log import get_logger

logger = get_logger(__name__)


def _print_result(result: dict) -> None:
    """输出方案和评审摘要。"""
    plan_text = result["plan"]
    rounds = result["rounds"]
    issues = result.get("issues_found", [])

    # 方案正文
    print("\n" + "=" * 60)
    print(plan_text)
    print("=" * 60)

    # 摘要
    logger.info(
        "plan_summary",
        rounds=rounds,
        plan_chars=len(plan_text),
        issues_found=len(issues),
        issues=issues[:5] if issues else [],
    )

    if issues:
        print(f"\n⚠ 评审发现 {len(issues)} 个问题（已尝试修正）:")
        for i in issues[:5]:
            print(f"  - {i[:120]}")
    else:
        print("\n✅ 方案通过评审")


if __name__ == "__main__":
    # 支持命令行参数或内置测试用例
    if len(sys.argv) > 1:
        user_input = " ".join(sys.argv[1:])
    else:
        # 默认测试用例
        user_input = (
            "下周二到周四去深圳出差，其中周三下午和晚上有空闲，"
            "预算2000元用于个人休闲，喜欢科技和创意园区。"
        )

    logger.info("start", input_chars=len(user_input))
    result = plan(user_input)
    _print_result(result)
