"""
Workflow Engine — 确定性状态机，替代 LLM 路由决策。

流程: Planner → Knowledge → Planner Refinement → Reviewer
       ┌──────────────────────────────────────────────┘
       │ 多信号决策（hard_checks + verdict + score）
       │ 需重试 → RetryRouter → max 3 次 → EXHAUSTED
       │ 通过 → FINISH
"""
from __future__ import annotations

from src.domain.agent_state import WorkflowState, AgentContext, AgentResult

MAX_RETRIES = 3


class WorkflowEngine:
    """确定性工作流引擎。管理 Agent 调度、状态写入、重试路由。"""

    def __init__(self, state: WorkflowState, agent_registry: dict):
        self.state = state
        self.agents = agent_registry  # {"planner": fn, "knowledge": fn, "reviewer": fn}

    # ============================================================
    # 内部方法
    # ============================================================

    def _call_agent(
        self, agent_name: str, upstream_data: dict, retry_context: dict | None = None
    ) -> AgentResult:
        """构建 AgentContext 并调用 Agent。"""
        ctx = AgentContext(
            session_id=self.state.session_id,
            user_input=self.state.user_input,
            upstream_data=upstream_data,
            retry_context=retry_context,
            negation_constraints=self.state.negation_constraints,  # 🛡️ Phase 1
        )
        print(f"[ENGINE] → {agent_name}")
        return self.agents[agent_name](ctx)

    def _checkpoint(self):
        """保存当前状态快照（保留最近 3 个）。"""
        snap = self.state.model_dump()
        self.state.checkpoints.append(snap)
        if len(self.state.checkpoints) > 3:
            self.state.checkpoints = self.state.checkpoints[-3:]

    def _rollback(self, target: str):
        """重试前清除目标 Agent 及其下游的所有产出。"""
        order = ["planner", "knowledge", "planner_refinement", "reviewer"]
        if target not in order:
            return
        idx = order.index(target)
        if idx <= order.index("planner"):
            self.state.plan = None
            self.state.knowledge_data = None
            self.state.refined_plan = None
            self.state.review_result = None
        elif idx <= order.index("knowledge"):
            self.state.knowledge_data = None
            self.state.refined_plan = None
            self.state.review_result = None
        elif idx <= order.index("planner_refinement"):
            self.state.refined_plan = None
            self.state.review_result = None

    def _should_retry(self, review: dict) -> bool:
        """综合 hard_checks + verdict + score 判断是否需要重试。"""
        hard = review.get("hard_checks", {})
        verdict = review.get("quality_scores", {}).get("verdict", "")
        score = review.get("quality_scores", {}).get("composite_score", 0)

        # 硬约束未通过 → 必须重试
        if not hard.get("passed", True):
            return True

        # LLM 判定不合格 → 重试
        if verdict == "REJECT":
            return True

        # LLM 判定需修改且分数不够高 → 重试
        if verdict == "REVISE" and score < 80:
            return True

        return False

    # 硬规则 rule → 重试目标 映射表（确定性路由）
    RULE_TO_TARGET = {
        "budget_overflow":          "knowledge",
        "budget_buffer_low":        "knowledge",
        "empty_plan":               "planner",
        "insufficient_activities":  "planner",
        "invalid_day_structure":    "planner",
        "missing_departure":        "planner",
        "missing_return_transport": "planner",
        "daily_duration_overflow":  "planner_refinement",
        "daily_duration_high":      "planner_refinement",
        "missing_activity_fields":  "planner_refinement",
        "time_conflict":            "planner_refinement",
    }

    def _classify_failure(self, review: dict) -> str:
        """根据 Reviewer 返回的 issues 判断失败类型，决定重试目标。

        优先使用 hard_checks.violations[].rule 做结构化路由，
        LLM issues 关键词匹配作为 fallback。
        """
        # ---- 第一层：硬规则结构化路由 ----
        violations = review.get("hard_checks", {}).get("violations", [])
        if violations:
            # blocking 优先，取第一条可匹配的 rule
            sorted_v = sorted(violations, key=lambda v: (0 if v.get("severity") == "blocking" else 1))
            for v in sorted_v:
                rule = v.get("rule", "")
                target = self.RULE_TO_TARGET.get(rule)
                if target:
                    print(f"[ENGINE] structured route: {rule} → {target}")
                    return target

        # ---- 第二层：LLM issues 关键词 fallback ----
        issues = review.get("issues", [])
        text = " ".join(
            i.get("category", "") + " " + i.get("evidence", "") + " " + i.get("fix_suggestion", "")
            for i in issues
        ).lower()

        # 可行性失败 → Knowledge 重新查询
        feasibility_keywords = [
            "budget", "price", "cost", "费用", "价格", "预算",
            "time_conflict", "时间", "地理", "distance", "duration",
            "feasibility", "fea",
        ]
        if any(kw in text for kw in feasibility_keywords):
            return "knowledge"

        # 完整性失败 → Planner 重新生成
        completeness_keywords = [
            "missing", "empty", "缺失", "empty_plan", "字段", "format",
            "completeness", "com",
        ]
        if any(kw in text for kw in completeness_keywords):
            return "planner"

        # 体验失败 → Planner Refinement 调整
        experience_keywords = [
            "experience", "exp", "节奏", "多样性", "个性化", "variety",
            "activity", "活动", "quality",
        ]
        if any(kw in text for kw in experience_keywords):
            return "planner_refinement"

        # 默认 → Planner（从头重来最安全）
        return "planner"

    # ============================================================
    # 主流程
    # ============================================================

    def run(self) -> WorkflowState:
        """执行完整 Workflow，返回最终 State。"""

        retry_feedback = None  # 在 rollback 前保存，避免被清空

        while self.state.retry_count <= MAX_RETRIES:
            # ---- Step 1: Planner ----
            retry_ctx = retry_feedback
            result = self._call_agent(
                "planner",
                upstream_data={"user_input": self.state.user_input},
                retry_context=retry_ctx,
            )
            if not result.success:
                print(f"[ENGINE] planner 失败: {result.error}")
                break
            self.state.plan = result.data
            self._checkpoint()

            # ---- Step 2: Knowledge ----
            result = self._call_agent(
                "knowledge",
                upstream_data=self.state.plan,
            )
            if not result.success:
                print(f"[ENGINE] knowledge 失败: {result.error}")
                break
            self.state.knowledge_data = result.data
            self._checkpoint()

            # ---- Step 3: Planner Refinement ----
            result = self._call_agent(
                "planner",
                upstream_data={
                    "plan": self.state.plan,
                    "knowledge_data": self.state.knowledge_data,
                    "user_input": self.state.user_input,
                },
            )
            if not result.success:
                print(f"[ENGINE] planner_refinement 失败: {result.error}")
                break
            self.state.refined_plan = result.data
            self._checkpoint()

            # ---- Step 4: Reviewer ----
            result = self._call_agent(
                "reviewer",
                upstream_data={
                    "plan": self.state.refined_plan,
                    "knowledge_data": self.state.knowledge_data,
                    "user_req": self.state.user_input,
                },
            )
            if not result.success:
                print(f"[ENGINE] reviewer 失败: {result.error}")
                break
            self.state.review_result = result.data
            self._checkpoint()

            # ---- 多信号决策 ----
            verdict = result.data.get("quality_scores", {}).get("verdict", "?")
            score = result.data.get("quality_scores", {}).get("composite_score", 0)
            hard_ok = result.data.get("hard_checks", {}).get("passed", True)
            print(f"[ENGINE] score={score} verdict={verdict} hard_checks_passed={hard_ok}")

            if not self._should_retry(result.data):
                print("[ENGINE] PASS → FINISH")
                break

            # ---- 重试 ----
            self.state.retry_count += 1
            if self.state.retry_count > MAX_RETRIES:
                print(f"[ENGINE] retry exhausted ({MAX_RETRIES} max)")
                break

            target = self._classify_failure(result.data)
            print(f"[ENGINE] retry #{self.state.retry_count} → {target}")
            self.state.retry_history.append({
                "attempt": self.state.retry_count,
                "score": score,
                "target": target,
                "issues_summary": [
                    {"category": i.get("category"), "severity": i.get("severity")}
                    for i in result.data.get("issues", [])[:3]
                ],
            })
            # 只提取 Planner 需要的结构化反馈，避免将完整 Reviewer 输出
            # （含 hard_checks/quality_scores/strengths 等元数据）传给 Planner，
            # 防止信息过载 + 旧 plan 引用失效导致 LLM 输出不稳定。
            review_data = result.data
            retry_feedback = {
                "retry_target": target,
                "weak_dimensions": [
                    {"dim": k, "score": v.get("score"), "reasoning": v.get("reasoning")}
                    for k, v in review_data.get("quality_scores", {}).items()
                    if isinstance(v, dict) and v.get("score", 5) < 4
                ],
                "blocking_violations": [
                    {"rule": v.get("rule"), "detail": v.get("detail")}
                    for v in review_data.get("hard_checks", {}).get("violations", [])
                    if v.get("severity") == "blocking"
                ],
                "issues": [
                    {
                        "severity": i.get("severity"),
                        "category": i.get("category"),
                        "evidence": i.get("evidence"),
                        "fix_suggestion": i.get("fix_suggestion"),
                    }
                    for i in review_data.get("issues", [])
                ],
            }
            self._rollback(target)

        return self.state
