import json
from llm_client import ask_llm
from planner_agent import run as planner_run
from knowledge_agent import run as knowledge_run
from reviewer_agent import run as reviewer_run

AGENTS = {
    "planner":    "行程规划 — 根据需求生成旅行方案",
    "knowledge":   "可行性验证 — 检查价格/时间/地理逻辑",
    "reviewer":  "质量评估 — 对方案评分(0-100)并给出改进建议",
}

def call_agent(agent_name: str, input_text: str) -> str:
    """调用业务 Agent，返回结构化结果。"""

    if agent_name == "planner":
        return planner_run(input_text)

    elif agent_name == "knowledge":
        return knowledge_run(input_text)

    elif agent_name == "reviewer":
        return reviewer_run(input_text)

    else:
        return json.dumps({"error": f"未知 agent: {agent_name}"}, ensure_ascii=False)

def run(user_input):
    ctx = f"用户需求: {user_input}"
    agents_desc = "\n".join(f"- {k}: {v}" for k, v in AGENTS.items())

    for step in range(1, 6):
        print(f"\n{'='*50}")
        print(f"[STEP {step}]")
        print(f"{'='*50}")

        prompt = (
            f"""你是一个行程规划的主控 Agent，正在为一位真实用户规划行程。

            ## 用户原始需求（这是唯一的需求来源，禁止猜测或假设其他需求）
            {ctx}
            
            ## 当前已完成的步骤
            {json.dumps(ctx, ensure_ascii=False, indent=2)}
            
            ## 你的任务
            根据用户原始需求，决定下一步动作。严格按以下 JSON 格式输出，不要输出任何其他文字：
            {{
                "action": "call_agent" | "ask_user" | "finish",
                "agent": "planner"/"knowledge"/"reviewer",   // 只能从这 3 个中选择
                "input": "传给该 agent 的详细指令，必须基于用户原始需求",
                "message": "给用户的说明（仅在 ask_user 或 finish 时需要）"
            }}

            ## 调用 reviewer 的铁律
            - input 必须**原样粘贴** planner 和 knowledge 返回的原始 JSON，禁止转述为自然语言
            - 示例: "评审以下方案。\\n用户需求：xxx\\nplanner输出：{{\\"plan\\":...}}\\nknowledge输出：{{\\"destination\\":...}}"

            ## 完成标准
            当你确认已经完成 Orchestrator（解析需求+决策分发），KnowledgeAgent,PlannerAgent，ReviewerAgent 都至少调用一遍，PlannerAgent调用之前要先调用KnowledgeAgent，而且 reviewer 评分 ≥70 分时，才能输出 action=finish。
            禁止跳过任何一步。即使你凭经验认为方案可行，也必须让 knowledge 和 reviewer 验证。
            **finish 的 message 必须包含 planner 生成的完整每日行程详情，格式为：**
            Day1: 活动1, 活动2...
            Day2: 活动1, 活动2...
            然后才是评价和总结。
            如果评分 <70，则再次调用 planner 修改方案。
            
            ## 铁律（违反将导致解析失败）
            - 你必须只输出一行纯 JSON，不要包含任何其他文字、解释、markdown 标记、代码块符号。
            - 如果你的思考过程需要表达，请直接融入 JSON 的字段中（如 message 字段），不要写在 JSON 之外。
            """
        )

        raw = ask_llm(prompt)
        print(f"[DECISION] {raw}")
        try:
            d = json.loads(raw)
        except json.JSONDecodeError:
            print(f"[ERROR] JSON 解析失败")
            break

        action = d.get("action", "")
        print(ctx)
        if action == "call_agent":
            a, inp = d["agent"], d["input"]
            print(f"[CALL] agent={a} input={inp}")
            res = call_agent(a, inp)
            print(f"[RESULT] {res}")
            ctx += f"\n{a}返回: {res}"
        elif action == "ask_user":
            print(f"[ASK] {d['message']}")
            ctx += f"\n已问用户: {d['message']}\n用户回答: (确认)"
        elif action == "finish":
            print(f"[FINISH] {d.get('message', '完成')}")
            return d.get("message", "完成")
        else:
            print(f"[ERROR] 未知 action: {action}")
            break

    print(f"\n[FINISH] 达到最大步数({step}/5)")
    return "达到最大步数"
