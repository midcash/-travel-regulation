"""确定性验证问题契约。"""

from __future__ import annotations

from enum import Enum

from pydantic import BaseModel, ConfigDict, Field, field_validator

from src.domain.models.enums import IssueSeverity
from src.domain.models.value_objects import ConstraintId, EvidenceId, IssueId, StableId


class ValidationGate(str, Enum):
    """验证问题所属的质量门。"""

    G0 = "g0"
    G1 = "g1"
    G2 = "g2"
    G3 = "g3"
    G4 = "g4"
    G5 = "g5"
    G6 = "g6"


class ValidationIssue(BaseModel):
    """可供验证器和 Targeted Repair 消费的结构化问题。"""

    model_config = ConfigDict(extra="forbid", frozen=True, str_strip_whitespace=True)

    issue_id: IssueId
    gate: ValidationGate
    severity: IssueSeverity
    type: str = Field(min_length=1, max_length=128)
    affected_ids: tuple[StableId, ...] = ()
    constraint_refs: tuple[ConstraintId, ...] = ()
    evidence_refs: tuple[EvidenceId, ...] = ()
    message: str = Field(min_length=1, max_length=1024)
    repair_strategy: str = Field(min_length=1, max_length=256)
    retryable: bool = False

    @field_validator("affected_ids", "constraint_refs", "evidence_refs")
    @classmethod
    def validate_unique_refs(cls, values: tuple[StableId, ...]) -> tuple[StableId, ...]:
        """拒绝重复引用，避免下游重复修复或重复计数。"""
        if len(values) != len(set(values)):
            raise ValueError("validation references must be unique")
        return values
