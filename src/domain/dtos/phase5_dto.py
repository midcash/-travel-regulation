"""
Phase 5 DTO — 两级裁决阶段的数据契约。

责任链:
  L1 确定性校验器 (纯代码) → HardChecksResult
  L2 语义校验器 (LLM 3步) → FatigueAssessment + SemanticFilterResult + ScenarioAdaptation
  合并 → Phase5Output (含 traffic_light / retry_target / suggested_action)

依赖: enums (Severity, TrafficLight, Verdict)
被引用: reviewer.py, validator.py, semantic_checker.py, workflow_engine.py
"""
from __future__ import annotations

from pydantic import BaseModel, Field

from src.domain.dtos.enums import Severity, TrafficLight, Verdict


# ============================================================
# Phase 5 输入
# ============================================================

class Phase5Input(BaseModel):
    """Phase 5 输入 — 待评审的规划和用户上下文。"""
    # TODO: plans 类型等 Phase 4 DTO 实现后改为 list[PlanDetail]
    plans: list[dict] = Field(default_factory=list)
    user_age: int | None = None
    negation_constraints: list[str] = Field(default_factory=list)  # 🛡️
    trip_purpose: str = "未知"
    preferences: list[str] = Field(default_factory=list)
    group_type: str = "solo"                            # solo/couple/family/elderly


# ============================================================
# L1 确定性校验
# ============================================================

class Violation(BaseModel):
    """单条违规记录。"""
    rule: str                                           # 规则名: budget_overflow/time_conflict/...
    severity: Severity
    detail: str
    evidence: str


class HardChecksResult(BaseModel):
    """L1 确定性校验器输出（纯代码，毫秒级）。"""
    passed: bool
    blocking_count: int = 0
    warning_count: int = 0
    violations: list[Violation] = Field(default_factory=list)


# ============================================================
# L2 语义校验 — Step 1: 体力合理性
# ============================================================

class FatigueAssessment(BaseModel):
    """体力合理性评估（L2 Step 1）。

    检测: 连续爬山、年龄适配、疲劳风险、高强度活动密度。
    """
    risk_level: str = "low"                             # low/medium/high/extreme
    concerns: list[str] = Field(default_factory=list)
    recommendations: list[str] = Field(default_factory=list)


# ============================================================
# L2 语义校验 — Step 2: 语义过滤
# ============================================================

class SemanticFilterResult(BaseModel):
    """语义过滤结果（L2 Step 2）。

    检测: negation_constraints 违规、语义网红、不适宜内容。
    """
    negation_violations_found: list[str] = Field(default_factory=list)  # 违规的 POI
    semantic_red_flags: list[str] = Field(default_factory=list)         # 语义网红等
    passed: bool = True


# ============================================================
# L2 语义校验 — Step 3: 场景适配
# ============================================================

class ScenarioAdaptation(BaseModel):
    """场景适配评估（L2 Step 3）。

    基于 trip_purpose 检查: 亲子→家庭餐厅, 情侣→私密景点, 商务→非景区路线。
    """
    trip_purpose: str = "未知"
    checks: list[dict] = Field(default_factory=list)    # [{"check": "包间", "passed": True}, ...]
    overall_match: bool = True


# ============================================================
# L2 语义校验 — 质量评分
# ============================================================

class QualityScore(BaseModel):
    """单个维度的评分。"""
    score: int = Field(ge=1, le=5)
    reasoning: str = ""


class QualityScores(BaseModel):
    """五维度质量评分 + 综合分 + 裁决。

    注意: 评审系统错误（如 LLM JSON 解析失败）通过 AgentResult.success=False
    表达，不在此 DTO 中增加 ERROR 状态 —— 保持 DTO 的语义纯净。
    """
    completeness: QualityScore = Field(default_factory=lambda: QualityScore(score=3, reasoning=""))
    feasibility: QualityScore = Field(default_factory=lambda: QualityScore(score=3, reasoning=""))
    constraint_sat: QualityScore = Field(default_factory=lambda: QualityScore(score=3, reasoning=""))
    experience: QualityScore = Field(default_factory=lambda: QualityScore(score=3, reasoning=""))
    accuracy: QualityScore = Field(default_factory=lambda: QualityScore(score=3, reasoning=""))
    composite_score: int = 0
    verdict: Verdict = Verdict.REJECT


class Issue(BaseModel):
    """评审发现的具体问题。"""
    severity: Severity
    category: str
    evidence: str
    fix_suggestion: str


# ============================================================
# Phase 5 输出
# ============================================================

class Phase5Output(BaseModel):
    """Phase 5 最终输出 — 两级裁决的完整报告。"""
    # L1
    hard_checks: HardChecksResult = Field(default_factory=lambda: HardChecksResult(passed=True))

    # L2（远期: L2 语义校验器未实现前为 None）
    fatigue: FatigueAssessment | None = None
    semantic_filter: SemanticFilterResult | None = None
    scenario_adaptation: ScenarioAdaptation | None = None

    # 质量评分（L1 锚定 + L2 LLM-as-Judge）
    quality_scores: QualityScores = Field(default_factory=QualityScores)
    issues: list[Issue] = Field(default_factory=list)
    strengths: list[str] = Field(default_factory=list)

    # 综合裁决（远期: L2 + L3 实现后填充）
    traffic_light: TrafficLight = TrafficLight.GREEN

    # 路由建议（L3 用户交互环使用，远期）
    retry_target: str | None = None                     # planner | knowledge | planner_refinement
    suggested_action: str = "DELIVER"                   # DELIVER | RETRY | CLARIFY | RESTART

    @property
    def should_retry(self) -> bool:
        """是否需要重试（红牌 + 有明确重试目标）。"""
        return self.traffic_light == TrafficLight.RED and self.retry_target is not None
