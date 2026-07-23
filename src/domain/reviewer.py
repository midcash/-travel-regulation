"""
ReviewerAgent — 方案B：代码硬规则 + LLM-as-Judge

Phase 1 (代码层): 硬约束校验 — 零成本、确定性、100%可靠
  - 预算溢出检测
  - 字段完整性检查
  - 每日活动数量/时长校验
  - 时间冲突检测

Phase 2 (LLM层): 5维度质量评分 + 问题诊断
  - 基于 plan_quality_rubric.md 的 COM/FEA/CON/EXP/ACC 体系
  - hard_checks 结果作为评分锚点，对抗 LLM 评分通胀
  - 每个 issue 附 evidence（引用 plan 具体字段），不虚构问题

输出: {hard_checks, quality_scores, issues, strengths}
"""
import json
import re
from src.infrastructure.deepseek_gateway import ask_llm
from src.domain.agent_state import AgentContext, AgentResult

# ============================================================
# Phase 1: 代码硬规则校验
# ============================================================

def _extract_json_blocks(text: str) -> list:
    """从文本中提取所有 JSON 对象/数组。"""
    candidates = []
    depth = 0
    start = -1
    for i, ch in enumerate(text):
        if ch in '{[':
            if depth == 0:
                start = i
            depth += 1
        elif ch in '}]':
            depth -= 1
            if depth == 0 and start >= 0:
                candidates.append(text[start:i + 1])
    return candidates


def _parse_input(input_text: str) -> tuple:
    """
    从 orchestrator 传来的输入中提取：
      - plan: planner 产出的行程 JSON
      - user_req: 用户原始需求文本
      - knowledge_data: KnowledgeAgent 的查询结果

    返回 (plan_dict, user_req_str, knowledge_dict)
    """
    full_text = input_text

    # 1. 提取 plan JSON（特征: 包含 "plan" key 和 "total_cost"）
    plan = {}
    for candidate in _extract_json_blocks(full_text):
        try:
            obj = json.loads(candidate)
            if isinstance(obj, dict) and "plan" in obj and "total_cost" in obj:
                plan = obj
                break
        except (json.JSONDecodeError, TypeError):
            continue

    # 2. 提取 KnowledgeAgent 数据（特征: 包含 "destination" 和 "transportation"）
    knowledge = {}
    for candidate in _extract_json_blocks(full_text):
        try:
            obj = json.loads(candidate)
            if isinstance(obj, dict) and "destination" in obj:
                knowledge = obj
                break
        except (json.JSONDecodeError, TypeError):
            continue

    # 3. 提取用户原始需求 — 取第一个非 JSON 的自然语言段落
    #    先去掉所有 JSON 块，剩下的第一段文本
    user_req = ""
    text_without_json = full_text
    for candidate in _extract_json_blocks(full_text):
        text_without_json = text_without_json.replace(candidate, " ")
    # 清理多余空白
    text_without_json = re.sub(r'\s+', ' ', text_without_json).strip()
    # 取 "用户需求:" 之后的部分
    req_match = re.search(r'用户需求[：:]\s*(.+?)(?:planner|knowledge|已|$)', text_without_json, re.DOTALL)
    if req_match:
        user_req = req_match.group(1).strip()
    if not user_req:
        # fallback: 直接取前 500 字符
        user_req = text_without_json[:500]

    return plan, user_req, knowledge


def _check_budget(plan: dict) -> list:
    """检查预算是否超支。"""
    violations = []
    total = plan.get("total_cost", 0)
    remaining = plan.get("budget_remaining", 0)
    user_budget = total + remaining  # 反推用户预算

    if remaining < 0:
        overshoot = abs(remaining)
        pct = round(overshoot / user_budget * 100, 1) if user_budget > 0 else 100
        violations.append({
            "rule": "budget_overflow",
            "severity": "blocking",
            "detail": f"总费用 {total} 超出预算 {user_budget} 达 {overshoot} 元 ({pct}%)",
            "evidence": f"total_cost={total}, budget_remaining={remaining} (应为 ≥0)"
        })
    elif remaining < user_budget * 0.05:
        # 缓冲不足 5%，warning
        violations.append({
            "rule": "budget_buffer_low",
            "severity": "warning",
            "detail": f"预算缓冲仅剩 {remaining} 元 ({round(remaining/user_budget*100, 1)}%)，无应急空间",
            "evidence": f"total_cost={total}, budget_remaining={remaining}"
        })

    return violations


def _check_daily_activities(plan: dict, phase1_output: dict | None = None) -> list:
    """检查每日活动的数量和时长。

    混合意图（如出差+个人休闲）时，允许部分天数无活动（出差日），
    不触发 insufficient_activities / empty_plan。
    """
    is_mixed = (
        phase1_output is not None
        and phase1_output.get("intent_type") == "mixed"
    )

    violations = []
    plan_days = plan.get("plan", {})

    if not plan_days:
        if not is_mixed:
            violations.append({
                "rule": "empty_plan",
                "severity": "blocking",
                "detail": "plan 中没有找到任何天次的活动安排",
                "evidence": "plan={}"
            })
        return violations

    for day_key in sorted(plan_days.keys()):
        activities = plan_days[day_key]
        if not isinstance(activities, list):
            violations.append({
                "rule": "invalid_day_structure",
                "severity": "blocking",
                "detail": f"{day_key} 不是有效的活动列表",
                "evidence": f"{day_key}={type(activities).__name__}"
            })
            continue

        # 检查活动数量（mixed intent 时跳过此检查——出差日允许 0 活动）
        if not is_mixed and len(activities) < 2:
            violations.append({
                "rule": "insufficient_activities",
                "severity": "blocking",
                "detail": f"{day_key} 仅有 {len(activities)} 个活动，要求每天至少 2 个",
                "evidence": f"{day_key}活动数={len(activities)}"
            })

        # 检查总时长
        total_duration = sum(
            a.get("duration_min", 0) for a in activities
            if isinstance(a, dict) and isinstance(a.get("duration_min"), (int, float))
        )
        if total_duration > 600:
            violations.append({
                "rule": "daily_duration_overflow",
                "severity": "blocking",
                "detail": f"{day_key} 活动总时长 {total_duration} 分钟 (>600 上限)",
                "evidence": f"{day_key}总时长={total_duration}min"
            })
        elif total_duration > 540:
            violations.append({
                "rule": "daily_duration_high",
                "severity": "warning",
                "detail": f"{day_key} 活动总时长 {total_duration} 分钟，接近上限 (600)，几乎没有缓冲",
                "evidence": f"{day_key}总时长={total_duration}min"
            })

        # 检查每个活动的必要字段
        for i, activity in enumerate(activities):
            if not isinstance(activity, dict):
                continue
            missing = [
                f for f in ["time", "activity", "cost", "duration_min"]
                if f not in activity or activity.get(f) in (None, "")
            ]
            if missing:
                violations.append({
                    "rule": "missing_activity_fields",
                    "severity": "warning",
                    "detail": f"{day_key} 第{i+1}个活动缺少字段: {', '.join(missing)}",
                    "evidence": f"{day_key}[{i}]={json.dumps(activity, ensure_ascii=False)[:100]}"
                })

    return violations


def _check_time_conflicts(plan: dict) -> list:
    """检查同一天内活动是否有时间重叠。"""
    violations = []

    def _time_to_minutes(t: str) -> int | None:
        """将 HH:MM 转为分钟数。"""
        m = re.match(r'(\d{1,2}):(\d{2})', str(t).strip())
        if not m:
            return None
        return int(m.group(1)) * 60 + int(m.group(2))

    plan_days = plan.get("plan", {})
    for day_key in sorted(plan_days.keys()):
        activities = plan_days[day_key]
        if not isinstance(activities, list) or len(activities) < 2:
            continue

        # 按开始时间排序
        sorted_acts = []
        for i, a in enumerate(activities):
            if not isinstance(a, dict):
                continue
            start = _time_to_minutes(a.get("time", ""))
            duration = a.get("duration_min", 0)
            if start is None:
                continue
            sorted_acts.append((start, duration, i, a.get("activity", f"活动{i+1}")))

        sorted_acts.sort()

        for i in range(len(sorted_acts) - 1):
            s1, d1, idx1, name1 = sorted_acts[i]
            s2, d2, idx2, name2 = sorted_acts[i + 1]
            end1 = s1 + d1 if d1 > 0 else s1 + 60  # 无时长默认 60min

            if end1 > s2:
                overlap = end1 - s2
                violations.append({
                    "rule": "time_conflict",
                    "severity": "blocking" if overlap > 30 else "warning",
                    "detail": f"{day_key}「{name1}」({sorted_acts[i][0]//60:02d}:{sorted_acts[i][0]%60:02d}) "
                              f"与「{name2}」({s2//60:02d}:{s2%60:02d}) 时间重叠 {overlap} 分钟",
                    "evidence": f"{day_key}[{idx1}].time={sorted_acts[i][0]//60:02d}:{sorted_acts[i][0]%60:02d}, "
                                f"{day_key}[{idx2}].time={s2//60:02d}:{s2%60:02d}"
                })

    return violations


def _check_transportation_coverage(plan: dict, phase1_output: dict | None = None) -> list:
    """检查是否有基本的交通覆盖（首日出发 + 末日返回）。

    混合意图时跳过此检查——用户的出差行程已覆盖往返交通。
    """
    is_mixed = (
        phase1_output is not None
        and phase1_output.get("intent_type") == "mixed"
    )

    violations = []
    plan_days = plan.get("plan", {})
    day_keys = sorted(plan_days.keys())

    if not day_keys:
        return violations

    if is_mixed:
        return violations  # 混合意图：不检查首末交通

    # 首日检查是否有出发交通
    first_day_activities = plan_days[day_keys[0]]
    transport_keywords = ["高铁", "飞机", "火车", "动车", "出发", "航班", "自驾", "大巴", "地铁", "打车", "出租", "公交"]
    has_departure = any(
        any(kw in a.get("activity", "") for kw in transport_keywords)
        for a in first_day_activities if isinstance(a, dict)
    )
    if not has_departure:
        violations.append({
            "rule": "missing_departure",
            "severity": "warning",
            "detail": f"{day_keys[0]} 未检测到出发交通方式（高铁/飞机/自驾等）",
            "evidence": f"{day_keys[0]}活动={[a.get('activity','') for a in first_day_activities if isinstance(a, dict)]}"
        })

    # 末日检查是否有返回交通
    if len(day_keys) >= 2:
        last_day_activities = plan_days[day_keys[-1]]
        has_return = any(
            any(kw in a.get("activity", "") for kw in transport_keywords + ["返回", "回家", "回程"])
            for a in last_day_activities if isinstance(a, dict)
        )
        if not has_return:
            violations.append({
                "rule": "missing_return_transport",
                "severity": "warning",
                "detail": f"{day_keys[-1]} 未检测到返程交通方式",
                "evidence": f"{day_keys[-1]}活动={[a.get('activity','') for a in last_day_activities if isinstance(a, dict)]}"
            })

    return violations


def _run_hard_checks(plan: dict, user_req: str = "", phase1_output: dict | None = None) -> dict:
    """运行所有代码层硬约束校验。

    Args:
        plan: Planner 产出的行程 dict。
        user_req: 用户原始需求（用于日志）。
        phase1_output: Phase 1.1 产出。mixed intent 时放宽部分校验。
    """
    all_violations = []
    all_violations.extend(_check_budget(plan))
    all_violations.extend(_check_daily_activities(plan, phase1_output))
    all_violations.extend(_check_time_conflicts(plan))
    all_violations.extend(_check_transportation_coverage(plan, phase1_output))

    blocking_count = sum(1 for v in all_violations if v["severity"] == "blocking")
    warning_count = sum(1 for v in all_violations if v["severity"] == "warning")

    return {
        "hard_checks": {
            "passed": blocking_count == 0,
            "blocking_count": blocking_count,
            "warning_count": warning_count,
            "violations": all_violations
        }
    }


# ============================================================
# Phase 2: LLM-as-Judge 质量评分
# ============================================================

REVIEWER_SYSTEM_PROMPT = """你是一个以"苛刻"著称的旅行方案评审专家。你的任务是对旅行规划方案进行纸面审查，找出所有不合理之处并给出质量评分。

## 评分体系（5维度 × 1-5分）

| 维度 | 权重 | 评分标准 |
|------|------|---------|
| 完整性 COM | 25% | 每天≥2活动？交通往返是否覆盖？每天是否有餐饮推荐？ |
| 可行性 FEA | 25% | 预算是否超支？时间是否充裕？地理路线是否合理？价格是否真实？ |
| 约束满足 CON | 25% | 硬约束100%？（预算/日期/人数）软约束≥70%？（偏好/饮食/无障碍） |
| 体验质量 EXP | 15% | 节奏是否合理？活动类型是否多样(≥3种)？个性化匹配率？是否有惊喜元素？ |
| 信息准确 ACC | 10% | 价格偏差是否<10%？是否有虚构地点/活动？数据是否与 KnowledgeAgent 查询结果一致？ |

## 评分规则

1. **先看 hard_checks 结果再打分**：代码已检测出的 blocking 问题必须在对应维度中体现为低分。
   例如 "budget_overflow" → FEA 维度最高只能 2 分
2. **每个维度给 1-5 分 + 1 句 reasoning**
3. composite_score = (COM×0.25 + FEA×0.25 + CON×0.25 + EXP×0.15 + ACC×0.10) × 20
4. **维度地板规则**：任一维度 < 2 → composite_score 上限 59

## 问题诊断要求

- 每个 issue 必须附 **evidence**（引用 "plan" 中的具体数据，如 "day1[0].cost=553"）
- 每个 issue 必须有 **concrete fix_suggestion**（可操作的修改建议，而非"请改进"）
- **禁止虚构问题**：无 evidence 的问题一律不写
- 如果 KnowledgeAgent 提供了价格数据，以 KnowledgeAgent 数据为 ground truth
- 按 severity 分类：blocking（阻断）> warning（警告）> suggestion（建议）

## 输出格式

严格按以下 JSON 输出，不要包含其他文字：

```json
{
  "quality_scores": {
    "completeness":    {"score": 4, "reasoning": "简要理由"},
    "feasibility":      {"score": 3, "reasoning": "简要理由"},
    "constraint_sat":  {"score": 4, "reasoning": "简要理由"},
    "experience":       {"score": 4, "reasoning": "简要理由"},
    "accuracy":         {"score": 5, "reasoning": "简要理由"},
    "composite_score": 83,
    "verdict": "PASS"
  },
  "issues": [
    {
      "severity": "blocking",
      "category": "budget",
      "evidence": "total_cost=3586, user_budget=3000",
      "fix_suggestion": "day2酒店从500/晚降至200/晚可节省600，或day3取消付费景点"
    }
  ],
  "strengths": [
    "行程节奏合理，day2密集和day3轻松形成对照"
  ]
}
```

verdict 取值：EXCELLENT(≥90) / PASS(80-89) / REVISE(60-79) / REJECT(<60)

## 铁律
- 你是苛刻的评审者，不要给面子分。有问题就说问题。
- 必须先列问题，再给分数。这能防止评分通胀。
- 只输出一行纯 JSON，无 markdown、无解释文字。"""


def _build_llm_prompt(plan: dict, user_req: str, knowledge_data: dict, hard_checks: dict) -> str:
    """构建 LLM 评审的用户消息。"""
    # 压缩 plan: 只保留每天活动摘要，不传完整 JSON 给 LLM（节省 token）
    plan_summary = {"total_cost": plan.get("total_cost"), "budget_remaining": plan.get("budget_remaining")}
    plan_summary["days"] = {}
    for day_key in sorted(plan.get("plan", {}).keys()):
        activities = plan["plan"][day_key]
        plan_summary["days"][day_key] = [
            {
                "time": a.get("time", ""),
                "activity": a.get("activity", ""),
                "cost": a.get("cost", 0),
                "duration_min": a.get("duration_min", 0)
            }
            for a in activities if isinstance(a, dict)
        ]

    # 压缩 knowledge: 只保留价格和目的地关键信息
    knowledge_summary = {}
    if knowledge_data:
        dest = knowledge_data.get("destination", {})
        if dest:
            knowledge_summary["destination"] = dest.get("city", "")
        knowledge_summary["hotels"] = [
            {"name": h.get("name", ""), "price_per_night": h.get("price_per_night", 0)}
            for h in knowledge_data.get("hotels", [])[:3]
        ]
        knowledge_summary["transportation"] = [
            {"type": t.get("type", ""), "from": t.get("from", ""), "to": t.get("to", ""),
             "price_range": t.get("price_range", {})}
            for t in knowledge_data.get("transportation", [])[:3]
        ]
        knowledge_summary["attractions"] = [
            {"name": a.get("name", ""), "ticket_price": a.get("ticket_price", 0)}
            for a in knowledge_data.get("attractions", [])[:5]
        ]

    prompt = f"""## 用户原始需求
{user_req}

## 代码硬约束校验结果（作为评分锚点，不可忽视）
{json.dumps(hard_checks, ensure_ascii=False, indent=2)}

## KnowledgeAgent 查询的真实数据（价格 ground truth）
{json.dumps(knowledge_summary, ensure_ascii=False, indent=2)}

## PlannerAgent 生成的方案
{json.dumps(plan_summary, ensure_ascii=False, indent=2)}

## 请按评审体系对该方案进行评分和问题诊断。
先逐条列出发现的问题（附 evidence），再给每个维度打分，最后计算 composite_score。"""
    return prompt


def _sanitize_json(raw: str) -> str:
    """从 LLM 输出中提取纯 JSON。"""
    raw = raw.strip()
    raw = re.sub(r"^```(?:json)?\s*", "", raw)
    raw = re.sub(r"\s*```$", "", raw)
    start = raw.find("{")
    end = raw.rfind("}")
    if start != -1 and end != -1 and end > start:
        raw = raw[start:end + 1]
    return raw


def _llm_review(plan: dict, user_req: str, knowledge_data: dict, hard_checks: dict) -> dict:
    """LLM 质量评分。"""
    if not plan:
        return {
            "quality_scores": {
                "completeness": {"score": 1, "reasoning": "未能从输入中解析到有效 plan JSON"},
                "feasibility": {"score": 1, "reasoning": "无 plan 数据"},
                "constraint_sat": {"score": 1, "reasoning": "无 plan 数据"},
                "experience": {"score": 1, "reasoning": "无 plan 数据"},
                "accuracy": {"score": 1, "reasoning": "无 plan 数据"},
                "composite_score": 20,
                "verdict": "REJECT"
            },
            "issues": [{
                "severity": "blocking",
                "category": "system",
                "evidence": "plan JSON 解析失败",
                "fix_suggestion": "检查 PlannerAgent 输出格式是否正确"
            }],
            "strengths": []
        }

    prompt = REVIEWER_SYSTEM_PROMPT + "\n\n" + _build_llm_prompt(plan, user_req, knowledge_data, hard_checks)
    raw = ask_llm(prompt)

    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError:
        sanitized = _sanitize_json(raw)
        try:
            parsed = json.loads(sanitized)
        except json.JSONDecodeError:
            return {
                "quality_scores": {
                    "composite_score": 0,
                    "verdict": "ERROR"
                },
                "issues": [{
                    "severity": "blocking",
                    "category": "system",
                    "evidence": "LLM JSON 解析失败",
                    "fix_suggestion": f"raw output: {raw[:300]}"
                }],
                "strengths": [],
                "llm_error": True,
                "raw_output": raw[:500]
            }

    return parsed


# ============================================================
# 主入口
# ============================================================

def run(context: AgentContext) -> AgentResult:
    """接收 AgentContext（upstream_data = {plan, knowledge_data, user_req}），返回评审结果。

    返回 AgentResult.data 包含: {hard_checks, quality_scores, issues, strengths}
    """
    # 从 context.upstream_data 提取结构化数据（替代旧的 _parse_input 文本解析）
    upstream = context.upstream_data
    plan = upstream.get("plan", {})
    user_req = upstream.get("user_req", context.user_input)
    knowledge_data = upstream.get("knowledge_data", {})
    phase1_output = upstream.get("phase1_output")  # 🔀 Phase 1.1 mixed intent 适配

    # Phase 1: 代码硬规则
    hard_checks = _run_hard_checks(plan, user_req, phase1_output)

    # Phase 2: LLM 评审
    llm_result = _llm_review(plan, user_req, knowledge_data, hard_checks)

    # 合并结果
    final = {**hard_checks, **llm_result}

    return AgentResult(agent="reviewer", data=final)
