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
    prompt_parts = [SYSTEM_PROMPT.format(user_input=context.user_input) + guard_block]
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
