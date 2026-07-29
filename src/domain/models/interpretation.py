"""M2 RequestInterpreter 的结构化解释结果契约。"""

from __future__ import annotations

from decimal import Decimal
from enum import Enum
from typing import Annotated, TypeAlias

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    StrictBool,
    StrictFloat,
    StrictInt,
    StrictStr,
    field_validator,
)

from src.domain.models.enums import ConstraintHardness, InteractionMode

ConfidenceScore: TypeAlias = Annotated[
    Decimal,
    Field(ge=Decimal("0"), le=Decimal("1")),
]
InterpretationValue: TypeAlias = (
    StrictStr
    | StrictInt
    | StrictFloat
    | StrictBool
    | tuple[StrictStr, ...]
)


class SafetyFlag(str, Enum):
    """解释阶段允许输出的安全标记。"""

    PII = "pii"
    PROMPT_INJECTION = "prompt_injection"
    DANGEROUS_ACTION = "dangerous_action"
    UNAUTHORIZED_ACTION = "unauthorized_action"
    INVALID_INPUT = "invalid_input"


class ExtractedEntity(BaseModel):
    """从用户请求中提取的实体候选。"""

    model_config = ConfigDict(extra="forbid", frozen=True, str_strip_whitespace=True)

    entity_type: str = Field(min_length=1, max_length=64)
    value: str = Field(min_length=1, max_length=512)
    normalized_value: str | None = Field(default=None, max_length=512)
    confidence: ConfidenceScore


class ConstraintCandidate(BaseModel):
    """尚未经过 ConstraintService 归一化的约束候选。"""

    model_config = ConfigDict(extra="forbid", frozen=True, str_strip_whitespace=True)

    category: str = Field(min_length=1, max_length=128)
    value: InterpretationValue
    hardness: ConstraintHardness
    scope: str = Field(min_length=1, max_length=128)
    confidence: ConfidenceScore


class InterpretationResult(BaseModel):
    """RequestInterpreter 输出的完整、可校验解释结果。"""

    model_config = ConfigDict(extra="forbid", frozen=True, str_strip_whitespace=True)

    mode_hint: InteractionMode | None
    extracted_entities: tuple[ExtractedEntity, ...]
    constraint_candidates: tuple[ConstraintCandidate, ...]
    explicit_questions: tuple[str, ...]
    references_to_current_plan: tuple[str, ...]
    field_confidence: dict[str, ConfidenceScore]
    overall_confidence: ConfidenceScore
    safety_flags: tuple[SafetyFlag, ...]

    @field_validator(
        "explicit_questions",
        "references_to_current_plan",
        "safety_flags",
    )
    @classmethod
    def validate_unique_textual_items(cls, values: tuple[object, ...]) -> tuple[object, ...]:
        """拒绝重复的澄清问题、计划引用或安全标记。"""
        if len(values) != len(set(values)):
            raise ValueError("interpretation items must be unique")
        return values

    @field_validator("field_confidence")
    @classmethod
    def validate_field_confidence_keys(
        cls,
        values: dict[str, ConfidenceScore],
    ) -> dict[str, ConfidenceScore]:
        """拒绝空字段名，避免产生无法关联的置信度。"""
        if any(not key.strip() for key in values):
            raise ValueError("field confidence keys must not be empty")
        return values
