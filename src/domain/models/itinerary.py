"""版本化行程计划契约。"""

from __future__ import annotations

from datetime import date as date_type
from datetime import datetime
from typing import Self

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from src.domain.models.enums import WorkflowStatus
from src.domain.models.validation import ValidationIssue
from src.domain.models.value_objects import (
    CandidateId,
    DateRange,
    EvidenceId,
    Money,
    PlanId,
    PlanItemId,
    StableId,
)


class PlanItem(BaseModel):
    """行程中的单个可追踪项目。"""

    model_config = ConfigDict(extra="forbid", frozen=True, str_strip_whitespace=True)

    plan_item_id: PlanItemId
    candidate_id: CandidateId
    day_number: int = Field(ge=1)
    title: str = Field(min_length=1, max_length=256)
    start_at: datetime | None = None
    end_at: datetime | None = None
    evidence_refs: tuple[EvidenceId, ...] = ()

    @model_validator(mode="after")
    def validate_time_window(self) -> Self:
        """确保行程项目的结束时间不早于开始时间。"""
        if self.start_at is not None and self.end_at is not None and self.end_at < self.start_at:
            raise ValueError("end_at must not be earlier than start_at")
        return self


class ItineraryDay(BaseModel):
    """行程中的一天及其项目引用。"""

    model_config = ConfigDict(extra="forbid", frozen=True, str_strip_whitespace=True)

    day_number: int = Field(ge=1)
    date: date_type | None = None
    item_refs: tuple[PlanItemId, ...] = ()

    @field_validator("item_refs")
    @classmethod
    def validate_item_refs(cls, values: tuple[PlanItemId, ...]) -> tuple[PlanItemId, ...]:
        """拒绝同一天重复引用同一项目。"""
        if len(values) != len(set(values)):
            raise ValueError("item_refs must be unique")
        return values


class PlanAlternative(BaseModel):
    """可供用户比较的替代方案引用。"""

    model_config = ConfigDict(extra="forbid", frozen=True, str_strip_whitespace=True)

    alternative_id: StableId
    item_refs: tuple[PlanItemId, ...] = ()
    rationale: str = Field(min_length=1, max_length=512)


class BudgetLine(BaseModel):
    """计划预算中的一条分类金额。"""

    model_config = ConfigDict(extra="forbid", frozen=True, str_strip_whitespace=True)

    category: str = Field(min_length=1, max_length=64)
    amount: Money


class BudgetBreakdown(BaseModel):
    """计划预算总额及分类明细。"""

    model_config = ConfigDict(extra="forbid", frozen=True, str_strip_whitespace=True)

    total: Money
    lines: tuple[BudgetLine, ...] = ()

    @model_validator(mode="after")
    def validate_currencies(self) -> Self:
        """确保预算总额和明细使用同一币种。"""
        if any(line.amount.currency != self.total.currency for line in self.lines):
            raise ValueError("budget breakdown must use one currency")
        return self


class PlanBuffer(BaseModel):
    """计划中显式记录的时间或预算缓冲。"""

    model_config = ConfigDict(extra="forbid", frozen=True, str_strip_whitespace=True)

    buffer_type: str = Field(min_length=1, max_length=64)
    minutes: int | None = Field(default=None, ge=0)
    amount: Money | None = None

    @model_validator(mode="after")
    def validate_buffer_value(self) -> Self:
        """缓冲必须至少表达一种确定的量。"""
        if self.minutes is None and self.amount is None:
            raise ValueError("buffer requires minutes or amount")
        return self


class ItineraryPlan(BaseModel):
    """可追溯、可验证且可版本化的行程计划。"""

    model_config = ConfigDict(extra="forbid", frozen=True, str_strip_whitespace=True)

    plan_id: PlanId
    version: int = Field(ge=1)
    status: WorkflowStatus
    date_range: DateRange | None = None
    days: tuple[ItineraryDay, ...] = ()
    items: tuple[PlanItem, ...] = ()
    alternatives: tuple[PlanAlternative, ...] = ()
    budget: BudgetBreakdown | None = None
    buffers: tuple[PlanBuffer, ...] = ()
    assumptions: tuple[str, ...] = ()
    warnings: tuple[str, ...] = ()
    evidence_refs: tuple[EvidenceId, ...] = ()
    validation_report: tuple[ValidationIssue, ...] = ()

    @model_validator(mode="after")
    def validate_item_references(self) -> Self:
        """确保天、备选和计划项目之间的引用完整且唯一。"""
        item_ids = tuple(item.plan_item_id for item in self.items)
        if len(item_ids) != len(set(item_ids)):
            raise ValueError("plan item IDs must be unique")
        item_id_set = set(item_ids)
        day_numbers = tuple(day.day_number for day in self.days)
        if len(day_numbers) != len(set(day_numbers)):
            raise ValueError("day numbers must be unique")
        for day in self.days:
            if not set(day.item_refs).issubset(item_id_set):
                raise ValueError("day item_refs must reference plan items")
        for alternative in self.alternatives:
            if not set(alternative.item_refs).issubset(item_id_set):
                raise ValueError("alternative item_refs must reference plan items")
        return self
