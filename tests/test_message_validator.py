"""MessageValidator.auto_fix() 单元测试 — v1.2.0 P3 ErrorRecovery.

覆盖:
1. dimensions 嵌套 dict → 扁平化自动修复
2. correlation_id 缺失 → UUID 自动生成
3. timestamp 超出容差 → 修正
4. payload 为空 / 必填字段缺失 → 不修复返回 None
5. 修复后消息通过二次校验
"""

import uuid as uuid_mod
from datetime import datetime, timedelta, timezone

import pytest

from core.message import (
    TIMESTAMP_TOLERANCE,
    AgentIdentity,
    AgentMessage,
    TaskType,
)
from core.message_validator import MessageValidator
from models.protocol import SchemaError, ValidationResult


# ============================================================
# Fixtures
# ============================================================


@pytest.fixture
def identity():
    return AgentIdentity("test", "1.0.0", ["test"], "localhost", "online")


@pytest.fixture
def identity2():
    return AgentIdentity("orchestrator", "1.0.0", ["orchestrate"], "orch://local", "online")


@pytest.fixture
def validator():
    """非 strict 模式 validator。"""
    v = MessageValidator(strict_mode=False)
    # 注册一个宽松的 RESPONSE_RESULT schema 覆盖 auto-loaded 的严格 schema
    # 否则 re-validation 会因为 status/data 缺失而失败
    v.register_schema(TaskType.RESPONSE_RESULT, {
        "type": "object",
        "properties": {
            "dimensions": {"type": "object"},
            "result": {"type": "string"},
            "data": {"type": "object"},
            "status": {"type": "string"},
        },
    })
    v.register_schema(TaskType.TASK_CREATE_ITINERARY, {
        "type": "object",
        "properties": {
            "destination": {"type": "object"},
            "duration_days": {"type": "integer"},
            "total_budget": {"type": "number"},
            "data": {"type": "string"},
        },
    })
    return v


# ============================================================
# Helper
# ============================================================


def _make_msg(
    identity,
    identity2,
    *,
    task_type=TaskType.RESPONSE_RESULT,
    payload=None,
    correlation_id=None,
    timestamp=None,
):
    """快捷构造 AgentMessage。"""
    if payload is None:
        payload = {}
    if timestamp is None:
        timestamp = datetime.now(timezone.utc)
    return AgentMessage(
        message_id=str(uuid_mod.uuid4()),
        sender=identity,
        receiver=identity2,
        task_type=task_type,
        payload=payload,
        timestamp=timestamp,
        correlation_id=correlation_id,
    )


# ============================================================
# Scenario 1: dimensions 嵌套 dict → 扁平 (核心修复)
# ============================================================


class TestAutoFixDimensionsFlatten:
    """dimensions 嵌套 dict 自动扁平化。"""

    def test_flattens_nested_dimensions_in_payload(self, identity, identity2, validator):
        """dimensions 为嵌套 dict → 自动提取 score 为扁平值 + re-validation 通过。"""
        msg = _make_msg(
            identity, identity2,
            payload={
                "dimensions": {
                    "completeness": {"score": 5.0, "weight": 0.25},
                    "feasibility": {"score": 3.0, "weight": 0.25},
                }
            },
            correlation_id=str(uuid_mod.uuid4()),
        )

        # 构造 SchemaError 模拟 dimensions 嵌套问题
        result = ValidationResult(
            valid=False,
            errors=[
                SchemaError(
                    field_path="payload.dimensions.completeness",
                    expected="number",
                    actual="object (keys=['score', 'weight'])",
                    message="completeness should be number, got object",
                ),
                SchemaError(
                    field_path="payload.dimensions.feasibility",
                    expected="number",
                    actual="object (keys=['score', 'weight'])",
                    message="feasibility should be number, got object",
                ),
            ],
        )

        # auto_fix
        fixed = validator.auto_fix(msg, result)
        assert fixed is not None, "auto_fix should return fixed message"
        assert fixed._auto_fixed is not None
        assert any("dimensions_flattened" in f for f in fixed._auto_fixed)

        # 验证修复：dimensions 值变为扁平 number
        dims = fixed.payload.get("dimensions", {})
        assert dims.get("completeness") == 5.0
        assert dims.get("feasibility") == 3.0
        assert isinstance(dims["completeness"], float)

        # 二次校验通过
        re_result = validator.validate(fixed)
        assert re_result.valid, (
            f"Fixed message should pass re-validation: "
            f"{[e.message for e in re_result.errors]}"
        )

    def test_dimensions_only_flattens_nested_dicts(self, identity, identity2, validator):
        """已扁平的 dimensions 不做额外处理。"""
        msg = _make_msg(
            identity, identity2,
            payload={"dimensions": {"completeness": 5.0, "feasibility": 3.0}},
            correlation_id=str(uuid_mod.uuid4()),
        )

        result = ValidationResult(valid=True, errors=[], warnings=[])
        fixed = validator.auto_fix(msg, result)
        assert fixed is None, "No issues → should return None"


# ============================================================
# Scenario 2: payload 为空 / 必填字段缺失 → 不修复
# ============================================================


class TestAutoFixUnfixable:
    """不可修复场景：payload 为空、必填字段缺失。"""

    def test_empty_payload_returns_none(self, identity, identity2, validator):
        """payload 为空 → auto_fix 返回 None（不可修复）。"""
        msg = _make_msg(identity, identity2, payload={})

        result = ValidationResult(
            valid=False,
            errors=[
                SchemaError(
                    field_path="payload",
                    expected="object with required fields",
                    actual="empty object",
                    message="payload is empty",
                ),
            ],
        )

        fixed = validator.auto_fix(msg, result)
        assert fixed is None, "Empty payload should NOT be auto-fixable"

    def test_missing_required_field_returns_none(self, identity, identity2, validator):
        """必填字段缺失 → auto_fix 返回 None。"""
        msg = _make_msg(identity, identity2, payload={"destination": {"city": "Tokyo"}})

        result = ValidationResult(
            valid=False,
            errors=[
                SchemaError(
                    field_path="payload.duration_days",
                    expected="存在且非空",
                    actual="缺失",
                    message="缺少必填字段 'duration_days'",
                ),
            ],
        )

        fixed = validator.auto_fix(msg, result)
        assert fixed is None, "Missing required fields should NOT be auto-fixable"


# ============================================================
# Scenario 3: correlation_id 缺失 → 自动生成 UUID
# ============================================================


class TestAutoFixCorrelationId:
    """correlation_id 缺失 → 自动生成。"""

    def test_generates_uuid_for_missing_correlation_id(self, identity, identity2, validator):
        """响应消息缺 correlation_id → 自动生成 UUID v4 + _auto_fixed 标记。"""
        msg = _make_msg(
            identity, identity2,
            task_type=TaskType.RESPONSE_RESULT,
            payload={"result": "ok"},
            # correlation_id 缺失
        )

        # 无 schema 错误，仅 envelope 问题
        result = ValidationResult(valid=True, errors=[], warnings=[])

        fixed = validator.auto_fix(msg, result)
        assert fixed is not None, "auto_fix should fix missing correlation_id"
        assert fixed._auto_fixed is not None
        assert "correlation_id_auto_generated" in fixed._auto_fixed
        assert fixed.correlation_id is not None
        assert uuid_mod.UUID(fixed.correlation_id).version == 4

        # 二次校验通过
        re_result = validator.validate(fixed)
        assert re_result.valid, (
            f"Fixed message should pass re-validation: "
            f"{[e.message for e in re_result.errors]}"
        )

    def test_no_fix_for_request_without_correlation_id(self, identity, identity2, validator):
        """请求消息（非 response）缺 correlation_id → 不修复，返回 None。"""
        msg = _make_msg(
            identity, identity2,
            task_type=TaskType.TASK_CREATE_ITINERARY,
            payload={"destination": {"city": "Tokyo"}},
        )

        result = ValidationResult(valid=True, errors=[], warnings=[])
        fixed = validator.auto_fix(msg, result)
        assert fixed is None, "Request without correlation_id is valid, no fix needed"


# ============================================================
# Scenario 4: timestamp 超出容差 → 修正
# ============================================================


class TestAutoFixTimestamp:
    """timestamp 超出容差 → 自动修正为当前 UTC 时间。"""

    def test_corrects_old_timestamp(self, identity, identity2, validator):
        """旧 timestamp → auto_fix 修正为当前时间 + _auto_fixed 标记。"""
        old_time = datetime.now(timezone.utc) - timedelta(minutes=10)
        msg = _make_msg(identity, identity2, timestamp=old_time)

        result = ValidationResult(valid=True, errors=[], warnings=[])

        fixed = validator.auto_fix(msg, result)
        assert fixed is not None, "auto_fix should fix out-of-tolerance timestamp"
        assert fixed._auto_fixed is not None
        assert "timestamp_corrected_to_utc_now" in fixed._auto_fixed

        # 修复后 timestamp 应在容差内
        diff = abs(datetime.now(timezone.utc) - fixed.timestamp)
        assert diff < TIMESTAMP_TOLERANCE

        # 二次校验通过
        re_result = validator.validate(fixed)
        assert re_result.valid

    def test_corrects_future_timestamp(self, identity, identity2, validator):
        """未来 timestamp → auto_fix 修正为当前时间。"""
        future_time = datetime.now(timezone.utc) + timedelta(minutes=10)
        msg = _make_msg(identity, identity2, timestamp=future_time)

        result = ValidationResult(valid=True, errors=[], warnings=[])
        fixed = validator.auto_fix(msg, result)
        assert fixed is not None
        assert "timestamp_corrected_to_utc_now" in fixed._auto_fixed

    def test_no_fix_for_timestamp_within_tolerance(self, identity, identity2, validator):
        """容差内的 timestamp + 合法请求消息 → 不修复。"""
        within = datetime.now(timezone.utc) - timedelta(minutes=3)
        msg = _make_msg(
            identity, identity2,
            task_type=TaskType.TASK_CREATE_ITINERARY,
            payload={"destination": {"city": "Tokyo"}},
            timestamp=within,
        )

        result = ValidationResult(valid=True, errors=[], warnings=[])
        fixed = validator.auto_fix(msg, result)
        assert fixed is None, "Timestamp within tolerance → no fix needed"


# ============================================================
# Scenario 5: 无错误无问题 → 跳过修复
# ============================================================


class TestAutoFixNoOp:
    """无需修复时正确返回 None。"""

    def test_no_issues_returns_none(self, identity, identity2, validator):
        """全合法消息 → auto_fix 返回 None。"""
        msg = _make_msg(
            identity, identity2,
            task_type=TaskType.TASK_CREATE_ITINERARY,
            payload={"destination": {"city": "Tokyo"}},
            timestamp=datetime.now(timezone.utc),
        )

        result = ValidationResult(valid=True, errors=[], warnings=[])
        fixed = validator.auto_fix(msg, result)
        assert fixed is None, "No issues → should return None"


# ============================================================
# Scenario 6: 多项修复同时生效
# ============================================================


class TestAutoFixMultiple:
    """多修复项同时应用：dimensions + correlation_id + timestamp。"""

    def test_all_three_fixes_applied(self, identity, identity2, validator):
        """同时修复 dimensions 嵌套 + correlation_id 缺失 + timestamp 偏差。"""
        old_time = datetime.now(timezone.utc) - timedelta(minutes=10)
        msg = _make_msg(
            identity, identity2,
            task_type=TaskType.RESPONSE_RESULT,
            payload={
                "dimensions": {
                    "completeness": {"score": 5.0, "weight": 0.25},
                }
            },
            timestamp=old_time,
            # correlation_id 缺失
        )

        result = ValidationResult(
            valid=False,
            errors=[
                SchemaError(
                    field_path="payload.dimensions.completeness",
                    expected="number",
                    actual="object (keys=['score', 'weight'])",
                    message="completeness should be number",
                ),
            ],
        )

        fixed = validator.auto_fix(msg, result)
        assert fixed is not None
        assert fixed._auto_fixed is not None

        fixes = fixed._auto_fixed
        assert any("dimensions_flattened" in f for f in fixes), f"fixes={fixes}"
        assert "correlation_id_auto_generated" in fixes
        assert "timestamp_corrected_to_utc_now" in fixes
        assert len(fixes) == 3

        # 所有修复均已生效
        dims = fixed.payload.get("dimensions", {})
        assert dims.get("completeness") == 5.0
        assert fixed.correlation_id is not None
        diff = abs(datetime.now(timezone.utc) - fixed.timestamp)
        assert diff < TIMESTAMP_TOLERANCE

        # 二次校验通过
        re_result = validator.validate(fixed)
        assert re_result.valid, (
            f"Triple-fixed message should pass re-validation: "
            f"{[e.message for e in re_result.errors]}"
        )

    def test_mixed_fixable_and_unfixable_returns_none(self, identity, identity2, validator):
        """混合可修复+不可修复错误 → 放弃修复，返回 None。"""
        old_time = datetime.now(timezone.utc) - timedelta(minutes=10)
        msg = _make_msg(
            identity, identity2,
            task_type=TaskType.RESPONSE_RESULT,
            payload={
                "dimensions": {
                    "completeness": {"score": 5.0, "weight": 0.25},
                }
            },
            timestamp=old_time,
        )

        result = ValidationResult(
            valid=False,
            errors=[
                SchemaError(
                    field_path="payload.dimensions.completeness",
                    expected="number",
                    actual="object (keys=['score', 'weight'])",
                    message="completeness should be number",
                ),
                SchemaError(
                    field_path="payload.duration_days",
                    expected="存在且非空",
                    actual="缺失",
                    message="缺少必填字段 'duration_days'",
                ),
            ],
        )

        fixed = validator.auto_fix(msg, result)
        assert fixed is None, (
            "Mixed fixable+unfixable → should return None (don't partially fix)"
        )
