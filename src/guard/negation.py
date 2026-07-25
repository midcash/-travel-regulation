"""
Negation Guard — 代码级否定词提取器。

绕过 LLM 直接扫描用户输入中的中文否定句式，
提取被排除的内容作为 hard constraints 注入 Planner prompt。

依赖: 无（纯正则，零外部依赖）
被引用: orchestrator.py, workflow_engine.py
"""
from __future__ import annotations

import re

# 否定关键词列表（按长度降序排列，确保长词优先匹配）
_NEGATION_WORDS: list[str] = [
    "不喜欢", "不希望", "不考虑",
    "不要", "不想", "避免", "拒绝", "讨厌",
    "不含", "不吃", "不坐", "不去", "不逛", "不买",
    "不许", "别去", "别吃", "别买",
    "排除", "别", "禁止",
]

# 标点符号——用作约束边界的停止符
_STOP_PATTERN = re.compile(r"[，,。\.！!？?；;、\n\r]")

# 拆分连词——将复合约束项拆分为独立约束
_SPLIT_PATTERN = re.compile(r"[和、,，]|或者|以及|还有|包括")

# 约束开头的冗余动词（否定词结束后的第一个动作词，不属于约束内容）
_LEADING_VERB_PATTERN = re.compile(r"^(去|坐|吃|逛|买|看|玩|住|到|选择|安排|参加|体验)")


def _find_all_negation_positions(text: str) -> list[tuple[int, int, str]]:
    """扫描文本中所有否定词的位置。

    Args:
        text: 用户输入文本。

    Returns:
        [(起始位置, 结束位置, 否定词), ...]，按起始位置排序。
    """
    positions: list[tuple[int, int, str]] = []
    for word in _NEGATION_WORDS:
        start = 0
        while True:
            idx = text.find(word, start)
            if idx == -1:
                break
            positions.append((idx, idx + len(word), word))
            start = idx + 1  # 继续搜索后续出现
    positions.sort()
    return positions


def _remove_overlapping_positions(
    positions: list[tuple[int, int, str]],
) -> list[tuple[int, int, str]]:
    """移除重叠的否定词位置。

    当两个否定词重叠或相邻时（如 "不要" 和 "不坐" 在 "不要坐" 中），
    保留更靠前的否定词，避免重复提取导致约束前缀残留。

    Args:
        positions: 按起始位置排序的否定词位置列表。

    Returns:
        去重后的位置列表。
    """
    if len(positions) <= 1:
        return positions

    filtered = [positions[0]]
    for pos in positions[1:]:
        last_start, last_end, _ = filtered[-1]
        cur_start, _, _ = pos
        # 当前否定词起始位置在前一个否定词的覆盖范围内 → 跳过
        if cur_start <= last_end:
            continue
        filtered.append(pos)
    return filtered


def _trim_constraint(text: str) -> str:
    """清理约束文本：去空白、去首尾标点、去冗余前缀动词。"""
    text = text.strip().strip("，,。.！!？?；;、""''」」")
    # 去掉约束开头的冗余动作动词（如 "坐飞机" → "飞机"）
    text = _LEADING_VERB_PATTERN.sub("", text)
    return text.strip()


def extract_negation_constraints(text: str) -> list[str]:
    """从用户输入中提取否定约束列表。

    扫描中文否定词（不要/不想/避免/...），提取其后的约束关键词，
    以标点或下一个否定词为边界截取，并用连词（和/、/或）拆分多项目。

    Args:
        text: 用户原始输入文本。

    Returns:
        否定约束列表（去重、去空白）。若无否定词命中则返回空列表。

    Examples:
        >>> extract_negation_constraints("不要网红店，避免太辣的食物")
        ['网红店', '太辣的食物']

        >>> extract_negation_constraints("周末北京去上海两天，预算3000")
        []
    """
    if not text or not text.strip():
        return []

    positions = _find_all_negation_positions(text)
    if not positions:
        return []

    # 移除重叠的否定词位置（如"不要坐"中"不坐"与"不要"重叠）
    positions = _remove_overlapping_positions(positions)

    raw_constraints: list[str] = []

    for neg_start, neg_end, word in positions:
        # 从否定词结束位置向后提取
        segment = text[neg_end:]

        # 找到最近的停止边界（标点 或 下一个否定词）
        cut_positions: list[int] = []

        # 标点停止符
        for stop_match in _STOP_PATTERN.finditer(segment):
            cut_positions.append(stop_match.start())

        # 后续否定词（在 segment 中的相对位置）
        for other_start, _, _ in positions:
            if other_start > neg_end:
                relative = other_start - neg_end
                cut_positions.append(relative)

        if cut_positions:
            cut_at = min(cut_positions)
            segment = segment[:cut_at]

        # 清理并拆分连词
        segment = segment.strip()
        if segment:
            # 先用拆分连词切分
            parts = _SPLIT_PATTERN.split(segment)
            for part in parts:
                cleaned = _trim_constraint(part)
                if cleaned and len(cleaned) >= 1:
                    raw_constraints.append(cleaned)

    # 去重（保持顺序）
    seen: set[str] = set()
    result: list[str] = []
    for c in raw_constraints:
        if c not in seen:
            seen.add(c)
            result.append(c)

    return result
