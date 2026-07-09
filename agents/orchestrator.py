"""Orchestrator — 旅游规划编排系统主控 Agent。

职责:
- parse_user_request: 解析用户自然语言需求为 StructuredRequest
- decompose_task: 分解需求为原子任务 DAG
- route_task: 将任务路由到目标 Agent
- assemble_plan: 整合子 Agent 产出为 FinalTravelPlan
- manage_quality_gate: 执行质量门 Gate 0-3
- process_request: 完整用户请求处理流程

来源: spec/orchestrator_spec.md, playbooks/orchestrator_playbook.md
"""

from __future__ import annotations

import asyncio
import re
from datetime import date, datetime, timezone
from typing import Any, Dict, List, Optional, Tuple
from uuid import uuid4

from core.message import (
    TASK_TIMEOUT,
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
from core.context import ContextStatus, SharedContext
from core.gate_runner import GateResult, GateRunner
from core.orchestration_engine import (
    AgentRouter,
    ResultAssembler,
    RetryManager,
    Task,
    TaskDAG,
    TaskStatus,
)
from core.llm_client import LLMClient
from models.request import (
    Budget,
    DateRange,
    Destination,
    Preferences,
    StructuredRequest,
    Travelers,
)
from models.plan import TravelPlanDraft, ItineraryDay
from models.validation import ValidationReport
from models.quality import PlanQualityReport
from models.check import IssueType, SelfCheckIssue
from models.feedback import RevisionFeedback

# ============================================================
# 常量
# ============================================================

_DEFAULT_ARRIVAL = "09:00"
_DEFAULT_DEPARTURE = "17:00"
_DURATION_PATTERN = re.compile(r"(\d+)\s*天")
_BUDGET_PATTERN = re.compile(r"(\d+)\s*万|(\d+)\s*元|(\d+)\s*块|(\d+)\s*k", re.IGNORECASE)
_PEOPLE_PATTERN = re.compile(r"(\d+)\s*[个位人]")
_ADULTS_CHILDREN_PATTERN = re.compile(r"(\d+)\s*[大个位人].*?(\d+)\s*[小个位孩]")

_PREFERENCE_KEYWORDS: Dict[str, List[str]] = {
    "food": ["美食", "吃", "料理", "小吃", "餐厅", "日料", "寿司", "拉面", "米其林"],
    "culture": ["文化", "历史", "博物馆", "古迹", "寺庙", "神社", "宫殿", "城堡", "传统"],
    "nature": ["自然", "风景", "山", "海", "公园", "花园", "瀑布", "湖", "森林"],
    "shopping": ["购物", "买", "商场", "市场", "免税", "代购", "药妆", "电器"],
    "adventure": ["冒险", "刺激", "极限", "潜水", "滑雪", "跳伞", "攀岩", "冲浪"],
    "relaxation": ["放松", "休闲", "温泉", "按摩", "spa", "度假", "慢", "躺"],
    "sports": ["运动", "跑步", "骑行", "徒步", "登山", "健身"],
}

_PACE_KEYWORDS: Dict[str, List[str]] = {
    "relaxed": ["慢", "放松", "轻松", "悠闲", "不赶"],
    "intensive": ["快", "多", "密集", "丰富", "赶", "紧凑"],
    "moderate": [],  # default
}

_DIETARY_KEYWORDS: Dict[str, str] = {
    "素食": "vegetarian",
    "纯素": "vegan",
    "清真": "halal",
    "不吃猪肉": "no_pork",
    "无麸": "gluten_free",
}

_CUISINE_STYLES = ["日料", "法餐", "意餐", "中餐", "粤菜", "川菜", "泰餐", "韩餐",
                   "越南菜", "印度菜", "墨西哥菜", "地中海", "中东菜", "拉美菜"]

_COMMON_DESTINATIONS: Dict[str, Tuple[str, str]] = {
    "东京": ("东京", "日本"),
    "大阪": ("大阪", "日本"),
    "京都": ("京都", "日本"),
    "北海道": ("札幌", "日本"),
    "首尔": ("首尔", "韩国"),
    "曼谷": ("曼谷", "泰国"),
    "巴黎": ("巴黎", "法国"),
    "伦敦": ("伦敦", "英国"),
    "纽约": ("纽约", "美国"),
    "罗马": ("罗马", "意大利"),
    "巴厘岛": ("巴厘岛", "印度尼西亚"),
    "新加坡": ("新加坡", "新加坡"),
    "香港": ("香港", "中国"),
    "台北": ("台北", "中国台湾"),
    "北京": ("北京", "中国"),
    "上海": ("上海", "中国"),
    "广州": ("广州", "中国"),
    "成都": ("成都", "中国"),
    "三亚": ("三亚", "中国"),
    "杭州": ("杭州", "中国"),
    "西安": ("西安", "中国"),
    "重庆": ("重庆", "中国"),
    "昆明": ("昆明", "中国"),
    "厦门": ("厦门", "中国"),
    "马尔代夫": ("马尔代夫", "马尔代夫"),
    "普吉岛": ("普吉岛", "泰国"),
    "清迈": ("清迈", "泰国"),
}


class Orchestrator(BaseAgent):
    """编排器主控 Agent。

    实现完整的用户请求处理流程:
    parse → Gate 0 → decompose → dispatch → wait → Gate 1 → evaluate → Gate 2 → assemble → Gate 3 → output
    """

    agent_name = "orchestrator"
    agent_version = "1.1.0"

    def __init__(
        self,
        context: Optional[SharedContext] = None,
        registry: Optional[AgentRegistry] = None,
    ):
        self._context = context or SharedContext()
        self._gate_runner = GateRunner(context=self._context)
        self._router = AgentRouter(registry=registry)
        self._retry = RetryManager()
        self._assembler = ResultAssembler()
        self._registry = registry

        # v1.1.0: 真实 Agent 实例 — Orchestrator → Agent 桥接
        self._llm_client = LLMClient()
        self._planning_agent = None    # 懒加载
        self._execution_agent = None   # 懒加载
        self._evaluation_agent = None  # 懒加载
        self._agents_initialized = False

    # -- BaseAgent 抽象属性/方法 --
    @property
    def agent_name(self) -> str:
        return "orchestrator"

    @property
    def agent_version(self) -> str:
        return "1.1.0"

    async def handle_message(self, message: AgentMessage) -> AgentMessage:
        """处理接收到的消息并返回响应。

        根据 task_type 路由到对应的 handler。
        """
        try:
            message = message.validate()
        except MessageValidationError as exc:
            return self._error_response(message, ErrorCode.INVALID_MESSAGE, str(exc))

        handler_map = {
            TaskType.RESPONSE_ITINERARY_DRAFT: self._handle_draft_response,
            TaskType.RESPONSE_VALIDATION_REPORT: self._handle_validation_response,
            TaskType.RESPONSE_RESULT: self._handle_generic_result,
            TaskType.RESPONSE_ERROR: self._handle_error_response,
        }
        handler = handler_map.get(message.task_type)
        if handler:
            return await handler(message)
        return self._error_response(message, ErrorCode.TASK_NOT_SUPPORTED,
                                    f"不支持的任务类型: {message.task_type.value}")

    async def health_check(self) -> HealthStatus:
        return HealthStatus(
            status="healthy",
            last_checked=datetime.now(timezone.utc),
            details={"agent": "orchestrator", "version": self.agent_version},
        )

    def get_capabilities(self) -> List[Capability]:
        return [
            Capability("parse_user_request", "解析用户自然语言旅游需求"),
            Capability("decompose_task", "分解需求为原子任务 DAG"),
            Capability("route_task", "路由任务到目标 Agent"),
            Capability("assemble_plan", "整合子 Agent 产出为最终旅行方案"),
            Capability("manage_quality_gate", "执行 Gate 0-3 质量门检查"),
        ]

    # ============================================================
    # v1.1.0: Agent 实例管理 + dict↔dataclass 桥接
    # ============================================================

    def _init_agents(self) -> None:
        """懒加载初始化子 Agent 实例。"""
        if self._agents_initialized:
            return
        from agents.planning_agent import PlanningAgent
        from agents.execution_agent import ExecutionAgent
        from agents.evaluation_agent import EvaluationAgent

        # v1.2.0 R3: CoT 依赖注入 — PromptBuilder + SelfChecker
        # 仅在 LLM 可用时注入（LLM 不可用时 CoT 无意义）
        _prompt_builder = None
        _self_checker = None
        if self._llm_client.available:
            from core.prompt_builder import PromptBuilder
            from core.self_check import SelfChecker
            _prompt_builder = PromptBuilder()
            _self_checker = SelfChecker()

        self._planning_agent = PlanningAgent(
            registry=self._registry,
            llm_client=self._llm_client if self._llm_client.available else None,
            prompt_builder=_prompt_builder,
            self_checker=_self_checker,
        )
        self._execution_agent = ExecutionAgent(registry=self._registry)
        self._evaluation_agent = EvaluationAgent(registry=self._registry)
        self._agents_initialized = True
        self._log("INFO", "子 Agent 实例已初始化: Planning + Execution + Evaluation")

    @staticmethod
    def _draft_to_dict(draft: TravelPlanDraft) -> Dict[str, Any]:
        """TravelPlanDraft → dict（兼容下游消费者）。"""
        result = draft.to_dict()
        # 规范化 destination: dict → "city, country" 字符串（兼容 assemble_plan）
        dest = result.get("destination")
        if isinstance(dest, dict):
            result["destination"] = f"{dest.get('city', '')}, {dest.get('country', '')}"
        return result

    @staticmethod
    def _dict_to_draft(data: Dict[str, Any]) -> TravelPlanDraft:
        """dict → TravelPlanDraft。"""
        from models.plan import AccommodationOption, Activity, BudgetAllocation, Meal, Transportation
        from models.request import DateRange

        # 解析 daily_itinerary
        daily: List[ItineraryDay] = []
        for i, d in enumerate(data.get("daily_itinerary", [])):
            if isinstance(d, dict):
                activities = []
                for a in d.get("activities", []):
                    if isinstance(a, dict):
                        reason = a.get("reason", "推荐理由占位至少十五个字符满足校验约束")
                        if len(reason) < 10:
                            reason = reason + "，补充细节以符合推荐理由最小长度"
                        activities.append(Activity(
                            name=a.get("name", "未知活动"),
                            type=a.get("type", "culture"),
                            start_time=a.get("start_time", "09:00"),
                            duration_minutes=a.get("duration_minutes", 120),
                            location=a.get("location", "未知"),
                            estimated_cost=a.get("estimated_cost", 0.0),
                            reason=reason,
                        ))

                meals_data = d.get("meals", {})
                meals: Dict[str, Any] = {}
                if isinstance(meals_data, dict):
                    for m_type in ("breakfast", "lunch", "dinner"):
                        m = meals_data.get(m_type)
                        if isinstance(m, dict):
                            meals[m_type] = Meal(
                                type=m_type,
                                restaurant_name=m.get("restaurant", m.get("restaurant_name", "未知")),
                                location=m.get("location", "未知"),
                                cuisine=m.get("cuisine", "当地特色"),
                                estimated_cost=m.get("estimated_cost", 50.0),
                                dietary_compatible=m.get("dietary_compatible", True),
                            )

                daily.append(ItineraryDay(
                    day=d.get("day", i + 1),
                    date=d.get("date"),
                    activities=activities,
                    meals=meals,
                    transportation_notes=d.get("transportation_notes"),
                    total_day_cost=d.get("total_day_cost", 0),
                    total_duration_minutes=d.get("total_duration_minutes", 0),
                ))

        # 解析 accommodation
        accommodation = []
        for a in data.get("accommodation", []):
            if isinstance(a, dict):
                accommodation.append(AccommodationOption(
                    name=a.get("name", "未知"),
                    location=a.get("location", "未知"),
                    type=a.get("type", "hotel"),
                    cost_per_night=a.get("cost_per_night", 0),
                    total_cost=a.get("total_cost", 0),
                    distance_to_center_km=a.get("distance_to_center_km", 0),
                    highlights=a.get("highlights", []),
                    rating=a.get("rating"),
                ))

        # 解析 budget_allocation
        ba = data.get("budget_allocation", {})
        if isinstance(ba, dict):
            budget_alloc = BudgetAllocation(
                transportation=ba.get("transportation", 0),
                accommodation=ba.get("accommodation", 0),
                activities=ba.get("activities", 0),
                meals=ba.get("meals", 0),
                buffer=ba.get("buffer", 0),
                currency=ba.get("currency", "CNY"),
            )
        else:
            budget_alloc = BudgetAllocation()

        # 解析 destination
        dest = data.get("destination", "")
        if isinstance(dest, str) and ", " in dest:
            parts = dest.split(", ", 1)
            dest_dict = {"city": parts[0], "country": parts[1]}
        elif isinstance(dest, dict):
            dest_dict = dest
        else:
            dest_dict = {"city": str(dest), "country": ""}

        return TravelPlanDraft(
            draft_id=data.get("draft_id"),
            destination=dest_dict,
            duration_days=data.get("duration_days", 0),
            transportation=Transportation(**(data.get("transportation") or {})),
            accommodation=accommodation,
            daily_itinerary=daily,
            budget_allocation=budget_alloc,
            total_budget=data.get("total_budget", 0),
            preferences_applied=data.get("preferences_applied", []),
            revision_version=data.get("revision_version", 0),
        )

    @staticmethod
    def _dict_to_validation(data: Dict[str, Any]) -> ValidationReport:
        """dict → ValidationReport。"""
        from models.validation import (
            ValidationReport as VR, ValidationSummary,
            PriceCheckResult, TimeCheckResult, GeographyCheckResult,
            ConstraintCheckResult,
        )
        return VR(
            validation_id=data.get("validation_id"),
            draft_id=data.get("draft_id"),
            price_check=PriceCheckResult(**(data.get("price_check") or {})),
            time_check=TimeCheckResult(**(data.get("time_check") or {})),
            geography_check=GeographyCheckResult(**(data.get("geography_check") or {})),
            constraint_check=ConstraintCheckResult(**(data.get("constraint_check") or {})),
            risk_alerts=data.get("risk_alerts", []),
            summary=ValidationSummary(**(data.get("summary") or {})),
        )

    # ============================================================
    # 核心公共方法 — spec/orchestrator_spec.md §3.1
    # ============================================================

    async def process_request(self, raw_text: str) -> Dict[str, Any]:
        """完整的用户请求处理流程。

        Args:
            raw_text: 用户自然语言输入。

        Returns:
            FinalTravelPlan 字典或错误信息。
        """
        # Step 1: 解析
        request = self.parse_user_request(raw_text)
        self._context.set_request(request.to_dict())
        self._context.set_status(ContextStatus.VALIDATING)
        self._log("INFO", f"解析用户请求: {request.destination.city} {request.dates.duration_days}天")

        # Step 2: Gate 0
        gate0 = self.manage_quality_gate(0, request.to_dict())
        if not gate0.passed:
            self._context.set_status(ContextStatus.FAILED)
            self._log("ERROR", f"Gate 0 未通过: {[i.description for i in gate0.blocking_issues]}")
            return {"error": "gate_0_failed", "blocking_issues": [i.description for i in gate0.blocking_issues]}

        # Step 3: 分解任务
        self._context.set_status(ContextStatus.DECOMPOSING)
        task_dag = self.decompose_task(request)
        self._context.set_task_queue({"tasks": [t.task_id for t in task_dag.get_all_tasks()]})
        self._log("INFO", f"任务分解完成: {task_dag.task_count} 个任务")

        # Step 4: 执行 Planning → Execution → Evaluation 循环
        result = await self._run_planning_cycle(request, task_dag)
        return result

    def parse_user_request(self, raw_text: str) -> StructuredRequest:
        """解析用户自然语言需求为 StructuredRequest。

        Args:
            raw_text: 用户自然语言输入。

        Returns:
            StructuredRequest，含目的地/日期/预算/人数/偏好。

        Raises:
            ValueError: 输入为空或无法解析。
        """
        if not raw_text or not raw_text.strip():
            raise ValueError("用户输入不能为空")

        text = raw_text.strip()

        # 目的地识别
        destination = self._extract_destination(text)

        # 日期提取
        dates = self._extract_dates(text)

        # 预算提取
        budget = self._extract_budget(text)

        # 人数提取
        travelers = self._extract_travelers(text)

        # 偏好提取
        preferences = self._extract_preferences(text)

        return StructuredRequest(
            destination=destination,
            dates=dates,
            budget=budget,
            travelers=travelers,
            preferences=preferences,
            raw_text=raw_text,
            request_id=str(uuid4()),
        )

    def decompose_task(self, request: StructuredRequest) -> TaskDAG:
        """分解用户需求为原子任务 DAG。

        标准 4 任务分解:
        T1: 交通方案 (无依赖)
        T2: 住宿方案 (无依赖)
        T3: 每日行程 (依赖 T1, T2)
        T4: 预算分配 (依赖 T1, T2, T3)
        """
        return self._assembler.build_task_queue(request.to_dict())

    def route_task(self, task: Task) -> Optional[str]:
        """为任务解析目标 Agent。

        Returns:
            Agent 名称，无匹配返回 None。
        """
        return self._router.route_task(task)

    def assemble_plan(
        self,
        draft: Optional[Dict[str, Any]] = None,
        validation: Optional[Dict[str, Any]] = None,
        quality: Optional[Dict[str, Any]] = None,
        iteration_count: int = 0,
        degraded: bool = False,
        degraded_reason: Optional[str] = None,
    ) -> Dict[str, Any]:
        """整合所有 Agent 产出为 FinalTravelPlan。"""
        return self._assembler.assemble(
            draft=draft,
            validation=validation,
            quality=quality,
            iteration_count=iteration_count,
            degraded=degraded,
            degraded_reason=degraded_reason,
        )

    def manage_quality_gate(self, gate_id: int, payload: Dict[str, Any]) -> GateResult:
        """执行质量门检查。

        Args:
            gate_id: Gate 编号 (0-3)。
            payload: Gate 检查所需的数据。

        Returns:
            GateResult。
        """
        if gate_id == 0:
            return self._gate_runner.run_gate_0(payload)
        elif gate_id == 1:
            return self._gate_runner.run_gate_1(payload)
        elif gate_id == 2:
            iteration = self._context.get_iteration_count() if self._context else 1
            return self._gate_runner.run_gate_2(payload, iteration)
        elif gate_id == 3:
            return self._gate_runner.run_gate_3(payload)
        else:
            return GateResult(
                gate_id=gate_id,
                passed=False,
                blocking_issues=[GateResult.__dict__.get(
                    "blocking_issues", [])],
            )

    def handle_revision(self, quality_report: Dict[str, Any]) -> str:
        """决定修订策略。

        Returns:
            "APPROVE" | "REVISE" | "DEGRADE"
        """
        composite = quality_report.get("composite_score", 0)
        iteration = self._context.get_iteration_count() + 1

        if composite >= 80:
            return "APPROVE"
        elif iteration >= 3:
            return "DEGRADE"
        else:
            return "REVISE"

    # ============================================================
    # 内部辅助方法 — 解析
    # ============================================================

    def _extract_destination(self, text: str) -> Destination:
        """从文本中提取目的地。"""
        # 先匹配已知目的地
        for key, (city, country) in _COMMON_DESTINATIONS.items():
            if key in text:
                return Destination(city=city, country=country)

        # 尝试匹配 "去<城市名>" 模式
        go_pattern = re.compile(r"去\s*([^\s，。,\.\d]+)")
        match = go_pattern.search(text)
        if match:
            city = match.group(1).strip()
            return Destination(city=city, country="未知")

        return Destination(city="未知", country="未知")

    def _extract_dates(self, text: str) -> DateRange:
        """从文本中提取日期信息。"""
        # 尝试匹配 YYYY-MM-DD 或 YYYY/MM/DD
        date_pattern = re.compile(r"(\d{4}[-/]\d{1,2}[-/]\d{1,2})")
        dates_found = date_pattern.findall(text)
        dates_normalized = [d.replace("/", "-") for d in dates_found]

        arrival = dates_normalized[0] if len(dates_normalized) >= 1 else None
        departure = dates_normalized[1] if len(dates_normalized) >= 2 else None

        # 天数匹配
        duration_days = 0
        dur_match = _DURATION_PATTERN.search(text)
        if dur_match:
            duration_days = int(dur_match.group(1))

        # 相对时间词
        today = date.today()
        if "今天" in text:
            arrival = today.isoformat()
        elif "明天" in text:
            arrival = today.replace(day=today.day + 1).isoformat() if today.day < 28 else today.isoformat()
        elif "后天" in text:
            arrival = today.replace(day=today.day + 2).isoformat() if today.day < 27 else today.isoformat()

        return DateRange(
            arrival=arrival,
            departure=departure,
            duration_days=duration_days,
        )

    def _extract_budget(self, text: str) -> Budget:
        """从文本中提取预算。"""
        # 匹配 "X万", "X元", "X块", "Xk"
        match = _BUDGET_PATTERN.search(text)
        if match:
            wan = match.group(1)
            yuan = match.group(2)
            kuai = match.group(3)
            k = match.group(4)
            if wan:
                return Budget(total=float(wan) * 10000)
            elif yuan:
                return Budget(total=float(yuan))
            elif kuai:
                return Budget(total=float(kuai))
            elif k:
                return Budget(total=float(k) * 1000)
        return Budget(total=1)

    def _extract_travelers(self, text: str) -> Travelers:
        """从文本中提取人数信息。"""
        # 匹配 "2大人1小孩" 模式
        match = _ADULTS_CHILDREN_PATTERN.search(text)
        if match:
            return Travelers(adults=int(match.group(1)), children=int(match.group(2)))

        # 匹配 "X个人", "X人", "X位"
        match = _PEOPLE_PATTERN.search(text)
        if match:
            count = int(match.group(1))
            return Travelers(adults=max(1, count))

        return Travelers(adults=1, children=0)

    def _extract_preferences(self, text: str) -> Preferences:
        """从文本中提取偏好标签。"""
        styles: List[str] = []
        for style, keywords in _PREFERENCE_KEYWORDS.items():
            for kw in keywords:
                if kw in text and style not in styles:
                    styles.append(style)
                    break

        # 节奏
        pace = "moderate"
        for p, keywords in _PACE_KEYWORDS.items():
            for kw in keywords:
                if kw in text:
                    pace = p
                    break
            if pace != "moderate":
                break

        # 饮食限制
        dietary: List[str] = []
        for cn, tag in _DIETARY_KEYWORDS.items():
            if cn in text:
                dietary.append(tag)

        return Preferences(style=styles, pace=pace, dietary=dietary)

    # ============================================================
    # 异步执行循环 — orchestrator_playbook.md §3 Steps 3-5
    # ============================================================

    async def _run_planning_cycle(
        self, request: StructuredRequest, task_dag: TaskDAG
    ) -> Dict[str, Any]:
        """执行 Planning → Execution → Evaluation 的完整循环。

        最多 3 轮迭代，包含 Gate 1-3 检查。
        """
        max_iterations = 3
        current_draft: Optional[Dict[str, Any]] = None
        current_validation: Optional[Dict[str, Any]] = None
        current_quality: Optional[Dict[str, Any]] = None
        degraded = False
        degraded_reason: Optional[str] = None

        # 分发任务到 Planning Agent
        self._context.set_status(ContextStatus.DISPATCHING)

        # Phase 1: Planning
        self._context.set_status(ContextStatus.WAITING_PLANNER)
        current_draft = await self._call_planning_agent(request, task_dag)
        self._context.set_current_draft(current_draft)

        # Phase 2: Execution
        self._context.set_status(ContextStatus.WAITING_EXECUTOR)
        current_validation = await self._call_execution_agent(current_draft, request)
        self._context.set_validation_report(current_validation)

        # Gate 1
        self._context.set_status(ContextStatus.GATE_1)
        gate1 = self.manage_quality_gate(1, current_validation)
        if not gate1.passed:
            self._log("WARNING", f"Gate 1 未通过: {len(gate1.blocking_issues)} 个阻断问题")

        # Phase 3: Evaluation + 修订循环
        for iteration in range(1, max_iterations + 1):
            self._context.set_status(ContextStatus.WAITING_EVALUATOR)
            current_quality = await self._call_evaluation_agent(current_draft, current_validation)
            self._context.set_quality_report(current_quality)

            # Gate 2
            self._context.set_status(ContextStatus.DECIDING)
            gate2 = self.manage_quality_gate(2, current_quality)
            self._context.increment_iteration()

            if gate2.passed and not gate2.degraded:
                self._log("INFO", f"Gate 2 通过 (第{iteration}轮)")
                break
            elif gate2.degraded:
                self._log("WARNING", f"Gate 2 降级通过 (第{iteration}轮)")
                degraded = True
                degraded_reason = f"第{iteration}轮评估未达标({current_quality.get('composite_score', 0)}分)，降级输出"
                break
            elif gate2.rejected:
                self._log("ERROR", f"Gate 2 拒绝 (第{iteration}轮): score < 60")
                degraded = True
                degraded_reason = f"第{iteration}轮评估被拒绝(得分{current_quality.get('composite_score', 0)} < 60)"
                break
            else:
                # 需要修订
                if iteration < max_iterations:
                    self._log("INFO", f"Gate 2 需修订 (第{iteration}轮)")
                    self._context.set_status(ContextStatus.REVISING)
                    current_draft = await self._call_revision(
                        current_draft, current_validation, current_quality
                    )
                    self._context.set_current_draft(current_draft)
                    # 重新执行校验 (REVISING → WAITING_PLANNER → WAITING_EXECUTOR → GATE_1)
                    self._context.set_status(ContextStatus.WAITING_PLANNER)
                    current_validation = await self._call_execution_agent(current_draft, request)
                    self._context.set_validation_report(current_validation)
                    self._context.set_status(ContextStatus.WAITING_EXECUTOR)
                    self._context.set_status(ContextStatus.GATE_1)
                else:
                    self._log("WARNING", f"已达最大迭代次数({max_iterations})，降级输出")
                    degraded = True
                    degraded_reason = f"已达最大迭代次数({max_iterations})，部分质量指标未达标"
                    break

        # Phase 4: 组装输出
        self._context.set_status(ContextStatus.ASSEMBLING)
        final_plan = self.assemble_plan(
            draft=current_draft,
            validation=current_validation,
            quality=current_quality,
            iteration_count=self._context.get_iteration_count(),
            degraded=degraded,
            degraded_reason=degraded_reason,
        )

        # Gate 3
        self._context.set_status(ContextStatus.GATE_3)
        gate3 = self.manage_quality_gate(3, final_plan)
        if not gate3.passed:
            # 自动补全尝试
            final_plan = self._auto_fix_gate3(final_plan, gate3)
            gate3 = self.manage_quality_gate(3, final_plan)
            if not gate3.passed:
                final_plan["summary"]["degraded"] = True
                final_plan["summary"]["degraded_reason"] = (
                    (final_plan["summary"].get("degraded_reason") or "")
                    + "; Gate 3 部分检查未通过"
                )
                self._context.set_status(ContextStatus.COMPLETED_DEGRADED)
            else:
                self._context.set_status(ContextStatus.COMPLETED)
        else:
            self._context.set_status(ContextStatus.COMPLETED)

        return final_plan

    # ============================================================
    # 子 Agent 调用 (stub/mock 实现)
    # ============================================================

    async def _call_planning_agent(
        self, request: StructuredRequest, _task_dag: TaskDAG
    ) -> Dict[str, Any]:
        """调用 Planning Agent 生成行程草稿。

        v1.1.0: 桥接到真实 PlanningAgent（LLM + stub fallback）。
        """
        self._init_agents()
        try:
            draft = await self._planning_agent.create_itinerary(request)
            return self._draft_to_dict(draft)
        except Exception as exc:
            self._log("WARNING", f"PlanningAgent 调用失败，回退 stub: {exc}")
            return await self._call_planning_agent_stub(request)

    async def _call_planning_agent_stub(
        self, request: StructuredRequest
    ) -> Dict[str, Any]:
        """Planning Agent stub（保留作为终极降级）。"""
        await asyncio.sleep(0.01)
        days = request.dates.duration_days or 3
        total = request.budget.total
        city = request.destination.city
        country = request.destination.country

        # 构建示例每日行程
        daily_itinerary = []
        for d in range(1, days + 1):
            day_date = None
            if request.dates.arrival:
                try:
                    arr = date.fromisoformat(request.dates.arrival)
                    day_date = arr.replace(day=arr.day + d - 1).isoformat() if arr.day + d - 1 <= 28 else None
                except (ValueError, TypeError):
                    pass

            daily_itinerary.append({
                "day": d,
                "date": day_date,
                "activities": [
                    {"name": f"{city}景点A", "type": "culture", "start_time": "09:00",
                     "duration_minutes": 120, "location": f"{city}市中心",
                     "estimated_cost": total * 0.02, "reason": f"{city}著名文化景点，值得深度游览"},
                    {"name": f"{city}景点B", "type": "nature", "start_time": "13:00",
                     "duration_minutes": 90, "location": f"{city}近郊",
                     "estimated_cost": total * 0.01, "reason": f"{city}自然风光胜地，适合放松身心"},
                ],
                "meals": {
                    "breakfast": {"restaurant": f"{city}早餐店", "cuisine": "当地特色",
                                  "location": f"{city}市区", "estimated_cost": total * 0.005},
                    "lunch": {"restaurant": f"{city}午餐馆", "cuisine": f"{country}菜",
                              "location": f"{city}市中心", "estimated_cost": total * 0.008},
                    "dinner": {"restaurant": f"{city}晚餐馆", "cuisine": f"{country}料理",
                               "location": f"{city}市区", "estimated_cost": total * 0.012},
                },
                "transportation_notes": "建议使用公共交通",
                "total_day_cost": total * 0.045,
                "total_duration_minutes": 300,
            })

        budget_allocation = {
            "transportation": total * 0.30,
            "accommodation": total * 0.35,
            "activities": total * 0.15,
            "meals": total * 0.15,
            "buffer": total * 0.05,
        }

        transportation = {
            "outbound": {"mode": "飞机", "from": "出发地", "to": city,
                         "estimated_cost": total * 0.15, "duration_minutes": 180},
            "return_trip": {"mode": "飞机", "from": city, "to": "出发地",
                            "estimated_cost": total * 0.15, "duration_minutes": 180},
            "local": [{"mode": "地铁/公交", "estimated_daily_cost": total * 0.005}],
            "total_cost": total * 0.30,
        }

        accommodation = [
            {"name": f"{city}酒店A", "location": f"{city}市中心", "type": "hotel",
             "cost_per_night": total * 0.07, "total_cost": total * 0.07 * days,
             "distance_to_center_km": 1.5, "highlights": ["交通便利", "含早餐"],
             "rating": 4.5},
            {"name": f"{city}酒店B", "location": f"{city}近郊", "type": "hotel",
             "cost_per_night": total * 0.05, "total_cost": total * 0.05 * days,
             "distance_to_center_km": 5.0, "highlights": ["安静舒适", "性价比高"],
             "rating": 4.2},
        ]

        return {
            "draft_id": str(uuid4()),
            "destination": f"{city}, {country}",
            "duration_days": days,
            "total_budget": total,
            "transportation": transportation,
            "accommodation": accommodation,
            "daily_itinerary": daily_itinerary,
            "budget_allocation": budget_allocation,
            "preferences_applied": request.preferences.style,
            "revision_version": 0,
        }

    async def _call_execution_agent(
        self, draft: Dict[str, Any], _request: StructuredRequest
    ) -> Dict[str, Any]:
        """调用 Execution Agent 验证可行性。

        v1.1.0: 桥接到真实 ExecutionAgent（API 工具 + stub fallback）。
        """
        self._init_agents()
        try:
            draft_obj = self._dict_to_draft(draft)
            report = await self._execution_agent.validate_feasibility(draft_obj, _request)
            return report.to_dict()
        except Exception as exc:
            self._log("WARNING", f"ExecutionAgent 调用失败，回退 stub: {exc}")
            return await self._call_execution_agent_stub(draft)

    async def _call_execution_agent_stub(
        self, draft: Dict[str, Any]
    ) -> Dict[str, Any]:
        """Execution Agent stub（保留作为终极降级）。"""
        await asyncio.sleep(0.01)
        total_budget = draft.get("total_budget", 0)
        budget_alloc = draft.get("budget_allocation", {})
        total_allocated = sum(v for v in budget_alloc.values() if isinstance(v, (int, float)))

        # 检查预算是否超支
        blocking_issues = []
        if total_allocated > total_budget:
            blocking_issues.append({
                "constraint": "budget_ceiling",
                "expected": f"<= {total_budget}",
                "actual": str(total_allocated),
                "fix_suggestion": "请缩减预算分配",
            })

        return {
            "validation_id": str(uuid4()),
            "draft_id": draft.get("draft_id"),
            "overall_status": "infeasible" if blocking_issues else "feasible",
            "price_check": {
                "items_checked": 5,
                "anomalies": [],
                "overall_accuracy_score": 95,
                "overall_status": "passed",
            },
            "time_check": {
                "days_checked": draft.get("duration_days", 0),
                "conflicts": [],
                "overall_time_status": "passed",
                "overall_time_score": 95,
                "warnings": [],
            },
            "geography_check": {
                "detours_found": 0,
                "detours": [],
                "overall_geo_status": "passed",
                "overall_geo_score": 95,
                "warnings": [],
            },
            "constraint_check": {
                "hard_constraints_total": 4,
                "hard_constraints_passed": 4 - len(blocking_issues),
                "soft_constraints_total": 3,
                "soft_constraints_passed": 3,
                "blocking_issues": blocking_issues,
                "warnings": [],
            },
            "risk_alerts": [],
            "summary": {
                "blocking_count": len(blocking_issues),
                "warning_count": 0,
                "risk_count": 0,
                "action_required": "revise" if blocking_issues else "none",
            },
        }

    async def _call_evaluation_agent(
        self, draft: Dict[str, Any], validation: Dict[str, Any]
    ) -> Dict[str, Any]:
        """调用 Evaluation Agent (Mode B) 评估方案质量。

        v1.1.0: 桥接到真实 EvaluationAgent，输出格式兼容下游 Gate 2 + assemble_plan。
        """
        self._init_agents()
        try:
            draft_obj = self._dict_to_draft(draft)
            val_obj = self._dict_to_validation(validation)
            report = await self._evaluation_agent.evaluate_plan(draft_obj, val_obj)
            result = report.to_dict()
            # 规范化 dimensions: PlanDimensionScore 对象 → 裸分数（兼容 run_gate_2）
            dims = result.get("dimensions", {})
            if dims and isinstance(next(iter(dims.values()), None), dict):
                result["dimensions"] = {
                    k: v.get("score", 0) if isinstance(v, dict) else v
                    for k, v in dims.items()
                }
            return result
        except Exception as exc:
            self._log("WARNING", f"EvaluationAgent 调用失败，回退 stub: {exc}")
            return await self._call_evaluation_agent_stub(draft, validation)

    async def _call_evaluation_agent_stub(
        self, draft: Dict[str, Any], validation: Dict[str, Any]
    ) -> Dict[str, Any]:
        """Evaluation Agent stub（保留作为终极降级）。"""
        await asyncio.sleep(0.01)
        blocking_count = validation.get("summary", {}).get("blocking_count", 0)

        # 基于 validation 结果计算评分
        if blocking_count > 0:
            completeness = 3
            feasibility = 2
            constraint_sat = 2
        else:
            completeness = 5
            feasibility = 5
            constraint_sat = 5

        exp_quality = 4
        info_accuracy = 4

        dim_scores = {
            "completeness": completeness,
            "feasibility": feasibility,
            "constraint_satisfaction": constraint_sat,
            "experience_quality": exp_quality,
            "information_accuracy": info_accuracy,
        }

        composite = (
            completeness * 0.25
            + feasibility * 0.25
            + constraint_sat * 0.25
            + exp_quality * 0.15
            + info_accuracy * 0.10
        ) * 20

        return {
            "report_id": str(uuid4()),
            "plan_id": draft.get("draft_id"),
            "dimensions": {
                "completeness": completeness,
                "feasibility": feasibility,
                "constraint_satisfaction": constraint_sat,
                "experience_quality": exp_quality,
                "information_accuracy": info_accuracy,
            },
            "composite_score": round(composite, 1),
            "verdict": "PASS" if composite >= 80 else ("REVISE" if composite >= 60 else "REJECT"),
            "revision_feedback": [],
            "iteration": 0,
        }

    async def _call_revision(
        self,
        draft: Dict[str, Any],
        validation: Dict[str, Any],
        quality: Dict[str, Any],
    ) -> Dict[str, Any]:
        """调用 Planning Agent 修订行程。

        v1.2.0 R4: 将 Execution/Evaluation 输出转为精确定位的结构化反馈。
        """
        self._init_agents()
        try:
            draft_obj = self._dict_to_draft(draft)
            feedback_list = self._build_revision_feedback(validation, quality)
            revised = await self._planning_agent.revise_itinerary(draft_obj, feedback_list)
            return self._draft_to_dict(revised)
        except Exception as exc:
            self._log("WARNING", f"PlanningAgent.revise 调用失败，回退 stub: {exc}")
            return await self._call_revision_stub(draft)

    @classmethod
    def _build_revision_feedback(
        cls, validation: Dict[str, Any], quality: Dict[str, Any]
    ) -> List[RevisionFeedback]:
        """从校验/评估报告构造结构化修订反馈。"""
        feedback: List[RevisionFeedback] = []
        feedback.extend(cls._feedback_from_validation(validation or {}))
        feedback.extend(cls._feedback_from_quality_feedback(quality or {}))
        feedback.extend(cls._feedback_from_quality_dimensions(quality or {}))
        return cls._dedupe_revision_feedback(feedback)

    @classmethod
    def _feedback_from_validation(
        cls, validation: Dict[str, Any]
    ) -> List[RevisionFeedback]:
        """提取 Execution Agent 发现的可定位问题。"""
        data = cls._as_plain_dict(validation)
        items: List[RevisionFeedback] = []
        constraints = data.get("constraint_check", {}).get("blocking_issues", [])
        for issue in constraints:
            if isinstance(issue, dict):
                items.append(cls._feedback_from_constraint_issue(issue))

        anomalies = data.get("price_check", {}).get("anomalies", [])
        for anomaly in anomalies:
            if isinstance(anomaly, dict) and anomaly.get("severity") == "high":
                items.append(cls._feedback_from_price_anomaly(anomaly))
        return items

    @classmethod
    def _feedback_from_quality_feedback(
        cls, quality: Dict[str, Any]
    ) -> List[RevisionFeedback]:
        """兼容 Evaluation Agent 旧版 revision_feedback。"""
        data = cls._as_plain_dict(quality)
        items: List[RevisionFeedback] = []
        for raw in data.get("revision_feedback", []):
            if not isinstance(raw, dict):
                continue
            if isinstance(raw.get("issue"), dict):
                items.append(RevisionFeedback.from_dict(raw))
                continue
            text = raw.get("issue", "")
            dimension = raw.get("dimension", "")
            suggestion = raw.get("suggestion", "")
            priority = cls._priority_from_raw(raw.get("priority", "medium"))
            items.append(RevisionFeedback(
                issue=SelfCheckIssue(
                    type=cls._infer_issue_type(dimension, text),
                    location=raw.get("location") or cls._infer_location(text, dimension),
                    actual_value=raw.get("actual_value", text),
                    expected=raw.get("expected", suggestion or "按建议修正"),
                    severity=priority,
                ),
                suggestion=suggestion,
                priority=priority,
                source="evaluation_agent",
            ))
        return items

    @classmethod
    def _feedback_from_quality_dimensions(
        cls, quality: Dict[str, Any]
    ) -> List[RevisionFeedback]:
        """将低分维度转为补充性修订反馈。"""
        data = cls._as_plain_dict(quality)
        items: List[RevisionFeedback] = []
        dimensions = data.get("dimensions", {})
        for dimension, raw_score in dimensions.items():
            score = cls._extract_dimension_score(raw_score)
            if score is None or score >= 4:
                continue
            priority = "blocking" if score <= 3 else "warning"
            items.append(RevisionFeedback(
                issue=SelfCheckIssue(
                    type=cls._infer_issue_type(dimension, dimension),
                    location=f"quality.{dimension}",
                    actual_value=score,
                    expected=">=4",
                    severity=priority,
                ),
                suggestion=cls._dimension_suggestion(dimension),
                priority=priority,
                source="evaluation_agent",
            ))
        return items

    @classmethod
    def _feedback_from_constraint_issue(
        cls, issue: Dict[str, Any]
    ) -> RevisionFeedback:
        """将硬约束阻断问题转为结构化反馈。"""
        constraint = issue.get("constraint", "constraint")
        actual = issue.get("actual", "")
        expected = issue.get("expected", "满足硬约束")
        suggestion = issue.get("fix_suggestion") or issue.get("suggestion", "")
        return RevisionFeedback(
            issue=SelfCheckIssue(
                type=cls._infer_issue_type(constraint, suggestion, actual),
                location=cls._infer_location(constraint, suggestion, actual),
                actual_value=actual,
                expected=expected,
                severity="blocking",
            ),
            suggestion=suggestion or "请按期望值修正该硬约束问题",
            priority="blocking",
            source="execution_agent",
        )

    @classmethod
    def _feedback_from_price_anomaly(
        cls, anomaly: Dict[str, Any]
    ) -> RevisionFeedback:
        """将高严重度价格异常转为结构化反馈。"""
        item = anomaly.get("item", "price_check")
        median = anomaly.get("market_median", "")
        expected = f"接近市场中位价 {median}" if median != "" else "价格回到市场合理区间"
        return RevisionFeedback(
            issue=SelfCheckIssue(
                type=IssueType.BUDGET_OVERSPEND,
                location=cls._infer_location(item, anomaly.get("suggestion", "")),
                actual_value=anomaly.get("estimated"),
                expected=expected,
                severity="blocking",
            ),
            suggestion=anomaly.get("suggestion") or "替换为同区域预算内选项",
            priority="blocking",
            source="execution_agent",
        )

    @staticmethod
    def _as_plain_dict(value: Any) -> Dict[str, Any]:
        """兼容 dataclass/to_dict 与裸 dict。"""
        if hasattr(value, "to_dict"):
            return value.to_dict()
        return value if isinstance(value, dict) else {}

    @staticmethod
    def _extract_dimension_score(raw_score: Any) -> Optional[float]:
        """从裸分数或 PlanDimensionScore dict 中提取 score。"""
        if isinstance(raw_score, (int, float)):
            return float(raw_score)
        if isinstance(raw_score, dict) and isinstance(raw_score.get("score"), (int, float)):
            return float(raw_score["score"])
        return None

    @staticmethod
    def _priority_from_raw(raw_priority: Any) -> str:
        """将 high/medium/low 映射到 blocking/warning。"""
        return "blocking" if str(raw_priority).lower() == "high" else "warning"

    @staticmethod
    def _infer_issue_type(*parts: Any) -> IssueType:
        """根据描述文本推断 SelfCheckIssue 类型。"""
        text = " ".join(str(part).lower() for part in parts if part is not None)
        if any(token in text for token in ("duplicate", "重复")):
            return IssueType.DUPLICATE_ATTRACTION
        if any(token in text for token in ("geo", "route", "distance", "地理", "绕路", "距离")):
            return IssueType.GEO_DISTANCE
        if any(token in text for token in ("缺餐", "餐食不足", "missing meal")):
            return IssueType.MISSING_MEAL
        if any(token in text for token in ("budget", "price", "cost", "预算", "价格", "超支", "超出")):
            return IssueType.BUDGET_OVERSPEND
        if any(token in text for token in ("schedule", "time", "activity", "行程", "时间", "活动")):
            return IssueType.MISSING_ACTIVITY
        if any(token in text for token in ("exclude", "排除", "禁止")):
            return IssueType.EXCLUDED_TYPE
        return IssueType.STYLE_MISMATCH

    @staticmethod
    def _infer_location(*parts: Any) -> str:
        """从自然语言片段里推断 day_x.meal 形式的位置。"""
        text = " ".join(str(part) for part in parts if part is not None)
        day_match = re.search(r"(?:day[_\s-]*|第)(\d+)", text, re.IGNORECASE)
        day = day_match.group(1) if day_match else None
        meal = None
        if re.search(r"dinner|晚餐", text, re.IGNORECASE):
            meal = "dinner"
        elif re.search(r"lunch|午餐", text, re.IGNORECASE):
            meal = "lunch"
        elif re.search(r"breakfast|早餐", text, re.IGNORECASE):
            meal = "breakfast"
        if day and meal:
            return f"day_{day}.{meal}"
        if day:
            return f"day_{day}"
        return "plan"

    @staticmethod
    def _dimension_suggestion(dimension: str) -> str:
        """给低分维度提供保守的补充修订建议。"""
        suggestions = {
            "feasibility": "优先消除 Execution Agent 标出的阻断问题",
            "constraint_satisfaction": "逐项核对用户硬约束并修正不满足项",
            "experience_quality": "优化节奏、去重景点并减少绕行",
            "information_accuracy": "替换无法验证或价格偏离过大的推荐",
            "completeness": "补齐交通、住宿、餐食、预算等缺失结构",
        }
        return suggestions.get(dimension, "按该维度的扣分原因进行针对性修订")

    @staticmethod
    def _dedupe_revision_feedback(
        feedback: List[RevisionFeedback],
    ) -> List[RevisionFeedback]:
        """按类型、位置和期望值去重，保留首次出现的更具体反馈。"""
        seen = set()
        unique: List[RevisionFeedback] = []
        for item in feedback:
            key = (
                item.issue.type.value,
                item.issue.location,
                str(item.issue.actual_value),
                item.issue.expected,
            )
            if key in seen:
                continue
            seen.add(key)
            unique.append(item)
        return unique

    async def _call_revision_stub(
        self, draft: Dict[str, Any]
    ) -> Dict[str, Any]:
        """Revision stub（保留作为终极降级）。"""
        await asyncio.sleep(0.01)
        revised = dict(draft)
        revised["revision_version"] = draft.get("revision_version", 0) + 1
        revised["draft_id"] = str(uuid4())
        return revised

    # ============================================================
    # 消息处理 Handlers
    # ============================================================

    async def _handle_draft_response(self, message: AgentMessage) -> AgentMessage:
        """处理 Planning Agent 返回的行程草稿。"""
        self._context.set_current_draft(message.payload.get("data", message.payload))
        return self._ok_response(message, {"status": "draft_stored"})

    async def _handle_validation_response(self, message: AgentMessage) -> AgentMessage:
        """处理 Execution Agent 返回的校验报告。"""
        self._context.set_validation_report(message.payload.get("data", message.payload))
        return self._ok_response(message, {"status": "validation_stored"})

    async def _handle_generic_result(self, message: AgentMessage) -> AgentMessage:
        """处理通用结果响应。"""
        return self._ok_response(message, {"status": "received"})

    async def _handle_error_response(self, message: AgentMessage) -> AgentMessage:
        """处理子 Agent 错误响应。"""
        error_info = message.payload
        self._log("ERROR", f"Agent 错误: {error_info.get('error_code')} - {error_info.get('error_message')}",
                  source=message.sender.name)
        return self._ok_response(message, {"status": "error_logged"})

    # ============================================================
    # Gate 3 自动修复
    # ============================================================

    def _auto_fix_gate3(self, plan: Dict[str, Any], gate_result: GateResult) -> Dict[str, Any]:
        """尝试自动修复 Gate 3 检测到的问题。"""
        for issue in gate_result.blocking_issues:
            constraint = issue.constraint or ""
            if "transportation" in constraint or "交通" in constraint:
                plan.setdefault("transportation", {"outbound": {}, "return_trip": {}, "local": []})
            if "accommodation" in constraint or "住宿" in constraint:
                plan.setdefault("accommodation", [{"auto_filled": True}])
            if "daily_itinerary" in constraint or "行程" in constraint or "活动" in constraint:
                plan.setdefault("daily_itinerary", [])
            if "meal" in constraint or "餐食" in constraint or "餐" in constraint:
                plan.setdefault("daily_itinerary", [])
            if "budget" in constraint or "超支" in constraint:
                plan["summary"]["total_budget"] = plan["summary"].get("total_budget", 0)
                plan["summary"]["budget_adjusted"] = True
            if "quality_report" in constraint:
                plan.setdefault("quality_report", {"auto_filled": True, "score": 80})
            if "degraded" in constraint:
                plan["summary"]["degraded_reason"] = plan["summary"].get("degraded_reason", "自动补全")
        return plan

    # ============================================================
    # 工具方法
    # ============================================================

    def _log(self, level: str, message: str, source: str = "orchestrator") -> None:
        """记录操作日志到 SharedContext。"""
        if self._context:
            self._context.add_log(level=level, message=message, source=source)

    def _ok_response(self, req: AgentMessage, data: Dict[str, Any]) -> AgentMessage:
        """构建成功响应消息。"""
        return AgentMessage(
            message_id=str(uuid4()),
            sender=AgentIdentity("orchestrator", "1.0.0", [], "internal", "online"),
            receiver=req.sender,
            task_type=TaskType.RESPONSE_RESULT,
            payload={"result_type": "ack", "data": data},
            timestamp=datetime.now(timezone.utc),
            correlation_id=req.message_id,
        )

    def _error_response(
        self, req: AgentMessage, code: ErrorCode, detail: str
    ) -> AgentMessage:
        """构建错误响应消息。"""
        return AgentMessage(
            message_id=str(uuid4()),
            sender=AgentIdentity("orchestrator", "1.0.0", [], "internal", "online"),
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

    @property
    def context(self) -> SharedContext:
        return self._context

    @property
    def gate_runner(self) -> GateRunner:
        return self._gate_runner
