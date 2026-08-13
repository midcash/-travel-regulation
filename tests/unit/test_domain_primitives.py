from __future__ import annotations

from datetime import date
from decimal import Decimal

import pytest
from pydantic import ValidationError

from src.domain.errors import WorkflowError
from src.domain.models.enums import (
    ConstraintHardness,
    ErrorCategory,
    EvidenceStatus,
    InteractionMode,
    IssueSeverity,
    WorkflowStatus,
)
from src.domain.models.value_objects import DateRange, GeoPoint, Money


def test_domain_enums_serialize_to_lower_snake_case() -> None:
    assert InteractionMode.PLAN.value == "plan"
    assert ConstraintHardness.ASSUMPTION.value == "assumption"
    assert EvidenceStatus.UNAVAILABLE.value == "unavailable"
    assert WorkflowStatus.NEEDS_CONFIRMATION.value == "needs_confirmation"
    assert IssueSeverity.BLOCKING.value == "blocking"
    assert ErrorCategory.STATE_CONFLICT.value == "state_conflict"


def test_money_accepts_decimal_and_normalizes_currency() -> None:
    money = Money(amount=Decimal("123.45"), currency=" cny ")

    assert money.amount == Decimal("123.45")
    assert money.currency == "CNY"


def test_money_rejects_float_negative_amount_and_unknown_fields() -> None:
    with pytest.raises(ValueError, match="must be Decimal"):
        Money(amount=1.2, currency="CNY")
    with pytest.raises(ValidationError):
        Money(amount=Decimal("-0.01"), currency="CNY")
    with pytest.raises(ValidationError):
        Money(amount=Decimal("1"), currency="CNY", extra="rejected")


def test_date_range_is_inclusive_and_rejects_reversed_range() -> None:
    date_range = DateRange(start=date(2026, 7, 26), end=date(2026, 7, 28))

    assert date_range.days == 3
    with pytest.raises(ValidationError, match="end must not be earlier"):
        DateRange(start=date(2026, 7, 28), end=date(2026, 7, 26))


def test_geo_point_validates_wgs84_bounds_and_is_immutable() -> None:
    point = GeoPoint(latitude=31.2304, longitude=121.4737)

    assert point.latitude == 31.2304
    with pytest.raises(ValidationError):
        GeoPoint(latitude=91, longitude=0)
    with pytest.raises(ValidationError):
        GeoPoint(latitude=0, longitude=181)
    with pytest.raises(ValidationError):
        point.latitude = 0


def test_workflow_error_exposes_safe_payload_without_cause() -> None:
    cause = RuntimeError("secret upstream response")
    error = WorkflowError(
        "trace-1",
        "validation",
        ErrorCategory.TOOL,
        "tool_timeout",
        "工具查询超时",
        upstream_refs=("candidate-1",),
        retryable=True,
        cause=cause,
    )

    assert str(error) == "工具查询超时"
    assert error.retryable is True
    assert error.cause is cause
    assert error.public_payload().model_dump(mode="json") == {
        "trace_id": "trace-1",
        "stage": "validation",
        "category": "tool",
        "code": "tool_timeout",
        "safe_message": "工具查询超时",
        "upstream_refs": ["candidate-1"],
        "retryable": True,
        "cause_code": None,
    }
    assert "secret upstream response" not in repr(error.public_payload())
