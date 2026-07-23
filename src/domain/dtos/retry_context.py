"""
RetryContext — 重试时传给 Agent 的结构化反馈。

仅包含 Planner 需要的信息，不含评审元数据（hard_checks/quality_scores 细节），
防止信息过载导致 LLM 输出不稳定。

依赖: enums.Severity
被引用: workflow_engine.py（替代当前 dict 拼装）, agent_state.AgentContext
"""
from __future__ import annotations

from pydantic import BaseModel, Field

from src.domain.dtos.enums import Severity


class WeakDimension(BaseModel):
    """评分维度弱点（quality_scores 中 score < 4 的维度）。"""
    dim: str                                          # 维度名: completeness/feasibility/constraint_sat/experience/accuracy
    score: int                                        # 当前得分 1-5
    reasoning: str = ""


class BlockingViolation(BaseModel):
    """阻断性违规（hard_checks.violations 中 severity=blocking 的项）。"""
    rule: str                                         # 规则名: budget_overflow/empty_plan/time_conflict/...
    detail: str


class RetryIssue(BaseModel):
    """需要修正的具体问题。"""
    severity: Severity
    category: str
    evidence: str
    fix_suggestion: str


class RetryContext(BaseModel):
    """重试时传给 Planner 的结构化反馈。

    仅包含 Planner 修正所需的三类信息：
    - 弱维度（引导质量提升方向）
    - 阻断违规（必须修正的硬约束问题）
    - 具体问题（含 evidence 和 fix_suggestion）

    不含 hard_checks/quality_scores/strengths 等评审元数据。
    """
    retry_target: str                                 # planner | knowledge | planner_refinement
    weak_dimensions: list[WeakDimension] = Field(default_factory=list)
    blocking_violations: list[BlockingViolation] = Field(default_factory=list)
    issues: list[RetryIssue] = Field(default_factory=list)
