import json
import re
from src.infrastructure.deepseek_gateway import ask_llm
from src.domain.agent_state import AgentContext, AgentResult

SYSTEM_PROMPT = """你是一个专业旅行规划师。你必须严格按以下 JSON schema 输出，不得包含任何其他文字。

    ## 推理步骤（在内心完成，不要显式输出）
    1. 解析需求：目的地、天数、预算、偏好、出发地
    2. 确定锚点：往返交通方式及费用、住宿地点及费用
    3. 逐天填充：每天先放固定活动（交通/住宿），再按偏好填充景点和餐饮
    4. 约束校验：总费用 ≤ 预算，每天活动 ≤ 5 个，同天活动地理聚类
    5. 按 schema 输出
    
    ## 输出 Schema
    {{
        "reasoning": {{
          "需求解析": "",
          "锚点确定": "",
          "day1思路": "",
          "day2思路": "",
          "约束校验": "总费用≤ OK，每天活动个 OK，偏好全覆盖 OK"
        }},
        "plan": {{
            "day1": [
                {{"time": "HH:MM", "activity": "string", "cost": number, "duration_min": number}}
            ],
            "day2": [...]
        }},
        "total_cost": number,
        "budget_remaining": number,
        "preference_coverage": {{"偏好标签": ["对应的活动名称"]}}
    }}
    
    ## 硬约束
    - 总费用必须 ≤ 用户预算
    - 每天活动总时长 ≤ 600 分钟
    - 相邻活动地理距离 > 50km 时必须包含交通方式
    - preference_coverage 中每个偏好标签至少对应 1 个活动
    - 只输出一行纯 JSON，不得包含任何 markdown 标记、代码块符号、解释文字
    
    ## 用户需求
    {user_input} """


def _sanitize_json(raw: str) -> str:
    """从 LLM 原始输出中提取纯 JSON 字符串。"""
    raw = raw.strip()
    raw = re.sub(r"^```(?:json)?\s*", "", raw)
    raw = re.sub(r"\s*```$", "", raw)
    start = raw.find("{")
    end = raw.rfind("}")
    if start != -1 and end != -1 and end > start:
        raw = raw[start:end + 1]
    return raw


def _build_intent_summary(phase1_output: dict | None) -> str:
    """从 Phase1Output 构建结构化意图摘要。

    Args:
        phase1_output: Phase 1.1 产出的结构化意图数据。为 None 时返回空字符串。

    Returns:
        结构化摘要文本，可直接注入 prompt。空字符串表示无结构化数据可用。
    """
    if not phase1_output:
        return ""

    parts: list[str] = []

    dest = phase1_output.get("destination")
    if dest:
        parts.append(f"目的地: {dest}")

    origin = phase1_output.get("origin")
    if origin:
        parts.append(f"出发地: {origin}")

    days = phase1_output.get("days", 0)
    if days:
        parts.append(f"规划天数: {days}天")

    free_slots = phase1_output.get("free_time_slots", [])
    if free_slots:
        parts.append(f"可用时间段: {'、'.join(free_slots)}")

    budget = phase1_output.get("budget", 0)
    if budget:
        travelers = phase1_output.get("travelers", 1)
        parts.append(f"预算: {budget}元 ({travelers}人)")

    prefs = phase1_output.get("preferences", [])
    if prefs:
        parts.append(f"偏好: {'、'.join(prefs)}")

    trip_purpose = phase1_output.get("trip_purpose")
    if trip_purpose and trip_purpose != "未知":
        parts.append(f"出行目的: {trip_purpose}")

    intent_type = phase1_output.get("intent_type", "travel")
    if intent_type == "mixed":
        parts.append("注意: 用户为混合意图（如出差+个人休闲），仅需规划可用时间段内的活动")

    missing = phase1_output.get("missing_dimensions", [])
    if missing:
        parts.append(f"缺失信息: {'、'.join(missing)}（可合理推断或标注待确认）")

    return "\n".join(parts)


def _build_guard_block(constraints: list[str]) -> str:
    """将否定约束列表构建为 prompt 硬性排除指令块。"""
    if not constraints:
        return ""
    items = "\n".join(f"❌ {c}" for c in constraints)
    return f"""
## 🛡️ 硬性排除约束（必须遵守）
以下内容已被用户明确排除，绝对不得出现在行程中：
{items}
"""


def run(context: AgentContext) -> AgentResult:
    """根据 AgentContext 生成行程草案，返回 AgentResult。"""

    # 构建 prompt：系统 prompt + 硬性排除约束 + 用户需求 + reviewer 反馈（重试时）
    guard_block = _build_guard_block(context.negation_constraints)

    # Phase 1.1: 结构化意图摘要 + 原始输入（双输入）
    intent_summary = _build_intent_summary(context.phase1_output)
    if intent_summary:
        user_prompt = f"""## 结构化意图（解析自用户输入）
{intent_summary}

## 用户原始输入（参考语气和偏好优先级）
{context.user_input}"""
    else:
        user_prompt = context.user_input

    prompt_parts = [SYSTEM_PROMPT.format(user_input=user_prompt) + guard_block]
    if context.retry_context:
        prompt_parts.append(
            f"\n\n## 上次评审反馈（必须修正以下问题）\n{json.dumps(context.retry_context, ensure_ascii=False, indent=2)}"
        )

    raw = ask_llm("\n".join(prompt_parts))

    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError:
        # 安全打印（避免 Windows GBK 编码崩溃）
        safe = raw.encode("ascii", errors="replace").decode("ascii")
        print("===== RAW LLM OUTPUT =====")
        print(safe[:500])
        print("===== SANITIZED =====")
        sanitized = _sanitize_json(raw)
        print(sanitized.encode("ascii", errors="replace").decode("ascii")[:500])
        try:
            parsed = json.loads(sanitized)
        except json.JSONDecodeError:
            return AgentResult(
                agent="planner",
                data={},
                success=False,
                error=f"JSON 解析失败: {safe[:200]}",
            )

    return AgentResult(agent="planner", data=parsed)
