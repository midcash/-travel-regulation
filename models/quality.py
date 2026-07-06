"""评估/质量数据模型 — Evaluation Agent 的 Mode A/B/C 输出结构。

包含:
- DimensionScore / CodeQualityReport (Mode A: 代码质量评估)
- PlanDimensionScore / PlanQualityReport (Mode B: 业务产出评估)
- AblationResult / AblationResults / ImportanceScore / Assessment360
  / SynergyReport / ContributionReport (Mode C: Agent 贡献度评估)

来源: spec/evaluator_spec.md, evaluation/code_quality_rubric.md, evaluation/gate_definitions.md
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional


# ============================================================
# Mode A: 代码质量评估 — spec/evaluator_spec.md §2.1
# ============================================================


@dataclass
class DimensionScore:
    """单个维度的代码质量评分 (Mode A)。

    对应 code_quality_rubric.md 的 5 个评分维度之一。

    Attributes:
        dimension: 维度名称 (correctness / robustness / readability
                   / performance / security)。
        score: 评分 1-5。
        weight: 维度权重 (0-1 之间, 如 0.30)。
        issues: 该维度发现的缺陷列表。
        evidence: 评分依据的引用或证据 (代码片段、测试结果等)。
    """

    dimension: str
    score: float
    weight: float
    issues: List[str] = field(default_factory=list)
    evidence: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        """将当前对象序列化为字典。"""
        return {
            "dimension": self.dimension,
            "score": self.score,
            "weight": self.weight,
            "issues": list(self.issues),
            "evidence": self.evidence,
        }


@dataclass
class CodeQualityReport:
    """代码质量评估报告 (Mode A 输出)。

    对应 evaluator_spec.md §2.1 的 CodeQualityReport 结构。

    Attributes:
        report_id: 报告唯一标识 (UUID)。
        target_agent: 被评估的 Agent 名称。
        code_files: 被评估的代码文件路径列表。
        dimensions: 各维度评分, key 为维度名称, value 为 DimensionScore。
        total_score: 加权总分 (1-5), 由 Sigma(score x weight) 计算。
        verdict: 判定结果 (PASS / PASS_WITH_SUGGESTIONS
                 / NEEDS_REVISION / REJECT)。
        suggestions: 改进建议列表。
        action_items: 具体操作项, 每项含 action / priority / effort 等。
        evaluated_at: 评估完成时间 (ISO 8601)。
    """

    report_id: Optional[str] = None
    target_agent: str = ""
    code_files: List[str] = field(default_factory=list)
    dimensions: Dict[str, DimensionScore] = field(default_factory=dict)
    total_score: float = 0.0
    verdict: str = ""
    suggestions: List[str] = field(default_factory=list)
    action_items: List[Dict[str, Any]] = field(default_factory=list)
    evaluated_at: Optional[str] = None

    def __post_init__(self) -> None:
        """自动计算 verdict (若未显式设置)。"""
        if not self.verdict:
            self.verdict = self._compute_verdict()

    def _compute_verdict(self) -> str:
        """根据 total_score 计算判定结果。

        Rules (code_quality_rubric.md section 8):
            total_score >= 4.0 -> PASS
            total_score >= 3.0 -> PASS_WITH_SUGGESTIONS
            total_score >= 2.0 -> NEEDS_REVISION
            total_score <  2.0 -> REJECT
        """
        if self.total_score >= 4.0:
            return "PASS"
        if self.total_score >= 3.0:
            return "PASS_WITH_SUGGESTIONS"
        if self.total_score >= 2.0:
            return "NEEDS_REVISION"
        return "REJECT"

    def to_dict(self) -> Dict[str, Any]:
        """将当前对象序列化为字典。"""
        return {
            "report_id": self.report_id,
            "target_agent": self.target_agent,
            "code_files": list(self.code_files),
            "dimensions": {k: v.to_dict() for k, v in self.dimensions.items()},
            "total_score": self.total_score,
            "verdict": self.verdict,
            "suggestions": list(self.suggestions),
            "action_items": [dict(item) for item in self.action_items],
            "evaluated_at": self.evaluated_at,
        }


# ============================================================
# Mode B: 业务产出评估 — spec/evaluator_spec.md §2.2
# ============================================================


@dataclass
class PlanDimensionScore:
    """单个维度的计划质量评分 (Mode B)。

    对应 evaluator_spec.md section 2.2 的 5 个评估维度之一。

    Attributes:
        dimension: 维度名称 (completeness / feasibility
                   / constraint_satisfaction / experience_quality
                   / information_accuracy)。
        score: 评分 1-5。
        weight: 维度权重 (0-1 之间, 如 0.25)。
        issues: 该维度发现的缺陷列表。
        suggestions: 该维度的改进建议列表。
    """

    dimension: str
    score: float
    weight: float
    issues: List[str] = field(default_factory=list)
    suggestions: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        """将当前对象序列化为字典。"""
        return {
            "dimension": self.dimension,
            "score": self.score,
            "weight": self.weight,
            "issues": list(self.issues),
            "suggestions": list(self.suggestions),
        }


@dataclass
class PlanQualityReport:
    """业务产出评估报告 (Mode B 输出)。

    对应 evaluator_spec.md section 2.2 的 PlanQualityReport 结构。

    Attributes:
        report_id: 报告唯一标识 (UUID)。
        plan_id: 被评估方案的唯一标识。
        dimensions: 各维度评分, key 为维度名称, value 为 PlanDimensionScore。
        composite_score: 综合得分 (0-100), 由
                         Sigma(score x weight) x 20 计算。
        verdict: 判定结果 (PASS / REVISE / REJECT)。
        revision_feedback: 修订反馈列表, 每项含 dimension / issue
                          / suggestion / priority。
        iteration: 当前迭代轮次 (从 0 开始)。
        evaluated_at: 评估完成时间 (ISO 8601)。
    """

    report_id: Optional[str] = None
    plan_id: Optional[str] = None
    dimensions: Dict[str, PlanDimensionScore] = field(default_factory=dict)
    composite_score: float = 0.0
    verdict: str = ""
    revision_feedback: List[Dict[str, Any]] = field(default_factory=list)
    iteration: int = 0
    evaluated_at: Optional[str] = None

    def __post_init__(self) -> None:
        """自动计算 verdict (若未显式设置)。"""
        if not self.verdict:
            self.verdict = self._compute_verdict()

    def _compute_verdict(self) -> str:
        """根据 composite_score 计算判定结果。

        Rules (evaluator_spec.md section 2.2):
            composite_score >= 80 -> PASS
            composite_score >= 60 -> REVISE
            composite_score <  60 -> REJECT
        """
        if self.composite_score >= 80:
            return "PASS"
        if self.composite_score >= 60:
            return "REVISE"
        return "REJECT"

    def to_dict(self) -> Dict[str, Any]:
        """将当前对象序列化为字典。"""
        return {
            "report_id": self.report_id,
            "plan_id": self.plan_id,
            "dimensions": {k: v.to_dict() for k, v in self.dimensions.items()},
            "composite_score": self.composite_score,
            "verdict": self.verdict,
            "revision_feedback": [dict(item) for item in self.revision_feedback],
            "iteration": self.iteration,
            "evaluated_at": self.evaluated_at,
        }


# ============================================================
# Mode C: Agent 贡献度评估 — spec/evaluator_spec.md section 2.3
# ============================================================


@dataclass
class AblationResult:
    """单次消融实验的配置与结果。

    对应 evaluator_spec.md section 2.3 C1 的一次消融运行记录。

    Attributes:
        config_name: 配置名称 (如 'full', 'no_planner', 'no_executor')。
        agents_present: 该配置下参与的 Agent 名称列表。
        score: 该配置下的综合质量得分 (0-100)。
        llm_calls: 该配置下使用的 LLM 调用次数。
        duration_seconds: 该配置下的运行耗时 (秒)。
        test_cases_run: 该配置下运行的测试用例数。
    """

    config_name: str
    agents_present: List[str]
    score: float
    llm_calls: int
    duration_seconds: float
    test_cases_run: int

    def to_dict(self) -> Dict[str, Any]:
        """将当前对象序列化为字典。"""
        return {
            "config_name": self.config_name,
            "agents_present": list(self.agents_present),
            "score": self.score,
            "llm_calls": self.llm_calls,
            "duration_seconds": self.duration_seconds,
            "test_cases_run": self.test_cases_run,
        }


@dataclass
class AblationResults:
    """完整 LOO 消融实验结果汇总。

    对应 evaluator_spec.md section 2.3 C1 的输出结构。

    Attributes:
        baseline_score: 全量配置下的基线得分 (S_full)。
        results: 各消融配置的运行结果列表。
        marginal_contributions: 各 Agent 的边际贡献,
                               key 为 agent 名, value 为 MC 得分。
        contribution_rates: 各 Agent 的贡献率百分比,
                           key 为 agent 名, value 为 CR %。
        sample_size: 测试用例数 (样本量)。
        confidence_interval: 置信区间 (可选), 含 lower / upper 边界。
    """

    baseline_score: float
    results: List[AblationResult] = field(default_factory=list)
    marginal_contributions: Dict[str, float] = field(default_factory=dict)
    contribution_rates: Dict[str, float] = field(default_factory=dict)
    sample_size: int = 0
    confidence_interval: Optional[Dict[str, float]] = None

    def to_dict(self) -> Dict[str, Any]:
        """将当前对象序列化为字典。"""
        return {
            "baseline_score": self.baseline_score,
            "results": [r.to_dict() for r in self.results],
            "marginal_contributions": dict(self.marginal_contributions),
            "contribution_rates": dict(self.contribution_rates),
            "sample_size": self.sample_size,
            "confidence_interval": (
                dict(self.confidence_interval)
                if self.confidence_interval is not None
                else None
            ),
        }


@dataclass
class ImportanceScore:
    """Agent 重要性评分 (C2 输出)。

    对应 evaluator_spec.md section 2.3 C2 的评分矩阵结果。

    Attributes:
        agent_name: Agent 名称。
        score: 重要性得分 (1-5), 收到评分的均值。
        rank: 重要性排名 (1 为最高)。
        label: 标签 (veto / bottleneck / free_rider / standard)。
        ratings_received: 收到的评分, key 为评分者 agent 名,
                         value 为评分 (1-5)。
    """

    agent_name: str
    score: float
    rank: int
    label: str
    ratings_received: Dict[str, float] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        """将当前对象序列化为字典。"""
        return {
            "agent_name": self.agent_name,
            "score": self.score,
            "rank": self.rank,
            "label": self.label,
            "ratings_received": dict(self.ratings_received),
        }


@dataclass
class Assessment360:
    """360 度三角评估结果 (C3 输出)。

    对应 evaluator_spec.md section 2.3 C3 的自我-同行-上级评估。

    Attributes:
        agent_name: 被评估的 Agent 名称。
        self_score: 自我评分 (1-5)。
        peer_score: 同行 (下游) 评分均值 (1-5)。
        supervisory_score: 上级 (Orchestrator) 评分 (1-5)。
        bias: 偏差值 = Self - (Peer + Supervisory) / 2。
        alignment: 校准状态 (overconfident / underconfident / aligned)。
    """

    agent_name: str
    self_score: float
    peer_score: float
    supervisory_score: float
    bias: float
    alignment: str

    def to_dict(self) -> Dict[str, Any]:
        """将当前对象序列化为字典。"""
        return {
            "agent_name": self.agent_name,
            "self_score": self.self_score,
            "peer_score": self.peer_score,
            "supervisory_score": self.supervisory_score,
            "bias": self.bias,
            "alignment": self.alignment,
        }


@dataclass
class SynergyReport:
    """协同效应分析报告 (C4 输出)。

    对应 evaluator_spec.md section 2.3 C4 的协同分析结果。

    Attributes:
        synergy_gain: 协同增益值 = S_full - max(S_p_alone, S_e_alone)。
        efficiency_pct: 协同效率百分比 =
                       S_full / (S_p_alone + S_e_alone) x 100%。
        level: 协同等级 (strong / moderate / weak)。
        standalone_scores: 各 Agent 独立运行得分,
                          key 为 agent 名, value 为得分。
        full_score: 全量配置下的得分 (S_full)。
    """

    synergy_gain: float
    efficiency_pct: float
    level: str
    standalone_scores: Dict[str, float] = field(default_factory=dict)
    full_score: float = 0.0

    def to_dict(self) -> Dict[str, Any]:
        """将当前对象序列化为字典。"""
        return {
            "synergy_gain": self.synergy_gain,
            "efficiency_pct": self.efficiency_pct,
            "level": self.level,
            "standalone_scores": dict(self.standalone_scores),
            "full_score": self.full_score,
        }


@dataclass
class ContributionReport:
    """Agent 贡献度评估报告 (Mode C 输出)。

    对应 evaluator_spec.md section 2.3 的 ContributionReport 结构,
    聚合了 C1-C5 的全部分析结果。

    Attributes:
        report_id: 报告唯一标识 (UUID)。
        ablation: LOO 消融实验结果。
        importance_scores: Agent 重要性评分列表。
        assessments_360: 360 度三角评估结果列表。
        synergy: 协同效应分析报告。
        cost_quality_ratio: 成本-质量比 (可选),
                           CoQ = LLM 调用次数 / 质量得分。
        generated_at: 报告生成时间 (ISO 8601)。
    """

    report_id: Optional[str] = None
    ablation: Optional[AblationResults] = None
    importance_scores: List[ImportanceScore] = field(default_factory=list)
    assessments_360: List[Assessment360] = field(default_factory=list)
    synergy: Optional[SynergyReport] = None
    cost_quality_ratio: Optional[float] = None
    generated_at: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        """将当前对象序列化为字典。"""
        return {
            "report_id": self.report_id,
            "ablation": self.ablation.to_dict() if self.ablation is not None else None,
            "importance_scores": [s.to_dict() for s in self.importance_scores],
            "assessments_360": [a.to_dict() for a in self.assessments_360],
            "synergy": self.synergy.to_dict() if self.synergy is not None else None,
            "cost_quality_ratio": self.cost_quality_ratio,
            "generated_at": self.generated_at,
        }
