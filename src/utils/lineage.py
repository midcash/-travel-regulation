"""
Hermes Lineage 压缩模块。

当对话超过 Token 预算时，对历史阶段输出进行摘要压缩，
保留关键决策信息，丢弃冗余细节。防止长对话（如 30 天行程）
和多轮重试导致 Token 窗口溢出。

此为基础版，后续 Phase 根据实际场景迭代压缩策略。

用法:
    from src.utils.lineage import compress
    compact = compress(phase_output, target_ratio=0.3)
"""

from __future__ import annotations

# 压缩时必须保留的顶层字段（即使超过 target_ratio 也不丢弃）
_PRESERVE_KEYS = frozenset({
    "intent_type",
    "destination",
    "origin",
    "check_in",
    "check_out",
    "days",
    "budget",
    "travelers",
    "trip_purpose",
    "negation_constraints",
    "confidence",
    "pace_mode",
})

# plan 内每个 activity 被压缩后保留的字段
_ACTIVITY_KEEP_KEYS = frozenset({"time", "activity", "duration_min"})


def compress(phase_output: dict, target_ratio: float = 0.3) -> dict:
    """压缩阶段输出，减少 Token 占用。

    保留关键决策字段（intent / destination / budget / constraints），
    压缩 plan 中的 activity 详情（丢弃 cost / notes，仅保留时间+名称+时长）。

    Args:
        phase_output: 原始阶段输出 dict。
        target_ratio: 目标压缩比（0.0~1.0），当前占位参数，基础版不考虑精确比。

    Returns:
        压缩后的 dict。
    """
    if not phase_output:
        return {}

    result: dict = {}

    # 第一遍：保留关键字段
    for key in _PRESERVE_KEYS:
        if key in phase_output:
            result[key] = phase_output[key]

    # 第二遍：保留简单值字段
    for key, value in phase_output.items():
        if key in result:
            continue
        if isinstance(value, (str, int, float, bool, type(None))):
            result[key] = value

    # 压缩 plan → 每个 activity 仅保留 time + activity + duration_min
    plan = phase_output.get("plan", {})
    if isinstance(plan, dict) and plan:
        compact_plan: dict[str, list[dict]] = {}
        for day, activities in plan.items():
            if not isinstance(activities, list):
                compact_plan[day] = activities
                continue
            compact_activities: list[dict] = []
            for act in activities:
                if not isinstance(act, dict):
                    compact_activities.append(act)
                    continue
                compact_act = {
                    k: v for k, v in act.items()
                    if k in _ACTIVITY_KEEP_KEYS
                }
                compact_activities.append(compact_act)
            compact_plan[day] = compact_activities
        result["plan"] = compact_plan
        result["_compressed"] = True  # 标记：已被压缩

    # 列表类型字段（issues / violations / preferences）— 保留但限制长度
    for list_key in ("issues", "violations", "preferences", "negation_constraints"):
        if list_key in phase_output and isinstance(phase_output[list_key], list):
            result[list_key] = phase_output[list_key][:10]

    return result
