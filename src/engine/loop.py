"""
双 LLM 对抗规划 — 主编排模块。

流程: Negation Guard → LLM-A 生成 → L1 确定性校验 → LLM-B 对抗评审 → 修订循环(≤N轮)

替代旧的 orchestrator + workflow_engine + Phase 1 pipeline 的 5 次串行调用。
"""
from __future__ import annotations

import time
from typing import TypedDict

from src.config import Settings
from src.engine.prompts import build_plan_prompt, build_revision_prompt
from src.gateway.deepseek import ask_llm
from src.guard.negation import extract_negation_constraints
from src.obs.log import get_logger
from src.obs.metric import (
    AGENT_CALLS_TOTAL,
    AGENT_DURATION_SECONDS,
    RETRY_COUNT_TOTAL,
)
from src.obs.trace import trace_agent, trace_session
from src.review.l1 import run_l1_checks
from src.review.l2 import run_l2_review

logger = get_logger(__name__)


class PlanResult(TypedDict):
    plan: str
    rounds: int
    issues_found: list[str]

MAX_REVISION_ROUNDS = 2


class PlanningError(RuntimeError):
    # 当前自由文本规划流程的显式失败。
    def __init__(self, stage: str, safe_message: str, *, retryable: bool = False) -> None:
        super().__init__(safe_message)
        self.stage = stage
        self.safe_message = safe_message
        self.retryable = retryable


def plan(
    user_input: str,
    max_rounds: int | None = None,
    settings: Settings | None = None,
) -> PlanResult:
    """双 LLM 对抗规划。

    最多 max_rounds 轮修订。每轮: L1 代码校验 → LLM-B 对抗评审 → 有问题则 A 修订。

    Args:
        user_input: 用户原始需求。
        max_rounds: 最大修订轮次；省略时读取 strict 配置。
        settings: 可注入的已校验配置。

    Returns:
        {"plan": str, "rounds": int, "issues_found": list[str]}
    """
    if settings is None:
        raise PlanningError('bootstrap', 'Settings must be provided by the composition root')
    current_settings = settings
    revision_limit = (
        current_settings.max_revision_rounds if max_rounds is None else max_rounds
    )
    if revision_limit < 0:
        raise PlanningError('configuration', '最大修订轮次不能小于 0')

    t_start = time.perf_counter()
    all_issues_found: list[str] = []

    with trace_session("default"):
        # ---- Phase 0: Negation Guard ----
        constraints = extract_negation_constraints(user_input)
        if constraints:
            logger.info("negation_guard_hit", constraints=constraints)

        # ---- Round 0: LLM-A 初始生成 ----
        logger.info("plan_generation_start")
        t_a = time.perf_counter()
        with trace_agent("planner_a", "default"):
            try:
                plan_text = ask_llm(
                    build_plan_prompt(user_input, constraints),
                    settings=current_settings,
                )
            except Exception as exc:
                raise PlanningError('generation', '初始方案生成失败') from exc
        elapsed_a = int((time.perf_counter() - t_a) * 1000)
        AGENT_CALLS_TOTAL.labels(agent="planner_a", status="success").inc()
        AGENT_DURATION_SECONDS.labels(agent="planner_a").observe(elapsed_a / 1000)
        logger.info("plan_generation_done", duration_ms=elapsed_a)

        # ---- Revision Loop ----
        for round_num in range(revision_limit + 1):
            # L1: 确定性校验
            l1_issues = run_l1_checks(plan_text, constraints)
            if l1_issues:
                logger.info("l1_issues_found", count=len(l1_issues), round=round_num)

            # L2: LLM-B 对抗评审
            try:
                l2_result = run_l2_review(
                    user_input,
                    plan_text,
                    constraints,
                    settings=current_settings,
                )
            except Exception as exc:
                raise PlanningError('review', '方案评审失败') from exc
            if not isinstance(l2_result, dict) or not isinstance(
                l2_result.get('pass'), bool
            ):
                raise PlanningError('review', '方案评审返回格式非法')

            if not l1_issues and l2_result["pass"]:
                logger.info(
                    "plan_passed_review",
                    rounds=round_num + 1,
                    total_duration_ms=int((time.perf_counter() - t_start) * 1000),
                )
                break

            # 记录发现的问题
            round_issues = l1_issues + l2_result.get("issues", [])
            all_issues_found.extend(round_issues)

            if round_num >= revision_limit:
                logger.warning(
                    "revision_rounds_exhausted",
                    max_rounds=revision_limit,
                    remaining_issues=len(round_issues),
                )
                raise PlanningError('revision', '修订轮次耗尽，方案未通过验证')

            # ---- LLM-A 修订 ----
            RETRY_COUNT_TOTAL.labels(
                agent="planner_a", reason="l2_review"
            ).inc()
            logger.info(
                "plan_revision",
                round=round_num + 1,
                issue_count=len(round_issues),
            )
            issues_text = "\n".join(
                f"{i+1}. {issue}" for i, issue in enumerate(round_issues)
            )
            t_a = time.perf_counter()
            with trace_agent("planner_a_revision", "default"):
                try:
                    plan_text = ask_llm(
                        build_revision_prompt(user_input, plan_text, issues_text),
                        settings=current_settings,
                    )
                except Exception as exc:
                    raise PlanningError('revision', '方案修订失败') from exc
            elapsed_a = int((time.perf_counter() - t_a) * 1000)
            AGENT_CALLS_TOTAL.labels(agent="planner_a", status="success").inc()
            AGENT_DURATION_SECONDS.labels(agent="planner_a").observe(elapsed_a / 1000)

    return {
        "plan": plan_text,
        "rounds": round_num + 1,
        "issues_found": all_issues_found,
    }
