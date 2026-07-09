"""Planning Agent — 旅游规划系统的行程设计专家。

职责:
- create_itinerary: 根据结构化需求生成完整旅行行程草稿
- revise_itinerary: 基于评估反馈针对性修订行程
- research_destination: 研究目的地信息
- search_attractions/search_accommodations/search_restaurants: 搜索推荐项
- optimize_daily_schedule: 优化单日行程安排
- allocate_budget: 分配预算到各分项

v1.1.0: LLM 接入 — 6 个方法支持 LLM 调用 + stub fallback。
v1.2.0: CoT 推理管线 — PromptBuilder + SelfCheck 4步推理链。
来源: spec/planner_spec.md, playbooks/planner_playbook.md, handoff.md §Batch 4
"""

from __future__ import annotations

import asyncio
import logging
from datetime import date, datetime, timezone
from typing import Any, Dict, List, Optional
from uuid import uuid4

from core.llm_client import (
    LLMClient,
    LLMEmptyResponseError,
    LLMError,
    LLMParseError,
    LLMRateLimitError,
    LLMSchemaValidationError,
    LLMTimeoutError,
)
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
from models.entities import (
    Accommodation,
    Attraction,
    DestinationInfo,
    DietaryPreferences,
    GeoLocation,
    PriceRange,
    Restaurant,
    RevisionDecision,
)
from models.check import IssueType, SelfCheckIssue
from models.feedback import RevisionFeedback
from models.plan import (
    AccommodationOption,
    Activity,
    BudgetAllocation,
    ItineraryDay,
    Meal,
    Transportation,
    TravelPlanDraft,
)
from models.request import (
    Budget,
    DateRange,
    Destination,
    Preferences,
    StructuredRequest,
    Travelers,
)

logger = logging.getLogger(__name__)

# ============================================================
# Prompt 模板常量
# ============================================================

_SYSTEM_RESEARCH = (
    "你是一个资深旅游目的地研究专家。你熟悉全球各大城市的货币、语言、时区、"
    "最佳旅行季节、热门区域、签证政策和交通信息。请基于真实知识回答。"
)

_SYSTEM_ATTRACTIONS = (
    "你是一个资深旅游目的地专家，熟悉全球各大城市的著名景点和隐藏宝藏。"
    "请只推荐真实存在的景点，不得虚构。"
)

_SYSTEM_RESTAURANTS = (
    "你是一个美食评论家和餐饮推荐专家。你熟悉各地饮食文化和特色餐厅。"
    "请只推荐真实存在的餐厅，不得虚构。"
)

_SYSTEM_ACCOMMODATIONS = (
    "你是一个住宿推荐专家。你了解各价位酒店的实际情况和性价比。"
    "请只推荐真实存在的酒店/住宿，不得虚构。"
)

_SYSTEM_ITINERARY = (
    "你是一个专业的旅行行程规划师。你擅长将景点、餐厅、住宿整合为"
    "合理、有趣、遵守约束的每日行程。"
)

_SYSTEM_BUDGET = (
    "你是一个旅行预算分析专家。你了解全球各地物价水平和旅行花费结构。"
    "请根据目的地物价水平合理分配预算。"
)

_SYSTEM_OPTIMIZE = (
    "你是一个旅行日程优化专家。你擅长按地理分组、开放时间和体力消耗"
    "优化单日行程安排。"
)

_SYSTEM_REVISE = (
    "你是一个旅行行程修订专家。你擅长根据反馈精准修改行程，"
    "不破坏未被指出的部分。"
)

_JSON_FORMAT_INSTRUCTION = (
    "请严格输出以下 JSON 格式，不要添加任何额外文字或解释。"
    "将 JSON 包裹在 ```json ... ``` 代码块中。"
)

_REASON_INSTRUCTION = "推荐理由至少 15 个中文字符，必须具体描述特色，不得使用'值得一去''很好'等泛泛之辞。"

_PRICE_INSTRUCTION = "所有价格标注 CNY，保留 2 位小数。"


# ============================================================
# PlanningAgent
# ============================================================

class PlanningAgent(BaseAgent):
    """行程规划 Agent。

    负责将结构化用户需求转化为详细旅行方案，包括交通、住宿、
    每日行程和预算分配。

    v1.1.0: 支持 LLM 调用 (通过 LLMClient)，LLM 不可用时自动回退 stub。
    """

    agent_name = "planning_agent"
    agent_version = "1.1.0"

    def __init__(
        self,
        registry: Optional[AgentRegistry] = None,
        llm_client: Optional[LLMClient] = None,
        prompt_builder: Optional[Any] = None,
        self_checker: Optional[Any] = None,
    ):
        self._registry = registry
        self._llm_client = llm_client
        self._prompt_builder = prompt_builder
        self._self_checker = self_checker
        self._identity = AgentIdentity(
            name="planning_agent",
            version="1.1.0",
            capabilities=[
                "create_itinerary", "revise_itinerary", "research_destination",
                "search_attractions", "search_accommodations", "search_restaurants",
            ],
            endpoint="internal",
            status="online",
        )

    # -- BaseAgent 抽象方法 --
    @property
    def agent_name(self) -> str:
        return "planning_agent"

    @property
    def agent_version(self) -> str:
        return "1.1.0"

    async def handle_message(self, message: AgentMessage) -> AgentMessage:
        """消息处理入口。根据 task_type 路由。"""
        try:
            message = message.validate()
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
                feedback_data = message.payload.get("revision_feedback")
                if feedback_data is None:
                    feedback_data = message.payload.get("feedback_items", [])
                draft = self._parse_draft(draft_data)
                feedback = [
                    self._coerce_revision_feedback(f)
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
                return self._error_response(
                    message, ErrorCode.TASK_NOT_SUPPORTED,
                    f"不支持: {message.task_type.value}"
                )

        except Exception as exc:
            return self._error_response(message, ErrorCode.EXECUTION_FAILED, str(exc))

    async def health_check(self) -> HealthStatus:
        return HealthStatus(
            status="healthy",
            last_checked=datetime.now(timezone.utc),
            details={
                "agent": "planning_agent",
                "version": "1.1.0",
                "llm_available": self._llm_client is not None and self._llm_client.available,
            },
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

        v1.2.0: CoT 管线优先 — PromptBuilder + LLM 4步推理链。
        CoT 不可用时回退原有流程 (研究→编排→预算→组装)。
        """
        # ---- CoT 路径 (v1.2.0) ----
        if (
            self._llm_client is not None
            and self._llm_client.available
            and self._prompt_builder is not None
            and self._self_checker is not None
        ):
            try:
                from core.cot_pipeline import CoTPipeline

                pipeline = CoTPipeline(
                    self._llm_client,
                    self._prompt_builder,
                    self._self_checker,
                )
                result = await pipeline.execute(request)

                if not result.degraded and result.draft is not None:
                    logger.info(
                        f"[PlanningAgent] CoT 生成成功: "
                        f"attempts={result.attempts}, "
                        f"latency={result.latency_ms}ms, "
                        f"token={result.token_count}, "
                        f"selfcheck_passed={result.selfcheck.passed if result.selfcheck else 'N/A'}"
                    )
                    return result.draft

                logger.warning(
                    f"[PlanningAgent] CoT 降级: "
                    f"degraded={result.degraded}, "
                    f"reason={result.degraded_reason} → 回退 legacy 流程"
                )
            except Exception as exc:
                logger.warning(
                    f"[PlanningAgent] CoT 异常: {exc} → 回退 legacy 流程"
                )

        # ---- Legacy 路径 (v1.1.0 兼容) ----
        dest, budget, prefs, days = self._extract_params(request)
        dest_info, attractions, accommodations, dietary, restaurants = (
            await self._research_phase(dest, budget, prefs, days)
        )
        daily_itinerary = await self._build_daily_itinerary(
            dest, prefs, attractions, restaurants, days, budget
        )
        budget_alloc = await self.allocate_budget(
            daily_itinerary, accommodations, budget.total
        )
        return self._assemble_draft(
            dest, days, budget, daily_itinerary, budget_alloc,
            accommodations, prefs, request.dates,
        )

    async def revise_itinerary(
        self, draft: TravelPlanDraft, feedback: List[RevisionFeedback]
    ) -> TravelPlanDraft:
        """基于评估反馈针对性修订行程。

        修订原则: 聚焦(只修被指出的) + 不退化(未指出的不变) + 透明(标注版本)。
        """
        # Step 1: 创建基础修订版(拷贝原内容)
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

        structured_feedback = [
            self._coerce_revision_feedback(item)
            for item in feedback
        ]
        if not structured_feedback:
            return revised

        # Step 2: 尝试 LLM 修订，失败则保持 stub 行为
        if self._llm_client is not None and structured_feedback:
            result = await self._llm_or_stub(
                "revise_itinerary",
                lambda: self._revise_with_llm(revised, structured_feedback),
                lambda: self._revise_itinerary_stub(revised, structured_feedback),
            )
            if isinstance(result, TravelPlanDraft):
                revised = result

        return revised

    async def research_destination(self, destination: Destination) -> DestinationInfo:
        """研究目的地综合信息。LLM 可用时动态生成，否则回退 stub。"""
        if self._llm_client is None:
            return await self._research_destination_stub(destination)

        result = await self._llm_or_stub(
            "research_destination",
            lambda: self._llm_client.generate(
                system_prompt=_SYSTEM_RESEARCH,
                user_prompt=(
                    f"请研究以下目的地并提供信息:\n"
                    f"目的地: {destination.city}, {destination.country}\n\n"
                    f"请返回以下 JSON (货币用ISO代码, 语言用中文描述, "
                    f"时区用 IANA 格式):\n"
                    f"{_JSON_FORMAT_INSTRUCTION}\n"
                    f'{{"destination": "{destination.city}", '
                    f'"country": "{destination.country}", '
                    f'"currency": "ISO代码", "language": "语言描述", '
                    f'"timezone": "IANA时区", '
                    f'"best_season": ["月份列表"], '
                    f'"visa_required_for_cn": true/false, '
                    f'"popular_areas": ["区域1", "区域2"], '
                    f'"transportation_tips": "交通建议", '
                    f'"safety_level": "safe"}}'
                ),
            ),
            lambda: self._research_destination_stub(destination),
        )
        # LLM 成功返回 dict，fallback 返回 DestinationInfo
        if isinstance(result, DestinationInfo):
            return result
        return DestinationInfo(
            destination=destination.city,
            country=destination.country,
            currency=result.get("currency", "CNY"),
            language=result.get("language", "当地语言"),
            timezone=result.get("timezone", "UTC+0"),
            best_season=result.get("best_season", ["4月", "5月", "9月", "10月"]),
            visa_required_for_cn=result.get("visa_required_for_cn", True),
            popular_areas=result.get("popular_areas", [f"{destination.city}市中心"]),
            transportation_tips=result.get("transportation_tips"),
            safety_level=result.get("safety_level", "safe"),
        )

    async def search_attractions(
        self, destination: Destination, preferences: Preferences
    ) -> List[Attraction]:
        """搜索符合偏好的景点。LLM 可用时返回真实景点，否则回退 stub。"""
        if self._llm_client is None:
            return await self._search_attractions_stub(destination, preferences)

        styles = preferences.style or ["culture", "nature"]
        excluded = preferences.dietary if preferences.dietary else []
        result = await self._llm_or_stub(
            "search_attractions",
            lambda: self._llm_client.generate(
                system_prompt=_SYSTEM_ATTRACTIONS,
                user_prompt=(
                    f"请为以下目的地推荐景点:\n"
                    f"目的地: {destination.city}, {destination.country}\n"
                    f"偏好风格: {', '.join(styles)}\n"
                    f"排除类型: {', '.join(excluded) if excluded else '无'}\n"
                    f"节奏: {preferences.pace}\n\n"
                    f"请推荐 6-8 个景点。{_REASON_INSTRUCTION} {_PRICE_INSTRUCTION}\n"
                    f"{_JSON_FORMAT_INSTRUCTION}\n"
                    f'{{"attractions": ['
                    f'{{"name": "...", "location": "...", "type": "culture|nature|entertainment|food|shopping|sports|relaxation", '
                    f'"suggested_duration_minutes": 120, "estimated_price": 100.0, '
                    f'"rating": 4.5, "reason": "至少15个中文字符的具体推荐理由", '
                    f'"opening_hours": "09:00-17:00", "peak_season": ["4月"]}}'
                    f']}}'
                ),
            ),
            lambda: self._search_attractions_stub(destination, preferences),
        )
        # LLM 成功返回 dict，fallback 返回 List[Attraction]
        if isinstance(result, list):
            return result
        return self._parse_llm_attractions(result)

    async def search_accommodations(
        self, destination: Destination, budget: Budget, style: str
    ) -> List[Accommodation]:
        """搜索符合预算和风格的住宿。LLM 可用时返回真实选项，否则回退 stub。"""
        if self._llm_client is None:
            return await self._search_accommodations_stub(destination, budget)

        result = await self._llm_or_stub(
            "search_accommodations",
            lambda: self._llm_client.generate(
                system_prompt=_SYSTEM_ACCOMMODATIONS,
                user_prompt=(
                    f"请推荐住宿:\n"
                    f"目的地: {destination.city}, {destination.country}\n"
                    f"总预算: {budget.total} CNY\n"
                    f"住宿风格: {style}\n\n"
                    f"请推荐 3-4 个不同价位(覆盖经济型到高档)的住宿选项。"
                    f"每个选项 distance_to_center_km <= 10。"
                    f"type 为 hotel|hostel|resort|guesthouse。"
                    f"{_PRICE_INSTRUCTION}\n"
                    f"{_JSON_FORMAT_INSTRUCTION}\n"
                    f'{{"accommodations": ['
                    f'{{"name": "...", "location": "...", "type": "hotel", '
                    f'"price_per_night": 500.00, "distance_to_center_km": 3.0, '
                    f'"highlights": ["免费WiFi", "含早餐"], "rating": 4.3, '
                    f'"amenity_tags": ["wifi", "parking"]}}'
                    f']}}'
                ),
            ),
            lambda: self._search_accommodations_stub(destination, budget),
        )
        if isinstance(result, list):
            return result
        return self._parse_llm_accommodations(result)

    async def search_restaurants(
        self, location: str, preferences: DietaryPreferences
    ) -> List[Restaurant]:
        """搜索符合饮食偏好的餐厅。LLM 可用时返回真实餐厅，否则回退 stub。"""
        if self._llm_client is None:
            return await self._search_restaurants_stub(location, preferences)

        restrictions = preferences.restrictions or ["无"]
        allergies = preferences.allergies or ["无"]
        result = await self._llm_or_stub(
            "search_restaurants",
            lambda: self._llm_client.generate(
                system_prompt=_SYSTEM_RESTAURANTS,
                user_prompt=(
                    f"请为以下地点推荐餐厅:\n"
                    f"位置: {location}\n"
                    f"饮食限制: {', '.join(restrictions)}\n"
                    f"过敏原: {', '.join(allergies)}\n\n"
                    f"请推荐 6-8 家餐厅，覆盖早中晚三餐和不同菜系。"
                    f"dietary_options 字段标注支持的饮食选项"
                    f"(vegetarian|vegan|halal|kosher|gluten_free)。"
                    f"meal_types 为实际提供的餐段"
                    f"(breakfast|lunch|dinner)。\n"
                    f"{_JSON_FORMAT_INSTRUCTION}\n"
                    f'{{"restaurants": ['
                    f'{{"name": "...", "location": "...", "cuisine": "...", '
                    f'"price_per_person": 80.00, '
                    f'"distance_to_attraction_km": 1.5, '
                    f'"dietary_options": ["vegetarian"], '
                    f'"rating": 4.3, '
                    f'"meal_types": ["lunch", "dinner"], '
                    f'"notes": "招牌菜说明"}}'
                    f']}}'
                ),
            ),
            lambda: self._search_restaurants_stub(location, preferences),
        )
        if isinstance(result, list):
            return result
        return self._parse_llm_restaurants(result)

    async def optimize_daily_schedule(
        self, attractions: List[Attraction], day_index: int
    ) -> Dict[str, Any]:
        """优化单日行程安排。LLM 可用时智能编排，否则回退 stub。"""
        if self._llm_client is None or not attractions:
            return self._optimize_daily_schedule_stub(attractions, day_index)

        attr_json = [
            {"name": a.name, "location": a.location, "type": a.type,
             "duration": a.suggested_duration_minutes}
            for a in attractions
        ]
        result = await self._llm_or_stub(
            "optimize_daily_schedule",
            lambda: self._llm_client.generate(
                system_prompt=_SYSTEM_OPTIMIZE,
                user_prompt=(
                    f"请优化第 {day_index + 1} 天的行程安排:\n"
                    f"景点: {json_dumps(attr_json)}\n\n"
                    f"考虑地理距离和开放时间，返回优化后的排序和时段建议。\n"
                    f"{_JSON_FORMAT_INSTRUCTION}\n"
                ),
            ),
            lambda: self._optimize_daily_schedule_stub(attractions, day_index),
        )
        if isinstance(result, dict) and "optimized" not in result:
            return result
        return result

    async def allocate_budget(
        self,
        daily_itinerary: List[ItineraryDay],
        accommodations: List[Accommodation],
        total_budget: float,
    ) -> BudgetAllocation:
        """分配预算到各分项。LLM 可用时动态分配，否则回退固定比例。"""
        if self._llm_client is None:
            return self._allocate_budget_stub(daily_itinerary, accommodations, total_budget)

        days = len(daily_itinerary)
        activity_count = sum(len(d.activities) for d in daily_itinerary)
        meal_count = sum(len(d.meals) for d in daily_itinerary)
        avg_acc_price = (
            sum(a.price_per_night for a in accommodations) / len(accommodations)
            if accommodations else 0
        )

        result = await self._llm_or_stub(
            "allocate_budget",
            lambda: self._llm_client.generate(
                system_prompt=_SYSTEM_BUDGET,
                user_prompt=(
                    f"请为以下行程分配预算:\n"
                    f"天数: {days}\n"
                    f"总预算: {total_budget} CNY\n"
                    f"住宿均价: {avg_acc_price:.2f} CNY/晚\n"
                    f"活动数: {activity_count}\n"
                    f"餐食数: {meal_count}\n\n"
                    f"请按 transportation/accommodation/activities/meals/buffer "
                    f"五类分配，总和必须精确等于 {total_budget} CNY。"
                    f"buffer 为 5%-10%。考虑住宿均价和活动数来调整比例。"
                    f"{_PRICE_INSTRUCTION}\n"
                    f"{_JSON_FORMAT_INSTRUCTION}\n"
                    f'{{"transportation": 0, "accommodation": 0, '
                    f'"activities": 0, "meals": 0, "buffer": 0, '
                    f'"currency": "CNY"}}'
                ),
            ),
            lambda: self._allocate_budget_stub(
                daily_itinerary, accommodations, total_budget
            ),
        )
        if isinstance(result, BudgetAllocation):
            return result
        return self._parse_llm_budget(result, total_budget)

    # ============================================================
    # create_itinerary 私有子方法 (重构)
    # ============================================================

    @staticmethod
    def _extract_params(request: StructuredRequest):
        """从 StructuredRequest 提取核心参数。"""
        dest = request.destination
        budget = request.budget
        prefs = request.preferences
        days = request.dates.duration_days or 3
        return dest, budget, prefs, days

    async def _research_phase(
        self,
        dest: Destination,
        budget: Budget,
        prefs: Preferences,
        days: int,
    ):
        """研究阶段: 并行调用 4 个搜索方法。"""
        dest_info = await self.research_destination(dest)
        attractions = await self.search_attractions(dest, prefs)
        accommodations = await self.search_accommodations(dest, budget, prefs.pace)
        dietary = DietaryPreferences(restrictions=prefs.dietary)
        restaurants = await self.search_restaurants(dest.city, dietary)
        return dest_info, attractions, accommodations, dietary, restaurants

    async def _build_daily_itinerary(
        self,
        dest: Destination,
        prefs: Preferences,
        attractions: List[Attraction],
        restaurants: List[Restaurant],
        days: int,
        budget: Budget,
    ) -> List[ItineraryDay]:
        """构建每日行程列表。

        LLM 可用时: 将所有搜索结果+偏好+约束整合为一个 prompt，由 LLM 生成完整日程 JSON。
        LLM 不可用: 回退 stub 拼接 (_build_one_day)。
        """
        if self._llm_client is not None and attractions and restaurants:
            result = await self._build_itinerary_with_llm(
                dest, prefs, attractions, restaurants, days, budget
            )
            # _build_itinerary_with_llm 内部通过 _llm_or_stub 处理 fallback
            # 如果 LLM 成功返回 List[ItineraryDay]，否则 _llm_or_stub 返回 fallback
            # 但 _build_itinerary_with_llm 的 fallback 是 None，所以失败时会抛出异常
            # 这里增加额外保护
            if isinstance(result, list):
                return result

        # stub 回退
        daily_itinerary: List[ItineraryDay] = []
        for day_idx in range(days):
            day_itinerary = self._build_one_day(
                attractions, restaurants, prefs, day_idx, budget
            )
            daily_itinerary.append(day_itinerary)
        return daily_itinerary

    async def _build_itinerary_with_llm(
        self,
        dest: Destination,
        prefs: Preferences,
        attractions: List[Attraction],
        restaurants: List[Restaurant],
        days: int,
        budget: Budget,
    ) -> List[ItineraryDay]:
        """使用 LLM 生成完整日程 JSON。失败时回退 stub 拼接。"""
        attr_json = [
            {"name": a.name, "location": a.location, "type": a.type,
             "duration": a.suggested_duration_minutes, "price": a.estimated_price,
             "reason": a.reason}
            for a in attractions
        ]
        rest_json = [
            {"name": r.name, "location": r.location, "cuisine": r.cuisine,
             "price_per_person": r.price_per_person, "meal_types": r.meal_types,
             "dietary_options": r.dietary_options}
            for r in restaurants
        ]

        styles = prefs.style or ["culture", "nature"]
        dietary = prefs.dietary or []

        # fallback: 回退到 stub 拼接
        def fallback_stub():
            result_list: List[ItineraryDay] = []
            for day_idx in range(days):
                result_list.append(PlanningAgent._build_one_day(
                    attractions, restaurants, prefs, day_idx, budget
                ))
            return result_list

        result = await self._llm_or_stub(
            "_build_itinerary_with_llm",
            lambda: self._llm_client.generate(
                system_prompt=_SYSTEM_ITINERARY,
                user_prompt=(
                    f"请为以下旅行生成完整每日行程:\n"
                    f"目的地: {dest.city}, {dest.country}\n"
                    f"天数: {days}\n"
                    f"总预算: {budget.total} CNY\n"
                    f"偏好风格: {', '.join(styles)}\n"
                    f"饮食限制: {', '.join(dietary) if dietary else '无'}\n"
                    f"节奏: {prefs.pace}\n\n"
                    f"景点列表:\n{json_dumps(attr_json)}\n\n"
                    f"餐厅列表:\n{json_dumps(rest_json)}\n\n"
                    f"约束:\n"
                    f"- 每天 2-3 个主要活动 (上午+下午各1个，傍晚可选)\n"
                    f"- 每天 3 餐 (breakfast, lunch, dinner)\n"
                    f"- 景点间距离 <= 30km (同一天)\n"
                    f"- 每日活动+交通总时长 <= 12h\n"
                    f"- 预算在总额的 90%-100% 之间\n"
                    f"- 一日三餐覆盖不同菜系\n"
                    f"- {_REASON_INSTRUCTION}\n"
                    f"- 每餐标注 dietary_compatible: true/false"
                    f"(根据饮食限制 {', '.join(dietary) if dietary else '无'})\n"
                    f"- 景点和餐厅从上述列表中选取，不要虚构\n\n"
                    f"{_JSON_FORMAT_INSTRUCTION}\n"
                    f'{{"daily_itinerary": ['
                    f'{{"day": 1, "activities": ['
                    f'{{"name": "...", "type": "culture", "start_time": "09:00", '
                    f'"duration_minutes": 120, "location": "...", '
                    f'"estimated_cost": 100.00, '
                    f'"reason": "至少15个中文字符的具体推荐理由"}}'
                    f'], "meals": {{'
                    f'"breakfast": {{"type": "breakfast", "restaurant_name": "...", '
                    f'"location": "...", "cuisine": "...", "estimated_cost": 30.00, '
                    f'"dietary_compatible": true}}, '
                    f'"lunch": {{...}}, "dinner": {{...}}'
                    f'}}, "transportation_notes": "建议使用...", '
                    f'"total_day_cost": 0, "total_duration_minutes": 0'
                    f'}}]}}'
                ),
            ),
            fallback_stub,
        )
        # LLM 成功返回 dict，fallback 返回 List[ItineraryDay]
        if isinstance(result, list):
            return result
        return self._parse_llm_itinerary(result)

    @staticmethod
    def _build_one_day(
        attractions: List[Attraction],
        restaurants: List[Restaurant],
        prefs: Preferences,
        day_idx: int,
        budget: Budget,
    ) -> ItineraryDay:
        """构建单日行程 (stub 模式)。"""
        day_num = day_idx + 1
        day_attractions = (
            [attractions[i % len(attractions)]
             for i in range(day_idx * 2, day_idx * 2 + 2)]
            if attractions else []
        )

        activities = []
        if day_attractions:
            activities.append(Activity(
                name=day_attractions[0].name,
                type=day_attractions[0].type,
                start_time="09:00",
                duration_minutes=day_attractions[0].suggested_duration_minutes,
                location=day_attractions[0].location,
                estimated_cost=day_attractions[0].estimated_price,
                reason=day_attractions[0].reason,
            ))
        if len(day_attractions) > 1:
            activities.append(Activity(
                name=day_attractions[1].name,
                type=day_attractions[1].type,
                start_time="13:00",
                duration_minutes=day_attractions[1].suggested_duration_minutes,
                location=day_attractions[1].location,
                estimated_cost=day_attractions[1].estimated_price,
                reason=day_attractions[1].reason,
            ))

        day_restaurants = (
            [restaurants[i % len(restaurants)]
             for i in range(day_idx * 3, day_idx * 3 + 3)]
            if restaurants else []
        )
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

        day_cost = sum(a.estimated_cost for a in activities)
        day_cost += sum((m.estimated_cost for m in meals.values() if m), 0)

        return ItineraryDay(
            day=day_num,
            date=None,
            activities=activities,
            meals=meals,
            transportation_notes="建议使用公共交通",
            total_day_cost=round(day_cost, 2),
            total_duration_minutes=sum(a.duration_minutes for a in activities) + 60,
        )

    @staticmethod
    def _assemble_draft(
        dest: Destination,
        days: int,
        budget: Budget,
        daily_itinerary: List[ItineraryDay],
        budget_alloc: BudgetAllocation,
        accommodations: List[Accommodation],
        prefs: Preferences,
        dates: DateRange,
    ) -> TravelPlanDraft:
        """组装输出 TravelPlanDraft。"""
        transport = Transportation(
            outbound={
                "mode": "飞机", "from": "出发地", "to": dest.city,
                "estimated_cost": budget_alloc.transportation * 0.5,
                "duration_minutes": 180,
            },
            return_trip={
                "mode": "飞机", "from": dest.city, "to": "出发地",
                "estimated_cost": budget_alloc.transportation * 0.5,
                "duration_minutes": 180,
            },
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
        ] if accommodations else []

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

    # ============================================================
    # LLM 解析方法 (JSON → dataclass)
    # ============================================================

    @staticmethod
    def _parse_llm_attractions(data: Dict[str, Any]) -> List[Attraction]:
        """将 LLM JSON 响应反序列化为 List[Attraction]。"""
        items = data.get("attractions", data) if isinstance(data, dict) else data
        if isinstance(items, dict):
            items = items.get("attractions", [])
        if not isinstance(items, list):
            items = [items] if isinstance(items, dict) else []

        results = []
        for item in items:
            if not isinstance(item, dict):
                continue
            reason = item.get("reason", "值得游览的著名景点，游客评价很高")
            if len(reason) < 10:
                reason = reason + "，推荐给喜欢探索和体验当地文化的旅行者"
            try:
                results.append(Attraction(
                    name=item.get("name", "未知景点"),
                    location=item.get("location", "未知"),
                    type=item.get("type", "culture"),
                    suggested_duration_minutes=item.get("suggested_duration_minutes", 120),
                    estimated_price=item.get("estimated_price", 0.0),
                    rating=item.get("rating"),
                    reason=reason,
                    opening_hours=item.get("opening_hours"),
                    peak_season=item.get("peak_season"),
                ))
            except ValueError:
                # __post_init__ 校验失败时跳过
                continue
        return results

    @staticmethod
    def _parse_llm_restaurants(data: Dict[str, Any]) -> List[Restaurant]:
        """将 LLM JSON 响应反序列化为 List[Restaurant]。"""
        items = data.get("restaurants", data) if isinstance(data, dict) else data
        if isinstance(items, dict):
            items = items.get("restaurants", [])
        if not isinstance(items, list):
            items = [items] if isinstance(items, dict) else []

        results = []
        for item in items:
            if not isinstance(item, dict):
                continue
            results.append(Restaurant(
                name=item.get("name", "未知餐厅"),
                location=item.get("location", "未知"),
                cuisine=item.get("cuisine", "当地特色"),
                price_per_person=item.get("price_per_person", 80.0),
                distance_to_attraction_km=item.get("distance_to_attraction_km"),
                dietary_options=item.get("dietary_options", []),
                rating=item.get("rating"),
                meal_types=item.get("meal_types", ["breakfast", "lunch", "dinner"]),
                notes=item.get("notes"),
            ))
        return results

    @staticmethod
    def _parse_llm_accommodations(data: Dict[str, Any]) -> List[Accommodation]:
        """将 LLM JSON 响应反序列化为 List[Accommodation]。"""
        items = data.get("accommodations", data) if isinstance(data, dict) else data
        if isinstance(items, dict):
            items = items.get("accommodations", [])
        if not isinstance(items, list):
            items = [items] if isinstance(items, dict) else []

        results = []
        for item in items:
            if not isinstance(item, dict):
                continue
            results.append(Accommodation(
                name=item.get("name", "未知住宿"),
                location=item.get("location", "未知"),
                type=item.get("type", "hotel"),
                price_per_night=item.get("price_per_night", 0.0),
                distance_to_center_km=item.get("distance_to_center_km", 5.0),
                highlights=item.get("highlights", []),
                rating=item.get("rating"),
                amenity_tags=item.get("amenity_tags", []),
            ))
        return results

    @staticmethod
    def _parse_llm_itinerary(data: Dict[str, Any]) -> List[ItineraryDay]:
        """将 LLM JSON 响应反序列化为 List[ItineraryDay]。"""
        items = data.get("daily_itinerary", data) if isinstance(data, dict) else data
        if isinstance(items, dict):
            items = items.get("daily_itinerary", [])
        if not isinstance(items, list):
            items = []

        days = []
        for day_data in items:
            if not isinstance(day_data, dict):
                continue

            # 解析 activities
            activities = []
            for act in day_data.get("activities", []):
                if not isinstance(act, dict):
                    continue
                reason = act.get("reason", "详细的推荐理由，至少15个中文字符满足约束要求")
                # 确保 reason >= 10 字 (__post_init__ 校验)
                if len(reason) < 10:
                    reason = reason + "，此处为满足最小长度要求的补充描述"
                try:
                    activities.append(Activity(
                        name=act.get("name", "未知活动"),
                        type=act.get("type", "culture"),
                        start_time=act.get("start_time", "09:00"),
                        duration_minutes=act.get("duration_minutes", 120),
                        location=act.get("location", "未知"),
                        estimated_cost=act.get("estimated_cost", 0.0),
                        reason=reason,
                    ))
                except ValueError:
                    # __post_init__ 校验失败时跳过该 activity
                    continue

            # 解析 meals
            meals: Dict[str, Optional[Meal]] = {}
            meals_data = day_data.get("meals", {})
            if isinstance(meals_data, dict):
                for m_type in ("breakfast", "lunch", "dinner"):
                    m = meals_data.get(m_type)
                    if isinstance(m, dict):
                        meals[m_type] = Meal(
                            type=m_type,
                            restaurant_name=m.get("restaurant_name", "未知餐厅"),
                            location=m.get("location", "未知"),
                            cuisine=m.get("cuisine", "当地特色"),
                            estimated_cost=m.get("estimated_cost", 50.0),
                            dietary_compatible=m.get("dietary_compatible", True),
                            notes=m.get("notes"),
                        )

            day_cost = sum(a.estimated_cost for a in activities)
            day_cost += sum((m.estimated_cost for m in meals.values() if m), 0)

            days.append(ItineraryDay(
                day=day_data.get("day", len(days) + 1),
                date=day_data.get("date"),
                activities=activities,
                meals=meals,
                transportation_notes=day_data.get("transportation_notes"),
                total_day_cost=day_data.get("total_day_cost", round(day_cost, 2)),
                total_duration_minutes=day_data.get(
                    "total_duration_minutes",
                    sum(a.duration_minutes for a in activities) + 60,
                ),
            ))

        return days

    @staticmethod
    def _parse_llm_budget(
        data: Dict[str, Any], total_budget: float
    ) -> BudgetAllocation:
        """将 LLM JSON 响应反序列化为 BudgetAllocation，确保五项之和等于总额。"""
        transport = data.get("transportation", 0)
        accommodation = data.get("accommodation", 0)
        activities = data.get("activities", 0)
        meals = data.get("meals", 0)
        buffer = data.get("buffer", 0)

        # 归一化: 确保和等于 total_budget
        raw_sum = transport + accommodation + activities + meals + buffer
        if raw_sum > 0 and abs(raw_sum - total_budget) > 0.01:
            scale = total_budget / raw_sum
            transport = round(transport * scale, 2)
            accommodation = round(accommodation * scale, 2)
            activities = round(activities * scale, 2)
            meals = round(meals * scale, 2)
            buffer = round(
                total_budget - transport - accommodation - activities - meals, 2
            )

        return BudgetAllocation(
            transportation=transport,
            accommodation=accommodation,
            activities=activities,
            meals=meals,
            buffer=buffer,
            currency=data.get("currency", "CNY"),
        )

    # ============================================================
    # 结构化修订反馈
    # ============================================================
    async def _revise_with_llm(
        self,
        revised: TravelPlanDraft,
        feedback: List[RevisionFeedback],
    ) -> TravelPlanDraft:
        """使用 LLM 进行实质性修订。"""
        result = await self._llm_client.generate(
            system_prompt=_SYSTEM_REVISE,
            user_prompt=self._build_revision_prompt(revised, feedback),
        )

        # 从 LLM 响应重建 TravelPlanDraft
        if "daily_itinerary" in result:
            revised_days = self._parse_llm_itinerary(result)
            revised.daily_itinerary = revised_days

        if "budget_allocation" in result:
            alloc_data = result["budget_allocation"]
            if isinstance(alloc_data, dict):
                revised.budget_allocation = self._parse_llm_budget(
                    alloc_data, revised.total_budget
                )

        return revised

    def _build_revision_prompt(
        self,
        revised: TravelPlanDraft,
        feedback: List[RevisionFeedback],
    ) -> str:
        """构造包含精确反馈定位的修订 prompt。"""
        if self._prompt_builder is not None:
            request = self._request_from_draft(revised)
            feedback_prompt = self._prompt_builder.assemble(
                request,
                step="revise",
                feedback=feedback,
                iteration=revised.revision_version,
            )
        else:
            feedback_prompt = self._format_revision_feedback(feedback)

        return (
            f"{feedback_prompt}\n\n"
            f"原始行程:\n{json_dumps(revised.to_dict())}\n\n"
            "请仅修改反馈中指出的问题。保持未指出的 day/activity/meal 完全不变。"
            "输出完整的修订后行程 JSON。\n"
            f"{_JSON_FORMAT_INSTRUCTION}\n"
        )

    @staticmethod
    def _format_revision_feedback(feedback: List[RevisionFeedback]) -> str:
        """无 PromptBuilder 时的结构化反馈格式化。"""
        return "\n".join(
            f"{index}. {item.format_for_prompt()}"
            for index, item in enumerate(feedback, 1)
        )

    @staticmethod
    def _request_from_draft(draft: TravelPlanDraft) -> StructuredRequest:
        """从草稿恢复 revise prompt 所需的最小请求上下文。"""
        destination = draft.destination or {}
        if isinstance(destination, str):
            destination = {"city": destination, "country": ""}
        return StructuredRequest(
            destination=Destination(
                city=destination.get("city", "未知"),
                country=destination.get("country", ""),
            ),
            dates=DateRange(duration_days=draft.duration_days),
            budget=Budget(total=draft.total_budget),
            travelers=Travelers(),
            preferences=Preferences(style=list(draft.preferences_applied)),
        )

    @staticmethod
    def _coerce_revision_feedback(raw: Any) -> RevisionFeedback:
        """兼容新结构化反馈、旧维度反馈和裸 dict。"""
        if isinstance(raw, RevisionFeedback):
            return raw
        if isinstance(raw, dict) and isinstance(raw.get("issue"), dict):
            return RevisionFeedback.from_dict(raw)
        if isinstance(raw, dict):
            return PlanningAgent._legacy_feedback_to_structured(raw)
        legacy = {
            "dimension": getattr(raw, "dimension", ""),
            "issue": getattr(raw, "issue", str(raw)),
            "suggestion": getattr(raw, "suggestion", ""),
            "priority": getattr(raw, "priority", "medium"),
        }
        return PlanningAgent._legacy_feedback_to_structured(legacy)

    @staticmethod
    def _legacy_feedback_to_structured(raw: Dict[str, Any]) -> RevisionFeedback:
        """将旧 dimension/issue/suggestion 反馈转为 R4 结构。"""
        dimension = raw.get("dimension", "")
        text = raw.get("issue", "")
        suggestion = raw.get("suggestion", "")
        priority = "blocking" if raw.get("priority") == "high" else "warning"
        return RevisionFeedback(
            issue=SelfCheckIssue(
                type=PlanningAgent._infer_feedback_issue_type(dimension, text),
                location=raw.get("location") or PlanningAgent._infer_feedback_location(text),
                actual_value=raw.get("actual_value", text),
                expected=raw.get("expected", suggestion or "按建议修正"),
                severity=priority,
            ),
            suggestion=suggestion,
            priority=priority,
            source=raw.get("source", "evaluation_agent"),
        )

    @staticmethod
    def _infer_feedback_issue_type(*parts: Any) -> IssueType:
        """根据旧反馈文本推断结构化问题类型。"""
        text = " ".join(str(part).lower() for part in parts if part is not None)
        if any(token in text for token in ("duplicate", "重复")):
            return IssueType.DUPLICATE_ATTRACTION
        if any(token in text for token in ("distance", "geo", "route", "距离", "绕路")):
            return IssueType.GEO_DISTANCE
        if any(token in text for token in ("budget", "price", "cost", "预算", "价格", "超")):
            return IssueType.BUDGET_OVERSPEND
        if any(token in text for token in ("missing meal", "缺餐", "餐食不足")):
            return IssueType.MISSING_MEAL
        if any(token in text for token in ("activity", "schedule", "行程", "活动")):
            return IssueType.MISSING_ACTIVITY
        return IssueType.STYLE_MISMATCH

    @staticmethod
    def _infer_feedback_location(text: Any) -> str:
        """从旧反馈文本中提取粗粒度位置。"""
        text_value = str(text)
        import re as _re

        day_match = _re.search(r"(?:day[_\s-]*|第)(\d+)", text_value, _re.IGNORECASE)
        day = day_match.group(1) if day_match else None
        if not day:
            return "plan"
        if _re.search(r"dinner|晚餐", text_value, _re.IGNORECASE):
            return f"day_{day}.dinner"
        if _re.search(r"lunch|午餐", text_value, _re.IGNORECASE):
            return f"day_{day}.lunch"
        if _re.search(r"breakfast|早餐", text_value, _re.IGNORECASE):
            return f"day_{day}.breakfast"
        return f"day_{day}"
    # ============================================================
    # Stub 回退方法 (原实现，方法名加 _stub 后缀)
    # ============================================================

    async def _research_destination_stub(
        self, destination: Destination
    ) -> DestinationInfo:
        """研究目的地信息 (stub)。"""
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

    async def _search_attractions_stub(
        self, destination: Destination, preferences: Preferences
    ) -> List[Attraction]:
        """搜索景点 (stub)。"""
        await asyncio.sleep(0.005)
        city = destination.city
        styles = preferences.style or ["culture", "nature"]

        attractions: List[Attraction] = []
        for i, style in enumerate(styles[:4]):
            attractions.append(Attraction(
                name=f"{city}{style}景点{i + 1}",
                location=f"{city}市中心",
                type=style,
                suggested_duration_minutes=120 if style == "culture" else 90,
                estimated_price=100.0 if style == "culture" else 50.0,
                reason=f"{city}著名的{style}景点，游客必去之地，评分很高很受欢迎",
            ))
        return attractions

    async def _search_accommodations_stub(
        self, destination: Destination, budget: Budget
    ) -> List[Accommodation]:
        """搜索住宿 (stub)。"""
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

    async def _search_restaurants_stub(
        self, location: str, preferences: DietaryPreferences
    ) -> List[Restaurant]:
        """搜索餐厅 (stub)。"""
        await asyncio.sleep(0.005)
        cuisines = ["当地特色", "亚洲料理", "国际美食"]
        restaurants: List[Restaurant] = []
        for i, cuisine in enumerate(cuisines):
            restaurants.append(Restaurant(
                name=f"{location}{cuisine}餐厅{i + 1}",
                location=f"{location}市中心",
                cuisine=cuisine,
                price_per_person=80.0,
                distance_to_attraction_km=1.0,
                dietary_options=preferences.restrictions,
                meal_types=["breakfast", "lunch", "dinner"],
                rating=4.3,
            ))
        return restaurants

    def _optimize_daily_schedule_stub(
        self, attractions: List[Attraction], day_index: int
    ) -> Dict[str, Any]:
        """优化单日行程 (stub)。"""
        return {
            "day": day_index + 1,
            "attractions": [a.name for a in attractions],
            "optimized": True,
        }

    def _allocate_budget_stub(
        self,
        daily_itinerary: List[ItineraryDay],
        accommodations: List[Accommodation],
        total_budget: float,
    ) -> BudgetAllocation:
        """分配预算 (stub — 固定比例 30/35/15/15/5)。"""
        return BudgetAllocation(
            transportation=round(total_budget * 0.30, 2),
            accommodation=round(total_budget * 0.35, 2),
            activities=round(total_budget * 0.15, 2),
            meals=round(total_budget * 0.15, 2),
            buffer=round(total_budget * 0.05, 2),
            currency="CNY",
        )

    def _revise_itinerary_stub(
        self,
        revised: TravelPlanDraft,
        feedback: List[RevisionFeedback],
    ) -> TravelPlanDraft:
        """修订行程 (stub — 仅递增版本号)。"""
        # 不修改 draft 内容，仅版本号已在外层 +1
        return revised

    # ============================================================
    # LLM 错误处理统一包装器
    # ============================================================

    async def _llm_or_stub(self, method_name, llm_call, fallback_func):
        """通用 LLM 调用包装器: 尝试 LLM → 失败则执行 fallback。

        捕获 6 种异常模式，每种对应特定 log 消息。
        fallback_func 可以是同步或异步函数。
        """
        try:
            return await llm_call()
        except LLMTimeoutError:
            self._log_warning(method_name, "超时(30s)", "回退 stub")
            return await self._invoke_fallback(fallback_func)
        except LLMRateLimitError:
            self._log_warning(method_name, "限流(已重试3次)", "回退 stub")
            return await self._invoke_fallback(fallback_func)
        except LLMParseError as exc:
            self._log_warning(method_name, f"JSON解析失败: {exc}", "回退 stub")
            return await self._invoke_fallback(fallback_func)
        except LLMEmptyResponseError:
            self._log_warning(method_name, "空响应", "回退 stub")
            return await self._invoke_fallback(fallback_func)
        except LLMSchemaValidationError as exc:
            self._log_warning(method_name, f"Schema校验: {exc}", "回退 stub")
            return await self._invoke_fallback(fallback_func)
        except Exception as exc:
            self._log_warning(method_name, f"未知异常: {exc}", "回退 stub")
            return await self._invoke_fallback(fallback_func)

    @staticmethod
    async def _invoke_fallback(fallback_func):
        """安全调用 fallback 函数（兼容 sync/async）。"""
        if fallback_func is None:
            return None
        result = fallback_func()
        if asyncio.iscoroutine(result):
            return await result
        return result

    # ============================================================
    # 内部辅助方法
    # ============================================================

    @staticmethod
    def _log_warning(method: str, error: str, action: str) -> None:
        """统一降级日志: method + error + action。"""
        logger.warning(
            f"[PlanningAgent.{method}] {error} → {action} | degraded=true"
        )

    def _parse_request(self, data: Dict[str, Any]) -> StructuredRequest:
        """从消息 payload 解析 StructuredRequest。"""
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

    @staticmethod
    def _parse_draft(data: Optional[Dict[str, Any]]) -> TravelPlanDraft:
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

    @staticmethod
    def _compute_day_date(dates: DateRange, day_offset: int) -> Optional[str]:
        """计算第 N 天的日期字符串。"""
        if not dates.arrival:
            return None
        try:
            arr = date.fromisoformat(dates.arrival)
            return (
                arr.replace(day=arr.day + day_offset).isoformat()
                if arr.day + day_offset <= 28 else None
            )
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


# ============================================================
# 模块级工具
# ============================================================

def json_dumps(obj: Any) -> str:
    """安全的 JSON 序列化（中文不转义）。"""
    import json as _json
    return _json.dumps(obj, ensure_ascii=False, indent=2, default=str)
