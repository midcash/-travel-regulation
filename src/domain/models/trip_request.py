"""TripRequest 及其请求级值对象。"""

from __future__ import annotations

from enum import Enum
from typing import Self

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from src.domain.models.enums import InteractionMode
from src.domain.models.value_objects import (
    DateRange,
    Money,
    RequestId,
    SessionId,
    StableId,
    TripId,
)


class BudgetSemantics(str, Enum):
    """预算金额的解释方式。"""

    MAXIMUM = "maximum"
    RANGE = "range"
    TARGET = "target"


class BudgetSpec(BaseModel):
    """带金额语义的预算约束。"""

    model_config = ConfigDict(extra="forbid", frozen=True)

    semantics: BudgetSemantics
    minimum: Money | None = None
    maximum: Money | None = None
    target: Money | None = None

    @model_validator(mode="after")
    def validate_shape(self) -> Self:
        """校验预算语义与金额字段一一对应。"""
        if self.semantics == BudgetSemantics.MAXIMUM:
            if self.maximum is None or self.minimum is not None or self.target is not None:
                raise ValueError("maximum budget requires only maximum")
        elif self.semantics == BudgetSemantics.RANGE:
            if self.minimum is None or self.maximum is None or self.target is not None:
                raise ValueError("range budget requires minimum and maximum")
            if self.minimum.currency != self.maximum.currency:
                raise ValueError("budget range must use one currency")
            if self.minimum.amount > self.maximum.amount:
                raise ValueError("budget minimum must not exceed maximum")
        elif self.semantics == BudgetSemantics.TARGET:
            if self.target is None or self.minimum is not None or self.maximum is not None:
                raise ValueError("target budget requires only target")
        else:
            raise ValueError("unsupported budget semantics")

        amounts = tuple(
            money
            for money in (self.minimum, self.maximum, self.target)
            if money is not None
        )
        if amounts and len({money.currency for money in amounts}) != 1:
            raise ValueError("budget amounts must use one currency")
        if any(money.amount <= 0 for money in amounts):
            raise ValueError("budget amounts must be positive")
        return self


class TravelerProfile(BaseModel):
    """影响规划的同行人群数量和无障碍需求。"""

    model_config = ConfigDict(extra="forbid", frozen=True)

    adults: int = Field(ge=1)
    children: int = Field(default=0, ge=0)
    seniors: int = Field(default=0, ge=0)
    accessibility_needs: tuple[str, ...] = Field(default_factory=tuple)

    @field_validator("accessibility_needs")
    @classmethod
    def validate_accessibility_needs(cls, values: tuple[str, ...]) -> tuple[str, ...]:
        """拒绝空的无障碍需求标签。"""
        if any(not value for value in values):
            raise ValueError("accessibility needs must not be empty")
        return values

    @property
    def total_count(self) -> int:
        """返回同行总人数。"""
        return self.adults + self.children + self.seniors


class TripRequest(BaseModel):
    """旅行规划请求的结构化入口契约。"""

    model_config = ConfigDict(extra="forbid", frozen=True, str_strip_whitespace=True)

    request_id: RequestId
    trip_id: TripId
    session_id: SessionId
    origin: str = Field(min_length=1)
    destinations: tuple[str, ...] = Field(min_length=1)
    date_range: DateRange | None = None
    duration_days: int | None = Field(default=None, gt=0)
    travelers: TravelerProfile
    budget: BudgetSpec | None = None
    preferences: tuple[str, ...] = Field(default_factory=tuple)
    explicit_exclusions: tuple[str, ...] = Field(default_factory=tuple)
    locale: str = Field(default="zh-CN", min_length=2)
    timezone: str = Field(default="Asia/Shanghai", min_length=1)
    requested_mode: InteractionMode = InteractionMode.PLAN
    raw_input_ref: StableId | None = None
    schema_version: str = Field(default="1.0", min_length=1)

    @field_validator("origin")
    @classmethod
    def validate_origin(cls, value: str) -> str:
        """拒绝空的出发地。"""
        if not value:
            raise ValueError("origin must not be empty")
        return value

    @field_validator("destinations", "preferences", "explicit_exclusions")
    @classmethod
    def validate_text_items(cls, values: tuple[str, ...]) -> tuple[str, ...]:
        """拒绝空的目的地、偏好或排除项。"""
        if any(not value for value in values):
            raise ValueError("text items must not be empty")
        return values

    @model_validator(mode="after")
    def validate_date_specification(self) -> Self:
        """校验日期范围和明确天数至少提供一个且彼此一致。"""
        if self.date_range is None and self.duration_days is None:
            raise ValueError("date_range or duration_days is required")
        if (
            self.date_range is not None
            and self.duration_days is not None
            and self.date_range.days != self.duration_days
        ):
            raise ValueError("date_range and duration_days must agree")
        return self
