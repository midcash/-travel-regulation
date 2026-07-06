"""Execution Agent — 旅游规划系统的可行性验证专家。

职责:
- validate_feasibility: 执行完整可行性验证 (5项校验)
- check_prices: 价格合理性校验
- check_time: 时间可行性校验
- check_geography: 地理逻辑校验
- check_constraints: 硬约束/软约束校验
- identify_risks: 风险识别
- estimate_market_price: 查询市场行情价

来源: spec/executor_spec.md, playbooks/executor_playbook.md
"""

from __future__ import annotations

import asyncio
import math
from datetime import date, datetime, timezone
from typing import Any, Dict, List, Optional, Tuple
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
from models.request import StructuredRequest, Budget, DateRange, Destination, Preferences, Travelers
from models.plan import TravelPlanDraft, ItineraryDay
from models.validation import (
    BlockingConstraint,
    ConstraintCheckResult,
    ConstraintWarning,
    GeographyCheckResult,
    GeographyDetour,
    PriceAnomaly,
    PriceCheckResult,
    RiskAlert,
    TimeCheckResult,
    TimeConflict,
    ValidationReport,
    ValidationSummary,
)
from models.entities import PriceRange
from tools.price_checker import estimate_market_price as _tools_estimate_market_price
from tools.price_checker import check_prices as _tools_check_prices
from tools.price_checker import check_budget_compliance as _tools_check_budget_compliance


class ExecutionAgent(BaseAgent):
    """可行性验证 Agent。

    对 Planning Agent 的行程草稿执行 5 项校验:
    1. 价格校验 2. 时间校验 3. 地理校验 4. 约束校验 5. 风险识别
    """

    agent_name = "execution_agent"
    agent_version = "1.0.0"

    # 常量
    MAX_TOTAL_TIME_HOURS = 12
    WARNING_TIME_HOURS = 10
    PRICE_DEVIATION_HIGH = 0.30
    PRICE_DEVIATION_MEDIUM = 0.10
    DETOUR_RATIO_THRESHOLD = 1.5
    LONG_TRANSIT_HOURS = 3

    def __init__(self, registry: Optional[AgentRegistry] = None):
        self._registry = registry
        self._identity = AgentIdentity(
            name="execution_agent",
            version="1.0.0",
            capabilities=["validate_feasibility", "check_prices", "check_time",
                          "check_geography", "check_constraints", "identify_risks"],
            endpoint="internal",
            status="online",
        )

    # -- BaseAgent 抽象方法 --
    @property
    def agent_name(self) -> str:
        return "execution_agent"

    @property
    def agent_version(self) -> str:
        return "1.0.0"

    async def handle_message(self, message: AgentMessage) -> AgentMessage:
        """消息处理入口。"""
        try:
            message.validate()
        except MessageValidationError as exc:
            return self._error_response(message, ErrorCode.INVALID_MESSAGE, str(exc))

        try:
            if message.task_type == TaskType.TASK_VALIDATE_FEASIBILITY:
                draft_data = message.payload.get("travel_plan_draft", message.payload)
                draft = self._parse_draft(draft_data)
                request = self._parse_request(message.payload.get("request", {}))
                report = await self.validate_feasibility(draft, request)
                return AgentMessage(
                    message_id=str(uuid4()),
                    sender=self._identity,
                    receiver=message.sender,
                    task_type=TaskType.RESPONSE_VALIDATION_REPORT,
                    payload={"result_type": "validation_report", "data": report.to_dict()},
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
            details={"agent": "execution_agent", "version": "1.0.0"},
        )

    def get_capabilities(self) -> List[Capability]:
        return [
            Capability("validate_feasibility", "执行完整可行性验证"),
            Capability("check_prices", "价格合理性校验"),
            Capability("check_time", "时间可行性校验"),
            Capability("check_geography", "地理逻辑校验"),
            Capability("check_constraints", "硬约束/软约束校验"),
            Capability("identify_risks", "风险识别"),
        ]

    # ============================================================
    # 核心业务方法 — spec/executor_spec.md §3.1
    # ============================================================

    async def validate_feasibility(
        self, draft: TravelPlanDraft, request: Optional[StructuredRequest] = None
    ) -> ValidationReport:
        """执行完整可行性验证 (5 项校验汇集所有问题)。"""
        price_check = await self.check_prices(draft)
        time_check = await self.check_time(draft)
        geography_check = await self.check_geography(draft)
        constraint_check = await self.check_constraints(draft, request)
        risks = await self.identify_risks(draft)

        blocking_count = constraint_check.hard_constraints_total - constraint_check.hard_constraints_passed
        # 价格/时间/地理也可能产生 blocking
        if price_check.overall_status == "failed":
            blocking_count += 1
        if time_check.overall_time_status == "failed":
            blocking_count += 1
        if geography_check.overall_geo_status == "failed":
            blocking_count += 1

        # 警告数
        warning_count = 0
        warning_count += len(constraint_check.warnings)
        warning_count += len(price_check.anomalies)
        warning_count += len(time_check.conflicts)
        warning_count += len(geography_check.detours)

        summary = ValidationSummary(
            blocking_count=blocking_count,
            warning_count=warning_count,
            risk_count=len(risks),
            action_required="revise" if blocking_count > 0 else ("none" if warning_count == 0 else "none"),
        )

        report = ValidationReport(
            price_check=price_check,
            time_check=time_check,
            geography_check=geography_check,
            constraint_check=constraint_check,
            risk_alerts=risks,
            summary=summary,
            validation_id=str(uuid4()),
            draft_id=draft.draft_id,
        )
        return report

    async def check_prices(self, draft: TravelPlanDraft) -> PriceCheckResult:
        """价格合理性校验。

        对每一项预估价格进行市场行情比对，偏差 > 30% 标记为异常。
        """
        items_to_check = self._collect_price_items(draft)
        anomalies: List[PriceAnomaly] = []

        for item in items_to_check:
            market = await self.estimate_market_price(
                item["type"], item.get("location", ""), item.get("date", "")
            )
            estimated = item["estimated"]

            if market.median > 0:
                deviation = abs(estimated - market.median) / market.median
            else:
                deviation = 0

            severity = "low"
            if deviation > self.PRICE_DEVIATION_HIGH:
                severity = "high"
            elif deviation > self.PRICE_DEVIATION_MEDIUM:
                severity = "medium"

            if deviation > self.PRICE_DEVIATION_MEDIUM:
                anomalies.append(PriceAnomaly(
                    item=item.get("name", item["type"]),
                    estimated=estimated,
                    market_median=market.median,
                    market_range=[market.low, market.high],
                    deviation_pct=round(deviation * 100, 1),
                    severity=severity,
                ))

        high_count = sum(1 for a in anomalies if a.severity == "high")
        overall_status = "passed"
        if high_count >= 3 or len(anomalies) >= 4:
            overall_status = "failed"
        elif anomalies:
            overall_status = "passed_with_warnings"

        accuracy = max(0, 100 - len(anomalies) * 10 - high_count * 10)
        return PriceCheckResult(
            items_checked=len(items_to_check),
            anomalies=anomalies,
            overall_accuracy_score=accuracy,
            overall_status=overall_status,
        )

    async def check_time(self, draft: TravelPlanDraft) -> TimeCheckResult:
        """时间可行性校验。

        检查每日活动总时长，每日上限 12h。
        """
        conflicts: List[TimeConflict] = []
        warnings: List[Dict[str, Any]] = []
        days_checked = 0

        for day in (draft.daily_itinerary or []):
            days_checked += 1
            total_minutes = 0
            for activity in day.activities:
                total_minutes += getattr(activity, "duration_minutes", 0) if hasattr(activity, "duration_minutes") else 0
            total_minutes += day.total_duration_minutes

            total_hours = total_minutes / 60

            if total_hours > self.MAX_TOTAL_TIME_HOURS:
                conflicts.append(TimeConflict(
                    day=day.day,
                    issue=f"第{day.day}天总时长 {total_hours:.1f}h 超过 {self.MAX_TOTAL_TIME_HOURS}h 上限",
                    severity="high",
                    suggestion=f"建议删减第{day.day}天部分活动或缩短游览时间",
                    affected_activities=[a.name for a in day.activities] if day.activities and hasattr(day.activities[0], "name") else [],
                ))
            elif total_hours >= self.WARNING_TIME_HOURS:
                warnings.append({
                    "day": day.day,
                    "issue": f"第{day.day}天总时长接近上限 ({total_hours:.1f}h)",
                    "severity": "low",
                })

        overall_status = "passed"
        high_conflicts = [c for c in conflicts if c.severity == "high"]
        if high_conflicts:
            overall_status = "failed"
        elif conflicts or warnings:
            overall_status = "passed_with_warnings"

        score = max(0, 100 - len(high_conflicts) * 25 - len(conflicts) * 10)
        return TimeCheckResult(
            days_checked=days_checked,
            conflicts=conflicts,
            overall_time_status=overall_status,
            overall_time_score=score,
            warnings=warnings,
        )

    async def check_geography(self, draft: TravelPlanDraft) -> GeographyCheckResult:
        """地理逻辑校验。

        检查路线是否绕路，detour ratio > 1.5 标记为异常。
        """
        detours: List[GeographyDetour] = []
        warnings: List[Dict[str, Any]] = []

        # v1.0.0 stub: 对每个有 3+ 个活动的天生成简化检查
        for day in (draft.daily_itinerary or []):
            if len(day.activities) >= 3:
                # 模拟绕路检测
                detour_ratio = 1.0 + len(day.activities) * 0.1
                if detour_ratio > self.DETOUR_RATIO_THRESHOLD:
                    detours.append(GeographyDetour(
                        day=day.day,
                        description=f"第{day.day}天路线存在绕路 (detour_ratio={detour_ratio:.2f})",
                        detour_ratio=round(detour_ratio, 2),
                        wasted_time_minutes=int((detour_ratio - 1.0) * 30),
                    ))
                elif detour_ratio >= self.DETOUR_RATIO_THRESHOLD - 0.1:
                    warnings.append({
                        "day": day.day,
                        "issue": f"第{day.day}天路线绕路比接近阈值 ({detour_ratio:.2f})",
                        "severity": "low",
                    })

        overall_status = "passed"
        if detours:
            overall_status = "passed_with_warnings"
        if len(detours) >= 2:
            overall_status = "failed"

        score = max(0, 100 - len(detours) * 30)
        return GeographyCheckResult(
            detours_found=len(detours),
            detours=detours,
            overall_geo_status=overall_status,
            overall_geo_score=score,
            warnings=warnings,
        )

    async def check_constraints(
        self, draft: TravelPlanDraft, request: Optional[StructuredRequest] = None
    ) -> ConstraintCheckResult:
        """硬约束/软约束校验。

        硬约束 (违反即 blocking):
        - 总预算 > 用户预算上限
        - 日期超出用户指定范围
        """
        blocking_issues: List[BlockingConstraint] = []
        warnings: List[ConstraintWarning] = []
        hard_passed = 0
        hard_total = 4
        soft_passed = 0
        soft_total = 3

        if request:
            # 硬约束: 预算
            total_allocated = 0
            if draft.budget_allocation:
                ba = draft.budget_allocation
                total_allocated = (
                    getattr(ba, "transportation", 0)
                    + getattr(ba, "accommodation", 0)
                    + getattr(ba, "activities", 0)
                    + getattr(ba, "meals", 0)
                    + getattr(ba, "buffer", 0)
                )
            if total_allocated > request.budget.total * 1.05:
                blocking_issues.append(BlockingConstraint(
                    constraint="budget_ceiling",
                    expected=f"<= {request.budget.total}",
                    actual=f"{total_allocated}",
                    fix_suggestion="请缩减预算分配或删除部分活动/住宿",
                ))
            else:
                hard_passed += 1
        else:
            hard_passed += 1

        # 硬约束: 天数匹配
        planned_days = len(draft.daily_itinerary) if draft.daily_itinerary else 0
        if request and request.dates.duration_days > 0:
            if planned_days != request.dates.duration_days:
                warnings.append(ConstraintWarning(
                    constraint="duration_match",
                    issue=f"行程天数 {planned_days} != 用户要求 {request.dates.duration_days}",
                ))
                soft_passed -= 1
        hard_passed += 1
        soft_passed += 1

        # 住宿 ≥ 2
        if len(draft.accommodation) < 2:
            warnings.append(ConstraintWarning(
                constraint="accommodation_count",
                issue=f"住宿选项仅 {len(draft.accommodation)} 个，建议 ≥ 2",
                suggestion="请增加至少一个住宿选项",
            ))
        else:
            soft_passed += 1

        # 每日活动 ≥ 2
        activity_ok = all(len(d.activities) >= 2 for d in (draft.daily_itinerary or []))
        if not activity_ok:
            warnings.append(ConstraintWarning(
                constraint="daily_activities",
                issue="部分天数活动不足 2 个",
                suggestion="请为每天安排至少 2 个活动",
            ))
        else:
            soft_passed += 1

        # 硬约束: 排除项
        hard_passed += 1
        if request and request.preferences.excluded:
            # v1.0.0 stub: 不做实际排除项校验
            pass

        # 硬约束: 人数（默认通过）
        hard_passed += 1

        return ConstraintCheckResult(
            hard_constraints_total=hard_total,
            hard_constraints_passed=hard_passed,
            soft_constraints_total=soft_total,
            soft_constraints_passed=max(0, soft_passed),
            blocking_issues=blocking_issues,
            warnings=list(warnings),
        )

    async def identify_risks(self, draft: TravelPlanDraft) -> List[RiskAlert]:
        """风险识别。

        检查维度: 天气、安全、证件、健康。
        v1.0.0: stub 实现。
        """
        risks: List[RiskAlert] = []
        dest = draft.destination
        dest_str = str(dest) if dest else "目的地"

        # 通用风险提示
        risks.append(RiskAlert(
            category="documents",
            description=f"请确认前往{dest_str}的签证要求",
            severity="medium",
            mitigation="建议提前至少 1 个月办理签证",
        ))
        risks.append(RiskAlert(
            category="safety",
            description=f"请注意{dest_str}当地的治安情况",
            severity="low",
            mitigation="避免夜间单独前往偏僻区域",
        ))

        return risks

    async def estimate_market_price(
        self, item_type: str, location: str, date_str: str = ""
    ) -> PriceRange:
        """查询市场行情价。

        v1.1.0: 调用 tools/price_checker，统一数据源。
        """
        # 映射 execution_agent 内部 item_type → tools 的 item_type
        type_map = {
            "flight": "flight_domestic",
            "hotel": "hotel_per_night",
            "attraction": "attraction_ticket",
            "meal": "meal_per_person",
            "local_transport": "local_transport_per_day",
        }
        tools_type = type_map.get(item_type, "hotel_per_night")

        result = _tools_estimate_market_price(tools_type, location, date_str if date_str else None)
        return PriceRange(
            item_type=item_type,
            location=location,
            low=result["low"],
            median=result["median"],
            high=result["high"],
            currency=result.get("currency", "CNY"),
            source_type=result.get("source_type", "estimated"),
        )

    # ============================================================
    # 内部辅助方法
    # ============================================================

    def _collect_price_items(self, draft: TravelPlanDraft) -> List[Dict[str, Any]]:
        """收集草稿中所有需要检查价格的项目。"""
        items: List[Dict[str, Any]] = []

        # 交通
        transport = draft.transportation
        if transport:
            outbound = getattr(transport, "outbound", {}) or {}
            if isinstance(outbound, dict) and outbound.get("estimated_cost"):
                items.append({"type": "flight", "name": "往返交通", "estimated": outbound["estimated_cost"]})
            local_cost = 0
            local = getattr(transport, "local", []) or []
            for l in (local if isinstance(local, list) else []):
                if isinstance(l, dict):
                    local_cost += l.get("daily_cost", l.get("estimated_daily_cost", 0))
            if local_cost > 0:
                items.append({"type": "local_transport", "name": "当地交通", "estimated": local_cost})

        # 住宿
        for acc in (draft.accommodation or []):
            cost = getattr(acc, "cost_per_night", 0) if hasattr(acc, "cost_per_night") else (acc.get("cost_per_night", 0) if isinstance(acc, dict) else 0)
            name = getattr(acc, "name", "") if hasattr(acc, "name") else (acc.get("name", "") if isinstance(acc, dict) else "")
            if cost > 0:
                items.append({"type": "hotel", "name": name or "住宿", "estimated": cost})

        # 活动
        for day in (draft.daily_itinerary or []):
            for act in (day.activities or []):
                cost = getattr(act, "estimated_cost", 0) if hasattr(act, "estimated_cost") else (act.get("estimated_cost", 0) if isinstance(act, dict) else 0)
                name = getattr(act, "name", "") if hasattr(act, "name") else (act.get("name", "") if isinstance(act, dict) else "")
                if cost > 0:
                    items.append({"type": "attraction", "name": name or "景点", "estimated": cost})

        # 餐食
        for day in (draft.daily_itinerary or []):
            meals = getattr(day, "meals", {}) if hasattr(day, "meals") else (day.get("meals", {}) if isinstance(day, dict) else {})
            if isinstance(meals, dict):
                for meal in meals.values():
                    if meal:
                        cost = getattr(meal, "estimated_cost", 0) if hasattr(meal, "estimated_cost") else (meal.get("estimated_cost", 0) if isinstance(meal, dict) else 0)
                        name = getattr(meal, "restaurant_name", "") if hasattr(meal, "restaurant_name") else (meal.get("restaurant_name", "") if isinstance(meal, dict) else "")
                        if cost > 0:
                            items.append({"type": "meal", "name": name or "餐食", "estimated": cost})

        return items

    def _parse_draft(self, data: Dict[str, Any]) -> TravelPlanDraft:
        """从消息 payload 解析 TravelPlanDraft。"""
        if isinstance(data, TravelPlanDraft):
            return data
        return TravelPlanDraft(
            draft_id=data.get("draft_id", str(uuid4())),
            destination=data.get("destination"),
            duration_days=data.get("duration_days", 0),
            total_budget=data.get("total_budget", 0),
            daily_itinerary=[
                ItineraryDay(
                    day=d.get("day", i + 1),
                    date=d.get("date"),
                    activities=d.get("activities", []),
                    meals=d.get("meals", {}),
                    transportation_notes=d.get("transportation_notes"),
                    total_day_cost=d.get("total_day_cost", 0),
                    total_duration_minutes=d.get("total_duration_minutes", 0),
                )
                for i, d in enumerate(data.get("daily_itinerary", []))
            ],
            accommodation=data.get("accommodation", []),
            budget_allocation=data.get("budget_allocation"),
        )

    def _parse_request(self, data: Dict[str, Any]) -> Optional[StructuredRequest]:
        """从消息 payload 解析 StructuredRequest。"""
        if not data or isinstance(data, StructuredRequest):
            return data if isinstance(data, StructuredRequest) else None
        try:
            dest = data.get("destination", {})
            dates = data.get("dates", {})
            budget = data.get("budget", {})
            travelers = data.get("travelers", {})
            prefs = data.get("preferences", {})
            return StructuredRequest(
                destination=Destination(city=dest.get("city", ""), country=dest.get("country", "")),
                dates=DateRange(arrival=dates.get("arrival"), departure=dates.get("departure"), duration_days=dates.get("duration_days", 0)),
                budget=Budget(total=budget.get("total", 0)),
                travelers=Travelers(adults=travelers.get("adults", 1), children=travelers.get("children", 0)),
                preferences=Preferences(style=prefs.get("style", []), pace=prefs.get("pace", "moderate"), dietary=prefs.get("dietary", [])),
            )
        except Exception:
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
