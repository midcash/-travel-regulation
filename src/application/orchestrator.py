"""Orchestrator — 入口层，Phase 1 意图解析 + WorkflowEngine 调度。"""
import json

from src.domain.agent_state import WorkflowState
from src.application.workflow_engine import WorkflowEngine
from src.domain.planner import run as planner_run
from src.domain.knowledge_agent import run as knowledge_run
from src.domain.reviewer import run as reviewer_run
from src.application.guards.negation_guard import extract_negation_constraints
from src.infrastructure.deepseek_gateway import ask_llm
from src.phase1.prompts import PHASE1_COT_PROMPT
from src.domain.dtos.phase1_dto import Phase1RawOutput, Phase1Output


def _sanitize_json(raw: str) -> str:
    """从 LLM 输出中提取纯 JSON 字符串。"""
    import re
    raw = raw.strip()
    raw = re.sub(r"^```(?:json)?\s*", "", raw)
    raw = re.sub(r"\s*```$", "", raw)
    start = raw.find("{")
    end = raw.rfind("}")
    if start != -1 and end != -1 and end > start:
        raw = raw[start:end + 1]
    return raw


def run(user_input: str) -> WorkflowState:
    """使用确定性 Workflow Engine 执行旅游规划流程。

    Phase 1: Negation Guard + CoT 意图解析。
    Phase 2-5: WorkflowEngine 调度 Planner → Knowledge → Planner → Reviewer。
    """
    # ---- Phase 1.0: Negation Guard ----
    negation_constraints = extract_negation_constraints(user_input)
    if negation_constraints:
        print(f"[NEGATION_GUARD] 命中: {negation_constraints}")

    # ---- Phase 1.1: CoT 意图解析 ----
    cot_prompt = PHASE1_COT_PROMPT.format(user_input=user_input)
    cot_raw = ask_llm(cot_prompt)
    try:
        cot_parsed = json.loads(cot_raw)
    except json.JSONDecodeError:
        sanitized = _sanitize_json(cot_raw)
        try:
            cot_parsed = json.loads(sanitized)
        except json.JSONDecodeError as e:
            raise RuntimeError(
                f"Phase 1 CoT 意图解析失败: JSON 解析错误: {e}\n"
                f"原始输出(前500字符): {cot_raw[:500]}"
            ) from e

    raw_output = Phase1RawOutput(**cot_parsed)
    print(f"[PHASE1] intent={raw_output.intent_type.value} "
          f"dest={raw_output.destination} days={raw_output.days} "
          f"budget={raw_output.budget} confidence={raw_output.confidence} "
          f"free_slots={raw_output.free_time_slots} missing={raw_output.missing_dimensions}")

    # ---- 合并: CoT + Negation Guard → Phase1Output ----
    # 从 preferences 中移除与 negation_constraints 子串匹配的项
    filtered_prefs = [
        p for p in raw_output.preferences
        if not any(nc in p for nc in negation_constraints)
    ]

    phase1_output = Phase1Output(
        intent_type=raw_output.intent_type,
        destination=raw_output.destination,
        origin=raw_output.origin,
        check_in=raw_output.check_in,
        check_out=raw_output.check_out,
        days=raw_output.days,
        budget=raw_output.budget,
        travelers=raw_output.travelers,
        preferences=filtered_prefs,
        trip_purpose=raw_output.trip_purpose,
        negation_constraints=negation_constraints,
        free_time_slots=raw_output.free_time_slots,
        confidence=raw_output.confidence,
        missing_dimensions=raw_output.missing_dimensions,
    )

    if phase1_output.needs_clarification:
        print(f"[PHASE1] ⚠️ 需要澄清: missing={phase1_output.missing_dimensions} "
              f"confidence={phase1_output.confidence}（继续执行，由 Planner 自行处理）")

    # ---- WorkflowEngine ----
    state = WorkflowState(
        session_id="default",
        user_input=user_input,
        negation_constraints=negation_constraints,
        phase1_output=phase1_output.model_dump(),
    )
    agents = {
        "planner": planner_run,
        "knowledge": knowledge_run,
        "reviewer": reviewer_run,
    }

    engine = WorkflowEngine(state, agents)
    final_state = engine.run()

    # 摘要输出
    review = final_state.review_result or {}
    score = review.get("quality_scores", {}).get("composite_score", 0)
    print(f"\n===== 最终结果 =====")
    print(f"评分: {score} | 重试: {final_state.retry_count}次")
    print(f"重试历史: {final_state.retry_history}")

    return final_state
