"""Negation Guard — 单元测试。"""
from __future__ import annotations

import pytest
from src.application.guards.negation_guard import extract_negation_constraints


@pytest.mark.parametrize(
    "user_input,expected_subset",
    [
        # T06: 排除网红店
        (
            "不要网红店，避免太辣的食物",
            ["网红店", "太辣的食物"],
        ),
        # T07: 多层否定（5个约束）
        (
            "不想爬山，不要人多的地方，讨厌商业化严重的景区，拒绝跟团，不含购物点",
            ["爬山", "人多的地方", "商业化严重的景区", "跟团", "购物点"],
        ),
        # T08: 拒绝特定交通，和拆分
        (
            "不要坐飞机，拒绝红眼航班和早班高铁",
            ["飞机", "红眼航班", "早班高铁"],
        ),
        # T09: 排除历史景点
        (
            "不想去历史博物馆类景点，不要陵墓",
            ["历史博物馆类景点", "陵墓"],
        ),
        # T10: 安全/饮食限制，和+、拆分
        (
            "不吃生食和路边摊，不要危险的水上活动，避免深夜外出",
            ["生食", "路边摊", "危险的水上活动", "深夜外出"],
        ),
    ],
)
def test_extract_negation_constraints(user_input: str, expected_subset: list[str]):
    """验证否定词守卫对所有标准否定句式的正确提取。"""
    result = extract_negation_constraints(user_input)
    for expected in expected_subset:
        assert expected in result, (
            f"Missing '{expected}' in result: {result}"
        )
    # 结果不应包含多余内容（精确匹配数量）
    assert len(result) == len(expected_subset), (
        f"Count mismatch: expected {len(expected_subset)}, got {len(result)}: {result}"
    )


def test_no_negation_returns_empty():
    """常规需求不应命中否定词。"""
    result = extract_negation_constraints("周末北京去上海两天，预算3000")
    assert result == []


def test_empty_input_returns_empty():
    """空输入返回空列表。"""
    result = extract_negation_constraints("")
    assert result == []


def test_whitespace_only_returns_empty():
    """纯空白输入返回空列表。"""
    result = extract_negation_constraints("   ")
    assert result == []


def test_deduplication():
    """重复约束应去重。"""
    result = extract_negation_constraints("不要爬山，也不想爬山")
    assert result == ["爬山"]
