"""
Phase 1 DTO — 意图解析阶段的输入输出契约。

双保险架构:
  Step 1: LLM CoT 解析 → Phase1RawOutput
  Step 2: Negation Guard (代码正则) → negation_constraints
  Step 3: 合并 → Phase1Output

依赖: enums (IntentType, TripPurpose, PaceMode)
被引用: phase1/prompts.py, application/guards/negation_guard.py, orchestrator.py
"""
from __future__ import annotations

from pydantic import BaseModel, Field, field_validator

from src.domain.dtos.enums import IntentType, TripPurpose, PaceMode


class Phase1RawOutput(BaseModel):
    """Step 1: LLM CoT 解析原始输出。

    由 Phase 1 LLM prompt 直接产出，未经 Negation Guard 处理。
    LLM 可能对数值字段返回 null，field_validator 自动将 None → 默认值。
    """
    intent_type: IntentType = IntentType.TRAVEL
    destination: str | None = None
    origin: str | None = None
    date_range: str = ""                              # 自然语言日期，如 "下周二到周四"
    check_in: str | None = None                       # YYYY-MM-DD（标准化后）
    check_out: str | None = None                      # YYYY-MM-DD（标准化后）
    days: int = 0
    budget: float = 0
    travelers: int = 1
    preferences: list[str] = Field(default_factory=list)
    trip_purpose: TripPurpose = TripPurpose.UNKNOWN
    confidence: float = Field(default=0, ge=0, le=1)
    missing_dimensions: list[str] = Field(default_factory=list)
    free_time_slots: list[str] = Field(default_factory=list)  # 🔀 混合意图中用户可支配时间段
    raw_response: str = ""                            # LLM 原始输出（调试用）

    @field_validator("days", mode="before")
    @classmethod
    def _coerce_days(cls, v: int | None) -> int:
        """LLM 可能返回 null，None → 0。"""
        return 0 if v is None else v

    @field_validator("budget", mode="before")
    @classmethod
    def _coerce_budget(cls, v: float | None) -> float:
        """LLM 可能返回 null，None → 0。"""
        return 0.0 if v is None else v

    @field_validator("travelers", mode="before")
    @classmethod
    def _coerce_travelers(cls, v: int | None) -> int:
        """LLM 可能返回 null，None → 1。"""
        return 1 if v is None else v

    @field_validator("confidence", mode="before")
    @classmethod
    def _coerce_confidence(cls, v: float | None) -> float:
        """LLM 可能返回 null，None → 0。"""
        return 0.0 if v is None else v


class Phase1Output(BaseModel):
    """Phase 1 最终输出（LLM 解析 + Negation Guard 合并）。

    这是传给下游 Phase 2-4 的统一数据契约。
    """
    # 基本信息
    intent_type: IntentType = IntentType.TRAVEL
    destination: str | None = None
    origin: str | None = None
    check_in: str | None = None
    check_out: str | None = None
    days: int = 0
    budget: float = 0
    travelers: int = 1

    # 偏好与约束
    preferences: list[str] = Field(default_factory=list)
    trip_purpose: TripPurpose = TripPurpose.UNKNOWN
    negation_constraints: list[str] = Field(default_factory=list)  # 🛡️ Negation Guard 注入
    pace_mode: PaceMode = PaceMode.NORMAL            # 修正规格: 使用枚举而非裸 str
    free_time_slots: list[str] = Field(default_factory=list)  # 🔀 混合意图中用户可支配时间段

    # 门禁字段
    confidence: float = Field(default=0, ge=0, le=1)
    missing_dimensions: list[str] = Field(default_factory=list)

    @property
    def needs_clarification(self) -> bool:
        """是否需要进入澄清闭环。

        条件: confidence < 0.8 或 missing_dimensions > 2。
        """
        return self.confidence < 0.8 or len(self.missing_dimensions) > 2


def build_intent_summary(phase1_output: dict | None) -> str:
    """从 Phase1Output dict 构建结构化意图摘要文本。

    与 Phase1Output 定义放在同一文件，DTO 字段变更时此函数同步维护。

    Args:
        phase1_output: Phase 1.1 产出的结构化意图数据（model_dump 后的 dict）。
                       为 None 时返回空字符串。

    Returns:
        结构化摘要文本，可直接注入 Planner prompt。空字符串表示无结构化数据可用。
    """
    if not phase1_output:
        return ""

    parts: list[str] = []

    dest = phase1_output.get("destination")
    if dest:
        parts.append(f"目的地: {dest}")

    origin = phase1_output.get("origin")
    if origin:
        parts.append(f"出发地: {origin}")

    days = phase1_output.get("days", 0)
    if days:
        parts.append(f"规划天数: {days}天")

    free_slots = phase1_output.get("free_time_slots", [])
    if free_slots:
        parts.append(f"可用时间段: {'、'.join(free_slots)}")

    budget = phase1_output.get("budget", 0)
    if budget:
        travelers = phase1_output.get("travelers", 1)
        parts.append(f"预算: {budget}元 ({travelers}人)")

    prefs = phase1_output.get("preferences", [])
    if prefs:
        parts.append(f"偏好: {'、'.join(prefs)}")

    trip_purpose = phase1_output.get("trip_purpose")
    if trip_purpose and trip_purpose != "未知":
        parts.append(f"出行目的: {trip_purpose}")

    intent_type = phase1_output.get("intent_type", "travel")
    if intent_type == "mixed":
        parts.append("注意: 用户为混合意图（如出差+个人休闲），仅需规划可用时间段内的活动")

    missing = phase1_output.get("missing_dimensions", [])
    if missing:
        parts.append(f"缺失信息: {'、'.join(missing)}（可合理推断或标注待确认）")

    return "\n".join(parts)
