import json
import re
from llm_client import ask_llm

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
          "约束校验": "总费用≤ ✓，每天活动个 ✓，偏好全覆盖 ✓"
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


def run(input_text: str) -> str:
    """接收 Orchestrator 传来的需求描述，返回行程 JSON 字符串。"""
    prompt = SYSTEM_PROMPT.format(user_input=input_text)
    raw = ask_llm(prompt)

    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError:
        print("===== RAW LLM OUTPUT =====")
        print(repr(raw))          # 用 repr 可以看到隐藏字符
        print("===== SANITIZED =====")
        sanitized = _sanitize_json(raw) # 把 LLM 返回的“不干净的”JSON 字符串，清洗成一个可以被 json.loads() 直接解析的标准 JSON 字符串。
        print(repr(sanitized))
        parsed = json.loads(sanitized)

    return json.dumps(parsed, ensure_ascii=False)
