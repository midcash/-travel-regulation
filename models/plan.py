"""旅行计划数据模型。

包含旅行计划所需的全部数据类：
- Transportation / AccommodationOption / Activity / Meal / ItineraryDay
- BudgetAllocation / TravelPlanDraft / FinalTravelPlan

来源: spec/system_spec.md, spec/planner_spec.md, playbooks/orchestrator_playbook.md
"""

from __future__ import annotations

from dataclasses import dataclass, field, asdict
from enum import Enum
from typing import Any, Dict, List, Optional


class ActivityType(str, Enum):
    """活动类型枚举。

    Values:
        NATURE: 自然风光
        CULTURE: 文化历史
        ENTERTAINMENT: 娱乐休闲
        FOOD: 美食体验
        SHOPPING: 购物消费
        SPORTS: 体育运动
        RELAXATION: 放松休息
    """
    NATURE = "nature"
    CULTURE = "culture"
    ENTERTAINMENT = "entertainment"
    FOOD = "food"
    SHOPPING = "shopping"
    SPORTS = "sports"
    RELAXATION = "relaxation"


class MealType(str, Enum):
    """餐食类型枚举。

    Values:
        BREAKFAST: 早餐
        LUNCH: 午餐
        DINNER: 晚餐
        SNACK: 小吃/加餐
    """
    BREAKFAST = "breakfast"
    LUNCH = "lunch"
    DINNER = "dinner"
    SNACK = "snack"


class AccommodationType(str, Enum):
    """住宿类型枚举。

    Values:
        HOTEL: 酒店
        HOSTEL: 青年旅舍
        RESORT: 度假村
        GUESTHOUSE: 民宿/客栈
    """
    HOTEL = "hotel"
    HOSTEL = "hostel"
    RESORT = "resort"
    GUESTHOUSE = "guesthouse"


@dataclass
class Transportation:
    """交通方案数据模型。

    包含往返大交通（飞机/火车等）和当地每日交通信息。
    """
    outbound: Dict[str, Any] = field(default_factory=dict)
    """去程交通信息（航班/火车/自驾等）。"""
    return_trip: Dict[str, Any] = field(default_factory=dict)
    """返程交通信息（航班/火车/自驾等）。"""
    local: List[Dict[str, Any]] = field(default_factory=list)
    """当地每日交通信息列表。"""
    total_cost: float = 0
    """交通总费用。"""

    def to_dict(self) -> Dict[str, Any]:
        """将数据类转换为字典格式。"""
        return asdict(self)


@dataclass
class AccommodationOption:
    """住宿选项数据模型。

    表示一个推荐的住宿选项，包含价格、位置、评分等信息。
    至少应提供 2 个不同价位或风格的选项供用户选择。
    """
    name: str
    """住宿名称。"""
    location: str
    """住宿位置/地址。"""
    type: str
    """住宿类型：hotel/hostel/resort/guesthouse。"""
    cost_per_night: float
    """每晚价格。"""
    total_cost: float
    """总住宿费用（每晚价格 x 住宿天数）。"""
    distance_to_center_km: float
    """距离市中心的距离（公里）。"""
    highlights: List[str] = field(default_factory=list)
    """亮点/特色描述列表。"""
    rating: Optional[float] = None
    """评分（可选，如 4.5）。"""

    def to_dict(self) -> Dict[str, Any]:
        """将数据类转换为字典格式。"""
        return asdict(self)


@dataclass
class Activity:
    """活动数据模型。

    表示每日行程中的一个具体活动/景点。
    每个活动必须有具体的推荐理由（至少 10 个字符）。
    """
    name: str
    """活动/景点名称。"""
    type: str
    """活动类型：nature/culture/entertainment/food/shopping/sports/relaxation。"""
    start_time: str
    """开始时间（如 '09:00'）。"""
    duration_minutes: int
    """建议游览时长（分钟）。"""
    location: str
    """活动地点。"""
    estimated_cost: float
    """预估费用（门票/消费等）。"""
    reason: str
    """推荐理由，必须具体且至少 10 个字符。"""
    notes: Optional[str] = None
    """备注信息（可选，如注意事项、提示等）。"""

    def __post_init__(self) -> None:
        """验证推荐理由长度是否满足最低要求。"""
        if len(self.reason) < 10:
            raise ValueError(
                f"推荐理由至少需要 10 个字符，当前为 {len(self.reason)} 个: {self.reason!r}"
            )

    def to_dict(self) -> Dict[str, Any]:
        """将数据类转换为字典格式。"""
        return asdict(self)


@dataclass
class Meal:
    """餐食数据模型。

    表示一餐推荐，包含餐厅信息、菜系和费用。
    必须考虑用户的饮食限制。
    """
    type: str
    """餐食类型：breakfast/lunch/dinner/snack。"""
    restaurant_name: str
    """餐厅名称。"""
    location: str
    """餐厅位置。"""
    cuisine: str
    """菜系（如 '川菜'、'Italian'）。"""
    estimated_cost: float
    """预估费用。"""
    dietary_compatible: bool = True
    """是否兼容用户的饮食限制。"""
    notes: Optional[str] = None
    """备注信息（可选）。"""

    def to_dict(self) -> Dict[str, Any]:
        """将数据类转换为字典格式。"""
        return asdict(self)


@dataclass
class ItineraryDay:
    """单日行程数据模型。

    表示一天完整的行程安排，包含活动、餐食和交通备注。
    每天至少应有 2 个主要活动和 3 餐推荐。
    """
    day: int
    """第几天（从 1 开始）。"""
    date: Optional[str] = None
    """日期（YYYY-MM-DD 格式，可选）。"""
    activities: List[Activity] = field(default_factory=list)
    """当日活动列表。"""
    meals: Dict[str, Optional[Meal]] = field(default_factory=dict)
    """当日餐食字典，键为 breakfast/lunch/dinner。"""
    transportation_notes: Optional[str] = None
    """当日交通备注（可选）。"""
    total_day_cost: float = 0
    """当日总费用。"""
    total_duration_minutes: int = 0
    """当日活动与交通总时长（分钟）。"""

    def to_dict(self) -> Dict[str, Any]:
        """将数据类转换为字典格式。"""
        return asdict(self)


@dataclass
class BudgetAllocation:
    """预算分配数据模型。

    将总预算分配到交通、住宿、活动、餐饮和缓冲金各分项。
    """
    transportation: float = 0
    """交通预算。"""
    accommodation: float = 0
    """住宿预算。"""
    activities: float = 0
    """活动预算。"""
    meals: float = 0
    """餐饮预算。"""
    buffer: float = 0
    """缓冲金（建议占总预算的 5%-10%）。"""
    currency: str = "CNY"
    """货币单位（默认 CNY）。"""

    def to_dict(self) -> Dict[str, Any]:
        """将数据类转换为字典格式。"""
        return asdict(self)


@dataclass
class TravelPlanDraft:
    """旅行计划草稿数据模型。

    Planning Agent 的主要输出物，包含完整的行程方案草稿。
    后续由 Execution Agent 验证可行性，Evaluation Agent 评估质量。
    """
    draft_id: Optional[str] = None
    """草稿唯一标识。"""
    destination: Any = None
    """目的地信息（城市、国家等结构化数据）。"""
    duration_days: int = 0
    """旅行天数。"""
    transportation: Transportation = field(default_factory=Transportation)
    """交通方案。"""
    accommodation: List[AccommodationOption] = field(default_factory=list)
    """住宿选项列表（至少 2 个选项）。"""
    daily_itinerary: List[ItineraryDay] = field(default_factory=list)
    """每日行程列表。"""
    budget_allocation: BudgetAllocation = field(default_factory=BudgetAllocation)
    """预算分配。"""
    total_budget: float = 0
    """总预算。"""
    preferences_applied: List[str] = field(default_factory=list)
    """已应用的用户偏好标签列表。"""
    revision_version: int = 0
    """修订版本号（0 = 原始版本，1+ = 修订版）。"""
    created_at: Optional[str] = None
    """创建时间（ISO 8601 格式，可选）。"""
    constraints_met: List[str] = field(default_factory=list)
    """已满足的约束条件列表。"""
    constraints_unmet: List[str] = field(default_factory=list)
    """未满足的约束条件列表。"""

    def to_dict(self) -> Dict[str, Any]:
        """将数据类转换为字典格式。"""
        return asdict(self)


@dataclass
class FinalTravelPlan:
    """最终旅行计划数据模型。

    Orchestrator 整合所有 Agent 产出后的最终输出物。
    通过 Gate 3 检查后交付给用户。
    """
    plan_id: str
    """计划唯一标识（UUID）。"""
    summary: Dict[str, Any]
    """计划摘要（目的地、天数、总预算、总体评分等）。"""
    transportation: Dict[str, Any]
    """交通方案总览（往返 + 当地交通）。"""
    accommodation: List[Dict[str, Any]]
    """住宿信息列表。"""
    daily_itinerary: List[Dict[str, Any]]
    """每日行程列表。"""
    budget_breakdown: Dict[str, Any]
    """预算明细（分项金额 + 货币单位）。"""
    quality_report: Dict[str, Any]
    """质量报告（综合评分、门禁结果、迭代轮次等）。"""
    metadata: Dict[str, Any]
    """元数据（版本信息、处理时间戳、参与 Agent 等）。"""

    def to_dict(self) -> Dict[str, Any]:
        """将数据类转换为字典格式。"""
        return asdict(self)
