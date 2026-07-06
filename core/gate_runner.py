"""质量门执行器 — Gate 0-3 的执行与判定逻辑。

包含:
- BlockingIssue / Warning 数据类
- GateResult 数据类 (统一 Gate 判定结果)
- GateRunner 类 (执行全部 4 个质量门)

来源: evaluation/gate_definitions.md
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime, timezone
from typing import Any, Dict, List, Optional

from .context import ContextStatus, SharedContext

# ============================================================
# Gate 0 日期校验常量
# ============================================================

_TODAY = date.today


# ============================================================
# BlockingIssue / Warning — gate_definitions.md §2-5
# ============================================================

@dataclass(frozen=True)
class BlockingIssue:
    """阻断性问题 — 必须解决才能通过质量门。"""

    description: str
    """问题描述。"""

    constraint: Optional[str] = None
    """违反的约束名称（可选）。"""

    fix_suggestion: Optional[str] = None
    """修复建议（可选）。"""


@dataclass(frozen=True)
class Warning_:
    """警告信息 — 不阻断但需关注。"""

    description: str
    """警告描述。"""

    constraint: Optional[str] = None
    """关联的约束名称（可选）。"""

    suggestion: Optional[str] = None
    """改进建议（可选）。"""


# ============================================================
# GateResult — gate_definitions.md §2-5
# ============================================================

@dataclass
class GateResult:
    """质量门执行结果。

    由 GateRunner.run_gate_*() 返回。
    """

    gate_id: int
    """Gate 编号 (0-3)。"""

    passed: bool
    """是否通过。"""

    blocking_issues: List[BlockingIssue] = field(default_factory=list)
    """阻断性问题列表。"""

    warnings: List[Warning_] = field(default_factory=list)
    """警告列表。"""

    degraded: bool = False
    """是否为降级通过 (仅 Gate 2 使用)。"""

    rejected: bool = False
    """是否被拒绝 (仅 Gate 2, score < 60)。"""

    revision_feedback: Optional[str] = None
    """修订反馈 (仅 Gate 2 使用)。"""

    timestamp: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    """Gate 执行时间戳。"""


# ============================================================
# GateRunner — gate_definitions.md §7
# ============================================================

class GateRunner:
    """质量门执行器。

    负责执行 Gate 0-3 的判定逻辑，记录执行历史到 gate_log。

    使用示例:
        runner = GateRunner(shared_context)
        result_0 = runner.run_gate_0(request)
        if not result_0.passed:
            ...  # 追问用户或拒绝
    """

    # -- Gate 2 维度常量 --
    DIMENSION_THRESHOLD = 3        # 1-5 制下，低于 3 分触发维度警告
    DIM_ESCALATION_COUNT = 3       # ≥ 3 个维度告警时升级为 blocking
    DIMENSION_NAMES = ("COM", "FEA", "CON", "EXP", "ACC")

    # -- Gate 2 评分阈值 --
    COMPOSITE_PASS = 80            # ≥ 80 通过
    COMPOSITE_REJECT = 60          # < 60 拒绝

    def __init__(self, context: Optional[SharedContext] = None):
        self.context = context
        self.gate_log: List[GateResult] = []

    # ============================================================
    # Gate 0: 输入校验 — gate_definitions.md §2
    # ============================================================

    def run_gate_0(self, request: Dict[str, Any]) -> GateResult:
        """执行 Gate 0 输入校验。

        校验目的地、日期、预算、人数等必填项。

        Args:
            request: 结构化用户请求字典，需包含:
                - destination (dict): {city, country}
                - dates (dict): {arrival, departure}
                - budget (dict): {total, currency}
                - travelers (dict): {adults, children}

        Returns:
            GateResult — passed=True 表示所有必填项合法。
        """
        blocking: List[BlockingIssue] = []
        warnings: List[Warning_] = []

        destination = request.get("destination") if request else None
        dates = request.get("dates") if request else None
        budget = request.get("budget") if request else None
        travelers = request.get("travelers") if request else None

        # 目的地非空
        if not destination or not destination.get("city"):
            blocking.append(BlockingIssue(
                description="目的地不能为空",
                constraint="destination.required",
                fix_suggestion="请提供目的地城市名称",
            ))

        # 出发日期非空、在未来
        arrival_str = dates.get("arrival") if dates else None
        if not arrival_str:
            blocking.append(BlockingIssue(
                description="出发日期不能为空",
                constraint="dates.arrival.required",
                fix_suggestion="请提供出发日期 (YYYY-MM-DD)",
            ))
        else:
            try:
                arrival_date = date.fromisoformat(arrival_str)
                if arrival_date < _TODAY():
                    blocking.append(BlockingIssue(
                        description="出发日期不能是过去的日期",
                        constraint="dates.arrival.future",
                        fix_suggestion="请提供未来的出发日期",
                    ))
            except (ValueError, TypeError):
                blocking.append(BlockingIssue(
                    description=f"出发日期格式无效: {arrival_str}",
                    constraint="dates.arrival.format",
                    fix_suggestion="请使用 YYYY-MM-DD 格式",
                ))

        # 返回日期非空、≥ 出发日期
        departure_str = dates.get("departure") if dates else None
        if not departure_str:
            blocking.append(BlockingIssue(
                description="返回日期不能为空",
                constraint="dates.departure.required",
                fix_suggestion="请提供返回日期 (YYYY-MM-DD)",
            ))
        elif arrival_str:
            try:
                departure_date = date.fromisoformat(departure_str)
                arrival_date_v = date.fromisoformat(arrival_str)
                if departure_date < arrival_date_v:
                    blocking.append(BlockingIssue(
                        description="返回日期不能早于出发日期",
                        constraint="dates.departure.order",
                        fix_suggestion="返回日期应 ≥ 出发日期",
                    ))
            except (ValueError, TypeError):
                blocking.append(BlockingIssue(
                    description=f"返回日期格式无效: {departure_str}",
                    constraint="dates.departure.format",
                    fix_suggestion="请使用 YYYY-MM-DD 格式",
                ))

        # 预算 > 0
        budget_total = budget.get("total") if budget else None
        if budget_total is None or budget_total <= 0:
            blocking.append(BlockingIssue(
                description="预算必须大于0",
                constraint="budget.total.positive",
                fix_suggestion="请输入大于 0 的预算金额",
            ))

        # 人数 ≥ 1 (默认 1)
        adults = travelers.get("adults", 1) if travelers else 1
        if adults < 1:
            warnings.append(Warning_(
                description="人数已自动设为1",
                constraint="travelers.adults.default",
            ))

        result = GateResult(
            gate_id=0,
            passed=len(blocking) == 0,
            blocking_issues=blocking,
            warnings=warnings,
        )
        self.gate_log.append(result)
        return result

    # ============================================================
    # Gate 1: 可行性检查 — gate_definitions.md §3
    # ============================================================

    def run_gate_1(self, validation: Dict[str, Any]) -> GateResult:
        """执行 Gate 1 可行性检查。

        读取 ValidationReport 判定是否存在硬约束违反。

        Args:
            validation: ValidationReport 字典，需包含:
                - constraint_check (dict): {blocking_issues, warnings}
                - summary (dict): {blocking_count, warning_count}

        Returns:
            GateResult — passed=True 表示无 blocking_issues。
        """
        blocking: List[BlockingIssue] = []
        warnings: List[Warning_] = []

        if not validation:
            blocking.append(BlockingIssue(
                description="缺少校验报告",
                constraint="validation_report.required",
            ))
            result = GateResult(gate_id=1, passed=False, blocking_issues=blocking)
            self.gate_log.append(result)
            return result

        constraint_check = validation.get("constraint_check", {})

        # 硬约束违反 → blocking
        constraint_blocking = constraint_check.get("blocking_issues", [])
        for issue in constraint_blocking:
            blocking.append(BlockingIssue(
                description=f"硬约束违反: {issue.get('constraint', 'unknown')}",
                constraint=issue.get("constraint"),
                fix_suggestion=issue.get("fix_suggestion"),
            ))

        # 汇总中的 blocking_count
        summary = validation.get("summary", {})
        if summary.get("blocking_count", 0) > 0:
            blocking.append(BlockingIssue(
                description=f"共 {summary['blocking_count']} 个阻断问题",
            ))

        # warnings 汇总
        warning_count = summary.get("warning_count", 0)
        if warning_count > 0:
            warnings.append(Warning_(
                description=f"共 {warning_count} 个警告",
            ))

        # 价格检查异常项
        price_check = validation.get("price_check", {})
        price_anomalies = price_check.get("anomalies", [])
        high_severity_count = sum(1 for a in price_anomalies if a.get("severity") == "high")
        if len(price_anomalies) > 3 or high_severity_count > 0:
            warnings.append(Warning_(
                description=f"价格检查发现 {len(price_anomalies)} 个异常 (含 {high_severity_count} 个高危)",
                suggestion="建议核实价格数据来源",
            ))

        # 时间冲突
        time_check = validation.get("time_check", {})
        time_conflicts = time_check.get("conflicts", [])
        if len(time_conflicts) > 2:
            warnings.append(Warning_(
                description=f"时间检查发现 {len(time_conflicts)} 个冲突",
                suggestion="建议优化每日行程密度",
            ))

        # 绕路
        geo_check = validation.get("geography_check", {})
        detours = geo_check.get("detours", [])
        if len(detours) > 1:
            warnings.append(Warning_(
                description=f"地理检查发现 {len(detours)} 处绕路",
                suggestion="建议优化路线顺序",
            ))

        result = GateResult(
            gate_id=1,
            passed=len(blocking) == 0,
            blocking_issues=blocking,
            warnings=warnings,
        )
        self.gate_log.append(result)
        return result

    # ============================================================
    # Gate 2: 质量评审 — gate_definitions.md §4
    # ============================================================

    def run_gate_2(self, quality_report: Dict[str, Any], iteration: int) -> GateResult:
        """执行 Gate 2 质量评审。

        分两阶段判定:
        Phase 1: 维度级检查 (5 维度，1-5 制)
        Phase 2: 综合评分判定

        Args:
            quality_report: PlanQualityReport 字典，需包含:
                - composite_score (float, 0-100)
                - dimensions (dict): {completeness, feasibility, constraint_satisfaction,
                  experience_quality, information_accuracy} (each 1-5)
                - revision_feedback (list, optional)
            iteration: 当前迭代轮次 (1-based)

        Returns:
            GateResult — 含 passed/degraded/rejected 三态判定。
        """
        if not quality_report:
            result = GateResult(
                gate_id=2,
                passed=False,
                rejected=True,
                blocking_issues=[BlockingIssue(description="缺少质量报告")],
            )
            self.gate_log.append(result)
            return result

        composite_score = quality_report.get("composite_score", 0)
        dimensions = quality_report.get("dimensions", {})

        # === Phase 1: 维度级检查 ===
        dim_scores = {
            "COM": dimensions.get("completeness", 0),
            "FEA": dimensions.get("feasibility", 0),
            "CON": dimensions.get("constraint_satisfaction", 0),
            "EXP": dimensions.get("experience_quality", 0),
            "ACC": dimensions.get("information_accuracy", 0),
        }

        dim_warnings: List[Warning_] = []
        for name, score in dim_scores.items():
            if score < self.DIMENSION_THRESHOLD:
                dim_warnings.append(Warning_(
                    description=f"维度 [{name}] 得分 {score} < {self.DIMENSION_THRESHOLD}，存在结构性缺陷",
                    constraint=f"dimension.{name}.threshold",
                ))

        dim_escalated = len(dim_warnings) >= self.DIM_ESCALATION_COUNT

        # === Phase 2: 综合评分判定 ===
        revision_feedback_list = quality_report.get("revision_feedback", [])
        revision_text = None
        if revision_feedback_list:
            revision_text = "; ".join(
                f.get("issue", "") for f in revision_feedback_list if f.get("issue")
            )

        # 综合 ≥ 80 但维度升级: 阻断
        if composite_score >= self.COMPOSITE_PASS and dim_escalated:
            dim_blocking = BlockingIssue(
                description=f"{len(dim_warnings)} 个维度得分低于 {self.DIMENSION_THRESHOLD}，方案结构性缺陷严重",
                fix_suggestion="需针对性修订低分维度",
            )
            feedback = (
                f"综合分达标但 {len(dim_warnings)} 个维度严重偏低，需针对性修订"
            )
            result = GateResult(
                gate_id=2,
                passed=False,
                blocking_issues=[dim_blocking],
                warnings=dim_warnings,
                revision_feedback=feedback,
            )
            self.gate_log.append(result)
            return result

        # 综合 ≥ 80 且无维度升级: 通过
        if composite_score >= self.COMPOSITE_PASS:
            result = GateResult(
                gate_id=2,
                passed=True,
                warnings=dim_warnings if dim_warnings else [],
            )
            self.gate_log.append(result)
            return result

        # 得分 < 60: REJECT
        if composite_score < self.COMPOSITE_REJECT:
            result = GateResult(
                gate_id=2,
                passed=False,
                rejected=True,
                blocking_issues=[BlockingIssue(
                    description=f"综合得分 {composite_score} < {self.COMPOSITE_REJECT}，严重缺陷，建议重新规划而非修订",
                )],
                warnings=dim_warnings,
            )
            self.gate_log.append(result)
            return result

        # 得分 60-79
        if iteration >= 3:
            # 达到最大迭代次数: 降级通过
            all_warnings = dim_warnings + [
                Warning_(description=f"已达最大迭代次数({iteration}/3)，降级输出")
            ]
            result = GateResult(
                gate_id=2,
                passed=True,
                degraded=True,
                warnings=all_warnings,
            )
            self.gate_log.append(result)
            return result

        # 得分 60-79 且未达迭代上限: 修订
        result = GateResult(
            gate_id=2,
            passed=False,
            blocking_issues=[BlockingIssue(
                description=f"综合得分 {composite_score} < {self.COMPOSITE_PASS}，需修订",
            )],
            warnings=dim_warnings,
            revision_feedback=revision_text or f"综合得分 {composite_score} 未达标",
        )
        self.gate_log.append(result)
        return result

    # ============================================================
    # Gate 3: 最终校验 — gate_definitions.md §5
    # ============================================================

    def run_gate_3(self, final_plan: Dict[str, Any]) -> GateResult:
        """执行 Gate 3 最终校验。

        检查结构完整性、内容完备性和格式合规性。

        Args:
            final_plan: FinalTravelPlan 字典，需包含:
                - transportation (dict)
                - accommodation (list)
                - daily_itinerary (list)
                - budget_breakdown (dict)
                - quality_report (dict)
                - summary (dict): {total_budget, degraded, degraded_reason}

        Returns:
            GateResult — passed=True 表示最终方案可输出。
        """
        blocking: List[BlockingIssue] = []

        if not final_plan:
            blocking.append(BlockingIssue(description="缺少最终方案"))
            result = GateResult(gate_id=3, passed=False, blocking_issues=blocking)
            self.gate_log.append(result)
            return result

        # 结构完整性
        if not final_plan.get("transportation"):
            blocking.append(BlockingIssue(
                description="缺少交通方案",
                fix_suggestion="请补充往返交通和当地交通方案",
            ))
        if not final_plan.get("accommodation"):
            blocking.append(BlockingIssue(
                description="缺少住宿方案",
                fix_suggestion="请补充住宿推荐",
            ))

        # 每日行程
        daily_itinerary = final_plan.get("daily_itinerary", [])
        if not daily_itinerary:
            blocking.append(BlockingIssue(
                description="缺少每日行程",
                fix_suggestion="请补充每日行程安排",
            ))
        else:
            for day_entry in daily_itinerary:
                day_num = day_entry.get("day", "?")
                activities = day_entry.get("activities", [])
                if len(activities) < 2:
                    blocking.append(BlockingIssue(
                        description=f"第{day_num}天活动不足 (至少2个)",
                        fix_suggestion=f"请为第{day_num}天补充至少2个活动",
                    ))

                meals = day_entry.get("meals", {})
                if isinstance(meals, dict):
                    meal_count = sum(
                        1 for k in ("breakfast", "lunch", "dinner")
                        if meals.get(k)
                    )
                else:
                    meal_count = len(meals) if isinstance(meals, list) else 0
                if meal_count < 2:
                    blocking.append(BlockingIssue(
                        description=f"第{day_num}天餐食推荐不足 (至少2餐)",
                        fix_suggestion=f"请为第{day_num}天补充餐食推荐",
                    ))

        # 预算合计
        budget_breakdown = final_plan.get("budget_breakdown", {})
        summary = final_plan.get("summary", {})
        total_budget = summary.get("total_budget", 0)
        total_allocated = sum(
            v for v in budget_breakdown.values()
            if isinstance(v, (int, float))
        )
        if total_allocated > total_budget:
            blocking.append(BlockingIssue(
                description=f"预算分配超支: {total_allocated} > {total_budget}",
                fix_suggestion="请调整预算分配，总分配额不得超过总预算",
            ))

        # 质量报告附件
        if not final_plan.get("quality_report"):
            blocking.append(BlockingIssue(
                description="缺少质量报告",
                fix_suggestion="请附加质量评估报告",
            ))

        # 降级标记
        if summary.get("degraded") and not summary.get("degraded_reason"):
            blocking.append(BlockingIssue(
                description="降级输出缺少降级原因",
                fix_suggestion="请标注 degraded_reason",
            ))

        result = GateResult(
            gate_id=3,
            passed=len(blocking) == 0,
            blocking_issues=blocking,
        )
        self.gate_log.append(result)
        return result

    # ============================================================
    # 辅助方法 — gate_definitions.md §7
    # ============================================================

    def get_gate_history(self) -> List[GateResult]:
        """返回所有 Gate 执行历史。"""
        return list(self.gate_log)

    def all_passed(self) -> bool:
        """检查是否所有 Gate 都通过。"""
        if not self.gate_log:
            return False
        return all(g.passed for g in self.gate_log)

    def last_result(self) -> Optional[GateResult]:
        """返回最近一次 Gate 执行结果。"""
        return self.gate_log[-1] if self.gate_log else None

    def reset(self) -> None:
        """清空 Gate 执行历史。"""
        self.gate_log.clear()
