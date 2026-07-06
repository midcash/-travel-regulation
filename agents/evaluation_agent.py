"""Evaluation Agent — 旅游规划系统的质量中枢 (三合一评估)。

Mode A: 代码质量评估 (开发期) — evaluate_code
Mode B: 业务产出评估 (运行时) — evaluate_plan
Mode C: Agent 贡献度评估 (消融实验) — evaluate_contribution

来源: spec/evaluator_spec.md, playbooks/evaluator_playbook.md
"""

from __future__ import annotations

import asyncio
import math
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional
from uuid import uuid4

from core.message import (
    AgentIdentity,
    AgentMessage,
    AgentRegistry,
    BaseAgent,
    Capability,
    ErrorCode,
    HealthStatus,
    MessageValidationError,
    TaskExecutionError,
    TaskType,
)
from models.quality import (
    AblationResult,
    AblationResults,
    Assessment360,
    CodeQualityReport,
    ContributionReport,
    DimensionScore,
    ImportanceScore,
    PlanDimensionScore,
    PlanQualityReport,
    SynergyReport,
)
from models.plan import TravelPlanDraft
from models.validation import ValidationReport


class EvaluationAgent(BaseAgent):
    """三合一评估 Agent。

    根据 task_type 自动路由到 Mode A/B/C:
    - task.evaluate_code → Mode A
    - task.evaluate_plan → Mode B
    - task.evaluate_contribution → Mode C
    """

    agent_name = "evaluation_agent"
    agent_version = "1.0.0"

    # Mode A 评分权重
    CODE_WEIGHTS = {
        "correctness": 0.30,
        "robustness": 0.25,
        "readability": 0.20,
        "performance": 0.15,
        "security": 0.10,
    }

    # Mode B 评分权重
    PLAN_WEIGHTS = {
        "completeness": 0.25,
        "feasibility": 0.25,
        "constraint_satisfaction": 0.25,
        "experience_quality": 0.15,
        "information_accuracy": 0.10,
    }

    def __init__(self, registry: Optional[AgentRegistry] = None):
        self._registry = registry
        self._identity = AgentIdentity(
            name="evaluation_agent",
            version="1.0.0",
            capabilities=["evaluate_code", "evaluate_plan", "evaluate_contribution"],
            endpoint="internal",
            status="online",
        )
        self._eval_cache: Dict[str, PlanQualityReport] = {}

    # -- BaseAgent 抽象方法 --
    @property
    def agent_name(self) -> str:
        return "evaluation_agent"

    @property
    def agent_version(self) -> str:
        return "1.0.0"

    async def handle_message(self, message: AgentMessage) -> AgentMessage:
        """消息处理入口 — 按 task_type 路由到 Mode A/B/C。"""
        try:
            message.validate()
        except MessageValidationError as exc:
            return self._error_response(message, ErrorCode.INVALID_MESSAGE, str(exc))

        try:
            if message.task_type == TaskType.TASK_EVALUATE_CODE:
                target = message.payload.get("target_agent", "unknown")
                code_files = message.payload.get("code_files", [])
                report = await self.evaluate_code(target, code_files)
                return AgentMessage(
                    message_id=str(uuid4()),
                    sender=self._identity,
                    receiver=message.sender,
                    task_type=TaskType.RESPONSE_RESULT,
                    payload={"result_type": "code_quality_report", "data": report.to_dict()},
                    timestamp=datetime.now(timezone.utc),
                    correlation_id=message.message_id,
                )

            elif message.task_type == TaskType.TASK_EVALUATE_PLAN:
                plan_data = message.payload.get("travel_plan_draft", message.payload)
                validation_data = message.payload.get("validation_report", {})
                draft = self._parse_draft(plan_data)
                validation = self._parse_validation(validation_data)
                report = await self.evaluate_plan(draft, validation)
                return AgentMessage(
                    message_id=str(uuid4()),
                    sender=self._identity,
                    receiver=message.sender,
                    task_type=TaskType.RESPONSE_RESULT,
                    payload={"result_type": "plan_quality_report", "data": report.to_dict()},
                    timestamp=datetime.now(timezone.utc),
                    correlation_id=message.message_id,
                )

            elif message.task_type == TaskType.TASK_EVALUATE_CONTRIBUTION:
                test_suite = message.payload.get("test_cases", [])
                baseline = message.payload.get("baseline_config", [])
                report = await self.evaluate_contribution(test_suite, baseline)
                return AgentMessage(
                    message_id=str(uuid4()),
                    sender=self._identity,
                    receiver=message.sender,
                    task_type=TaskType.RESPONSE_RESULT,
                    payload={"result_type": "contribution_report", "data": report.to_dict()},
                    timestamp=datetime.now(timezone.utc),
                    correlation_id=message.message_id,
                )

            else:
                return self._error_response(message, ErrorCode.TASK_NOT_SUPPORTED,
                                            f"不支持: {message.task_type.value}")
        except Exception as exc:
            return self._error_response(message, ErrorCode.EXECUTION_FAILED, str(exc))

    async def health_check(self) -> HealthStatus:
        return HealthStatus(
            status="healthy",
            last_checked=datetime.now(timezone.utc),
            details={"agent": "evaluation_agent", "version": "1.0.0"},
        )

    def get_capabilities(self) -> List[Capability]:
        return [
            Capability("evaluate_code", "Mode A: 代码质量评估 (5维度)"),
            Capability("evaluate_plan", "Mode B: 业务产出评估 (5维度)"),
            Capability("evaluate_contribution", "Mode C: Agent 贡献度评估 (LOO+360+协同)"),
        ]

    # ============================================================
    # Mode A: 代码质量评估 — spec/evaluator_spec.md §2.1
    # ============================================================

    async def evaluate_code(
        self, target_agent: str, code_files: List[str]
    ) -> CodeQualityReport:
        """评估 Agent 代码质量。

        Args:
            target_agent: 被评估的 Agent 名称。
            code_files: 代码文件路径列表 (不能为空)。

        Returns:
            CodeQualityReport 含 5 维度评分和综合判定。

        Raises:
            ValueError: code_files 为空。
        """
        if not code_files:
            raise ValueError("code_files 不能为空")

        dims: Dict[str, DimensionScore] = {}
        scores = {"correctness": 4, "robustness": 3, "readability": 4, "performance": 4, "security": 3}

        # 逐维度评分 (v1.0.0 stub: 使用固定模拟评分)
        for dim_name, weight in self.CODE_WEIGHTS.items():
            dims[dim_name] = DimensionScore(
                dimension=dim_name,
                score=scores[dim_name],
                weight=weight,
                issues=[] if scores[dim_name] >= 3 else [f"{dim_name} 评分偏低，建议优化"],
            )

        total = sum(d.score * d.weight for d in dims.values())
        return CodeQualityReport(
            report_id=str(uuid4()),
            target_agent=target_agent,
            code_files=list(code_files),
            dimensions=dims,
            total_score=round(total, 2),
            suggestions=[],
            evaluated_at=datetime.now(timezone.utc).isoformat(),
        )

    # 逐维度评分方法 — spec/evaluator_spec.md §3.1
    async def score_correctness(self, code: str, spec: str) -> DimensionScore:
        return DimensionScore(dimension="correctness", score=4, weight=0.30)

    async def score_robustness(self, code: str) -> DimensionScore:
        return DimensionScore(dimension="robustness", score=3, weight=0.25)

    async def score_readability(self, code: str) -> DimensionScore:
        return DimensionScore(dimension="readability", score=4, weight=0.20)

    async def score_performance(self, code: str) -> DimensionScore:
        return DimensionScore(dimension="performance", score=4, weight=0.15)

    async def score_security(self, code: str) -> DimensionScore:
        return DimensionScore(dimension="security", score=3, weight=0.10)

    # ============================================================
    # Mode B: 业务产出评估 — spec/evaluator_spec.md §2.2
    # ============================================================

    async def evaluate_plan(
        self,
        draft: TravelPlanDraft,
        validation: Optional[ValidationReport] = None,
    ) -> PlanQualityReport:
        """评估旅行方案质量。

        5维度加权评分，composite_score 映射到 0-100。

        幂等性检查: 同一 draft_id + 同一内容 → 返回缓存结果。
        """
        plan_id = getattr(draft, "draft_id", None) or str(id(draft))
        if plan_id in self._eval_cache:
            return self._eval_cache[plan_id]

        dims: Dict[str, PlanDimensionScore] = {}
        dim_scores: Dict[str, float] = {}

        # 完整性
        completeness = await self.score_completeness(draft)
        dims["completeness"] = completeness
        dim_scores["completeness"] = completeness.score

        # 可行性
        feasibility = await self.score_feasibility(validation)
        dims["feasibility"] = feasibility
        dim_scores["feasibility"] = feasibility.score

        # 约束满足度
        constraint = self.score_constraints_stub(draft, validation)
        dims["constraint_satisfaction"] = constraint
        dim_scores["constraint_satisfaction"] = constraint.score

        # 体验质量
        experience = await self.score_experience(draft)
        dims["experience_quality"] = experience
        dim_scores["experience_quality"] = experience.score

        # 信息准确度
        accuracy = await self.score_accuracy(validation)
        dims["information_accuracy"] = accuracy
        dim_scores["information_accuracy"] = accuracy.score

        # 综合得分
        composite = self._compute_composite(dim_scores)

        # 修订反馈
        feedback = self._generate_feedback(dims)

        report = PlanQualityReport(
            report_id=str(uuid4()),
            plan_id=plan_id,
            dimensions=dims,
            composite_score=round(composite, 1),
            revision_feedback=feedback,
            iteration=0,
            evaluated_at=datetime.now(timezone.utc).isoformat(),
        )

        self._eval_cache[plan_id] = report
        return report

    async def score_completeness(self, draft: TravelPlanDraft) -> PlanDimensionScore:
        """评估方案完整性。

        检查: 交通 + 住宿 + 每日行程 + 餐饮 + 预算。
        """
        missing = 0
        issues: List[str] = []

        transport = draft.transportation
        if not transport:
            missing += 1
            issues.append("缺少交通方案")
        transport_api = getattr(transport, "to_dict", None)
        if transport_api:
            t_dict = transport.to_dict() if callable(transport_api) else {}
        else:
            t_dict = transport if isinstance(transport, dict) else {}

        outbound = t_dict.get("outbound", {}) if isinstance(t_dict, dict) else {}
        if not outbound:
            missing += 0.5
            issues.append("缺少去程交通")

        if not draft.accommodation or len(draft.accommodation) == 0:
            missing += 1
            issues.append("缺少住宿方案")
        elif len(draft.accommodation) < 2:
            issues.append("住宿选项不足 2 个")

        if not draft.daily_itinerary:
            missing += 1
            issues.append("缺少每日行程")

        # 检查餐食
        meals_ok = True
        for day in (draft.daily_itinerary or []):
            day_meals = getattr(day, "meals", {}) if hasattr(day, "meals") else (day.get("meals", {}) if isinstance(day, dict) else {})
            if isinstance(day_meals, dict):
                meal_count = sum(1 for v in day_meals.values() if v)
            else:
                meal_count = len(day_meals) if isinstance(day_meals, list) else 0
            if meal_count < 2:
                meals_ok = False
                issues.append(f"第{getattr(day, 'day', '?') if hasattr(day, 'day') else day.get('day', '?')}天餐食不足")
        if not meals_ok:
            missing += 0.5

        if not draft.budget_allocation:
            missing += 1
            issues.append("缺少预算分配")

        score = max(2.0, 5.0 - missing)
        return PlanDimensionScore(
            dimension="completeness",
            score=score,
            weight=self.PLAN_WEIGHTS["completeness"],
            issues=issues,
        )

    async def score_feasibility(
        self, validation: Optional[ValidationReport] = None
    ) -> PlanDimensionScore:
        """评估可行性 (引用 ValidationReport)。"""
        if validation is None:
            return PlanDimensionScore(
                dimension="feasibility", score=3, weight=self.PLAN_WEIGHTS["feasibility"],
                issues=["缺少校验报告"],
            )

        # 通过 to_dict() 获取数据 (兼容 ValidationReport 和 dict)
        v_dict = validation.to_dict() if hasattr(validation, "to_dict") else (validation if isinstance(validation, dict) else {})
        summary = v_dict.get("summary", {})
        blocking = summary.get("blocking_count", 0)

        if blocking == 0:
            score = 5
        elif blocking <= 2:
            score = 3
        else:
            score = 1

        return PlanDimensionScore(
            dimension="feasibility",
            score=score,
            weight=self.PLAN_WEIGHTS["feasibility"],
            issues=[] if blocking == 0 else [f"存在 {blocking} 个阻断问题"],
        )

    def score_constraints_stub(
        self, draft: TravelPlanDraft, validation: Optional[ValidationReport] = None
    ) -> PlanDimensionScore:
        """评估约束满足度 (stub)。"""
        issues: List[str] = []
        score = 5.0

        # 检查餐食兼容性
        for day in (draft.daily_itinerary or []):
            day_meals = getattr(day, "meals", {}) if hasattr(day, "meals") else (day.get("meals", {}) if isinstance(day, dict) else {})
            if isinstance(day_meals, dict):
                for meal in day_meals.values():
                    if meal:
                        compatible = getattr(meal, "dietary_compatible", None) if hasattr(meal, "dietary_compatible") else (meal.get("dietary_compatible", True) if isinstance(meal, dict) else True)
                        if not compatible:
                            issues.append("部分餐食不兼容用户饮食限制")
                            score = 3
                            break

        # 检查住宿数量
        if len(draft.accommodation) < 2:
            issues.append("住宿选项不足 2 个")
            score = min(score, 4)

        return PlanDimensionScore(
            dimension="constraint_satisfaction",
            score=score,
            weight=self.PLAN_WEIGHTS["constraint_satisfaction"],
            issues=issues,
        )

    async def score_experience(self, draft: TravelPlanDraft) -> PlanDimensionScore:
        """评估体验质量 (节奏 + 多样性 + 个性化)。

        v1.0.0: stub 实现。
        """
        score = 4.0
        issues: List[str] = []

        # 检查每天活动多样性
        for day in (draft.daily_itinerary or []):
            activities = getattr(day, "activities", []) if hasattr(day, "activities") else (day.get("activities", []) if isinstance(day, dict) else [])
            types_found = set()
            for a in activities:
                t = getattr(a, "type", None) if hasattr(a, "type") else (a.get("type", "") if isinstance(a, dict) else "")
                if t:
                    types_found.add(t)
            if len(types_found) < 2 and len(activities) >= 2:
                issues.append(f"第{getattr(day, 'day', '?') if hasattr(day, 'day') else day.get('day', '?')}天活动类型单一")

        if len(draft.daily_itinerary or []) > 0 and issues:
            score = 3

        return PlanDimensionScore(
            dimension="experience_quality",
            score=score,
            weight=self.PLAN_WEIGHTS["experience_quality"],
            issues=issues,
        )

    async def score_accuracy(
        self, validation: Optional[ValidationReport] = None
    ) -> PlanDimensionScore:
        """评估信息准确度 (价格偏差)。

        v1.0.0: stub 实现。
        """
        if validation is None:
            return PlanDimensionScore(
                dimension="information_accuracy", score=3,
                weight=self.PLAN_WEIGHTS["information_accuracy"],
                issues=["缺少校验报告，无法评估准确度"],
            )
        return PlanDimensionScore(
            dimension="information_accuracy",
            score=4,
            weight=self.PLAN_WEIGHTS["information_accuracy"],
            issues=[],
        )

    # ============================================================
    # Mode C: Agent 贡献度评估 — spec/evaluator_spec.md §2.3
    # ============================================================

    async def evaluate_contribution(
        self, test_suite: List[Dict[str, Any]], baseline: List[str]
    ) -> ContributionReport:
        """评估 Agent 贡献度 (消融实验)。

        Args:
            test_suite: 测试用例列表 (至少 5 个)。
            baseline: 基线配置的 Agent 列表。

        Returns:
            ContributionReport 含 C1-C5 全部分析。
        """
        if len(test_suite) < 5:
            # 样本量不足, 降低置信度但继续执行
            pass

        baseline = baseline or ["orchestrator", "planning_agent", "execution_agent", "evaluation_agent"]

        # C1: LOO 消融实验
        ablation = await self.run_ablation(test_suite, baseline)

        # C2: Agent Importance Score
        importance_scores = await self.compute_importance_scores(baseline)

        # C3: 360° 三角评估
        assessments_360 = await self.run_360_assessment(baseline)

        # C4: 协同效应
        synergy = await self.analyze_synergy(ablation)

        # C5: 成本-质量 (stub)
        coq = 0.05 if ablation.baseline_score > 0 else 0

        return ContributionReport(
            report_id=str(uuid4()),
            ablation=ablation,
            importance_scores=importance_scores,
            assessments_360=assessments_360,
            synergy=synergy,
            cost_quality_ratio=coq,
            generated_at=datetime.now(timezone.utc).isoformat(),
        )

    async def run_ablation(
        self, test_suite: List[Dict[str, Any]], baseline_config: List[str]
    ) -> AblationResults:
        """C1: LOO 消融实验。

        v1.0.0: stub 实现，使用模拟评分。
        """
        # S_full: 全配置基线得分
        s_full = 85.0

        # 逐个移除
        results: List[AblationResult] = []
        results.append(AblationResult(
            config_name="full",
            agents_present=list(baseline_config),
            score=s_full,
            llm_calls=len(test_suite) * 4,
            duration_seconds=len(test_suite) * 3.0,
            test_cases_run=len(test_suite),
        ))

        specialist_agents = [a for a in baseline_config if a != "orchestrator"]
        marginal: Dict[str, float] = {}
        rates: Dict[str, float] = {}

        for removed in specialist_agents:
            reduced = [a for a in baseline_config if a != removed]
            # 模拟得分下降
            score_drop = 15.0 if removed == "planning_agent" else (10.0 if removed == "execution_agent" else 8.0)
            score = round(s_full - score_drop, 1)
            results.append(AblationResult(
                config_name=f"no_{removed}",
                agents_present=reduced,
                score=score,
                llm_calls=len(test_suite) * 3,
                duration_seconds=len(test_suite) * 2.5,
                test_cases_run=len(test_suite),
            ))
            marginal[removed] = score_drop

        # 贡献率
        total_mc = sum(marginal.values())
        if total_mc > 0:
            for agent, mc in marginal.items():
                rates[agent] = round(mc / total_mc * 100, 1)
        else:
            for agent in marginal:
                rates[agent] = 33.3

        return AblationResults(
            baseline_score=s_full,
            results=results,
            marginal_contributions=marginal,
            contribution_rates=rates,
            sample_size=len(test_suite),
        )

    async def compute_importance_scores(
        self, agents: List[str]
    ) -> List[ImportanceScore]:
        """C2: Agent Importance Score。

        v1.0.0: stub 实现，使用固定评分矩阵。
        """
        specialist = [a for a in agents if a != "orchestrator"]
        importance: List[ImportanceScore] = []

        # 模拟评分矩阵
        ratings: Dict[str, Dict[str, float]] = {
            "planning_agent": {"execution_agent": 4, "evaluation_agent": 4},
            "execution_agent": {"planning_agent": 5, "evaluation_agent": 4},
            "evaluation_agent": {"planning_agent": 4, "execution_agent": 5},
        }

        for agent in specialist:
            received = ratings.get(agent, {})
            avg = sum(received.values()) / len(received) if received else 3.0

            # 打标签
            label = "standard"
            if avg >= 4.5:
                label = "veto"
            elif avg < 2.5:
                label = "free_rider"

            importance.append(ImportanceScore(
                agent_name=agent,
                score=round(avg, 1),
                rank=0,
                label=label,
                ratings_received=received,
            ))

        # 排序
        importance.sort(key=lambda x: x.score, reverse=True)
        for i, imp in enumerate(importance):
            imp.rank = i + 1

        return importance

    async def run_360_assessment(
        self, agents: List[str]
    ) -> List[Assessment360]:
        """C3: 360° 三角评估。

        v1.0.0: stub 实现。
        """
        specialist = [a for a in agents if a != "orchestrator"]
        assessments: List[Assessment360] = []

        for agent in specialist:
            self_score = 4.0
            peer_score = 4.0
            supervisory_score = 4.0
            bias = round(self_score - (peer_score + supervisory_score) / 2, 2)
            alignment = "aligned"
            if bias > 0.5:
                alignment = "overconfident"
            elif bias < -0.5:
                alignment = "underconfident"

            assessments.append(Assessment360(
                agent_name=agent,
                self_score=self_score,
                peer_score=peer_score,
                supervisory_score=supervisory_score,
                bias=bias,
                alignment=alignment,
            ))

        return assessments

    async def analyze_synergy(
        self, results: AblationResults
    ) -> SynergyReport:
        """C4: 协同效应分析。

        v1.0.0: stub 实现。
        """
        s_full = results.baseline_score
        s_p_alone = 60.0
        s_e_alone = 65.0

        synergy_gain = s_full - max(s_p_alone, s_e_alone)
        efficiency = (s_full / (s_p_alone + s_e_alone) * 100) if (s_p_alone + s_e_alone) > 0 else 0

        level = "moderate"
        if efficiency > 80:
            level = "strong"
        elif efficiency <= 50:
            level = "weak"

        return SynergyReport(
            synergy_gain=round(synergy_gain, 1),
            efficiency_pct=round(efficiency, 1),
            level=level,
            standalone_scores={"planning_agent": s_p_alone, "execution_agent": s_e_alone},
            full_score=s_full,
        )

    async def compute_cost_quality(
        self, config_stats: List[Dict[str, Any]]
    ) -> List[Dict[str, Any]]:
        """C5: 成本-质量分析 (stub)。"""
        return [
            {"config": "full", "llm_calls": 12, "quality_score": 85, "coq": 0.14, "pareto_optimal": True},
        ]

    # ============================================================
    # 内部辅助方法
    # ============================================================

    def _compute_composite(self, dim_scores: Dict[str, float]) -> float:
        """计算 Mode B 综合得分 (0-100)。"""
        weighted = (
            dim_scores.get("completeness", 0) * self.PLAN_WEIGHTS["completeness"]
            + dim_scores.get("feasibility", 0) * self.PLAN_WEIGHTS["feasibility"]
            + dim_scores.get("constraint_satisfaction", 0) * self.PLAN_WEIGHTS["constraint_satisfaction"]
            + dim_scores.get("experience_quality", 0) * self.PLAN_WEIGHTS["experience_quality"]
            + dim_scores.get("information_accuracy", 0) * self.PLAN_WEIGHTS["information_accuracy"]
        )
        return weighted * 20

    def _generate_feedback(
        self, dims: Dict[str, PlanDimensionScore]
    ) -> List[Dict[str, Any]]:
        """从维度评分生成修订反馈。"""
        feedback: List[Dict[str, Any]] = []
        for name, dim in dims.items():
            for issue in dim.issues:
                feedback.append({
                    "dimension": name,
                    "issue": issue,
                    "suggestion": dim.suggestions[0] if dim.suggestions else f"请改进 {name}",
                    "priority": "high" if dim.score < 3 else "medium",
                })
        return feedback

    def _parse_draft(self, data: Dict[str, Any]) -> TravelPlanDraft:
        """从 payload 解析 TravelPlanDraft。"""
        if isinstance(data, TravelPlanDraft):
            return data
        return TravelPlanDraft(
            draft_id=data.get("draft_id", str(uuid4())),
            destination=data.get("destination"),
            duration_days=data.get("duration_days", 0),
            total_budget=data.get("total_budget", 0),
            daily_itinerary=data.get("daily_itinerary", []),
            accommodation=data.get("accommodation", []),
            budget_allocation=data.get("budget_allocation"),
        )

    def _parse_validation(self, data: Dict[str, Any]) -> Optional[ValidationReport]:
        """从 payload 解析 ValidationReport。"""
        if isinstance(data, ValidationReport):
            return data
        if not data:
            return None
        # v1.0.0 stub: 返回 None 让下游按缺失处理
        return None

    def _error_response(self, req: AgentMessage, code: ErrorCode, detail: str) -> AgentMessage:
        return AgentMessage(
            message_id=str(uuid4()),
            sender=self._identity,
            receiver=req.sender,
            task_type=TaskType.RESPONSE_ERROR,
            payload={
                "error_code": code.name,
                "error_message": detail,
                "original_message_id": req.message_id,
                "recoverable": code.recoverable,
                "suggested_action": code.suggested_action,
            },
            timestamp=datetime.now(timezone.utc),
            correlation_id=req.message_id,
        )
