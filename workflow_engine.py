"""
Workflow Engine — 确定性状态机，替代 LLM 路由决策。

流程: Planner → Knowledge → Planner Refinement → Reviewer
       ┌──────────────────────────────────────────────┘
       │ score < 70 → RetryRouter → max 3 次 → EXHAUSTED
       │ score ≥ 70 → FINISH
"""
from __future__ import annotations

from state import WorkflowState, AgentContext, AgentResult

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

    def _classify_failure(self, review: dict) -> str:
        """根据 Reviewer 返回的 issues 判断失败类型，决定重试目标。"""
        issues = review.get("issues", [])
        # 合并所有 issue 文本用于关键词匹配
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

        while self.state.retry_count <= MAX_RETRIES:
            # ---- Step 1: Planner ----
            is_retry = self.state.retry_count > 0
            retry_ctx = (
                self.state.review_result if is_retry else None
            )
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

            # ---- 评分判断 ----
            score = (
                result.data.get("quality_scores", {}).get("composite_score", 0)
            )
            print(f"[ENGINE] reviewer score = {score}")

            if score >= 70:
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
            self._rollback(target)

        return self.state
