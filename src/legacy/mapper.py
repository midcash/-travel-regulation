"""将 legacy 自由文本规划结果映射为严格类型化 DTO。"""

from __future__ import annotations

from collections.abc import Mapping

from pydantic import BaseModel, ConfigDict, Field, StrictInt, StrictStr


class LegacyPlanResult(BaseModel):
    """当前 legacy planner 的类型化结果边界。

    该模型保留旧流程的自由文本语义，但阻止未声明字段和宽松类型进入新代码。
    它不是 M1 的 ``ItineraryPlan``，因为 M1 尚未实现自由文本到结构化行程的解析。
    """

    model_config = ConfigDict(extra="forbid", frozen=True, str_strip_whitespace=True)

    plan: StrictStr = Field(min_length=1)
    rounds: StrictInt = Field(ge=1)
    issues_found: tuple[StrictStr, ...]


class LegacyPlanMapper:
    """legacy planner 结果的显式映射器。"""

    @staticmethod
    def map(raw_result: Mapping[str, object]) -> LegacyPlanResult:
        """校验并映射 legacy 结果。

        Args:
            raw_result: ``engine.loop.plan`` 返回的旧结果映射。

        Returns:
            LegacyPlanResult: 供新边界消费的不可变类型化结果。

        Raises:
            TypeError: 输入不是映射。
            pydantic.ValidationError: 结果缺字段、类型错误或包含未知字段。
        """
        if not isinstance(raw_result, Mapping):
            raise TypeError("legacy plan result must be a mapping")
        return LegacyPlanResult.model_validate(raw_result)


def map_legacy_plan_result(raw_result: Mapping[str, object]) -> LegacyPlanResult:
    """映射 legacy planner 结果的函数式入口。"""
    return LegacyPlanMapper.map(raw_result)
