"""
L1 确定性校验器 — 纯代码，毫秒级。

对 LLM-A 的自由文本方案进行确定性检查。
L1 只做代码比 LLM 更可靠的事：关键词扫描、数字比较。
"""
from __future__ import annotations

import re


def check_negation_violations(plan_text: str, constraints: list[str]) -> list[str]:
    """扫描方案文本中是否出现了用户明确排除的内容。

    Args:
        plan_text: LLM-A 生成的方案文本。
        constraints: Negation Guard 提取的否定约束列表。

    Returns:
        违规描述列表。每个元素格式: "否定约束违规: 方案中出现「{约束词}」"
    """
    if not constraints:
        return []

    violations: list[str] = []
    for c in constraints:
        if c in plan_text:
            violations.append(f"否定约束违规: 方案中出现「{c}」")

    return violations


def check_budget(plan_text: str) -> list[str]:
    """从方案文本中提取预算和总费用，检查是否超支。

    在自由文本中搜索数字模式，尝试比对。

    Args:
        plan_text: LLM-A 生成的方案文本。

    Returns:
        违规描述列表。空列表表示未发现预算问题。
    """
    issues: list[str] = []

    # 提取预算数值 — 匹配 "预算N元" / "预算: N" / "预算 N 元"
    budget_match = re.search(r'预算[：:\s]*(\d{3,6})\s*元?', plan_text)
    budget = int(budget_match.group(1)) if budget_match else None

    if budget is None:
        return issues  # 无法提取预算，不做校验

    # 提取总费用 — 匹配 "总费用N元" / "合计N元" / "总花费N元"
    total_match = re.search(r'(?:总费用|合计|总花费|总计)[：:\s]*(\d{3,6})\s*元?', plan_text)
    total = int(total_match.group(1)) if total_match else None

    if total is None:
        return issues  # 无法提取总费用，不做校验

    if total > budget:
        overshoot = total - budget
        pct = round(overshoot / budget * 100)
        issues.append(
            f"预算超支: 总费用 {total} 元，预算 {budget} 元，超出 {overshoot} 元 ({pct}%)"
        )
    elif total > budget * 0.95:
        remaining = budget - total
        issues.append(
            f"预算缓冲不足: 仅剩 {remaining} 元 ({round(remaining/budget*100)}%)"
        )

    return issues


def run_l1_checks(plan_text: str, constraints: list[str]) -> list[str]:
    """运行所有 L1 确定性校验。

    Args:
        plan_text: LLM-A 生成的方案文本。
        constraints: Negation Guard 提取的否定约束列表。

    Returns:
        所有违规描述列表。空列表 = 通过。
    """
    issues: list[str] = []
    issues.extend(check_negation_violations(plan_text, constraints))
    issues.extend(check_budget(plan_text))
    return issues
