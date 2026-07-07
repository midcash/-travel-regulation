"""Reasoning 模块数据模型。

包含 Chain-of-Thought 推理管线所需的全部中间产出类型：
- DestinationResearch (CoT Step 1 产出)
- CandidatePool (CoT Step 2 产出)
- CoTResult (推理管线完整产出)
- StepTrace (单步推理追踪)

v1.2.0 Step 0 — 数据模型先行定义。
来源: progress/handoff.md §12 Phase 0 Step 0
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, Dict, List, Optional

if TYPE_CHECKING:
    from models.check import SelfCheckResult
    from models.plan import TravelPlanDraft


@dataclass
class DestinationResearch:
    """CoT Step 1 产出：目的地分析。

    由 CoTPipeline._step_research() 在 LLM 调用后返回，
    包含目的地的货币、语言、时区、最佳季节、热门区域等基础信息。
    """

    currency: str = ""
    """本地货币代码（如 'JPY', 'EUR'）。"""

    language: str = ""
    """主要语言（如 '日语', '法语'）。"""

    timezone: str = ""
    """时区（如 'Asia/Tokyo', 'Europe/Paris'）。"""

    best_season: str = ""
    """最佳旅行季节描述（如 '3-5月, 10-11月'）。"""

    popular_districts: List[str] = field(default_factory=list)
    """热门区域列表（如 ['新宿', '浅草', '涩谷']）。"""

    transport_summary: str = ""
    """交通概况描述（如 '地铁发达，建议购买周游券'）。"""

    seasonal_notes: str = ""
    """季节性备注（如 '6月为梅雨季，需备雨具'）。"""

    price_level: str = "中"
    """物价水平：'高' | '中' | '低'。"""

    def to_dict(self) -> Dict[str, Any]:
        """将实例序列化为字典。"""
        return {
            "currency": self.currency,
            "language": self.language,
            "timezone": self.timezone,
            "best_season": self.best_season,
            "popular_districts": self.popular_districts,
            "transport_summary": self.transport_summary,
            "seasonal_notes": self.seasonal_notes,
            "price_level": self.price_level,
        }


@dataclass
class CandidatePool:
    """CoT Step 2 产出：筛选后的候选池。

    由 CoTPipeline._step_select() 基于目的地分析结果
    筛选出景点、住宿、餐厅候选列表。
    """

    attractions: List[Any] = field(default_factory=list)
    """候选景点列表 (Attraction 实例)。"""

    accommodations: List[Any] = field(default_factory=list)
    """候选住宿列表 (Accommodation 实例)。"""

    restaurants: List[Any] = field(default_factory=list)
    """候选餐厅列表 (Restaurant 实例)。"""

    selection_rationale: str = ""
    """筛选理由说明——为什么选择这些候选项。"""

    excluded: List[str] = field(default_factory=list)
    """被排除的地点名称列表及排除原因。"""

    def to_dict(self) -> Dict[str, Any]:
        """将实例序列化为字典。"""
        return {
            "attractions": [
                a.to_dict() if hasattr(a, "to_dict") else a
                for a in self.attractions
            ],
            "accommodations": [
                a.to_dict() if hasattr(a, "to_dict") else a
                for a in self.accommodations
            ],
            "restaurants": [
                r.to_dict() if hasattr(r, "to_dict") else r
                for r in self.restaurants
            ],
            "selection_rationale": self.selection_rationale,
            "excluded": self.excluded,
        }


@dataclass
class StepTrace:
    """单步推理追踪。

    记录 CoT 推理链中每一步的输入、输出、耗时和 token 消耗，
    用于 TRC (推理可追溯性) 维度的评分。
    """

    step_name: str
    """步骤名称（如 'research', 'select', 'compose', 'selfcheck'）。"""

    input_summary: str = ""
    """该步输入的摘要描述。"""

    output_summary: str = ""
    """该步输出的摘要描述。"""

    duration_ms: int = 0
    """该步执行耗时（毫秒）。"""

    token_count: int = 0
    """该步消耗的 token 数量。"""

    def to_dict(self) -> Dict[str, Any]:
        """将实例序列化为字典。"""
        return {
            "step_name": self.step_name,
            "input_summary": self.input_summary,
            "output_summary": self.output_summary,
            "duration_ms": self.duration_ms,
            "token_count": self.token_count,
        }


@dataclass
class CoTResult:
    """推理管线完整产出。

    由 CoTPipeline.execute() 返回，包含完整的推理中间产出、
    自检结果和性能指标。
    """

    draft: Optional[TravelPlanDraft] = None
    """最终生成的旅行计划草稿。"""

    research: Optional[DestinationResearch] = None
    """CoT Step 1 产出：目的地分析。"""

    candidates: Optional[CandidatePool] = None
    """CoT Step 2 产出：候选池。"""

    selfcheck: Optional[SelfCheckResult] = None
    """CoT Step 4 产出：自检结果。"""

    attempts: int = 1
    """compose → selfcheck 循环次数（正常为 1，自检不通过时为 2-3）。"""

    latency_ms: int = 0
    """总延迟（毫秒）。"""

    token_count: int = 0
    """总 token 消耗。"""

    trace: List[StepTrace] = field(default_factory=list)
    """每步推理追踪记录列表。"""

    degraded: bool = False
    """是否因 LLM 调用失败而降级到 stub。"""

    degraded_reason: str = ""
    """降级原因描述。"""

    def to_dict(self) -> Dict[str, Any]:
        """将实例序列化为字典。"""
        return {
            "draft": self.draft.to_dict() if self.draft else None,
            "research": self.research.to_dict() if self.research else None,
            "candidates": self.candidates.to_dict() if self.candidates else None,
            "selfcheck": self.selfcheck.to_dict() if self.selfcheck else None,
            "attempts": self.attempts,
            "latency_ms": self.latency_ms,
            "token_count": self.token_count,
            "trace": [t.to_dict() for t in self.trace],
            "degraded": self.degraded,
            "degraded_reason": self.degraded_reason,
        }
