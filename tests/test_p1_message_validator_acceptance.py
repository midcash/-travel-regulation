"""P1 验收测试: MessageValidator + 版本化开发。

覆盖全部 10 条验收标准。
"""
from __future__ import annotations

import json
import os
from datetime import datetime, timezone

from core.message import (
    AgentMessage, AgentIdentity, TaskType, VersionPolicy, PROTOCOL_VERSION,
    MessageValidationError,
)
from core.message_validator import MessageValidator
from models.protocol import CompatibilityResult, ValidationResult, SchemaError


def test_1_valid_message():
    """验收标准 1: 合法 task.create_itinerary 消息 → valid=True."""
    print("[Test 1] 合法消息 → valid=True")
    identity = AgentIdentity("test", "1.0.0", [], "localhost", "online")
    payload = {
        "destination": {"city": "Tokyo", "country": "Japan"},
        "duration_days": 5,
        "total_budget": 10000,
    }
    msg = AgentMessage(
        message_id="550e8400-e29b-41d4-a716-446655440000",
        sender=identity,
        receiver=identity,
        task_type=TaskType.TASK_CREATE_ITINERARY,
        payload=payload,
        timestamp=datetime.now(timezone.utc),
    )
    validator = MessageValidator(strict_mode=False)
    result = validator.validate(msg)
    assert result.valid, f"Expected valid=True, got {result.to_dict()}"
    print(f"  PASS: valid={result.valid}\n")


def test_2_invalid_message_missing_field():
    """验收标准 2: 非法消息（缺少 destination.city）→ valid=False + error."""
    print("[Test 2] 非法消息（缺少 destination.city）→ valid=False + error")
    identity = AgentIdentity("test", "1.0.0", [], "localhost", "online")
    bad_payload = {
        "destination": {"country": "Japan"},  # 缺少 city
        "duration_days": 5,
        "total_budget": 10000,
    }
    msg = AgentMessage(
        message_id="550e8400-e29b-41d4-a716-446655440001",
        sender=identity,
        receiver=identity,
        task_type=TaskType.TASK_CREATE_ITINERARY,
        payload=bad_payload,
        timestamp=datetime.now(timezone.utc),
    )
    validator = MessageValidator(strict_mode=False)
    result = validator.validate(msg)
    assert not result.valid, f"Expected valid=False, got {result.to_dict()}"
    assert len(result.errors) > 0, "Expected at least one error"
    assert any(
        "city" in e.field_path for e in result.errors
    ), f"Expected error about city, got {[e.field_path for e in result.errors]}"
    print(f"  PASS: valid={result.valid}, errors={len(result.errors)}")
    for e in result.errors:
        print(f"    - {e.field_path}: {e.message}")
    print()


def test_3_strict_mode_raises():
    """验收标准 3: strict_mode=True 时非法消息抛 MessageValidationError."""
    print("[Test 3] strict_mode=True 非法消息 → MessageValidationError")
    identity = AgentIdentity("test", "1.0.0", [], "localhost", "online")
    bad_payload = {
        "destination": {"country": "Japan"},
        "duration_days": 5,
        "total_budget": 10000,
    }
    msg = AgentMessage(
        message_id="550e8400-e29b-41d4-a716-446655440002",
        sender=identity,
        receiver=identity,
        task_type=TaskType.TASK_CREATE_ITINERARY,
        payload=bad_payload,
        timestamp=datetime.now(timezone.utc),
    )
    validator = MessageValidator(strict_mode=True)
    try:
        validator.validate(msg)
        assert False, "Expected MessageValidationError"
    except MessageValidationError as e:
        print(f"  PASS: MessageValidationError raised — {len(e.violations)} violations\n")


def test_4_version_policy_full():
    """验收标准 4: VersionPolicy.check("1.2", "1.2") → full."""
    print('[Test 4] VersionPolicy.check("1.2", "1.2") → full')
    r = VersionPolicy.check("1.2", "1.2")
    assert r.compatible is True
    assert r.level == "full"
    print(f"  PASS: compatible={r.compatible}, level={r.level}\n")


def test_5_version_policy_adapt():
    """验收标准 5: VersionPolicy.check("1.3", "1.2") → adapt."""
    print('[Test 5] VersionPolicy.check("1.3", "1.2") → adapt')
    r = VersionPolicy.check("1.3", "1.2")
    assert r.compatible is True
    assert r.level == "adapt"
    print(f"  PASS: compatible={r.compatible}, level={r.level}\n")


def test_6_version_policy_reject():
    """验收标准 6: VersionPolicy.check("2.0", "1.2") → reject."""
    print('[Test 6] VersionPolicy.check("2.0", "1.2") → reject')
    r = VersionPolicy.check("2.0", "1.2")
    assert r.compatible is False
    assert r.level == "reject"
    print(f"  PASS: compatible={r.compatible}, level={r.level}\n")


def test_7_negotiate():
    """验收标准 7: VersionPolicy.negotiate(["1.2", "1.1"], "1.1") → "1.1"."""
    print('[Test 7] VersionPolicy.negotiate(["1.2", "1.1"], "1.1") → "1.1"')
    v = VersionPolicy.negotiate(["1.2", "1.1"], "1.1")
    assert v == "1.1", f'Expected "1.1", got {v!r}'
    print(f"  PASS: {v}\n")

    # 7b: older client version → should negotiate to client version
    print('[Test 7b] VersionPolicy.negotiate(["1.0"], "1.2") → "1.0"')
    v = VersionPolicy.negotiate(["1.0"], "1.2")
    assert v == "1.0", f'Expected "1.0", got {v!r}'
    print(f"  PASS: {v}\n")

    # 7c: no compatible version → None
    print('[Test 7c] VersionPolicy.negotiate(["2.0"], "1.2") → None')
    v = VersionPolicy.negotiate(["2.0"], "1.2")
    assert v is None, f"Expected None, got {v!r}"
    print(f"  PASS: {v}\n")


def test_8_protocol_version_field():
    """验收标准 8: protocol_version 字段包含在 AgentMessage 中，默认值 "1.0"."""
    print('[Test 8] protocol_version 字段默认值为 "1.0"')
    identity = AgentIdentity("test", "1.0.0", [], "localhost", "online")
    msg_default = AgentMessage(
        message_id="550e8400-e29b-41d4-a716-446655440003",
        sender=identity,
        receiver=identity,
        task_type=TaskType.CONTROL_ABORT,
        payload={"reason": "user_cancel", "force": True},
        timestamp=datetime.now(timezone.utc),
    )
    assert msg_default.protocol_version == "1.0", (
        f'Expected "1.0", got {msg_default.protocol_version!r}'
    )
    # 显式传入 1.2
    msg_v12 = AgentMessage(
        message_id="550e8400-e29b-41d4-a716-446655440004",
        sender=identity,
        receiver=identity,
        task_type=TaskType.CONTROL_ABORT,
        payload={"reason": "user_cancel", "force": True},
        timestamp=datetime.now(timezone.utc),
        protocol_version="1.2",
    )
    assert msg_v12.protocol_version == "1.2", (
        f'Expected "1.2", got {msg_v12.protocol_version!r}'
    )
    print(f"  PASS: default={msg_default.protocol_version}, explicit={msg_v12.protocol_version}\n")


def test_9_schema_files_complete():
    """验收标准 9: 所有 9 个 JSON Schema 文件定义完整且合法."""
    print("[Test 9] 所有 9 个 JSON Schema 文件完整且合法")
    # 项目根目录 (tests/ 的父目录)
    project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    schemas_dir = os.path.join(project_root, "core", "message_schemas")
    schema_files = sorted(
        [f for f in os.listdir(schemas_dir) if f.endswith(".schema.json")]
    )
    expected = [
        "control.abort.schema.json",
        "response.error.schema.json",
        "response.itinerary_draft.schema.json",
        "response.result.schema.json",
        "response.validation_report.schema.json",
        "task.create_itinerary.schema.json",
        "task.evaluate_plan.schema.json",
        "task.revise_itinerary.schema.json",
        "task.validate_feasibility.schema.json",
    ]
    assert schema_files == expected, (
        f"File list mismatch:\n  Got: {schema_files}\n  Exp: {expected}"
    )
    for f in schema_files:
        filepath = os.path.join(schemas_dir, f)
        with open(filepath, encoding="utf-8") as fh:
            s = json.load(fh)
        assert "type" in s, f"{f} missing type"
        assert s["type"] == "object", f"{f} type should be object"
        assert "required" in s, f"{f} missing required"
        assert "properties" in s, f"{f} missing properties"
    print(f"  PASS: all {len(schema_files)} schema files valid\n")

    # 9b: MessageValidator auto-loads all 9 schemas
    print("[Test 9b] MessageValidator auto-loads all 9 schemas")
    v = MessageValidator(strict_mode=False)
    loaded = len(v._schemas)
    assert loaded == 9, f"Expected 9 loaded schemas, got {loaded}"
    print(f"  PASS: {loaded} schemas loaded\n")


def test_10_backward_compatible():
    """验收标准 10: 现有代码不因新增字段而破坏."""
    print('[Test 10] 现有代码向后兼容 — protocol_version 默认值 "1.0"')
    identity = AgentIdentity("test", "1.0.0", [], "localhost", "online")
    old_style_msg = AgentMessage(
        message_id="550e8400-e29b-41d4-a716-446655440005",
        sender=identity,
        receiver=identity,
        task_type=TaskType.TASK_CREATE_ITINERARY,
        payload={
            "destination": {"city": "Osaka", "country": "Japan"},
            "duration_days": 3,
            "total_budget": 5000,
        },
        timestamp=datetime.now(timezone.utc),
    )
    result_old = old_style_msg.validate()
    assert result_old is True, "Old-style message should validate"
    print(f"  PASS: validate()={result_old}, protocol_version={old_style_msg.protocol_version}\n")

    # 10b: validate() rule 0 catches empty protocol_version
    print("[Test 10b] validate() rule 0 catches empty protocol_version")
    try:
        msg_empty = AgentMessage(
            message_id="550e8400-e29b-41d4-a716-446655440006",
            sender=identity,
            receiver=identity,
            task_type=TaskType.CONTROL_ABORT,
            payload={"reason": "test", "force": False},
            timestamp=datetime.now(timezone.utc),
            protocol_version="",
        )
        msg_empty.validate()
        assert False, "Expected MessageValidationError for empty protocol_version"
    except MessageValidationError as e:
        print(f"  PASS: MessageValidationError raised")
        assert any(
            "protocol_version" in v for v in e.violations
        ), f"Expected protocol_version violation, got: {e.violations}"
        print(f"    violations: {e.violations}\n")


def test_older_client_compatibility():
    """额外测试: 旧版 client (1.0) 与新版 server (1.2) 兼容."""
    print('[Extra] VersionPolicy.check("1.0", "1.2") — 旧客户端兼容')
    r = VersionPolicy.check("1.0", "1.2")
    assert r.compatible is True
    assert r.level == "adapt", f"Expected adapt, got {r.level}"
    print(f"  PASS: compatible={r.compatible}, level={r.level}\n")


def test_version_parse_errors():
    """额外测试: _parse 错误处理."""
    print("[Extra] VersionPolicy._parse 错误处理")
    try:
        VersionPolicy._parse("")
        assert False, "Expected ValueError"
    except ValueError:
        pass
    try:
        VersionPolicy._parse("abc")
        assert False, "Expected ValueError"
    except ValueError:
        pass
    try:
        VersionPolicy._parse("1.2.3")
        assert False, "Expected ValueError"
    except ValueError:
        pass
    try:
        VersionPolicy._parse("-1.0")
        assert False, "Expected ValueError"
    except ValueError:
        pass
    print("  PASS: all parse errors caught\n")


def test_register_schema_type_check():
    """额外测试: register_schema 类型检查."""
    print("[Extra] register_schema 类型检查")
    v = MessageValidator(strict_mode=False)
    try:
        v.register_schema("not_a_task_type", {})  # type: ignore[arg-type]
        assert False, "Expected TypeError"
    except TypeError:
        pass
    try:
        v.register_schema(TaskType.CONTROL_ABORT, "not_a_dict")  # type: ignore[arg-type]
        assert False, "Expected TypeError"
    except TypeError:
        pass
    print("  PASS: type checks work\n")


def test_version_compatibility_in_validate():
    """额外测试: validate() 中版本不兼容 → valid=False."""
    print("[Extra] validate() 检测版本不兼容")
    identity = AgentIdentity("test", "1.0.0", [], "localhost", "online")
    msg = AgentMessage(
        message_id="550e8400-e29b-41d4-a716-446655440007",
        sender=identity,
        receiver=identity,
        task_type=TaskType.CONTROL_ABORT,
        payload={"reason": "test", "force": True},
        timestamp=datetime.now(timezone.utc),
        protocol_version="3.0",  # 不同 MAJOR → reject
    )
    validator = MessageValidator(strict_mode=False)
    result = validator.validate(msg)
    assert not result.valid, f"Expected valid=False for version mismatch, got {result.to_dict()}"
    assert any(
        "protocol_version" in e.field_path for e in result.errors
    ), f"Expected protocol_version error, got {[e.field_path for e in result.errors]}"
    print(f"  PASS: valid={result.valid}, errors={len(result.errors)}\n")


def test_message_validator_strict_rejects_version():
    """额外测试: strict_mode=True 版本不兼容 → 抛异常."""
    print("[Extra] strict_mode=True 版本不兼容 → MessageValidationError")
    identity = AgentIdentity("test", "1.0.0", [], "localhost", "online")
    msg = AgentMessage(
        message_id="550e8400-e29b-41d4-a716-446655440008",
        sender=identity,
        receiver=identity,
        task_type=TaskType.CONTROL_ABORT,
        payload={"reason": "test", "force": True},
        timestamp=datetime.now(timezone.utc),
        protocol_version="3.0",
    )
    validator = MessageValidator(strict_mode=True)
    try:
        validator.validate(msg)
        assert False, "Expected MessageValidationError"
    except MessageValidationError as e:
        print(f"  PASS: MessageValidationError raised — {len(e.violations)} violations\n")


def main():
    """运行所有验收测试."""
    print("=" * 60)
    print("P1 验收测试: MessageValidator + 版本化开发")
    print("=" * 60)
    print()

    tests = [
        test_1_valid_message,
        test_2_invalid_message_missing_field,
        test_3_strict_mode_raises,
        test_4_version_policy_full,
        test_5_version_policy_adapt,
        test_6_version_policy_reject,
        test_7_negotiate,
        test_8_protocol_version_field,
        test_9_schema_files_complete,
        test_10_backward_compatible,
        test_older_client_compatibility,
        test_version_parse_errors,
        test_register_schema_type_check,
        test_version_compatibility_in_validate,
        test_message_validator_strict_rejects_version,
    ]

    for test_fn in tests:
        try:
            test_fn()
        except Exception as e:
            print(f"  FAIL in {test_fn.__name__}: {e}")
            import traceback
            traceback.print_exc()
            return 1

    print("=" * 60)
    print("所有验收测试通过!")
    print("=" * 60)
    return 0


if __name__ == "__main__":
    exit(main())
