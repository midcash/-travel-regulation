"""Constraint 与不可变 ConstraintSnapshot 契约。"""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from enum import Enum
from typing import Annotated, Self, TypeAlias

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    StrictBool,
    StrictInt,
    StrictStr,
    field_validator,
    model_validator,
)

from src.domain.models.enums import ConstraintHardness
from src.domain.models.value_objects import (
    ConstraintId,
    DateRange,
    GeoPoint,
    Money,
    RequestId,
    StableId,
)


class ConstraintSource(str, Enum):
    """约束来源。"""

    USER = "user"
    PROFILE = "profile"
    SYSTEM = "system"
    ASSUMPTION = "assumption"


ConstraintValue: TypeAlias = (
    StrictStr
    | StrictBool
    | StrictInt
    | Decimal
    | date
    | tuple[StrictStr, ...]
    | Money
    | DateRange
    | GeoPoint
)


class Constraint(BaseModel):
    """单条类型化旅行约束。"""

    model_config = ConfigDict(extra="forbid", frozen=True, str_strip_whitespace=True)

    id: ConstraintId
    category: str = Field(min_length=1)
    normalized_value: Annotated[
        ConstraintValue,
        Field(description="已归一化的约束值"),
    ]
    hardness: ConstraintHardness
    priority: int = Field(ge=0)
    scope: str = Field(min_length=1)
    source: ConstraintSource
    confidence: Decimal = Field(ge=Decimal("0"), le=Decimal("1"))
    user_confirmed: bool = False
    conflict_group: StableId | None = None

    @field_validator("normalized_value")
    @classmethod
    def validate_normalized_value(cls, value: ConstraintValue) -> ConstraintValue:
        """拒绝空字符串和空集合作为归一化约束值。"""
        if isinstance(value, str) and not value:
            raise ValueError("normalized_value must not be empty")
        if isinstance(value, tuple) and not value:
            raise ValueError("normalized_value must not be empty")
        return value


class ConstraintSnapshot(BaseModel):
    """规划本轮使用的不可变约束快照。"""

    model_config = ConfigDict(extra="forbid", frozen=True)

    version: int = Field(ge=1)
    created_at: datetime
    request_id: RequestId
    constraints: tuple[Constraint, ...] = Field(default_factory=tuple)

    @field_validator("constraints")
    @classmethod
    def validate_unique_ids(cls, values: tuple[Constraint, ...]) -> tuple[Constraint, ...]:
        """拒绝同一快照内重复的约束 ID。"""
        ids = tuple(constraint.id for constraint in values)
        if len(ids) != len(set(ids)):
            raise ValueError("constraint IDs must be unique")
        return values

    @model_validator(mode="after")
    def validate_hard_conflicts(self) -> Self:
        """要求同范围硬约束的冲突必须显式使用同一 conflict_group。"""
        for index, left in enumerate(self.constraints):
            if left.hardness != ConstraintHardness.HARD:
                continue
            for right in self.constraints[index + 1 :]:
                if right.hardness != ConstraintHardness.HARD:
                    continue
                if left.category != right.category or left.scope != right.scope:
                    continue
                if left.normalized_value == right.normalized_value:
                    continue
                if left.conflict_group is None or left.conflict_group != right.conflict_group:
                    raise ValueError(
                        "conflicting hard constraints require one conflict_group"
                    )
        return self

    def by_hardness(self, hardness: ConstraintHardness) -> tuple[Constraint, ...]:
        """按约束硬度返回只读结果。"""
        return tuple(
            constraint for constraint in self.constraints if constraint.hardness == hardness
        )

    @property
    def hard_constraints(self) -> tuple[Constraint, ...]:
        """返回硬约束。"""
        return self.by_hardness(ConstraintHardness.HARD)

    @property
    def soft_constraints(self) -> tuple[Constraint, ...]:
        """返回软约束。"""
        return self.by_hardness(ConstraintHardness.SOFT)

    @property
    def assumptions(self) -> tuple[Constraint, ...]:
        """返回显式假设。"""
        return self.by_hardness(ConstraintHardness.ASSUMPTION)

    @property
    def unknown_constraints(self) -> tuple[Constraint, ...]:
        """返回尚未确定的约束。"""
        return self.by_hardness(ConstraintHardness.UNKNOWN)

    def new_version(
        self,
        constraints: tuple[Constraint, ...],
        created_at: datetime,
    ) -> ConstraintSnapshot:
        """基于当前快照创建递增版本，不修改当前对象。"""
        return ConstraintSnapshot(
            version=self.version + 1,
            created_at=created_at,
            request_id=self.request_id,
            constraints=constraints,
        )
