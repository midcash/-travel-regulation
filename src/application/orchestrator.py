"""Orchestrator — 入口层，Phase 1 意图解析 + WorkflowEngine 调度。"""
from __future__ import annotations

import time

from src.domain.agent_state import WorkflowState
from src.application.workflow_engine import WorkflowEngine
from src.domain.planner import run as planner_run
from src.domain.knowledge_agent import run as knowledge_run
from src.domain.reviewer import run as reviewer_run
from src.phase1.pipeline import run_phase1
from src.utils.logger import get_logger
from src.utils.tracing import trace_session, trace_phase

logger = get_logger(__name__)


def run(user_input: str) -> WorkflowState:
    """使用确定性 Workflow Engine 执行旅游规划流程。

    Phase 1: 双保险意图解析（Negation Guard + CoT LLM）。
    Phase 2-5: WorkflowEngine 调度 Planner → Knowledge → Planner → Reviewer。
    """
    t_start = time.perf_counter()

    with trace_session("default"):
        logger.info("orchestrator_started", input_chars=len(user_input))

        # ---- Phase 1: 意图解析 ----
        with trace_phase(1, "default"):
            phase1_output = run_phase1(user_input)

        # ---- WorkflowEngine ----
        state = WorkflowState(
            session_id="default",
            user_input=user_input,
            negation_constraints=phase1_output.negation_constraints,
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
        elapsed_ms = int((time.perf_counter() - t_start) * 1000)
        review = final_state.review_result or {}
        score = review.get("quality_scores", {}).get("composite_score", 0)
        logger.info(
            "orchestrator_finished",
            score=score,
            retry_count=final_state.retry_count,
            retry_history=final_state.retry_history,
            total_duration_ms=elapsed_ms,
        )

    return final_state
