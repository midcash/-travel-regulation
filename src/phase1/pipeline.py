"""
Phase 1 Pipeline — 意图解析的统一入口。

封装双保险架构的完整流程:
  Phase 1.0: Negation Guard（代码正则）
  Phase 1.1: CoT LLM 意图解析

依赖: guards/negation_guard, prompts, deepseek_gateway, dtos/phase1_dto
被引用: orchestrator.py
"""
from __future__ import annotations

import json

from src.application.guards.negation_guard import extract_negation_constraints
from src.infrastructure.deepseek_gateway import ask_llm
from src.phase1.prompts import PHASE1_COT_PROMPT
from src.domain.dtos.phase1_dto import Phase1RawOutput, Phase1Output
from src.utils.json_utils import sanitize_json
from src.utils.logger import get_logger

logger = get_logger(__name__)


def run_phase1(user_input: str) -> Phase1Output:
    """执行 Phase 1 双保险意图解析。

    Step 1: Negation Guard 提取硬约束（代码正则，0ms）。
    Step 2: CoT LLM 结构化意图解析。
    Step 3: 合并 Guard 约束 + CoT 产出 → Phase1Output。

    Args:
        user_input: 用户原始输入文本。

    Returns:
        Phase1Output: 结构化意图数据，含 negation_constraints 和 free_time_slots。

    Raises:
        RuntimeError: CoT LLM 解析失败时抛出。
    """
    # ---- Phase 1.0: Negation Guard ----
    negation_constraints = extract_negation_constraints(user_input)
    if negation_constraints:
        logger.info(
            "negation_guard_hit",
            constraints=negation_constraints,
            count=len(negation_constraints),
        )

    # ---- Phase 1.1: CoT 意图解析 ----
    cot_prompt = PHASE1_COT_PROMPT.format(user_input=user_input)
    cot_raw = ask_llm(cot_prompt)
    try:
        cot_parsed = json.loads(cot_raw)
    except json.JSONDecodeError:
        sanitized = sanitize_json(cot_raw)
        try:
            cot_parsed = json.loads(sanitized)
        except json.JSONDecodeError as e:
            logger.error(
                "phase1_cot_json_parse_failed",
                error=str(e),
                raw_preview=cot_raw[:500],
            )
            raise RuntimeError(
                f"Phase 1 CoT 意图解析失败: JSON 解析错误: {e}\n"
                f"原始输出(前500字符): {cot_raw[:500]}"
            ) from e

    raw_output = Phase1RawOutput(**cot_parsed)
    logger.info(
        "phase1_cot_parsed",
        intent=raw_output.intent_type.value,
        destination=raw_output.destination,
        days=raw_output.days,
        budget=raw_output.budget,
        confidence=raw_output.confidence,
        free_time_slots=raw_output.free_time_slots,
        missing_dimensions=raw_output.missing_dimensions,
    )

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
        logger.warning(
            "phase1_needs_clarification",
            missing_dimensions=phase1_output.missing_dimensions,
            confidence=phase1_output.confidence,
        )

    return phase1_output
