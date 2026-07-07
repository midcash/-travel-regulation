"""PromptBuilder — 分层 prompt 组装器。

纯文本引擎，不调用任何 API。
将关注点分离为："说什么"（YAML 模板）和"怎么说"（PromptBuilder 组装逻辑）。

设计原则：
- 模板内容（YAML/JSON）与组装逻辑（Python）解耦
- 修改模板文件不需要改 .py 文件
- 不依赖任何外部服务或 LLM API

v1.2.0 R1 — 替代 planning_agent.py 中硬编码的 f-string。
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List, Optional

import yaml

from models.request import Preferences, StructuredRequest

# ---------------------------------------------------------------------------
# 常量
# ---------------------------------------------------------------------------

# 模板文件名
_STABLE_TEMPLATE = "planner_stable.yaml"
_CONTEXT_TEMPLATE = "planner_context.yaml"
_PRICE_KNOWLEDGE = "price_knowledge.json"

# 预算分配默认比例
_DEFAULT_TRANSPORT_RATIO = "35%"
_DEFAULT_ACCOMMODATION_RATIO = "30%"
_DEFAULT_ACTIVITIES_RATIO = "15%"
_DEFAULT_MEALS_RATIO = "15%"
_DEFAULT_BUFFER_RATIO = "5%"

# 住宿预算占日均预算的默认比例
_ACCOMMODATION_DAILY_RATIO = 0.3
# 餐饮预算占日均预算的默认比例
_MEAL_DAILY_RATIO = 0.2

# 有效的 step 值
_VALID_STEPS = frozenset({
    "research", "attractions", "accommodations",
    "restaurants", "itinerary", "budget", "revise",
})

# 餐饮类型标签映射
_MEAL_LABELS: Dict[str, str] = {
    "breakfast": "早餐",
    "lunch": "午餐",
    "dinner": "晚餐",
}

# 住宿类型标签映射
_ACCOMMODATION_LABELS: Dict[str, str] = {
    "budget": "经济型",
    "mid": "中档",
    "luxury": "豪华型",
}

# 交通类型标签映射
_TRANSPORT_LABELS: Dict[str, str] = {
    "local_day_pass": "当地日票",
    "taxi_start": "出租车起步价",
    "shinkansen": "新干线",
    "metro_ticket": "地铁单程票",
    "intercity_bus": "城际巴士",
    "bts": "BTS 轻轨",
}

# 景点类型标签映射
_ATTRACTION_LABELS: Dict[str, str] = {
    "temple_shrine": "寺庙/神社",
    "museum": "博物馆",
    "theme_park": "主题公园",
    "eiffel_tower": "埃菲尔铁塔",
    "palace": "宫殿",
    "temple_park": "寺庙/公园",
    "panda_base": "大熊猫基地",
    "cultural_site": "文化遗址",
    "observation_deck": "观景台",
    "broadway": "百老汇",
    "temple": "寺庙",
    "floating_market": "水上市场",
}


class PromptBuilder:
    """分层 prompt 组装器。纯文本引擎，不调任何 API。

    设计原则：
    - 关注点分离：模板内容（YAML）与组装逻辑（Python）解耦
    - 修改模板文件不需要改 .py 文件
    - 不依赖任何外部服务或 LLM API

    用法::

        builder = PromptBuilder()
        prompt = builder.assemble(request, step="research")
    """

    def __init__(self, templates_dir: str = "") -> None:
        """初始化 PromptBuilder，加载所有模板和物价数据。

        Args:
            templates_dir: 模板目录路径。默认为空字符串，
                此时自动使用当前文件所在目录下的 prompt_templates/。
        """
        if templates_dir:
            self._templates_dir = Path(templates_dir)
        else:
            # 自动推导：当前文件在 core/ 下，模板在 core/prompt_templates/
            self._templates_dir = (
                Path(__file__).resolve().parent / "prompt_templates"
            )

        # 加载 YAML 模板
        self._stable: Dict[str, Any] = {}
        self._contexts: Dict[str, Any] = {}
        self._load_templates()

        # 加载物价数据
        self._price_data: Dict[str, Any] = {}
        self._load_price_knowledge()

    # ------------------------------------------------------------------
    # 公开方法
    # ------------------------------------------------------------------

    def assemble(
        self,
        request: StructuredRequest,
        step: str,
        feedback: Optional[List[Any]] = None,
        iteration: int = 0,
        **context_data: Any,
    ) -> str:
        """组装完整 prompt 字符串。

        Args:
            request: 结构化的用户请求。
            step: LLM 方法名称，必选。有效值:
                'research' | 'attractions' | 'accommodations' |
                'restaurants' | 'itinerary' | 'budget' | 'revise'
            feedback: 修订反馈列表（仅 revise 步骤需要）。
                列表元素应为 RevisionFeedback 实例或兼容对象。
            iteration: 当前修订轮次（0 = 原始生成）。
            **context_data: 步骤特定的额外上下文数据，可覆盖或补充
                自动推导的模板变量。

        Returns:
            完整的 prompt 字符串，可直接发送给 LLM。

        Raises:
            ValueError: 如果 step 不在有效值中。

        Example::

            >>> builder = PromptBuilder()
            >>> prompt = builder.assemble(request, step="research")
            >>> assert len(prompt) > 0
        """
        if step not in _VALID_STEPS:
            raise ValueError(
                f"无效的 step 值: {step!r}，"
                f"有效值: {sorted(_VALID_STEPS)}"
            )

        parts: List[str] = []

        # 1. Stable 部分：角色定义 + 核心规则 + 硬约束 + 推理链 + 自检
        parts.append(self._build_stable())

        # 2. 动态硬约束：从用户偏好中提取的 MUST/MUST_NOT
        dynamic_constraints = self.inject_hard_constraints(request.preferences)
        if dynamic_constraints:
            parts.append(dynamic_constraints)

        # 3. Context 部分：per-step 模板 + 变量填充
        context_vars = self._build_context_vars(request, step, **context_data)
        # revise 步骤：将反馈文本注入上下文变量
        if step == "revise" and feedback:
            context_vars["feedback_items"] = self._format_feedback_items(feedback)
        context_prompt = self._build_context(step, context_vars)
        if context_prompt:
            parts.append(context_prompt)

        # 4. Volatile 部分：修订轮次标记
        if step == "revise" and feedback:
            parts.append(self._build_volatile(feedback, iteration))

        return "\n\n".join(parts)

    def inject_hard_constraints(self, preferences: Preferences) -> str:
        """从用户偏好中提取约束，生成 MUST/MUST_NOT 语句。

        根据用户偏好动态生成约束，纳入 prompt 的硬约束区域。
        硬校验由 Execution Agent 负责。

        Args:
            preferences: 用户偏好对象。

        Returns:
            动态约束语句字符串。如果无特殊约束则返回空字符串。

        Example::

            >>> prefs = Preferences(excluded=["赌博", "夜店"])
            >>> builder.inject_hard_constraints(prefs)
            '## 用户特定约束\\nMUST_NOT: 不得推荐 赌博、夜店 类型的活动或地点。'
        """
        constraints: List[str] = []

        # excluded_types → MUST_NOT
        if preferences.excluded:
            excluded_str = "、".join(preferences.excluded)
            constraints.append(
                f"MUST_NOT: 不得推荐 {excluded_str} 类型的活动或地点。"
            )

        # dietary → MUST
        if preferences.dietary:
            dietary_str = "、".join(preferences.dietary)
            constraints.append(
                f"MUST: 所有餐厅推荐必须满足以下饮食限制：{dietary_str}。"
            )

        # accessibility → MUST（提示性）
        if preferences.accessibility:
            accessibility_str = "、".join(preferences.accessibility)
            constraints.append(
                f"MUST: 行程安排应考虑以下无障碍需求：{accessibility_str}。"
            )

        if not constraints:
            return ""

        return "## 用户特定约束\n" + "\n".join(constraints)

    # ------------------------------------------------------------------
    # 私有方法：模板加载
    # ------------------------------------------------------------------

    def _load_templates(self) -> None:
        """加载 YAML 模板文件。

        Raises:
            FileNotFoundError: 如果任一模板文件不存在。
            yaml.YAMLError: 如果 YAML 格式错误。
        """
        stable_path = self._templates_dir / _STABLE_TEMPLATE
        context_path = self._templates_dir / _CONTEXT_TEMPLATE

        if not stable_path.is_file():
            raise FileNotFoundError(
                f"Stable 模板文件不存在: {stable_path}"
            )
        if not context_path.is_file():
            raise FileNotFoundError(
                f"Context 模板文件不存在: {context_path}"
            )

        with open(stable_path, "r", encoding="utf-8") as f:
            self._stable = yaml.safe_load(f)

        with open(context_path, "r", encoding="utf-8") as f:
            self._contexts = yaml.safe_load(f)

    def _load_price_knowledge(self) -> None:
        """从 JSON 文件加载物价参考数据。

        Raises:
            FileNotFoundError: 如果文件不存在。
            json.JSONDecodeError: 如果 JSON 格式错误。
        """
        price_path = self._templates_dir / _PRICE_KNOWLEDGE

        if not price_path.is_file():
            raise FileNotFoundError(
                f"物价数据文件不存在: {price_path}"
            )

        with open(price_path, "r", encoding="utf-8") as f:
            self._price_data = json.load(f)

    # ------------------------------------------------------------------
    # 私有方法：prompt 子单元构建
    # ------------------------------------------------------------------

    def _build_stable(self) -> str:
        """构建 stable 部分：角色 + 核心规则 + 硬约束 + 推理链 + 自检。

        从 planner_stable.yaml 加载五个 section 并格式化为
        结构化 prompt 段落。

        Returns:
            格式化后的 stable prompt 字符串。
        """
        if not self._stable:
            return ""

        lines: List[str] = []

        # 角色定义
        identity = self._stable.get("identity", "")
        if identity:
            lines.append(identity)

        # 核心规则
        core_rules: list = self._stable.get("core_rules", [])
        if core_rules:
            lines.append("\n## 核心规则")
            for i, rule in enumerate(core_rules, 1):
                lines.append(f"{i}. {rule}")

        # 硬约束
        hard_constraints: list = self._stable.get("hard_constraints", [])
        if hard_constraints:
            lines.append("\n## 硬约束 (Hard Constraints)")
            for constraint in hard_constraints:
                lines.append(f"- {constraint}")

        # 推理链
        cot: dict = self._stable.get("chain_of_thought", {})
        if cot:
            lines.append("\n## 推理链 (Chain of Thought)")
            for key in sorted(cot.keys()):
                lines.append(f"- **{key}**: {cot[key]}")

        # 自检清单
        self_check: list = self._stable.get("self_check", [])
        if self_check:
            lines.append("\n## 自检清单 (Self Check)")
            for i, check in enumerate(self_check, 1):
                lines.append(f"{i}. {check}")

        return "\n".join(lines)

    def _build_context(
        self, step: str, context_vars: Dict[str, Any]
    ) -> str:
        """构建 context 部分：选择模板并填充变量。

        Args:
            step: LLM 方法名称。
            context_vars: 模板变量字典，key 对应模板中的 {placeholder}。

        Returns:
            填充后的 context prompt 字符串。如果模板为空则返回空字符串。

        Raises:
            KeyError: 如果模板中引用的变量不在 context_vars 中。
            ValueError: 如果 step 在 context 模板中没有定义。
        """
        step_config = self._contexts.get(step)
        if not step_config:
            raise ValueError(
                f"Context 模板中未找到 step={step!r} 的定义"
            )

        template: str = step_config.get("template", "")
        if not template:
            return ""

        try:
            return template.format(**context_vars)
        except KeyError as e:
            raise KeyError(
                f"模板 {step!r} 中缺少变量 {e}，"
                f"可用变量: {sorted(context_vars.keys())}"
            ) from e

    def _build_volatile(
        self,
        feedback: List[Any],
        iteration: int,
    ) -> str:
        """构建 volatile 部分：修订轮次标记。

        每轮修订时标注当前轮次，帮助 LLM 理解迭代上下文。
        具体的反馈内容已通过 context 模板的 {feedback_items} 注入。

        Args:
            feedback: 修订反馈列表。
            iteration: 当前修订轮次。

        Returns:
            轮次标记字符串。
        """
        return f"（当前为第 {iteration} 轮修订，请基于原始方案进行修改。）"

    # ------------------------------------------------------------------
    # 私有方法：上下文变量构建
    # ------------------------------------------------------------------

    def _build_context_vars(
        self,
        request: StructuredRequest,
        step: str,
        **context_data: Any,
    ) -> Dict[str, Any]:
        """根据 request 和 step 构建模板变量字典。

        先填充通用变量和步骤特定变量，再用外部 context_data 覆盖。

        Args:
            request: 结构化的用户请求。
            step: LLM 方法名称。
            **context_data: 外部传入的额外上下文数据。

        Returns:
            模板变量字典，key 为占位符名，value 为填充值。
        """
        dest = request.destination
        budget = request.budget
        dates = request.dates

        # 通用变量（所有 step 都可能用到）
        vars_dict: Dict[str, Any] = {
            "destination": dest.city,
            "country": dest.country,
            "currency": budget.currency,
            "total_budget": budget.total,
            "duration_days": dates.duration_days,
        }

        # 步骤特定的变量
        step_builders = {
            "research": self._build_vars_research,
            "attractions": self._build_vars_attractions,
            "accommodations": self._build_vars_accommodations,
            "restaurants": self._build_vars_restaurants,
            "itinerary": self._build_vars_itinerary,
            "budget": self._build_vars_budget,
            "revise": self._build_vars_revise,
        }

        builder = step_builders.get(step)
        if builder:
            vars_dict.update(builder(request))

        # 外部 context_data 可以覆盖或补充任何变量
        vars_dict.update(context_data)

        return vars_dict

    # ------------------------------------------------------------------
    # 各 step 的变量构建辅助方法
    # ------------------------------------------------------------------

    def _build_vars_research(
        self, request: StructuredRequest
    ) -> Dict[str, Any]:
        """构建 research 步骤的模板变量：货币提示 + 物价参考。"""
        vars_dict: Dict[str, Any] = {}
        dest_city = request.destination.city
        price_info = self._lookup_price(dest_city)

        if price_info:
            currency = price_info.get("currency", "")
            rate = price_info.get("exchange_rate_cny", "?")
            vars_dict["currency_hint"] = (
                f"{currency}（汇率: 1 {currency} ≈ {rate} CNY）"
            )
            vars_dict["price_reference"] = (
                self._format_price_reference(price_info)
            )
        else:
            vars_dict["currency_hint"] = (
                f"请根据目的地自行确定货币"
                f"（用户预算使用 {request.budget.currency}）"
            )
            vars_dict["price_reference"] = (
                "（该目的地暂无预置物价数据，请根据你的知识估算当地物价水平）"
            )

        return vars_dict

    def _build_vars_attractions(
        self, request: StructuredRequest
    ) -> Dict[str, Any]:
        """构建 attractions 步骤的模板变量。"""
        prefs = request.preferences
        return {
            "style": (
                "、".join(prefs.style) if prefs.style else "未指定"
            ),
            "excluded": (
                "、".join(prefs.excluded) if prefs.excluded else "无"
            ),
        }

    def _build_vars_accommodations(
        self, request: StructuredRequest
    ) -> Dict[str, Any]:
        """构建 accommodations 步骤的模板变量。"""
        budget = request.budget
        prefs = request.preferences
        days = max(request.dates.duration_days, 1)

        if budget.per_day:
            nightly = budget.per_day * _ACCOMMODATION_DAILY_RATIO
            budget_hint = f"每晚约 {nightly:.0f} {budget.currency}"
        else:
            daily = budget.total / days
            nightly = daily * _ACCOMMODATION_DAILY_RATIO
            budget_hint = (
                f"每晚约 {nightly:.0f} {budget.currency}"
                f"（总预算 {budget.total} {budget.currency}"
                f" / {days} 天）"
            )

        prefs_parts: List[str] = []
        if prefs.style:
            prefs_parts.append(f"风格: {'、'.join(prefs.style)}")
        prefs_parts.append(f"节奏: {prefs.pace}")
        preferences_hint = (
            "；".join(prefs_parts) if prefs_parts else "无特殊偏好"
        )

        return {
            "budget_hint": budget_hint,
            "preferences_hint": preferences_hint,
        }

    def _build_vars_restaurants(
        self, request: StructuredRequest
    ) -> Dict[str, Any]:
        """构建 restaurants 步骤的模板变量。"""
        budget = request.budget
        prefs = request.preferences
        days = max(request.dates.duration_days, 1)

        if budget.per_day:
            per_meal = budget.per_day * _MEAL_DAILY_RATIO
            budget_hint = f"每餐约 {per_meal:.0f} {budget.currency}"
        else:
            daily = budget.total / days
            per_meal = daily * _MEAL_DAILY_RATIO
            budget_hint = (
                f"每餐约 {per_meal:.0f} {budget.currency}"
                f"（总预算 {budget.total} {budget.currency}）"
            )

        cuisine_parts = list(prefs.style) if prefs.style else []
        cuisine_preferences = (
            "、".join(cuisine_parts) if cuisine_parts else "无特殊偏好"
        )

        return {
            "dietary": (
                "、".join(prefs.dietary) if prefs.dietary else "无特殊限制"
            ),
            "budget_hint": budget_hint,
            "cuisine_preferences": cuisine_preferences,
        }

    def _build_vars_itinerary(
        self, request: StructuredRequest
    ) -> Dict[str, Any]:
        """构建 itinerary 步骤的模板变量。

        注意：research_summary、candidates_* 等变量通常需要
        通过 context_data 传入（来自前序 LLM 步骤的产出）。
        此处提供默认占位符。
        """
        return {
            "research_summary": "（将由目的地研究阶段产出，或通过 context_data 传入）",
            "candidates_attractions": "（将由景点搜索阶段产出，或通过 context_data 传入）",
            "candidates_accommodations": "（将由住宿搜索阶段产出，或通过 context_data 传入）",
            "candidates_restaurants": "（将由餐厅搜索阶段产出，或通过 context_data 传入）",
        }

    def _build_vars_budget(
        self, request: StructuredRequest
    ) -> Dict[str, Any]:
        """构建 budget 步骤的模板变量：预算分配比例。"""
        return {
            "transport_ratio": _DEFAULT_TRANSPORT_RATIO,
            "accommodation_ratio": _DEFAULT_ACCOMMODATION_RATIO,
            "activities_ratio": _DEFAULT_ACTIVITIES_RATIO,
            "meals_ratio": _DEFAULT_MEALS_RATIO,
            "buffer_ratio": _DEFAULT_BUFFER_RATIO,
        }

    def _build_vars_revise(
        self, request: StructuredRequest
    ) -> Dict[str, Any]:
        """构建 revise 步骤的模板变量。

        feedback_items 的默认值 —— 实际值由 assemble() 在
        检测到 feedback 参数后注入。
        """
        return {
            "feedback_items": "（修订反馈详情将在下方列出）",
        }

    # ------------------------------------------------------------------
    # 反馈格式化
    # ------------------------------------------------------------------

    def _format_feedback_items(self, feedback: List[Any]) -> str:
        """将反馈列表格式化为 prompt 可用的文本。

        支持 RevisionFeedback（优先使用 format_for_prompt()）
        和裸 dict 两种格式。

        Args:
            feedback: 反馈对象列表。

        Returns:
            格式化后的反馈文本。
        """
        items: List[str] = []

        for i, fb in enumerate(feedback, 1):
            if hasattr(fb, "format_for_prompt"):
                # RevisionFeedback 或兼容对象
                items.append(f"{i}. {fb.format_for_prompt()}")
            elif isinstance(fb, dict):
                # 裸 dict 格式
                items.append(self._format_feedback_dict(i, fb))
            else:
                items.append(f"{i}. {str(fb)}")

        return "\n".join(items)

    @staticmethod
    def _format_feedback_dict(index: int, fb: Dict[str, Any]) -> str:
        """将单条 dict 格式的反馈转为文本。

        Args:
            index: 反馈序号。
            fb: 反馈字典。

        Returns:
            单条反馈的文本表示。
        """
        severity = str(fb.get("priority", fb.get("severity", "unknown")))
        location = str(fb.get("location", ""))
        actual = fb.get("actual_value", "")
        expected = str(fb.get("expected", ""))
        suggestion = str(fb.get("suggestion", ""))

        line = (
            f"{index}. [{severity.upper()}] {location}: "
            f"当前={actual}, 期望={expected}."
        )
        if suggestion:
            line += f" 建议: {suggestion}"
        return line

    # ------------------------------------------------------------------
    # 物价数据辅助方法
    # ------------------------------------------------------------------

    def _lookup_price(self, city_name: str) -> Optional[Dict[str, Any]]:
        """根据城市名称查找物价数据。

        Args:
            city_name: 城市名称（如 '东京', '巴黎'）。

        Returns:
            城市物价数据字典，未找到则返回 None。
        """
        cities = self._price_data.get("cities", {})
        return cities.get(city_name)

    def _format_price_reference(self, price_info: Dict[str, Any]) -> str:
        """将物价数据格式化为 LLM 可读的参考文本。

        输出包含餐饮、住宿、交通、景点/活动四个类别，
        每类细分为具体项目及价格区间。

        Args:
            price_info: 单个城市的物价数据字典。

        Returns:
            格式化后的物价参考文本。
        """
        lines: List[str] = ["### 当地物价参考（均价）"]

        # 餐饮
        meals = price_info.get("meals", {})
        if meals:
            lines.append("\n**餐饮**:")
            for meal_type, price in meals.items():
                label = _MEAL_LABELS.get(meal_type, meal_type)
                lines.append(f"  - {label}: {price}")

        # 住宿
        accommodation = price_info.get("accommodation", {})
        if accommodation:
            lines.append("\n**住宿**:")
            for acc_type, price in accommodation.items():
                label = _ACCOMMODATION_LABELS.get(acc_type, acc_type)
                lines.append(f"  - {label}: {price}")

        # 交通
        transport = price_info.get("transport", {})
        if transport:
            lines.append("\n**交通**:")
            for trans_type, price in transport.items():
                label = _TRANSPORT_LABELS.get(trans_type, trans_type)
                lines.append(f"  - {label}: {price}")

        # 景点
        attractions = price_info.get("attractions", {})
        if attractions:
            lines.append("\n**景点/活动**:")
            for attr_type, price in attractions.items():
                label = _ATTRACTION_LABELS.get(attr_type, attr_type)
                lines.append(f"  - {label}: {price}")

        return "\n".join(lines)


# -----------------------------------------------------------------------
# 模块级便捷函数
# -----------------------------------------------------------------------

def create_default_builder() -> PromptBuilder:
    """创建使用默认模板目录的 PromptBuilder 实例。

    等价于 ``PromptBuilder()``，使用当前文件所在目录下的
    ``prompt_templates/`` 作为模板目录。

    Returns:
        配置完成的 PromptBuilder 实例。
    """
    return PromptBuilder()
