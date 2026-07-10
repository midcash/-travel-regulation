"""SelfCheck 规则引擎 — Planning 输出前纯计算自检。

v1.2.0 R2 — 将 Execution Agent 的部分校验逻辑前移为 Planning 的规则引擎自检。
纯计算，不调任何 API/LLM，始终可用。

检查项（5 项）:
1. 预算检查 (blocking): 每日总花费 ≤ total_budget / days × 1.1
2. 地理检查 (warning): 同天任意两个景点间 Haversine 距离 ≤ 30km
3. 重复检查 (blocking): 同一景点不出现超过 1 天
4. 完整度检查 (warning): 每天 ≥ 2 个活动 + ≥ 2 餐推荐
5. 硬约束检查 (blocking): 未推荐 excluded_types 中的类型、偏好风格匹配

来源: spec/system_spec.md, evaluation/reasoning_quality_rubric.md §5 (SFC)
"""

from __future__ import annotations

import math
from typing import Any, Dict, List, Optional

from models.plan import TravelPlanDraft, ItineraryDay
from models.request import StructuredRequest
from models.check import IssueType, SelfCheckIssue, SelfCheckResult

# ============================================================
# 常量
# ============================================================

EARTH_RADIUS_KM: float = 6371.0
"""地球半径 (km)，Haversine 公式参数。"""

MAX_GEO_DISTANCE_KM: float = 30.0
"""同天两景点间最大允许直线距离 (km)。"""

BUDGET_FLOAT_RATIO: float = 1.1
"""单日预算浮动比例（允许超出 10%）。"""

MIN_ACTIVITIES_PER_DAY: int = 2
"""每天最少活动数量。"""

MIN_MEALS_PER_DAY: int = 2
"""每天最少餐食推荐数量。"""

# 偏好风格 → 活动类型映射，用于 _check_constraints 的风格匹配
_STYLE_TO_ACTIVITY_TYPES: Dict[str, List[str]] = {
    "culture": ["culture"],
    "food": ["food"],
    "nature": ["nature"],
    "shopping": ["shopping"],
    "adventure": ["sports", "entertainment"],
    "relaxation": ["relaxation"],
    "entertainment": ["entertainment"],
    "sports": ["sports"],
}


# ============================================================
# SelfChecker
# ============================================================

class SelfChecker:
    """Planning 输出前规则引擎自检。

    纯计算，不调任何 API/LLM，始终可用。
    将 Execution Agent 的部分校验逻辑前移，
    减少 Planning→Execution 无效修订轮次。

    使用方式::

        checker = SelfChecker()
        result = checker.check(draft, request)
        if not result.passed:
            for issue in result.blocking_issues:
                print(f"[{issue.type.value}] {issue.location}: {issue.actual_value}")
    """

    # ============================================================
    # 公共 API
    # ============================================================

    def check(
        self, draft: TravelPlanDraft, request: StructuredRequest
    ) -> SelfCheckResult:
        """运行全部 5 项检查，返回 SelfCheckResult。

        Args:
            draft: Planning Agent 产出的行程草稿。
            request: 用户原始请求（含预算、偏好、排除项等约束）。

        Returns:
            SelfCheckResult:
            - 存在任何 blocking 级违规 → passed=False
            - 仅 warning 级违规 → passed 仍为 True（不阻断）
        """
        issues: List[SelfCheckIssue] = []
        issues.extend(self._check_budget(draft, request))
        issues.extend(self._check_geo(draft, request))
        issues.extend(self._check_duplication(draft, request))
        issues.extend(self._check_restaurant_duplication(draft, request))
        issues.extend(self._check_completeness(draft, request))
        issues.extend(self._check_constraints(draft, request))

        has_blocking = any(i.severity == "blocking" for i in issues)
        return SelfCheckResult(passed=not has_blocking, issues=issues)

    # ============================================================
    # 检查 1: 预算检查 (blocking)
    # ============================================================

    def _check_budget(
        self, draft: TravelPlanDraft, request: StructuredRequest
    ) -> List[SelfCheckIssue]:
        """每日总花费 ≤ total_budget / days × 1.1（允许 10% 浮动）。"""
        issues: List[SelfCheckIssue] = []

        days = (
            len(draft.daily_itinerary)
            if draft.daily_itinerary
            else draft.duration_days
        )
        if days <= 0 or draft.total_budget <= 0:
            return issues

        daily_budget_limit = draft.total_budget / days * BUDGET_FLOAT_RATIO

        for day in draft.daily_itinerary:
            daily_spend = self._calc_daily_spend(day)
            if daily_spend > daily_budget_limit:
                issues.append(
                    SelfCheckIssue(
                        type=IssueType.BUDGET_OVERSPEND,
                        location=f"第{day.day}天",
                        actual_value=round(daily_spend, 2),
                        expected=(
                            f"≤ {round(daily_budget_limit, 2)} "
                            f"{getattr(request.budget, 'currency', 'CNY')}"
                        ),
                        severity="blocking",
                    )
                )

        return issues

    # ============================================================
    # 检查 2: 地理检查 (warning)
    # ============================================================

    def _check_geo(
        self, draft: TravelPlanDraft, request: StructuredRequest
    ) -> List[SelfCheckIssue]:
        """同天任意两个景点间 Haversine 距离 ≤ 30km。

        注意：
        - 地理检查 severity='warning'（非 blocking），
          因为 Haversine 直线距离 ≠ 实际交通时间。
        - 景点若无 geo 信息（geo=None 或缺少 lat/lng），跳过该景点对。
        """
        issues: List[SelfCheckIssue] = []

        for day in draft.daily_itinerary:
            activities = day.activities
            if len(activities) < 2:
                continue

            for i in range(len(activities)):
                geo_i = self._get_activity_geo(activities[i])
                if geo_i is None:
                    continue
                for j in range(i + 1, len(activities)):
                    geo_j = self._get_activity_geo(activities[j])
                    if geo_j is None:
                        continue

                    distance = self._haversine_distance(
                        geo_i[0], geo_i[1], geo_j[0], geo_j[1]
                    )
                    if distance > MAX_GEO_DISTANCE_KM:
                        name_i = getattr(activities[i], "name", f"景点{i + 1}")
                        name_j = getattr(activities[j], "name", f"景点{j + 1}")
                        issues.append(
                            SelfCheckIssue(
                                type=IssueType.GEO_DISTANCE,
                                location=f"第{day.day}天 {name_i} vs {name_j}",
                                actual_value=round(distance, 1),
                                expected=f"≤ {MAX_GEO_DISTANCE_KM}km",
                                severity="warning",
                            )
                        )

        return issues

    # ============================================================
    # 检查 3: 重复检查 (blocking)
    # ============================================================

    def _check_duplication(
        self, draft: TravelPlanDraft, request: StructuredRequest
    ) -> List[SelfCheckIssue]:
        """同一景点不出现超过 1 天。

        收集全部天次的景点名称，发现跨天重复即产生 blocking 级违规。
        景点名称为空字符串时跳过。
        """
        issues: List[SelfCheckIssue] = []
        # name → list of day numbers
        name_to_days: Dict[str, List[int]] = {}

        for day in draft.daily_itinerary:
            for activity in day.activities:
                name = getattr(activity, "name", "")
                if not name or not name.strip():
                    continue
                name = name.strip()
                if name not in name_to_days:
                    name_to_days[name] = []
                name_to_days[name].append(day.day)

        for name, days_list in name_to_days.items():
            if len(days_list) > 1:
                issues.append(
                    SelfCheckIssue(
                        type=IssueType.DUPLICATE_ATTRACTION,
                        location=f"景点 '{name}'",
                        actual_value=f"出现于第{', '.join(str(d) for d in days_list)}天",
                        expected="不重复",
                        severity="blocking",
                    )
                )

        return issues

    # ============================================================
    # 检查 3b: 餐厅重复检查 (blocking)
    # ============================================================

    def _check_restaurant_duplication(
        self, draft: TravelPlanDraft, request: StructuredRequest
    ) -> List[SelfCheckIssue]:
        """同一餐厅不出现超过 1 天。

        收集全部天次的 meal.restaurant_name，
        发现跨天重复即产生 blocking 级违规。
        餐厅名称为空时跳过。
        """
        issues: List[SelfCheckIssue] = []
        # restaurant_name → list of day numbers
        name_to_days: Dict[str, List[int]] = {}

        for day in draft.daily_itinerary:
            for meal in day.meals.values():
                if meal is None:
                    continue
                name = getattr(meal, "restaurant_name", "")
                if not name or not name.strip():
                    continue
                name = name.strip()
                if name not in name_to_days:
                    name_to_days[name] = []
                name_to_days[name].append(day.day)

        for name, days_list in name_to_days.items():
            if len(days_list) > 1:
                issues.append(
                    SelfCheckIssue(
                        type=IssueType.DUPLICATE_RESTAURANT,
                        location=f"餐厅 '{name}'",
                        actual_value=f"出现于第{', '.join(str(d) for d in days_list)}天",
                        expected="不重复",
                        severity="blocking",
                    )
                )

        return issues

    # ============================================================
    # 检查 4: 完整度检查 (warning)
    # ============================================================

    def _check_completeness(
        self, draft: TravelPlanDraft, request: StructuredRequest
    ) -> List[SelfCheckIssue]:
        """每天 ≥ 2 个活动 + ≥ 2 餐推荐。

        逐个检查每一天的活动数量和餐食数量，
        不足最低要求时产生 warning 级违规。
        """
        issues: List[SelfCheckIssue] = []

        for day in draft.daily_itinerary:
            activity_count = len(day.activities)
            if activity_count < MIN_ACTIVITIES_PER_DAY:
                issues.append(
                    SelfCheckIssue(
                        type=IssueType.MISSING_ACTIVITY,
                        location=f"第{day.day}天",
                        actual_value=f"仅 {activity_count} 个活动",
                        expected=f"≥ {MIN_ACTIVITIES_PER_DAY} 个活动",
                        severity="warning",
                    )
                )

            meal_count = sum(
                1 for m in day.meals.values() if m is not None
            )
            if meal_count < MIN_MEALS_PER_DAY:
                issues.append(
                    SelfCheckIssue(
                        type=IssueType.MISSING_MEAL,
                        location=f"第{day.day}天",
                        actual_value=f"仅 {meal_count} 餐推荐",
                        expected=f"≥ {MIN_MEALS_PER_DAY} 餐推荐",
                        severity="warning",
                    )
                )

        return issues

    # ============================================================
    # 检查 5: 硬约束检查 (blocking + warning)
    # ============================================================

    def _check_constraints(
        self, draft: TravelPlanDraft, request: StructuredRequest
    ) -> List[SelfCheckIssue]:
        """未推荐 excluded_types 中的类型、偏好风格基本匹配。"""
        issues: List[SelfCheckIssue] = []
        issues.extend(self._check_excluded_types(draft, request))
        issues.extend(self._check_style_match(draft, request))
        return issues

    def _check_excluded_types(
        self, draft: TravelPlanDraft, request: StructuredRequest
    ) -> List[SelfCheckIssue]:
        """检查是否推荐了用户明确排除的活动类型 (blocking)。"""
        issues: List[SelfCheckIssue] = []

        excluded = list(request.preferences.excluded) if request.preferences else []
        excluded_lower = {e.strip().lower() for e in excluded if e and e.strip()}
        if not excluded_lower:
            return issues

        for day in draft.daily_itinerary:
            for activity in day.activities:
                activity_type = getattr(activity, "type", "")
                if not activity_type:
                    continue
                if activity_type.strip().lower() in excluded_lower:
                    name = getattr(activity, "name", "未知景点")
                    issues.append(
                        SelfCheckIssue(
                            type=IssueType.EXCLUDED_TYPE,
                            location=f"第{day.day}天 {name}",
                            actual_value=f"type='{activity_type}'",
                            expected=(
                                f"不可为排除类型: "
                                f"{', '.join(sorted(excluded_lower))}"
                            ),
                            severity="blocking",
                        )
                    )

        return issues

    def _check_style_match(
        self, draft: TravelPlanDraft, request: StructuredRequest
    ) -> List[SelfCheckIssue]:
        """检查活动类型与用户偏好风格的匹配率 (warning)。"""
        issues: List[SelfCheckIssue] = []
        preferred_styles = (
            list(request.preferences.style) if request.preferences else []
        )
        if not preferred_styles:
            return issues

        # 收集偏好风格对应的可接受活动类型
        allowed_types: set = set()
        for style in preferred_styles:
            key = style.strip().lower()
            allowed_types.update(
                _STYLE_TO_ACTIVITY_TYPES.get(key, [key])
            )

        if not allowed_types:
            return issues

        total = matched = 0
        for day in draft.daily_itinerary:
            for activity in day.activities:
                total += 1
                atype = getattr(activity, "type", "")
                if atype and atype.strip().lower() in allowed_types:
                    matched += 1

        if total > 0:
            ratio = matched / total
            if ratio < 0.5:
                issues.append(
                    SelfCheckIssue(
                        type=IssueType.STYLE_MISMATCH,
                        location="整体行程",
                        actual_value=(
                            f"风格匹配 {matched}/{total} "
                            f"({round(ratio * 100)}%)"
                        ),
                        expected=(
                            f"偏好风格 {preferred_styles} "
                            f"对应活动类型 {sorted(allowed_types)}"
                        ),
                        severity="warning",
                    )
                )

        return issues

    # ============================================================
    # 静态工具方法
    # ============================================================

    @staticmethod
    def _calc_daily_spend(day: ItineraryDay) -> float:
        """计算单日总花费（活动 + 餐食 + 已声明的日总费用中取最大值）。

        Args:
            day: 单日行程。

        Returns:
            当日总花费金额。
        """
        activity_cost = sum(
            getattr(a, "estimated_cost", 0) for a in day.activities
        )
        meal_cost = 0
        for meal in day.meals.values():
            if meal is not None:
                meal_cost += getattr(meal, "estimated_cost", 0)
        return max(activity_cost + meal_cost, getattr(day, "total_day_cost", 0))

    @staticmethod
    def _haversine_distance(
        lat1: float, lng1: float, lat2: float, lng2: float
    ) -> float:
        """计算两点间的 Haversine 球面距离 (km)。

        公式:
            a = sin²(Δlat/2) + cos(lat1) * cos(lat2) * sin²(Δlng/2)
            c = 2 * atan2(√a, √(1-a))
            d = R * c

        Args:
            lat1: 点 1 纬度 (度)。
            lng1: 点 1 经度 (度)。
            lat2: 点 2 纬度 (度)。
            lng2: 点 2 经度 (度)。

        Returns:
            两点球面距离 (km)。
        """
        dlat = math.radians(lat2 - lat1)
        dlng = math.radians(lng2 - lng1)
        a = (
            math.sin(dlat / 2) ** 2
            + math.cos(math.radians(lat1))
            * math.cos(math.radians(lat2))
            * math.sin(dlng / 2) ** 2
        )
        c = 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))
        return EARTH_RADIUS_KM * c

    @staticmethod
    def _get_activity_geo(activity: Any) -> Optional[tuple]:
        """从活动对象中提取 (lat, lng) 坐标。

        兼容多种坐标来源:
        1. activity.geo (GeoLocation 对象，来自 models/entities.py)
        2. activity.location 为带 lat/lng 的 dict

        Args:
            activity: Activity 或类似对象。

        Returns:
            (lat, lng) 元组，或 None（无法获取坐标时）。
        """
        # 方式 1: activity.geo 是 GeoLocation 对象
        geo = getattr(activity, "geo", None)
        if geo is not None:
            lat = getattr(geo, "lat", None)
            lng = getattr(geo, "lng", None)
            if lat is not None and lng is not None:
                return (float(lat), float(lng))

        # 方式 2: activity.location 是包含 lat/lng 的 dict
        location = getattr(activity, "location", None)
        if isinstance(location, dict):
            lat = location.get("lat")
            lng = location.get("lng")
            if lat is not None and lng is not None:
                return (float(lat), float(lng))

        # 无法获取坐标
        return None
