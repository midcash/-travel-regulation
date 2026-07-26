"""
L2 对抗评审器 — LLM-B。

职责：同时读取用户输入 + LLM-A 的方案，查逻辑、事实、约束、安全。
不碰 L1 的活（预算算数、关键词扫描）。
"""
from __future__ import annotations

import re
from typing import TypedDict

from src.config import Settings
from src.engine.prompts import build_review_prompt
from src.gateway.deepseek import ask_llm
from src.obs.log import get_logger

logger = get_logger(__name__)

L2ReviewResult = TypedDict(
    'L2ReviewResult',
    {'pass': bool, 'issues': list[str]},
)


def run_l2_review(
    user_input: str,
    plan_text: str,
    constraints: list[str],
    *,
    settings: Settings,
) -> L2ReviewResult:
    """LLM-B 对抗评审。

    Args:
        user_input: 用户原始需求。
        plan_text: LLM-A 生成的方案文本。
        constraints: 否定约束列表（已注入 prompt）。

    Returns:
        {"pass": bool, "issues": list[str]}
        pass=True 表示方案通过评审，无需修改。
    """
    prompt = build_review_prompt(user_input, plan_text, constraints)
    response = ask_llm(prompt, settings=settings)

    # 判断结果
    passed = "PASS" in response.upper().split("\n")[0] or (
        "未发现" in response and "问题" in response
    )

    if passed and len(response.strip()) < 20:
        # 简洁的 PASS 回复
        logger.info("l2_review_pass")
        return {"pass": True, "issues": []}

    # 检查是否实质上是 PASS（评审意见中没有具体问题）
    issues = _parse_issues(response)

    if not issues:
        logger.info("l2_review_pass")
        return {"pass": True, "issues": []}

    logger.info("l2_review_fail", issue_count=len(issues))
    return {"pass": False, "issues": issues}


def _parse_issues(response: str) -> list[str]:
    """从 LLM-B 的自由文本回复中提取问题列表。

    尝试多种启发式：
    1. 编号列表 (1. 2. 3. 或 - 或 •)
    2. 如果都不匹配，将整个响应作为一条 issue
    """
    # 如果明确说没问题
    if any(
        phrase in response
        for phrase in ["未发现逻辑问题", "未发现问题", "没有逻辑问题", "方案合理"]
    ):
        return []

    # 尝试按编号拆分
    lines = response.strip().split("\n")
    numbered = [
        re.sub(r'^[\d]+[\.\)、]\s*', '', line).strip()
        for line in lines
        if re.match(r'^[\d]+[\.\)、]', line.strip()) and len(line.strip()) > 5
    ]

    if numbered:
        return numbered

    # 尝试按 - 或 • 拆分
    dashed = [
        re.sub(r'^[-•]\s*', '', line).strip()
        for line in lines
        if line.strip().startswith(('-', '•')) and len(line.strip()) > 5
    ]

    if dashed:
        return dashed

    # Fallback: 整个响应
    if len(response.strip()) > 20:
        return [response.strip()]

    return []
