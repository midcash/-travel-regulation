"""Orchestrator — 入口层，组装 WorkflowEngine 并执行。"""
from src.domain.agent_state import WorkflowState
from src.application.workflow_engine import WorkflowEngine
from src.domain.planner import run as planner_run
from src.domain.knowledge_agent import run as knowledge_run
from src.domain.reviewer import run as reviewer_run


def run(user_input: str) -> WorkflowState:
    """使用确定性 Workflow Engine 执行旅游规划流程。"""
    state = WorkflowState(
        session_id="default",
        user_input=user_input,
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
