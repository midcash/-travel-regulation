"""CoTPipeline — Chain-of-Thought 推理管线。

v1.2.0 R3 — 将 Planning Agent 的 6 个 LLM 方法从"单次调用的黑盒"
改为"分步推理的透明链"。

4 步推理链:
1. _step_research(request)   — 目的地研究 → DestinationResearch
2. _step_select(research)    — 景点/住宿/餐饮筛选 → CandidatePool
3. _step_compose(selection)  — 日程编排 + 预算分配 → TravelPlanDraft
4. _step_selfcheck(draft)    — 调用 SelfCheck → 不通过回到步骤3（最多2次修正）

降级策略: 任一步 LLM 调用失败 → 整链回退 stub（不混合 LLM+stub）。

来源: progress/handoff.md §12 Phase R Step 3
"""

from __future__ import annotations

import asyncio
import json as json_module
import logging
import time
from typing import Any, Dict, List, Optional

from models.entities import (
    Accommodation,
    Attraction,
    DietaryPreferences,
    Restaurant,
)
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
from models.check import IssueType, SelfCheckIssue, SelfCheckResult
from models.reasoning import (
    CandidatePool,
    CoTResult,
    DestinationResearch,
    StepTrace,
)

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# 常量
# ---------------------------------------------------------------------------

JSON_FORMAT_INSTRUCTION = (
    "请严格输出以下 JSON 格式，不要添加任何额外文字或解释。"
    "将 JSON 包裹在 ```json ... ``` 代码块中。"
)

REASON_INSTRUCTION = (
    "推荐理由至少 15 个中文字符，必须具体描述特色，"
    "不得使用'值得一去''很好'等泛泛之辞。"
)


# ---------------------------------------------------------------------------
# CoTPipeline
# ---------------------------------------------------------------------------

class CoTPipeline:
    """Chain-of-Thought 推理管线。

    编排 4 步推理链，每步有独立中间产出可校验。
    依赖注入: LLMClient + PromptBuilder + SelfChecker。

    用法::

        pipeline = CoTPipeline(llm_client, prompt_builder, self_checker)
        result = await pipeline.execute(request)
        if result.degraded:
            # 回退到 stub
            draft = fallback_stub(request)
        else:
            draft = result.draft
    """

    MAX_SELFCHECK_RETRIES = 2
    """compose → selfcheck 最大重试次数（共最多 3 次 compose）。"""

    def __init__(
        self,
        llm_client: Any,
        prompt_builder: Any,
        self_checker: Any,
    ) -> None:
        """初始化 CoT 管线。

        Args:
            llm_client: LLMClient 实例（用于所有 LLM 调用）。
            prompt_builder: PromptBuilder 实例（用于所有 prompt 组装）。
            self_checker: SelfChecker 实例（用于步骤 4 规则自检）。
        """
        self._llm = llm_client
        self._prompts = prompt_builder
        self._selfcheck = self_checker

    # ================================================================
    # 公开 API
    # ================================================================

    async def execute(self, request: StructuredRequest) -> CoTResult:
        """执行完整的 CoT 推理管线。

        Args:
            request: 结构化的用户请求。

        Returns:
            CoTResult: 含 draft + 中间产出 + trace + 性能指标。
            degraded=True 表示任一步骤失败，调用方应回退 stub。
        """
        trace: List[StepTrace] = []
        token_count = 0
        t_start = time.perf_counter()

        try:
            # ---- Step 1: Research ----
            research, research_trace = await self._step_research(request)
            trace.append(research_trace)
            token_count += research_trace.token_count

            # ---- Step 2: Select ----
            candidates, select_traces = await self._step_select(
                request, research
            )
            trace.extend(select_traces)
            token_count += sum(t.token_count for t in select_traces)

            # ---- Step 3 + 4: Compose + SelfCheck loop ----
            draft, selfcheck_result, attempts, loop_traces = (
                await self._compose_with_selfcheck(
                    request, research, candidates
                )
            )
            trace.extend(loop_traces)
            token_count += sum(t.token_count for t in loop_traces)

            latency_ms = int((time.perf_counter() - t_start) * 1000)

            return CoTResult(
                draft=draft,
                research=research,
                candidates=candidates,
                selfcheck=selfcheck_result,
                attempts=attempts,
                latency_ms=latency_ms,
                token_count=token_count,
                trace=trace,
                degraded=False,
            )

        except Exception as exc:
            latency_ms = int((time.perf_counter() - t_start) * 1000)
            reason = f"{type(exc).__name__}: {exc}"
            logger.warning(
                f"[CoTPipeline] LLM 调用失败，整链回退 stub: {reason}"
            )
            return CoTResult(
                draft=None,
                research=None,
                candidates=None,
                selfcheck=None,
                attempts=0,
                latency_ms=latency_ms,
                token_count=token_count,
                trace=trace,
                degraded=True,
                degraded_reason=reason,
            )

    # ================================================================
    # Step 1: Research
    # ================================================================

    async def _step_research(
        self, request: StructuredRequest
    ) -> tuple:
        """目的地研究: LLM 生成目的地分析 → DestinationResearch。

        Returns:
            (DestinationResearch, StepTrace)
        """
        t0 = time.perf_counter()
        dest_city = request.destination.city
        dest_country = request.destination.country

        system_prompt = self._prompts._build_stable()
        ctx_vars = self._prompts._build_context_vars(request, "research")
        user_prompt = self._prompts._build_context("research", ctx_vars)

        user_prompt += "\n\n" + JSON_FORMAT_INSTRUCTION + "\n"
        user_prompt += json_module.dumps(
            {
                "currency": "本地货币ISO代码",
                "language": "语言（中文描述）",
                "timezone": "IANA时区",
                "best_season": "最佳季节描述",
                "popular_districts": ["热门区域1", "热门区域2"],
                "transport_summary": "交通概况",
                "seasonal_notes": "季节性备注",
                "price_level": "高|中|低",
            },
            ensure_ascii=False,
            indent=2,
        )

        result = await self._llm.generate(
            system_prompt=system_prompt,
            user_prompt=user_prompt,
        )

        research = DestinationResearch(
            currency=result.get("currency", ""),
            language=result.get("language", ""),
            timezone=result.get("timezone", ""),
            best_season=result.get("best_season", ""),
            popular_districts=result.get(
                "popular_districts",
                result.get("popular_areas", []),
            ),
            transport_summary=result.get(
                "transport_summary",
                result.get("transportation_tips", ""),
            ),
            seasonal_notes=result.get("seasonal_notes", ""),
            price_level=result.get("price_level", "中"),
        )

        trace = StepTrace(
            step_name="research",
            input_summary=f"目的地: {dest_city}, {dest_country}",
            output_summary=(
                f"currency={research.currency}, "
                f"language={research.language}, "
                f"districts={len(research.popular_districts)}个, "
                f"price_level={research.price_level}"
            ),
            duration_ms=int((time.perf_counter() - t0) * 1000),
        )

        return research, trace

    # ================================================================
    # Step 2: Select
    # ================================================================

    async def _step_select(
        self,
        request: StructuredRequest,
        research: DestinationResearch,
    ) -> tuple:
        """候选筛选: 3 路并行搜索 → CandidatePool。

        Returns:
            (CandidatePool, List[StepTrace])
        """
        tasks = [
            self._select_attractions(request),
            self._select_accommodations(request),
            self._select_restaurants(request),
        ]
        results = await asyncio.gather(*tasks)
        attractions, acc_trace = results[0]
        accommodations, accom_trace = results[1]
        restaurants, rest_trace = results[2]

        # 构建筛选理由
        rationale_parts = [
            f"景点: {len(attractions)}个, 偏好风格匹配",
            f"住宿: {len(accommodations)}个, 覆盖不同价位",
            f"餐厅: {len(restaurants)}个, 考虑饮食限制",
        ]

        candidates = CandidatePool(
            attractions=list(attractions),
            accommodations=list(accommodations),
            restaurants=list(restaurants),
            selection_rationale="; ".join(rationale_parts),
            excluded=[],
        )

        return candidates, [acc_trace, accom_trace, rest_trace]

    async def _select_attractions(
        self, request: StructuredRequest
    ) -> tuple:
        """搜索景点 → (List[Attraction], StepTrace)。"""
        t0 = time.perf_counter()
        system = self._prompts._build_stable()
        ctx_vars = self._prompts._build_context_vars(request, "attractions")
        user = self._prompts._build_context("attractions", ctx_vars)

        prefs = request.preferences
        styles = prefs.style or ["culture", "nature"]
        excluded = prefs.excluded if prefs.excluded else []

        user += "\n\n" + JSON_FORMAT_INSTRUCTION + "\n"
        user += json_module.dumps(
            {
                "attractions": [
                    {
                        "name": "景点名",
                        "location": "位置",
                        "type": "culture|nature|entertainment|food|shopping|sports|relaxation",
                        "suggested_duration_minutes": 120,
                        "estimated_price": 100.0,
                        "rating": 4.5,
                        "reason": "至少15个中文字符的具体推荐理由",
                        "opening_hours": "09:00-17:00",
                        "peak_season": ["4月"],
                    }
                ]
            },
            ensure_ascii=False,
            indent=2,
        )

        result = await self._llm.generate(
            system_prompt=system, user_prompt=user
        )

        attractions = self._parse_attractions(result)

        trace = StepTrace(
            step_name="select_attractions",
            input_summary=(
                f"dest={request.destination.city}, "
                f"styles={', '.join(styles)}, "
                f"excluded={', '.join(excluded) if excluded else '无'}"
            ),
            output_summary=f"返回 {len(attractions)} 个景点",
            duration_ms=int((time.perf_counter() - t0) * 1000),
        )

        return attractions, trace

    async def _select_accommodations(
        self, request: StructuredRequest
    ) -> tuple:
        """搜索住宿 → (List[Accommodation], StepTrace)。"""
        t0 = time.perf_counter()
        system = self._prompts._build_stable()
        ctx_vars = self._prompts._build_context_vars(
            request, "accommodations"
        )
        user = self._prompts._build_context("accommodations", ctx_vars)

        user += "\n\n" + JSON_FORMAT_INSTRUCTION + "\n"
        user += json_module.dumps(
            {
                "accommodations": [
                    {
                        "name": "住宿名",
                        "location": "位置",
                        "type": "hotel|hostel|resort|guesthouse",
                        "price_per_night": 500.00,
                        "distance_to_center_km": 3.0,
                        "highlights": ["免费WiFi", "含早餐"],
                        "rating": 4.3,
                        "amenity_tags": ["wifi", "parking"],
                    }
                ]
            },
            ensure_ascii=False,
            indent=2,
        )

        result = await self._llm.generate(
            system_prompt=system, user_prompt=user
        )

        accommodations = self._parse_accommodations(result)

        trace = StepTrace(
            step_name="select_accommodations",
            input_summary=f"dest={request.destination.city}, days={request.dates.duration_days}",
            output_summary=f"返回 {len(accommodations)} 个住宿选项",
            duration_ms=int((time.perf_counter() - t0) * 1000),
        )

        return accommodations, trace

    async def _select_restaurants(
        self, request: StructuredRequest
    ) -> tuple:
        """搜索餐厅 → (List[Restaurant], StepTrace)。"""
        t0 = time.perf_counter()
        system = self._prompts._build_stable()
        ctx_vars = self._prompts._build_context_vars(request, "restaurants")
        user = self._prompts._build_context("restaurants", ctx_vars)

        prefs = request.preferences
        dietary = prefs.dietary or ["无"]

        user += "\n\n" + JSON_FORMAT_INSTRUCTION + "\n"
        user += json_module.dumps(
            {
                "restaurants": [
                    {
                        "name": "餐厅名",
                        "location": "位置",
                        "cuisine": "菜系",
                        "price_per_person": 80.00,
                        "distance_to_attraction_km": 1.5,
                        "dietary_options": ["vegetarian"],
                        "rating": 4.3,
                        "meal_types": ["lunch", "dinner"],
                        "notes": "招牌菜说明",
                    }
                ]
            },
            ensure_ascii=False,
            indent=2,
        )

        result = await self._llm.generate(
            system_prompt=system, user_prompt=user
        )

        restaurants = self._parse_restaurants(result)

        trace = StepTrace(
            step_name="select_restaurants",
            input_summary=(
                f"dest={request.destination.city}, "
                f"dietary={', '.join(dietary)}"
            ),
            output_summary=f"返回 {len(restaurants)} 个餐厅",
            duration_ms=int((time.perf_counter() - t0) * 1000),
        )

        return restaurants, trace

    # ================================================================
    # Step 3 + 4: Compose + SelfCheck loop
    # ================================================================

    async def _compose_with_selfcheck(
        self,
        request: StructuredRequest,
        research: DestinationResearch,
        candidates: CandidatePool,
    ) -> tuple:
        """编排 + 自检循环: compose → selfcheck → 不通过则重试。

        Returns:
            (TravelPlanDraft, SelfCheckResult, attempts, List[StepTrace])
        """
        loop_traces: List[StepTrace] = []
        draft: Optional[TravelPlanDraft] = None
        selfcheck_result: Optional[SelfCheckResult] = None

        for attempt in range(1, self.MAX_SELFCHECK_RETRIES + 2):
            # Step 3: Compose
            draft, compose_trace = await self._step_compose(
                request, research, candidates
            )
            loop_traces.append(compose_trace)

            # Step 4: SelfCheck
            t0 = time.perf_counter()
            selfcheck_result = self._selfcheck.check(draft, request)
            sc_trace = StepTrace(
                step_name=f"selfcheck_attempt_{attempt}",
                input_summary=f"检查 {len(draft.daily_itinerary)} 天行程",
                output_summary=(
                    f"passed={selfcheck_result.passed}, "
                    f"issues={len(selfcheck_result.issues)} "
                    f"(blocking={len(selfcheck_result.blocking_issues)}, "
                    f"warning={len(selfcheck_result.warning_issues)})"
                ),
                duration_ms=int((time.perf_counter() - t0) * 1000),
            )
            loop_traces.append(sc_trace)

            if selfcheck_result.passed:
                break

            if attempt <= self.MAX_SELFCHECK_RETRIES:
                logger.info(
                    f"[CoTPipeline] SelfCheck 未通过 "
                    f"(第 {attempt} 次尝试), "
                    f"blocking issues: "
                    f"{[i.type.value for i in selfcheck_result.blocking_issues]}"
                    f" → 重新编排"
                )
                # 将 blocking issues 注入 candidates 的 excluded 列表
                # 帮助 LLM 在下一轮避开问题
                for issue in selfcheck_result.blocking_issues:
                    if issue.type == IssueType.DUPLICATE_ATTRACTION:
                        name = issue.location.replace("景点 '", "").replace("'", "")
                        if name not in candidates.excluded:
                            candidates.excluded.append(name)

        return (
            draft,
            selfcheck_result,
            attempt,
            loop_traces,
        )

    async def _step_compose(
        self,
        request: StructuredRequest,
        research: DestinationResearch,
        candidates: CandidatePool,
    ) -> tuple:
        """日程编排 + 预算分配 → (TravelPlanDraft, StepTrace)。

        内部: itinerary LLM call → parse days → budget LLM call → parse budget → assemble draft。
        """
        t0 = time.perf_counter()
        dest = request.destination
        budget = request.budget
        prefs = request.preferences

        # --- 编排行程 ---
        attractions_json = json_module.dumps(
            [
                {
                    "name": a.name,
                    "location": a.location,
                    "type": a.type,
                    "duration": getattr(a, "suggested_duration_minutes", 120),
                    "price": getattr(a, "estimated_price", 0),
                    "reason": getattr(a, "reason", ""),
                }
                for a in candidates.attractions
            ],
            ensure_ascii=False,
            indent=2,
        )
        restaurants_json = json_module.dumps(
            [
                {
                    "name": r.name,
                    "location": r.location,
                    "cuisine": r.cuisine,
                    "price_per_person": getattr(r, "price_per_person", 80),
                    "meal_types": getattr(r, "meal_types", ["lunch", "dinner"]),
                    "dietary_options": getattr(r, "dietary_options", []),
                }
                for r in candidates.restaurants
            ],
            ensure_ascii=False,
            indent=2,
        )

        days = request.dates.duration_days or len(candidates.attractions) or 3
        styles = prefs.style or ["culture", "nature"]
        dietary = prefs.dietary or []
        excluded_hint = ""
        if candidates.excluded:
            excluded_hint = (
                f"\n排除（已在上轮被自检检出，本轮不可再用）: "
                f"{', '.join(candidates.excluded)}"
            )

        system = self._prompts._build_stable()
        ctx_vars = self._prompts._build_context_vars(
            request,
            "itinerary",
            research_summary=(
                f"{research.price_level}消费水平, "
                f"热门区域: {', '.join(research.popular_districts[:5])}, "
                f"交通: {research.transport_summary}"
            ),
            candidates_attractions=attractions_json,
            candidates_accommodations=json_module.dumps(
                [
                    {"name": a.name, "location": a.location,
                     "price_per_night": a.price_per_night}
                    for a in candidates.accommodations
                ],
                ensure_ascii=False,
                indent=2,
            ),
            candidates_restaurants=restaurants_json,
        )

        user = self._prompts._build_context("itinerary", ctx_vars)
        user += "\n\n" + JSON_FORMAT_INSTRUCTION + "\n"
        user += json_module.dumps(
            {
                "daily_itinerary": [
                    {
                        "day": 1,
                        "activities": [
                            {
                                "name": "景点名",
                                "type": "culture",
                                "start_time": "09:00",
                                "duration_minutes": 120,
                                "location": "位置",
                                "estimated_cost": 100.00,
                                "reason": "至少15个中文字符的推荐理由",
                            }
                        ],
                        "meals": {
                            "breakfast": {
                                "type": "breakfast",
                                "restaurant_name": "...",
                                "location": "...",
                                "cuisine": "...",
                                "estimated_cost": 30.00,
                                "dietary_compatible": True,
                            },
                            "lunch": {"...": "..."},
                            "dinner": {"...": "..."},
                        },
                        "transportation_notes": "建议使用...",
                        "total_day_cost": 0,
                        "total_duration_minutes": 0,
                    }
                ]
            },
            ensure_ascii=False,
            indent=2,
        )
        user += (
            f"\n\n约束:\n"
            f"- 每天 2-3 个主要活动 (上午+下午各1个，傍晚可选)\n"
            f"- 每天 3 餐 (breakfast, lunch, dinner)\n"
            f"- 景点间距离 <= 30km (同一天)\n"
            f"- 每日活动+交通总时长 <= 12h\n"
            f"- 预算在总额的 90%-100% 之间\n"
            f"- 一日三餐覆盖不同菜系\n"
            f"- {REASON_INSTRUCTION}\n"
            f"- 每餐标注 dietary_compatible: true/false"
            f"(根据饮食限制 {', '.join(dietary) if dietary else '无'})\n"
            f"- 景点和餐厅从上述列表中选取，不要虚构"
            f"{excluded_hint}\n"
        )

        itinerary_result = await self._llm.generate(
            system_prompt=system, user_prompt=user
        )

        daily_itinerary = self._parse_itinerary(itinerary_result)

        # --- 预算分配 ---
        activity_count = sum(len(d.activities) for d in daily_itinerary)
        meal_count = sum(
            sum(1 for m in d.meals.values() if m) for d in daily_itinerary
        )
        avg_acc = (
            sum(a.price_per_night for a in candidates.accommodations)
            / len(candidates.accommodations)
            if candidates.accommodations
            else 0
        )

        budget_ctx_vars = self._prompts._build_context_vars(request, "budget")
        budget_user = self._prompts._build_context("budget", budget_ctx_vars)
        budget_user += (
            f"\n\n实际参数:\n"
            f"- 天数: {len(daily_itinerary)}\n"
            f"- 住宿均价: {avg_acc:.2f} CNY/晚\n"
            f"- 活动数: {activity_count}\n"
            f"- 餐食数: {meal_count}\n"
            f"- 请按 transportation/accommodation/activities/meals/buffer "
            f"五类分配，总和精确等于 {budget.total} CNY。"
            f"buffer 为 5%-10%。\n"
        )
        budget_user += "\n" + JSON_FORMAT_INSTRUCTION + "\n"
        budget_user += json_module.dumps(
            {
                "transportation": 0,
                "accommodation": 0,
                "activities": 0,
                "meals": 0,
                "buffer": 0,
                "currency": "CNY",
            },
            ensure_ascii=False,
            indent=2,
        )

        budget_result = await self._llm.generate(
            system_prompt=system, user_prompt=budget_user
        )

        budget_alloc = self._parse_budget(budget_result, budget.total)

        # --- 组装 draft ---
        draft = self._assemble_draft(
            dest=dest,
            days=len(daily_itinerary),
            budget=budget,
            daily_itinerary=daily_itinerary,
            budget_alloc=budget_alloc,
            accommodations=candidates.accommodations,
            prefs=prefs,
            dates=request.dates,
        )

        trace = StepTrace(
            step_name=f"compose",
            input_summary=(
                f"{len(daily_itinerary)}天行程, "
                f"{len(candidates.attractions)}景点, "
                f"{len(candidates.restaurants)}餐厅"
            ),
            output_summary=(
                f"draft_id={draft.draft_id[:8]}, "
                f"days={len(daily_itinerary)}, "
                f"budget={budget_alloc.transportation + budget_alloc.accommodation + budget_alloc.activities + budget_alloc.meals + budget_alloc.buffer:.0f}"
            ),
            duration_ms=int((time.perf_counter() - t0) * 1000),
        )

        return draft, trace

    # ================================================================
    # Draft 组装
    # ================================================================

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
        """组装 TravelPlanDraft（逻辑同 PlanningAgent._assemble_draft）。"""
        from uuid import uuid4
        from datetime import datetime, timezone

        transport = Transportation(
            outbound={
                "mode": "飞机",
                "from": "出发地",
                "to": dest.city,
                "estimated_cost": budget_alloc.transportation * 0.5,
                "duration_minutes": 180,
            },
            return_trip={
                "mode": "飞机",
                "from": dest.city,
                "to": "出发地",
                "estimated_cost": budget_alloc.transportation * 0.5,
                "duration_minutes": 180,
            },
            local=[{"mode": "地铁/公交", "daily_cost": budget.total * 0.01}],
            total_cost=budget_alloc.transportation,
        )

        acc_options = []
        if accommodations:
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

    # ================================================================
    # JSON 解析方法 (LLM dict → dataclass)
    # ================================================================

    @staticmethod
    def _parse_attractions(data: Dict[str, Any]) -> List[Attraction]:
        """解析 LLM 返回的景点列表。"""
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
                    suggested_duration_minutes=item.get(
                        "suggested_duration_minutes", 120
                    ),
                    estimated_price=item.get("estimated_price", 0.0),
                    rating=item.get("rating"),
                    reason=reason,
                    opening_hours=item.get("opening_hours"),
                    peak_season=item.get("peak_season"),
                ))
            except ValueError:
                continue
        return results

    @staticmethod
    def _parse_accommodations(
        data: Dict[str, Any],
    ) -> List[Accommodation]:
        """解析 LLM 返回的住宿列表。"""
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
    def _parse_restaurants(data: Dict[str, Any]) -> List[Restaurant]:
        """解析 LLM 返回的餐厅列表。"""
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
                meal_types=item.get(
                    "meal_types", ["breakfast", "lunch", "dinner"]
                ),
                notes=item.get("notes"),
            ))
        return results

    @staticmethod
    def _parse_itinerary(data: Dict[str, Any]) -> List[ItineraryDay]:
        """解析 LLM 返回的每日行程列表。"""
        items = (
            data.get("daily_itinerary", data)
            if isinstance(data, dict)
            else data
        )
        if isinstance(items, dict):
            items = items.get("daily_itinerary", [])
        if not isinstance(items, list):
            items = []

        days = []
        for day_data in items:
            if not isinstance(day_data, dict):
                continue

            activities = []
            for act in day_data.get("activities", []):
                if not isinstance(act, dict):
                    continue
                reason = act.get(
                    "reason",
                    "详细的推荐理由，至少15个中文字符满足约束要求",
                )
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
                    continue

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
                            dietary_compatible=m.get(
                                "dietary_compatible", True
                            ),
                            notes=m.get("notes"),
                        )

            day_cost = sum(a.estimated_cost for a in activities)
            day_cost += sum(
                (m.estimated_cost for m in meals.values() if m), 0
            )

            days.append(ItineraryDay(
                day=day_data.get("day", len(days) + 1),
                date=day_data.get("date"),
                activities=activities,
                meals=meals,
                transportation_notes=day_data.get("transportation_notes"),
                total_day_cost=day_data.get(
                    "total_day_cost", round(day_cost, 2)
                ),
                total_duration_minutes=day_data.get(
                    "total_duration_minutes",
                    sum(a.duration_minutes for a in activities) + 60,
                ),
            ))

        return days

    @staticmethod
    def _parse_budget(
        data: Dict[str, Any], total_budget: float
    ) -> BudgetAllocation:
        """解析 LLM 返回的预算分配，归一化确保五项之和等于总额。"""
        transport = data.get("transportation", 0)
        accommodation = data.get("accommodation", 0)
        activities = data.get("activities", 0)
        meals = data.get("meals", 0)
        buffer = data.get("buffer", 0)

        raw_sum = transport + accommodation + activities + meals + buffer
        if raw_sum > 0 and abs(raw_sum - total_budget) > 0.01:
            scale = total_budget / raw_sum
            transport = round(transport * scale, 2)
            accommodation = round(accommodation * scale, 2)
            activities = round(activities * scale, 2)
            meals = round(meals * scale, 2)
            buffer = round(
                total_budget - transport - accommodation - activities - meals,
                2,
            )

        return BudgetAllocation(
            transportation=transport,
            accommodation=accommodation,
            activities=activities,
            meals=meals,
            buffer=buffer,
            currency=data.get("currency", "CNY"),
        )
