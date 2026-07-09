"""MessageValidator — 消息 Schema + 版本兼容性校验器。

发前校验+收后校验双重保障。strict_mode 可配。
使用 jsonschema 库进行 schema 校验，不可用时回退到基本字段存在性检查。

v1.2.0 P1 Step — MessageValidator + 版本化开发。
"""

from __future__ import annotations

import json
import logging
import os
from pathlib import Path
from typing import Any, Dict, List, Optional

from core.message import (
    AgentMessage,
    MessageValidationError,
    TaskType,
    VersionPolicy,
)
from models.protocol import CompatibilityResult, SchemaError, ValidationResult

logger = logging.getLogger(__name__)

# ============================================================
# jsonschema 库导入 — 不可用时回退到基本校验
# ============================================================

try:
    import jsonschema
    from jsonschema import ValidationError as JsonschemaValidationError

    _HAS_JSONSCHEMA = True
except ImportError:  # pragma: no cover — 可选依赖
    _HAS_JSONSCHEMA = False
    JsonschemaValidationError = None  # type: ignore[assignment,misc]


# ============================================================
# 模块级常量
# ============================================================

_SCHEMA_FILE_SUFFIX = ".schema.json"
"""Schema 文件后缀，用于识别和解析。"""


# ============================================================
# MessageValidator
# ============================================================


class MessageValidator:
    """消息 Schema + 版本兼容性校验器。

    发前+收时双重校验。strict_mode 可配。

    使用方式::

        validator = MessageValidator()
        result = validator.validate(message)
        if not result.valid:
            for err in result.errors:
                print(f"  {err.field_path}: {err.message}")
    """

    def __init__(
        self,
        schemas_dir: str = "core/message_schemas",
        strict_mode: bool = True,
    ) -> None:
        """初始化校验器。

        Args:
            schemas_dir: JSON Schema 文件目录路径。
            strict_mode: True → 非法消息抛 MessageValidationError;
                         False → 返回 warnings 放入 ValidationResult。
        """
        self._schemas_dir = schemas_dir
        self._strict_mode = strict_mode
        self._schemas: Dict[TaskType, dict] = {}

        self._load_schemas()

    # ----------------------------------------------------------
    # 公共 API
    # ----------------------------------------------------------

    def validate(self, message: AgentMessage) -> ValidationResult:
        """校验消息的 schema + 版本兼容性。

        校验顺序:
        1. 版本兼容性检查 (委托 VersionPolicy)
        2. JSON Schema 校验 (对照注册的 schema)

        Args:
            message: 待校验的 Agent 消息。

        Returns:
            ValidationResult，包含 valid、errors、warnings。

        Raises:
            MessageValidationError: strict_mode=True 且校验失败时抛出。
        """
        result = ValidationResult()

        # 步骤 1: 版本兼容性检查
        compat = self._check_version_compatibility(message)
        if not compat.compatible:
            error = SchemaError(
                field_path="protocol_version",
                expected=f"MAJOR 兼容 (当前: {VersionPolicy.server_version()})",
                actual=message.protocol_version,
                message=f"协议版本不兼容: {compat.level}",
            )
            result.errors.append(error)
            result.valid = False
        elif compat.level == "adapt":
            result.warnings.append(
                f"协议版本需适配: {compat.level} — {compat.adapt_rules}"
            )
        elif compat.level == "full" and compat.negotiated_version:
            # 完全兼容，可在 warnings 中记录下来（供调试用）
            pass

        # 步骤 2: JSON Schema 校验
        schema_errors = self._validate_schema(message)
        if schema_errors:
            result.errors.extend(schema_errors)
            result.valid = False

        # strict_mode: 非法消息抛异常
        if self._strict_mode and not result.valid:
            error_messages = [e.message for e in result.errors]
            raise MessageValidationError(
                message=f"消息校验失败 ({len(result.errors)} 个错误): {'; '.join(error_messages)}",
                violations=error_messages,
            )

        return result

    # ----------------------------------------------------------
    # ErrorRecovery — 格式错误自动修复 (v1.2.0 P3)
    # ----------------------------------------------------------

    def auto_fix(
        self, message: AgentMessage, validation_result: ValidationResult
    ) -> Optional[AgentMessage]:
        """尝试自动修复消息的格式错误。

        修复边界：仅修复可安全推断的格式问题。内容缺失/类型根本错误不修复。

        可修复:
        - dimensions 嵌套 dict → 扁平（{"completeness": {"score": 5}} → {"completeness": 5}）
        - correlation_id 缺失 → 自动生成 UUID v4 + warning
        - timestamp 超出容差 → 修正为当前 UTC 时间 + warning

        不可修复:
        - payload 为空 → 返回 None
        - 必填字段缺失 → 返回 None

        同时主动检查消息 envelope（correlation_id / timestamp），
        这些不由 JSON Schema 校验覆盖。

        Args:
            message: 原始消息（不会被修改，frozen dataclass）。
            validation_result: MessageValidator.validate() 的校验结果。

        Returns:
            修复后的新 AgentMessage 实例（_auto_fixed 字段记录修复操作）。
            不可修复时返回 None。
        """
        import uuid as uuid_mod
        from datetime import datetime, timedelta, timezone

        from core.message import TIMESTAMP_TOLERANCE

        fixes_applied: List[str] = []
        unfixable_errors: List[SchemaError] = []

        # 当前修复所需的状态
        fixed_payload: Optional[Dict[str, Any]] = None
        fixed_correlation_id: Optional[str] = None
        fixed_timestamp: Optional[datetime] = None

        # 步骤 1: 处理 schema 校验错误
        for error in validation_result.errors:
            field = error.field_path

            # --- dimensions 嵌套 dict → 扁平 ---
            if self._is_dimensions_nesting_error(error):
                if fixed_payload is None:
                    fixed_payload = dict(message.payload)
                self._flatten_dimensions(fixed_payload, error)
                fixes_applied.append(f"dimensions_flattened: {field}")

            # --- 不可修复（payload 为空、必填字段缺失等） ---
            else:
                unfixable_errors.append(error)

        # 步骤 2: 如果有不可修复的 schema 错误 → 放弃修复
        if unfixable_errors:
            logger.info(
                "auto_fix 放弃: %d 个不可修复错误 (如 %s)",
                len(unfixable_errors),
                unfixable_errors[0].field_path,
            )
            return None

        # 步骤 3: 主动检查消息 envelope 级别的可修复问题
        # (这些不会被 JSON Schema 校验覆盖，即使 validation_result 无错误也要检查)

        # correlation_id 缺失检查（仅响应消息）
        if (
            isinstance(message.task_type, TaskType)
            and message.task_type.is_response()
            and not message.correlation_id
        ):
            fixed_correlation_id = str(uuid_mod.uuid4())
            fixes_applied.append("correlation_id_auto_generated")
            logger.warning(
                "auto_fix: message=%s correlation_id 已自动生成 UUID v4",
                message.message_id,
            )

        # timestamp 超出容差检查
        now = datetime.now(timezone.utc)
        ts = message.timestamp
        if ts.tzinfo is None:
            ts = ts.replace(tzinfo=timezone.utc)
        diff = abs(now - ts)
        if diff > TIMESTAMP_TOLERANCE:
            fixed_timestamp = now
            fixes_applied.append("timestamp_corrected_to_utc_now")
            logger.warning(
                "auto_fix: message=%s timestamp 偏差 %.0fs 已修正",
                message.message_id,
                diff.total_seconds(),
            )

        # 没有应用任何修复 → 无需返回新消息
        if not fixes_applied:
            return None

        # 构建修复后的新消息
        new_payload = fixed_payload if fixed_payload is not None else dict(message.payload)
        new_correlation_id = (
            fixed_correlation_id
            if fixed_correlation_id is not None
            else message.correlation_id
        )
        new_timestamp = (
            fixed_timestamp if fixed_timestamp is not None else message.timestamp
        )

        fixed_message = AgentMessage(
            message_id=message.message_id,
            sender=message.sender,
            receiver=message.receiver,
            task_type=message.task_type,
            payload=new_payload,
            timestamp=new_timestamp,
            protocol_version=message.protocol_version,
            correlation_id=new_correlation_id,
            _auto_fixed=fixes_applied,
        )

        # 二次校验：修复后的消息必须通过 MessageValidator
        re_validation = self.validate(fixed_message)
        if not re_validation.valid:
            logger.warning(
                "auto_fix 修复后消息仍未通过二次校验: %s",
                [e.message for e in re_validation.errors],
            )
            return None

        logger.info(
            "auto_fix 成功修复 %d 项: %s",
            len(fixes_applied),
            fixes_applied,
        )
        return fixed_message

    # ----------------------------------------------------------
    # auto_fix 辅助方法
    # ----------------------------------------------------------

    @staticmethod
    def _is_dimensions_nesting_error(error: SchemaError) -> bool:
        """判断 SchemaError 是否为 dimensions 嵌套 dict 问题。

        特征: field_path 包含 'dimensions'，actual 为 'object' 类型描述，
        expected 为 'number' 或 'integer'。
        """
        return (
            "dimensions" in error.field_path
            and ("object" in error.actual.lower() or "keys" in error.actual.lower())
            and ("number" in error.expected.lower() or "integer" in error.expected.lower())
        )

    @staticmethod
    def _flatten_dimensions(payload: Dict[str, Any], error: SchemaError) -> None:
        """将 payload 中嵌套的 dimensions dict 扁平化。

        例如: {"completeness": {"score": 5.0, "weight": 0.25}}
           →  {"completeness": 5.0}

        Args:
            payload: 待修改的 payload 字典（原地修改）。
            error: 关联的 SchemaError（用于定位字段路径）。
        """
        field_path = error.field_path
        # field_path 格式: 'payload.dimensions.completeness'
        # 我们需要定位到 'dimensions' → 然后在 dimensions 下扁平化
        parts = field_path.split(".")

        # 找到 dimensions 在 payload 中的位置
        current: Any = payload
        for i, part in enumerate(parts):
            if part == "payload":
                continue
            if part == "dimensions":
                # current 应该是包含 dimensions 的 dict
                if isinstance(current, dict) and "dimensions" in current:
                    dims = current["dimensions"]
                    if isinstance(dims, dict):
                        for key, value in dims.items():
                            if isinstance(value, dict) and "score" in value:
                                dims[key] = value["score"]
                return
            if isinstance(current, dict):
                current = current.get(part)
                if current is None:
                    return
            else:
                return

    def register_schema(self, task_type: TaskType, schema: dict) -> None:
        """注册消息类型对应的 JSON Schema。

        Args:
            task_type: TaskType 枚举值。
            schema: JSON Schema dict (draft-07 格式)。
        """
        if not isinstance(task_type, TaskType):
            raise TypeError(
                f"task_type 必须是 TaskType 枚举值, 实际: {type(task_type).__name__}"
            )
        if not isinstance(schema, dict):
            raise TypeError(f"schema 必须是 dict, 实际: {type(schema).__name__}")

        self._schemas[task_type] = schema
        logger.debug("已注册 schema: %s", task_type.value)

    # ----------------------------------------------------------
    # 内部方法
    # ----------------------------------------------------------

    def _validate_schema(self, message: AgentMessage) -> List[SchemaError]:
        """对照注册的 JSON Schema 校验 payload。

        Args:
            message: 待校验的消息。

        Returns:
            SchemaError 列表。无错误时返回空列表。
        """
        task_type = message.task_type
        schema = self._schemas.get(task_type)

        if schema is None:
            # 未注册 schema 的消息类型 — 跳过 schema 校验，仅记录
            logger.debug("消息类型 %s 无已注册 schema，跳过 payload 校验", task_type.value)
            return []

        if _HAS_JSONSCHEMA:
            return self._validate_with_jsonschema(message.payload, schema, task_type)
        else:
            return self._validate_basic(message.payload, schema, task_type)

    def _validate_with_jsonschema(
        self,
        payload: Dict[str, Any],
        schema: dict,
        task_type: TaskType,
    ) -> List[SchemaError]:
        """使用 jsonschema 库进行完整校验。"""
        errors: List[SchemaError] = []
        validator_cls = jsonschema.validators.validator_for(schema)
        # 确保使用 draft-07 格式检查
        validator = validator_cls(schema, format_checker=jsonschema.FormatChecker())

        for e in validator.iter_errors(payload):
            field_path = _format_jsonschema_path(e)
            errors.append(
                SchemaError(
                    field_path=f"payload.{field_path}" if field_path else "payload",
                    expected=_describe_expected(e),
                    actual=_describe_actual(e.instance),
                    message=e.message,
                )
            )

        return errors

    def _validate_basic(
        self,
        payload: Dict[str, Any],
        schema: dict,
        task_type: TaskType,
    ) -> List[SchemaError]:
        """回退校验 — jsonschema 不可用时使用基本字段存在性检查。

        仅检查 required 字段存在性和基本类型匹配。
        不够精确但足以拦截最常见的格式错误。
        """
        errors: List[SchemaError] = []

        if not isinstance(payload, dict):
            errors.append(
                SchemaError(
                    field_path="payload",
                    expected="object",
                    actual=type(payload).__name__,
                    message="payload 必须是 dict / object 类型",
                )
            )
            return errors

        required: List[str] = schema.get("required", [])
        properties: Dict[str, Any] = schema.get("properties", {})

        # 1. 检查必填字段是否存在
        for field in required:
            if field not in payload:
                errors.append(
                    SchemaError(
                        field_path=f"payload.{field}",
                        expected="存在且非空",
                        actual="缺失",
                        message=f"缺少必填字段 '{field}'",
                    )
                )

        # 2. 对存在的字段做基本类型检查
        for field, value in payload.items():
            prop_schema = properties.get(field)
            if prop_schema is None:
                continue

            expected_type = prop_schema.get("type")
            if expected_type is None:
                continue

            type_ok = _check_basic_type(value, expected_type)
            if not type_ok:
                errors.append(
                    SchemaError(
                        field_path=f"payload.{field}",
                        expected=expected_type,
                        actual=type(value).__name__,
                        message=(
                            f"字段 '{field}' 类型不匹配: "
                            f"期望 {expected_type}, 实际 {type(value).__name__}"
                        ),
                    )
                )

            # 3. 若字段值本身是 object 且有 required 子字段，递归检查
            if isinstance(value, dict) and prop_schema.get("type") == "object":
                nested_required = prop_schema.get("required", [])
                for nested_field in nested_required:
                    if nested_field not in value:
                        errors.append(
                            SchemaError(
                                field_path=f"payload.{field}.{nested_field}",
                                expected="存在且非空",
                                actual="缺失",
                                message=(
                                    f"缺少必填字段 '{field}.{nested_field}'"
                                ),
                            )
                        )

        return errors

    def _check_version_compatibility(
        self, message: AgentMessage
    ) -> CompatibilityResult:
        """检查消息 protocol_version 与当前服务端的兼容性。

        委托给 VersionPolicy.check() 执行实际的版本比较逻辑。

        Args:
            message: 待检查的消息。

        Returns:
            CompatibilityResult，指示兼容性级别。
        """
        return VersionPolicy.check(message.protocol_version)

    # ----------------------------------------------------------
    # Schema 自动加载
    # ----------------------------------------------------------

    def _load_schemas(self) -> None:
        """自动加载 schemas_dir 下所有 .schema.json 文件并注册。

        文件名格式: task.create_itinerary.schema.json
        → 解析出 task_type 字符串 → 匹配 TaskType 枚举 → 注册。
        """
        schemas_path = Path(self._schemas_dir)

        if not schemas_path.is_dir():
            logger.warning(
                "Schema 目录不存在: %s — 跳过自动加载，请手动调用 register_schema()",
                self._schemas_dir,
            )
            return

        loaded_count = 0
        for file_path in schemas_path.glob(f"*{_SCHEMA_FILE_SUFFIX}"):
            try:
                task_type = self._parse_task_type_from_filename(file_path.name)
                if task_type is None:
                    logger.debug("无法从文件名解析 TaskType: %s", file_path.name)
                    continue

                schema_content = file_path.read_text(encoding="utf-8")
                schema = json.loads(schema_content)
                self._schemas[task_type] = schema
                loaded_count += 1
            except json.JSONDecodeError as e:
                logger.warning("Schema 文件 JSON 解析失败: %s — %s", file_path, e)
            except Exception as e:
                logger.warning("加载 schema 文件失败: %s — %s", file_path, e)

        logger.info(
            "已从 %s 加载 %d 个 schema (%d 个 .schema.json 文件)",
            self._schemas_dir,
            loaded_count,
            sum(1 for _ in schemas_path.glob(f"*{_SCHEMA_FILE_SUFFIX}")),
        )

    @staticmethod
    def _parse_task_type_from_filename(filename: str) -> Optional[TaskType]:
        """从 schema 文件名解析 TaskType。

        Examples:
            'task.create_itinerary.schema.json' → TaskType.TASK_CREATE_ITINERARY
            'response.error.schema.json' → TaskType.RESPONSE_ERROR
        """
        if not filename.endswith(_SCHEMA_FILE_SUFFIX):
            return None

        # 去掉后缀得到 task_type 字符串值
        type_value = filename[: -len(_SCHEMA_FILE_SUFFIX)]

        # 在 TaskType 枚举中查找匹配值
        for task_type in TaskType:
            if task_type.value == type_value:
                return task_type

        return None


# ============================================================
# 辅助函数
# ============================================================


def _format_jsonschema_path(error: Any) -> str:
    """将 jsonschema 的绝对路径 deque 格式化为点分隔的字段路径。"""
    path_parts: List[str] = []
    for part in error.absolute_path:
        if isinstance(part, int):
            path_parts.append(f"[{part}]")
        else:
            if path_parts:
                path_parts.append(".")
            path_parts.append(str(part))
    return "".join(path_parts)


def _describe_expected(error: Any) -> str:
    """从 jsonschema 错误中提取期望类型的描述。"""
    validator_name = error.validator
    validator_value = error.validator_value

    if validator_name == "type":
        expected_type = validator_value
        if isinstance(expected_type, list):
            return " | ".join(expected_type)
        return str(expected_type)
    elif validator_name == "required":
        return f"必填字段: {', '.join(validator_value)}"
    elif validator_name == "enum":
        return f"枚举值之一: {validator_value}"
    elif validator_name == "minimum":
        return f">= {validator_value}"
    elif validator_name == "maximum":
        return f"<= {validator_value}"
    elif validator_name == "minItems":
        return f"数组长度 >= {validator_value}"
    else:
        return validator_name


def _describe_actual(instance: Any) -> str:
    """描述实际值的类型或内容。"""
    if instance is None:
        return "null"
    if isinstance(instance, bool):
        return "boolean"
    if isinstance(instance, int):
        return "integer"
    if isinstance(instance, float):
        return "number"
    if isinstance(instance, str):
        short = instance[:50] + "..." if len(instance) > 50 else instance
        return f"string: {short!r}"
    if isinstance(instance, list):
        return f"array (len={len(instance)})"
    if isinstance(instance, dict):
        return f"object (keys={sorted(instance.keys())})"
    return type(instance).__name__


def _check_basic_type(value: Any, expected_type: str) -> bool:
    """基本类型检查（jsonschema 回退方案）。

    仅支持 JSON 基本类型: string, number, integer, boolean, array, object。
    """
    type_map = {
        "string": str,
        "number": (int, float),
        "integer": int,
        "boolean": bool,
        "array": list,
        "object": dict,
    }
    expected_python_type = type_map.get(expected_type)
    if expected_python_type is None:
        return True  # 未知类型，跳过检查
    return isinstance(value, expected_python_type)
