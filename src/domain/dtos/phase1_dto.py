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

from pydantic import BaseModel, Field

from src.domain.dtos.enums import IntentType, TripPurpose, PaceMode


class Phase1RawOutput(BaseModel):
    """Step 1: LLM CoT 解析原始输出。

    由 Phase 1 LLM prompt 直接产出，未经 Negation Guard 处理。
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
    raw_response: str = ""                            # LLM 原始输出（调试用）


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

    # 门禁字段
    confidence: float = Field(default=0, ge=0, le=1)
    missing_dimensions: list[str] = Field(default_factory=list)

    @property
    def needs_clarification(self) -> bool:
        """是否需要进入澄清闭环。

        条件: confidence < 0.8 或 missing_dimensions > 2。
        """
        return self.confidence < 0.8 or len(self.missing_dimensions) > 2
