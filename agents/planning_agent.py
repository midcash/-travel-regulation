"""Planning Agent — 旅游规划系统的行程设计专家。

职责:
- create_itinerary: 根据结构化需求生成完整旅行行程草稿
- revise_itinerary: 基于评估反馈针对性修订行程
- research_destination: 研究目的地信息
- search_attractions/search_accommodations/search_restaurants: 搜索推荐项
- optimize_daily_schedule: 优化单日行程安排
- allocate_budget: 分配预算到各分项

来源: spec/planner_spec.md, playbooks/planner_playbook.md
"""

from __future__ import annotations

import asyncio
from datetime import date, datetime, timezone
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
from models.request import (
    Budget,
    DateRange,
    Destination,
    Preferences,
    StructuredRequest,
    Travelers,
)
from models.entities import (
    Accommodation,
    Attraction,
    DestinationInfo,
    DietaryPreferences,
    GeoLocation,
    PriceRange,
    Restaurant,
    RevisionDecision,
    RevisionFeedback,
)
from models.plan import (
    Activity,
    AccommodationOption,
    BudgetAllocation,
    ItineraryDay,
    Meal,
    Transportation,
    TravelPlanDraft,
)


class PlanningAgent(BaseAgent):
    """行程规划 Agent。

    负责将结构化用户需求转化为详细旅行方案，包括交通、住宿、
    每日行程和预算分配。
    """

    agent_name = "planning_agent"
    agent_version = "1.0.0"

    def __init__(self, registry: Optional[AgentRegistry] = None):
        self._registry = registry
        self._identity = AgentIdentity(
            name="planning_agent",
            version="1.0.0",
            capabilities=["create_itinerary", "revise_itinerary", "research_destination"],
            endpoint="internal",
            status="online",
        )

    # -- BaseAgent 抽象方法 --
    @property
    def agent_name(self) -> str:
        return "planning_agent"

    @property
    def agent_version(self) -> str:
        return "1.0.0"

    async def handle_message(self, message: AgentMessage) -> AgentMessage:
        """消息处理入口。

        根据 task_type 路由到 create_itinerary 或 revise_itinerary。
        """
        try:
            message.validate()
        except MessageValidationError as exc:
            return self._error_response(message, ErrorCode.INVALID_MESSAGE, str(exc))

        try:
            if message.task_type == TaskType.TASK_CREATE_ITINERARY:
                request_data = message.payload
                request = self._parse_request(request_data)
                draft = await self.create_itinerary(request)
                return AgentMessage(
                    message_id=str(uuid4()),
                    sender=self._identity,
                    receiver=message.sender,
                    task_type=TaskType.RESPONSE_ITINERARY_DRAFT,
                    payload={"result_type": "itinerary_draft", "data": draft.to_dict()},
                    timestamp=datetime.now(timezone.utc),
                    correlation_id=message.message_id,
                )

            elif message.task_type == TaskType.TASK_REVISE_ITINERARY:
                draft_data = message.payload.get("original_draft")
                feedback_data = message.payload.get("revision_feedback", [])
                draft = self._parse_draft(draft_data)
                feedback = [
                    RevisionFeedback(
                        dimension=f.get("dimension", ""),
                        issue=f.get("issue", ""),
                        suggestion=f.get("suggestion", ""),
                        priority=f.get("priority", "medium"),
                    )
                    for f in feedback_data
                ]
                revised = await self.revise_itinerary(draft, feedback)
                return AgentMessage(
                    message_id=str(uuid4()),
                    sender=self._identity,
                    receiver=message.sender,
                    task_type=TaskType.RESPONSE_ITINERARY_DRAFT,
                    payload={"result_type": "itinerary_draft", "data": revised.to_dict()},
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
            details={"agent": "planning_agent", "version": "1.0.0"},
        )

    def get_capabilities(self) -> List[Capability]:
        return [
            Capability("create_itinerary", "生成完整旅行行程草稿"),
            Capability("revise_itinerary", "基于反馈针对性修订行程"),
            Capability("research_destination", "研究目的地综合信息"),
            Capability("search_attractions", "搜索符合偏好的景点"),
            Capability("search_accommodations", "搜索符合预算和风格的住宿"),
            Capability("search_restaurants", "搜索符合饮食偏好的餐厅"),
        ]

    # ============================================================
    # 核心业务方法 — spec/planner_spec.md §3.1
    # ============================================================

    async def create_itinerary(self, request: StructuredRequest) -> TravelPlanDraft:
        """生成新的旅行行程草稿。

        按 SOP 顺序: 研究 → 筛选 → 编排 → 分配预算 → 组装输出。
        """
        dest = request.destination
        budget = request.budget
        prefs = request.preferences
        days = request.dates.duration_days or 3

        # Step 2: 研究
        dest_info = await self.research_destination(dest)
        attractions = await self.search_attractions(dest, prefs)
        accommodations = await self.search_accommodations(dest, budget, prefs.pace)
        dietary = DietaryPreferences(restrictions=prefs.dietary)
        restaurants = await self.search_restaurants(dest.city, dietary)

        # Step 3: 日程编排
        daily_itinerary: List[ItineraryDay] = []
        for day_idx in range(days):
            day_num = day_idx + 1
            day_date = self._compute_day_date(request.dates, day_idx)

            # 选取当天景点 (循环使用)
            day_attractions = [attractions[i % len(attractions)] for i in range(day_idx * 2, day_idx * 2 + 2)] if attractions else []

            activities = []
            if day_attractions:
                activities.append(Activity(
                    name=day_attractions[0].name,
                    type="culture",
                    start_time="09:00",
                    duration_minutes=120,
                    location=day_attractions[0].location,
                    estimated_cost=day_attractions[0].estimated_price,
                    reason=day_attractions[0].reason,
                ))
            if len(day_attractions) > 1:
                activities.append(Activity(
                    name=day_attractions[1].name,
                    type="nature",
                    start_time="13:00",
                    duration_minutes=90,
                    location=day_attractions[1].location,
                    estimated_cost=day_attractions[1].estimated_price,
                    reason=day_attractions[1].reason,
                ))

            # 餐食
            day_restaurants = [restaurants[i % len(restaurants)] for i in range(day_idx * 3, day_idx * 3 + 3)] if restaurants else []
            meals: Dict[str, Optional[Meal]] = {}
            meal_types = ["breakfast", "lunch", "dinner"]
            for m_idx, m_type in enumerate(meal_types):
                if m_idx < len(day_restaurants):
                    r = day_restaurants[m_idx]
                    meals[m_type] = Meal(
                        type=m_type,
                        restaurant_name=r.name,
                        location=r.location,
                        cuisine=r.cuisine,
                        estimated_cost=r.price_per_person,
                        dietary_compatible=bool(prefs.dietary),
                    )

            # 计算日费用
            day_cost = sum(a.estimated_cost for a in activities)
            day_cost += sum((m.estimated_cost for m in meals.values() if m), 0)

            daily_itinerary.append(ItineraryDay(
                day=day_num,
                date=day_date,
                activities=activities,
                meals=meals,
                transportation_notes="建议使用公共交通",
                total_day_cost=round(day_cost, 2),
                total_duration_minutes=sum(a.duration_minutes for a in activities) + 60,
            ))

        # Step 4: 预算分配
        budget_alloc = self.allocate_budget(daily_itinerary, accommodations, budget.total)

        # Step 5: 组装
        transport = Transportation(
            outbound={"mode": "飞机", "from": "出发地", "to": dest.city,
                      "estimated_cost": budget_alloc.transportation * 0.5,
                      "duration_minutes": 180},
            return_trip={"mode": "飞机", "from": dest.city, "to": "出发地",
                         "estimated_cost": budget_alloc.transportation * 0.5,
                         "duration_minutes": 180},
            local=[{"mode": "地铁/公交", "daily_cost": budget.total * 0.01}],
            total_cost=budget_alloc.transportation,
        )

        acc_options = [
            AccommodationOption(
                name=a.name,
                location=a.location,
                type=a.type,
                cost_per_night=a.price_per_night,
                total_cost=a.price_per_night * days,
                distance_to_center_km=a.distance_to_center_km,
                highlights=a.highlights,
                rating=a.rating,
            )
            for a in accommodations[:2]
        ]

        return TravelPlanDraft(
            draft_id=str(uuid4()),
            destination={"city": dest.city, "country": dest.country},
            duration_days=days,
            transportation=transport,
            accommodation=acc_options,
            daily_itinerary=daily_itinerary,
            budget_allocation=budget_alloc,
            total_budget=budget.total,
            preferences_applied=prefs.style,
            revision_version=0,
            created_at=datetime.now(timezone.utc).isoformat(),
            constraints_met=["destination", "duration", "budget"],
            constraints_unmet=[],
        )

    async def revise_itinerary(
        self, draft: TravelPlanDraft, feedback: List[RevisionFeedback]
    ) -> TravelPlanDraft:
        """基于评估反馈针对性修订行程。

        修订原则:
        - 聚焦: 只修改被指出的问题部分
        - 不退化: 不修改未被指出的部分
        - 透明: 增加 revision_version
        """
        revised = TravelPlanDraft(
            draft_id=str(uuid4()),
            destination=draft.destination,
            duration_days=draft.duration_days,
            transportation=draft.transportation,
            accommodation=list(draft.accommodation),
            daily_itinerary=[ItineraryDay(
                day=d.day,
                date=d.date,
                activities=list(d.activities),
                meals=dict(d.meals),
                transportation_notes=d.transportation_notes,
                total_day_cost=d.total_day_cost,
                total_duration_minutes=d.total_duration_minutes,
            ) for d in draft.daily_itinerary],
            budget_allocation=draft.budget_allocation,
            total_budget=draft.total_budget,
            preferences_applied=list(draft.preferences_applied),
            revision_version=draft.revision_version + 1,
            created_at=datetime.now(timezone.utc).isoformat(),
            constraints_met=list(draft.constraints_met),
            constraints_unmet=list(draft.constraints_unmet),
        )

        # 聚焦修订: 仅处理反馈中提到的问题
        for fb in feedback:
            # v1.0.0 stub: 记录反馈但不做实质性修改
            # 真实实现会解析 feedback.dimension 和 feedback.issue 进行针对性修改
            pass

        return revised

    async def research_destination(self, destination: Destination) -> DestinationInfo:
        """研究目的地综合信息。

        v1.0.0: stub 实现，返回预置数据。
        """
        await asyncio.sleep(0.005)
        return DestinationInfo(
            destination=destination.city,
            country=destination.country,
            currency="CNY" if destination.country == "中国" else "USD",
            language="中文" if destination.country == "中国" else "当地语言",
            timezone="Asia/Shanghai" if destination.country == "中国" else "UTC+0",
            best_season=["4月", "5月", "9月", "10月"],
            popular_areas=[f"{destination.city}市中心", f"{destination.city}老城区"],
        )

    async def search_attractions(
        self, destination: Destination, preferences: Preferences
    ) -> List[Attraction]:
        """搜索符合偏好的景点。

        v1.0.0: stub 实现，返回模板化景点。
        """
        await asyncio.sleep(0.005)
        city = destination.city
        styles = preferences.style or ["culture", "nature"]

        attractions: List[Attraction] = []
        for i, style in enumerate(styles[:4]):
            attractions.append(Attraction(
                name=f"{city}{style}景点{i+1}",
                location=f"{city}市中心",
                type=style,
                suggested_duration_minutes=120 if style == "culture" else 90,
                estimated_price=100.0 if style == "culture" else 50.0,
                reason=f"{city}著名的{style}景点，游客必去之地，评分很高",
            ))
        return attractions

    async def search_accommodations(
        self, destination: Destination, budget: Budget, style: str
    ) -> List[Accommodation]:
        """搜索符合预算和风格的住宿。

        v1.0.0: stub 实现。
        """
        await asyncio.sleep(0.005)
        city = destination.city
        return [
            Accommodation(
                name=f"{city}舒心酒店",
                location=f"{city}市中心",
                type="hotel",
                price_per_night=budget.total * 0.07,
                distance_to_center_km=1.5,
                highlights=["交通便利", "含早餐", "免费WiFi"],
                rating=4.5,
            ),
            Accommodation(
                name=f"{city}经济宾馆",
                location=f"{city}近郊",
                type="hotel",
                price_per_night=budget.total * 0.05,
                distance_to_center_km=5.0,
                highlights=["安静舒适", "性价比高"],
                rating=4.2,
            ),
        ]

    async def search_restaurants(
        self, location: str, preferences: DietaryPreferences
    ) -> List[Restaurant]:
        """搜索符合饮食偏好的餐厅。

        v1.0.0: stub 实现。
        """
        await asyncio.sleep(0.005)
        cuisines = ["当地特色", "亚洲料理", "国际美食"]
        restaurants: List[Restaurant] = []
        for i, cuisine in enumerate(cuisines):
            restaurants.append(Restaurant(
                name=f"{location}{cuisine}餐厅{i+1}",
                location=f"{location}市中心",
                cuisine=cuisine,
                price_per_person=80.0,
                distance_to_attraction_km=1.0,
                dietary_options=preferences.restrictions,
                meal_types=["breakfast", "lunch", "dinner"],
                rating=4.3,
            ))
        return restaurants

    async def optimize_daily_schedule(
        self, attractions: List[Attraction], day_index: int
    ) -> Dict[str, Any]:
        """优化单日行程安排。

        v1.0.0: stub 实现，按地理分组和开放时间排列。
        """
        await asyncio.sleep(0.005)
        return {
            "day": day_index + 1,
            "attractions": [a.name for a in attractions],
            "optimized": True,
        }

    def allocate_budget(
        self,
        daily_itinerary: List[ItineraryDay],
        accommodations: List[Accommodation],
        total_budget: float,
    ) -> BudgetAllocation:
        """分配预算到各分项。

        原则:
        - 交通 30%
        - 住宿 35%
        - 活动 15%
        - 餐饮 15%
        - 缓冲 5%
        """
        days = len(daily_itinerary)
        return BudgetAllocation(
            transportation=round(total_budget * 0.30, 2),
            accommodation=round(total_budget * 0.35, 2),
            activities=round(total_budget * 0.15, 2),
            meals=round(total_budget * 0.15, 2),
            buffer=round(total_budget * 0.05, 2),
            currency="CNY",
        )

    # ============================================================
    # 内部辅助方法
    # ============================================================

    def _parse_request(self, data: Dict[str, Any]) -> StructuredRequest:
        """从消息 payload 中解析 StructuredRequest。"""
        dest_data = data.get("destination", {})
        dates_data = data.get("dates", {})
        budget_data = data.get("budget", {})
        travelers_data = data.get("travelers", {})
        prefs_data = data.get("preferences", {})

        return StructuredRequest(
            destination=Destination(
                city=dest_data.get("city", "未知"),
                country=dest_data.get("country", "未知"),
            ),
            dates=DateRange(
                arrival=dates_data.get("arrival"),
                departure=dates_data.get("departure"),
                duration_days=dates_data.get("duration_days", 0),
            ),
            budget=Budget(total=budget_data.get("total", 0)),
            travelers=Travelers(
                adults=travelers_data.get("adults", 1),
                children=travelers_data.get("children", 0),
            ),
            preferences=Preferences(
                style=prefs_data.get("style", []),
                pace=prefs_data.get("pace", "moderate"),
                dietary=prefs_data.get("dietary", []),
            ),
            request_id=data.get("request_id"),
        )

    def _parse_draft(self, data: Optional[Dict[str, Any]]) -> TravelPlanDraft:
        """从字典恢复 TravelPlanDraft。"""
        if not data:
            return TravelPlanDraft(draft_id=str(uuid4()))
        return TravelPlanDraft(
            draft_id=data.get("draft_id", str(uuid4())),
            destination=data.get("destination"),
            duration_days=data.get("duration_days", 0),
            total_budget=data.get("total_budget", 0),
            revision_version=data.get("revision_version", 0),
        )

    def _compute_day_date(self, dates: DateRange, day_offset: int) -> Optional[str]:
        """计算第 N 天的日期字符串。"""
        if not dates.arrival:
            return None
        try:
            arr = date.fromisoformat(dates.arrival)
            return arr.replace(day=arr.day + day_offset).isoformat() if arr.day + day_offset <= 28 else None
        except (ValueError, TypeError):
            return None

    def _error_response(
        self, req: AgentMessage, code: ErrorCode, detail: str
    ) -> AgentMessage:
        """构建错误响应。"""
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
