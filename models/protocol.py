"""Protocol 模块数据模型。

定义消息协议校验和版本协商所需的数据类型：
- SchemaError（单条 schema 校验错误）
- ValidationResult（校验结果汇总）
- CompatibilityResult（版本兼容性检查结果）

v1.2.0 Step 0 — 数据模型先行定义。
来源: progress/handoff.md §12 Phase 0 Step 0
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional


@dataclass
class SchemaError:
    """单条 JSON Schema 校验错误。

    由 MessageValidator 在校验消息时生成，
    精确定位不合规的字段路径并说明期望类型与实际类型的差异。
    """

    field_path: str
    """字段路径（如 'payload.dimensions.completeness'）。"""

    expected: str
    """期望的类型或格式（如 'number'）。"""

    actual: str
    """实际的类型或格式（如 'dict'）。"""

    message: str = ""
    """人类可读的错误描述。"""

    def to_dict(self) -> Dict[str, Any]:
        """将实例序列化为字典。"""
        return {
            "field_path": self.field_path,
            "expected": self.expected,
            "actual": self.actual,
            "message": self.message,
        }


@dataclass
class ValidationResult:
    """消息校验结果汇总。

    由 MessageValidator.validate() 返回，
    包含校验通过/失败状态、所有错误记录和警告信息。
    """

    valid: bool = True
    """是否通过校验。"""

    errors: List[SchemaError] = field(default_factory=list)
    """所有校验错误记录列表。"""

    warnings: List[str] = field(default_factory=list)
    """所有校验警告信息列表。"""

    def to_dict(self) -> Dict[str, Any]:
        """将实例序列化为字典。"""
        return {
            "valid": self.valid,
            "errors": [e.to_dict() for e in self.errors],
            "warnings": self.warnings,
        }

    @property
    def has_blocking_errors(self) -> bool:
        """是否有阻断级错误（即 valid == False）。"""
        return not self.valid


@dataclass
class CompatibilityResult:
    """版本兼容性检查结果。

    由 VersionPolicy 在进行版本协商时返回，
    指示双方的兼容性级别及可用的适配规则。
    """

    compatible: bool = True
    """是否兼容。"""

    level: str = "full"
    """兼容级别：
    - 'full': 完全兼容（同 MAJOR.MINOR）
    - 'adapt': 可适配（同 MAJOR，不同 MINOR——忽略未知字段）
    - 'reject': 不兼容（不同 MAJOR）
    """

    adapt_rules: List[str] = field(default_factory=list)
    """适配规则列表（如 ['ignore unknown fields']）。"""

    negotiated_version: Optional[str] = None
    """协商后的版本号。仅在 level != 'reject' 时有值。"""

    def to_dict(self) -> Dict[str, Any]:
        """将实例序列化为字典。"""
        return {
            "compatible": self.compatible,
            "level": self.level,
            "adapt_rules": self.adapt_rules,
            "negotiated_version": self.negotiated_version,
        }

    @classmethod
    def full(cls, version: str) -> "CompatibilityResult":
        """工厂方法：创建 'full' 兼容性结果。"""
        return cls(
            compatible=True,
            level="full",
            negotiated_version=version,
        )

    @classmethod
    def adapt(cls, version: str) -> "CompatibilityResult":
        """工厂方法：创建 'adapt' 兼容性结果。"""
        return cls(
            compatible=True,
            level="adapt",
            adapt_rules=["ignore unknown fields"],
            negotiated_version=version,
        )

    @classmethod
    def reject(cls) -> "CompatibilityResult":
        """工厂方法：创建 'reject' 兼容性结果。"""
        return cls(
            compatible=False,
            level="reject",
        )
