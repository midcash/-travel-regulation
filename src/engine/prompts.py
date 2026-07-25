"""
双 LLM 对抗架构的 Prompt 模板。

设计原则：极简。A 不预设输出结构，B 专注 LLM 擅长的事。
"""
from __future__ import annotations


def build_plan_prompt(user_input: str, constraints: list[str]) -> str:
    """构建 LLM-A 的方案生成 prompt。"""
    guard_block = _build_guard_block(constraints)
    return f"""你是一个专业旅行规划师。请根据用户需求生成详细的旅行方案。

{guard_block}
## 用户需求
{user_input}

请自由输出方案，包含具体地点、时间安排、费用估算。"""


def build_review_prompt(user_input: str, plan: str, constraints: list[str]) -> str:
    """构建 LLM-B 的对抗评审 prompt。"""
    guard_block = _build_guard_block(constraints)
    return f"""你是一个严苛的旅行方案评审员。请对以下方案逐条审查。

## 用户原始需求
{user_input}

{guard_block}
## 需要评审的方案
{plan}

## 审查维度
1. 事实错误：地点是否存在？距离/交通方式是否合理？价格是否真实？
2. 逻辑矛盾：天数/时间是否正确？是否规划了用户没有空闲的时段？
3. 约束违规：用户明确排除的内容（如"不要网红店"）是否出现在方案中？
4. 安全风险：是否建议了危险活动？是否考虑了特殊人群（老人/儿童）？

## 输出格式
- 逐条列出发现的问题（附具体引用）
- 如果方案完全合理，回复 PASS"""


def build_revision_prompt(user_input: str, plan: str, issues_text: str) -> str:
    """构建修订 prompt：将 B 的反馈注入 A 的上下文。"""
    return f"""根据评审意见修改旅行方案。请彻底解决下面列出的每一个问题。

## 用户需求
{user_input}

## 原方案
{plan}

## 必须修正的问题
{issues_text}

输出修改后的完整方案。"""


def _build_guard_block(constraints: list[str]) -> str:
    """否定约束 → prompt 硬性排除指令。"""
    if not constraints:
        return ""
    items = "\n".join(f"❌ {c}" for c in constraints)
    return f"""## 🛡️ 硬性排除（绝对不得出现在方案中）
{items}

"""
