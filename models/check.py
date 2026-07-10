"""SelfCheck 数据模型。

定义 Planning Agent 输出前自检所需的类型：
- IssueType 枚举（违规类型）
- SelfCheckIssue（单条违规记录）
- SelfCheckResult（自检结果汇总）

v1.2.0 Step 0 — 数据模型先行定义。
来源: progress/handoff.md §12 Phase 0 Step 0
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List


class IssueType(Enum):
    """自检违规类型枚举。

    用于 SelfCheck 规则引擎在 Planning 输出前
    识别具体的约束违反类型。
    """

    BUDGET_OVERSPEND = "budget_overspend"
    """单日总花费超出预算上限（含 10% 浮动）。"""

    GEO_DISTANCE = "geo_distance"
    """同天任意两个景点直线距离超过 30km。"""

    DUPLICATE_ATTRACTION = "duplicate_attraction"
    """同一景点在多个天次重复出现。"""

    DUPLICATE_RESTAURANT = "duplicate_restaurant"
    """同一餐厅在多个天次重复出现。"""

    MISSING_MEAL = "missing_meal"
    """某天缺少推荐的餐食（不足 2 餐）。"""

    MISSING_ACTIVITY = "missing_activity"
    """某天缺少活动（不足 2 个活动）。"""

    STYLE_MISMATCH = "style_mismatch"
    """推荐内容与用户偏好风格不匹配。"""

    EXCLUDED_TYPE = "excluded_type"
    """推荐了用户明确排除的活动类型。"""


@dataclass
class SelfCheckIssue:
    """单条自检违规记录。

    由 SelfChecker 的各个检查方法在发现违规时生成，
    包含违规类型、定位、实际值与期望值的对比。
    """

    type: IssueType
    """违规类型。"""

    location: str = ""
    """违规定位（如 'day_2.dinner', 'day_3.morning'）。"""

    actual_value: Any = None
    """实际检测到的值（如 8000 表示超支金额，'浅草寺' 表示重复景点名）。"""

    expected: str = ""
    """期望的约束描述（如 '≤ 1500 CNY', '≤ 30km', '不重复'）。"""

    severity: str = "blocking"
    """严重程度：'blocking' | 'warning'。"""

    def to_dict(self) -> Dict[str, Any]:
        """将实例序列化为字典。"""
        return {
            "type": self.type.value,
            "location": self.location,
            "actual_value": self.actual_value,
            "expected": self.expected,
            "severity": self.severity,
        }


@dataclass
class SelfCheckResult:
    """自检结果汇总。

    由 SelfChecker.check() 返回，
    包含通过/失败状态和所有违规记录列表。
    """

    passed: bool = True
    """是否全部检查通过（无 blocking 级违规）。"""

    issues: List[SelfCheckIssue] = field(default_factory=list)
    """所有违规记录列表（含 blocking 和 warning 级别）。"""

    @property
    def blocking_issues(self) -> List[SelfCheckIssue]:
        """返回所有 blocking 级别的违规记录。"""
        return [i for i in self.issues if i.severity == "blocking"]

    @property
    def warning_issues(self) -> List[SelfCheckIssue]:
        """返回所有 warning 级别的违规记录。"""
        return [i for i in self.issues if i.severity == "warning"]

    def to_dict(self) -> Dict[str, Any]:
        """将实例序列化为字典。"""
        return {
            "passed": self.passed,
            "issues": [i.to_dict() for i in self.issues],
        }
