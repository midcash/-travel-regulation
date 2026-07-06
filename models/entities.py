"""旅游规划编排系统的实体数据模型。

包含所有核心业务实体:
- GeoLocation / Attraction / Restaurant / Accommodation (景点/餐饮/住宿)
- DestinationInfo / PriceRange (目的地信息/价格范围)
- DietaryPreferences / RevisionFeedback / RevisionDecision (偏好/修订反馈/决策)

来源: spec/planner_spec.md §4, spec/executor_spec.md §3.1, spec/executor_spec.md §4.2
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional


# ============================================================
# GeoLocation — spec/planner_spec.md §4 (隐含依赖)
# ============================================================

@dataclass
class GeoLocation:
    """地理坐标位置。

    用于 Attraction / Restaurant / Accommodation 的可选地理标注，
    支持距离计算和路线优化。
    """

    lat: float
    """纬度 (WGS-84, -90 ~ 90)。"""

    lng: float
    """经度 (WGS-84, -180 ~ 180)。"""

    address: Optional[str] = None
    """文本地址描述，可选。"""

    def to_dict(self) -> Dict[str, Any]:
        """将实例序列化为字典。"""
        return {
            "lat": self.lat,
            "lng": self.lng,
            "address": self.address,
        }


# ============================================================
# Attraction — spec/planner_spec.md §4.1
# ============================================================

@dataclass
class Attraction:
    """景点推荐实体。

    约束 (spec/planner_spec.md §4.1):
    - 必须包含: 名称、位置、类型、建议时长、预估价格、推荐理由
    - 类型枚举: nature | culture | entertainment | food | shopping | sports | relaxation
    - 推荐理由必须 >= 10 字
    """

    name: str
    """景点名称。"""

    location: str
    """景点位置描述 (如城市/区域/地址)。"""

    geo: Optional[GeoLocation] = None
    """可选的地理坐标，用于距离计算和路线优化。"""

    type: str = "culture"
    """景点类型: nature | culture | entertainment | food | shopping | sports | relaxation。"""

    suggested_duration_minutes: int = 60
    """建议游览时长 (分钟)。"""

    estimated_price: float = 0.0
    """预估门票/活动价格 (CNY)。"""

    rating: Optional[float] = None
    """用户评分 (1.0 ~ 5.0)，可选。"""

    reason: str = ""
    """推荐理由。约束: 必须 >= 10 个字符，不得为泛泛之辞。"""

    opening_hours: Optional[str] = None
    """开放时间描述 (如 "09:00-17:00")，可选。"""

    peak_season: Optional[List[str]] = None
    """旺季月份列表 (如 ["6月", "7月", "8月"])，可选。"""

    def __post_init__(self) -> None:
        if self.reason and len(self.reason) < 10:
            raise ValueError(
                f"推荐理由至少需要 10 个字符，当前为 {len(self.reason)} 个: {self.reason!r}"
            )

    def to_dict(self) -> Dict[str, Any]:
        """将实例序列化为字典。"""
        return {
            "name": self.name,
            "location": self.location,
            "geo": self.geo.to_dict() if self.geo else None,
            "type": self.type,
            "suggested_duration_minutes": self.suggested_duration_minutes,
            "estimated_price": self.estimated_price,
            "rating": self.rating,
            "reason": self.reason,
            "opening_hours": self.opening_hours,
            "peak_season": self.peak_season,
        }


# ============================================================
# Restaurant — spec/planner_spec.md §4.2
# ============================================================

@dataclass
class Restaurant:
    """餐厅推荐实体。

    约束 (spec/planner_spec.md §4.2):
    - 必须包含: 名称、位置、菜系、人均价格、与景点距离
    - 必须考虑用户的饮食限制
    - 一日三餐必须覆盖不同的菜系或风格
    """

    name: str
    """餐厅名称。"""

    location: str
    """餐厅位置描述。"""

    geo: Optional[GeoLocation] = None
    """可选的地理坐标。"""

    cuisine: str = ""
    """菜系类型 (如 "日式", "法式", "粤菜")。"""

    price_per_person: float = 0.0
    """人均消费价格 (CNY)。"""

    distance_to_attraction_km: Optional[float] = None
    """与最近/关联景点的距离 (公里)，可选。"""

    dietary_options: List[str] = field(default_factory=list)
    """支持的饮食选项列表 (如 "vegetarian", "vegan", "halal", "gluten_free")。"""

    rating: Optional[float] = None
    """用户评分 (1.0 ~ 5.0)，可选。"""

    meal_types: List[str] = field(default_factory=lambda: ["breakfast", "lunch", "dinner"])
    """可提供的餐段: breakfast | lunch | dinner。"""

    notes: Optional[str] = None
    """补充说明 (如招牌菜、高峰期等)，可选。"""

    def to_dict(self) -> Dict[str, Any]:
        """将实例序列化为字典。"""
        return {
            "name": self.name,
            "location": self.location,
            "geo": self.geo.to_dict() if self.geo else None,
            "cuisine": self.cuisine,
            "price_per_person": self.price_per_person,
            "distance_to_attraction_km": self.distance_to_attraction_km,
            "dietary_options": self.dietary_options,
            "rating": self.rating,
            "meal_types": self.meal_types,
            "notes": self.notes,
        }


# ============================================================
# Accommodation — spec/planner_spec.md §4.3
# ============================================================

@dataclass
class Accommodation:
    """住宿推荐实体。

    约束 (spec/planner_spec.md §4.3):
    - 至少 2 个选项 (不同价位或风格)
    - 必须包含: 名称、位置、类型、每晚价格、距市中心距离、亮点
    - 距主要景点聚集区 <= 10km 或地铁沿线
    """

    name: str
    """住宿名称。"""

    location: str
    """住宿位置描述。"""

    geo: Optional[GeoLocation] = None
    """可选的地理坐标。"""

    type: str = "hotel"
    """住宿类型: hotel | hostel | resort | guesthouse | apartment。"""

    price_per_night: float = 0.0
    """每晚价格 (CNY)。"""

    distance_to_center_km: float = 0.0
    """距市中心的距离 (公里)。"""

    highlights: List[str] = field(default_factory=list)
    """亮点列表 (如 "免费WiFi", "含早餐", "泳池")。"""

    rating: Optional[float] = None
    """用户评分 (1.0 ~ 5.0)，可选。"""

    amenity_tags: List[str] = field(default_factory=list)
    """设施标签列表 (如 "wifi", "parking", "gym", "pool")。"""

    def to_dict(self) -> Dict[str, Any]:
        """将实例序列化为字典。"""
        return {
            "name": self.name,
            "location": self.location,
            "geo": self.geo.to_dict() if self.geo else None,
            "type": self.type,
            "price_per_night": self.price_per_night,
            "distance_to_center_km": self.distance_to_center_km,
            "highlights": self.highlights,
            "rating": self.rating,
            "amenity_tags": self.amenity_tags,
        }


# ============================================================
# DestinationInfo — spec/planner_spec.md §3.1 (research_destination)
# ============================================================

@dataclass
class DestinationInfo:
    """目的地综合信息。

    由 research_destination() 返回，包含目的地的基础设施信息、
    文化背景和旅行注意事项。
    """

    destination: str
    """目的地名称 (如 "东京", "巴黎")。"""

    country: str
    """所属国家。"""

    currency: str
    """本地货币代码 (如 "JPY", "EUR")。"""

    language: str
    """主要语言。"""

    timezone: str
    """时区 (如 "Asia/Tokyo", "Europe/Paris")。"""

    best_season: List[str] = field(default_factory=list)
    """最佳旅行季节/月份列表。"""

    visa_required_for_cn: bool = True
    """中国护照是否需要签证。"""

    popular_areas: List[str] = field(default_factory=list)
    """热门区域列表。"""

    transportation_tips: Optional[str] = None
    """交通建议，可选。"""

    safety_level: str = "safe"
    """安全等级: safe | caution | risky。"""

    def to_dict(self) -> Dict[str, Any]:
        """将实例序列化为字典。"""
        return {
            "destination": self.destination,
            "country": self.country,
            "currency": self.currency,
            "language": self.language,
            "timezone": self.timezone,
            "best_season": self.best_season,
            "visa_required_for_cn": self.visa_required_for_cn,
            "popular_areas": self.popular_areas,
            "transportation_tips": self.transportation_tips,
            "safety_level": self.safety_level,
        }


# ============================================================
# PriceRange — spec/executor_spec.md §3.1 (estimate_market_price), §4.2
# ============================================================

@dataclass
class PriceRange:
    """市场价格范围，由 estimate_market_price() 返回。

    约束 (spec/executor_spec.md §4.2):
    - 所有价格必须标注货币单位
    - 必须注明价格来源类型: api | cache | estimated
    - 缓存数据必须标注数据日期 (data_date)
    """

    item_type: str
    """价格项目类型 (如 "flight", "hotel", "attraction", "meal")。"""

    location: str
    """价格适用的位置/地区。"""

    low: float
    """市场低价位估算。"""

    median: float
    """市场中位数价格估算。"""

    high: float
    """市场高价位估算。"""

    currency: str = "CNY"
    """货币单位，默认为 CNY。"""

    source_type: str = "estimated"
    """价格来源类型: api | cache | estimated。"""

    data_date: Optional[str] = None
    """数据日期 (YYYY-MM-DD)。当 source_type == "cache" 时必填。"""

    confidence: str = "medium"
    """置信度: high | medium | low。"""

    def __post_init__(self) -> None:
        if self.source_type == "cache" and not self.data_date:
            raise ValueError(
                "source_type='cache' 时 data_date 不能为空"
            )

    def to_dict(self) -> Dict[str, Any]:
        """将实例序列化为字典。"""
        return {
            "item_type": self.item_type,
            "location": self.location,
            "low": self.low,
            "median": self.median,
            "high": self.high,
            "currency": self.currency,
            "source_type": self.source_type,
            "data_date": self.data_date,
            "confidence": self.confidence,
        }


# ============================================================
# DietaryPreferences — spec/planner_spec.md §4.2, §5.2
# ============================================================

@dataclass
class DietaryPreferences:
    """用户饮食偏好。

    用于约束餐厅推荐，确保推荐的菜品满足用户的饮食限制。
    """

    restrictions: List[str] = field(default_factory=list)
    """饮食限制: vegetarian | vegan | halal | kosher | gluten_free | none。"""

    allergies: List[str] = field(default_factory=list)
    """过敏原列表 (如 "peanut", "seafood", "dairy")。"""

    spice_tolerance: str = "medium"
    """辣度耐受: none | mild | medium | high。"""

    notes: Optional[str] = None
    """补充说明，可选。"""

    def to_dict(self) -> Dict[str, Any]:
        """将实例序列化为字典。"""
        return {
            "restrictions": self.restrictions,
            "allergies": self.allergies,
            "spice_tolerance": self.spice_tolerance,
            "notes": self.notes,
        }


# ============================================================
# RevisionFeedback — spec/planner_spec.md §2.2
# ============================================================

@dataclass
class RevisionFeedback:
    """修订反馈条目，由 Evaluation Agent 生成。

    用于向 Planning Agent 反馈行程中的具体问题，
    支持精确指向需要修改的部分。
    """

    dimension: str
    """反馈维度 (如 "schedule", "budget", "geography", "restaurant", "accommodation")。"""

    issue: str
    """具体问题描述。"""

    suggestion: str
    """改进建议。"""

    priority: str = "medium"
    """优先级: high | medium | low。"""

    original_draft_id: Optional[str] = None
    """关联的原始草稿 ID，可选。用于追踪修订历史。"""

    def to_dict(self) -> Dict[str, Any]:
        """将实例序列化为字典。"""
        return {
            "dimension": self.dimension,
            "issue": self.issue,
            "suggestion": self.suggestion,
            "priority": self.priority,
            "original_draft_id": self.original_draft_id,
        }


# ============================================================
# RevisionDecision — spec/planner_spec.md §2.2
# ============================================================

@dataclass
class RevisionDecision:
    """修订决策，由 Evaluation Agent 的评估结果确定。

    决定行程草稿是否通过、需要修订、或降级处理。
    """

    decision: str = "REVISE"
    """决策: APPROVE | REVISE | DEGRADE。"""

    reason: str = ""
    """决策理由。"""

    iteration: int = 0
    """当前修订迭代次数 (从 0 开始，每次 REVISE 加 1)。"""

    feedback_items: List[RevisionFeedback] = field(default_factory=list)
    """反馈条目列表，REVISE 或 DEGRADE 时必须非空。"""

    def to_dict(self) -> Dict[str, Any]:
        """将实例序列化为字典。"""
        return {
            "decision": self.decision,
            "reason": self.reason,
            "iteration": self.iteration,
            "feedback_items": [item.to_dict() for item in self.feedback_items],
        }
