from __future__ import annotations

from datetime import date
from decimal import Decimal
from unittest.mock import patch

import pytest

from src.domain.errors import WorkflowError
from src.domain.models.constraint import ConstraintSource
from src.domain.models.enums import ConstraintHardness
from src.domain.models.interpretation import ConstraintCandidate
from src.domain.models.value_objects import DateRange
from src.domain.services.constraint_service import (
    ConstraintObservation,
    ConstraintService,
    _currency_code,
    _date_value,
    _find_currency,
    _merge_multi,
    _money,
    _NormalizedConstraint,
    _value,
)


def _normalized(
    value: object,
    *,
    category: str = "origin",
    source: ConstraintSource = ConstraintSource.USER,
    is_current: bool = True,
    hardness: ConstraintHardness = ConstraintHardness.HARD,
) -> _NormalizedConstraint:
    return _NormalizedConstraint(
        category=category,
        normalized_value=value,  # type: ignore[arg-type]
        hardness=hardness,
        scope="trip",
        source=source,
        confidence=Decimal("0.8"),
        user_confirmed=False,
        is_current=is_current,
    )


def test_constraint_service_reaches_empty_scope_fail_fast_without_schema_coercion() -> None:
    candidate = ConstraintCandidate.model_construct(
        category="destination",
        value="Hangzhou",
        hardness=ConstraintHardness.SOFT,
        scope="",
        confidence=Decimal("0.8"),
    )
    observation = ConstraintObservation.model_construct(
        candidate=candidate,
        source=ConstraintSource.USER,
        user_confirmed=False,
    )

    with pytest.raises(WorkflowError, match="scope"):
        ConstraintService._normalize_observation(
            observation,
            trace_id="trace:scope",
            reference_date=date(2026, 7, 30),
            default_currency="CNY",
            is_current=True,
        )


def test_constraint_service_covers_currency_and_generic_value_rejection_branches() -> None:
    with pytest.raises(ValueError):
        _value("currency", 123, reference_date=None, default_currency="CNY")
    with pytest.raises(ValueError):
        _value("preference", ("",), reference_date=None, default_currency="CNY")
    with pytest.raises(ValueError):
        _value("preference", "", reference_date=None, default_currency="CNY")
    with pytest.raises(ValueError):
        _value("preference", float("inf"), reference_date=None, default_currency="CNY")
    with pytest.raises(TypeError):
        _value("preference", [], reference_date=None, default_currency="CNY")

    with pytest.raises(TypeError):
        _money(object(), default_currency="CNY")
    with pytest.raises(ValueError):
        _money(float("inf"), default_currency="CNY")
    assert _find_currency("€20") == "EUR"
    assert _currency_code("rmb") == "CNY"


def test_constraint_service_covers_date_range_defensive_and_invalid_month_branches() -> None:
    original = _date_value
    with patch(
        "src.domain.services.constraint_service._date_value",
        side_effect=[
            DateRange(start=date(2026, 8, 1), end=date(2026, 8, 2)),
            date(2026, 8, 3),
        ],
    ):
        with pytest.raises(TypeError):
            original("2026-08-01/2026-08-03", reference_date=date(2026, 7, 30))

    assert _date_value("12月31日至1月2日", reference_date=date(2026, 7, 30))
    with pytest.raises(ValueError):
        _date_value("Foo 1 to Bar 2", reference_date=date(2026, 7, 30))
    with pytest.raises(ValueError):
        _date_value("Foo 1", reference_date=date(2026, 7, 30))


def test_constraint_service_covers_duplicate_winner_and_multi_value_loop_branches() -> None:
    values = [
        _normalized("Hangzhou", is_current=False),
        _normalized("Hangzhou", is_current=True),
        _normalized(("quiet", "walkable"), category="preference"),
        _normalized("quiet", category="preference", is_current=False),
    ]
    merged = ConstraintService._merge(values, trace_id="trace:merge")
    assert merged
    assert _merge_multi(
        [_normalized("quiet", category="preference", is_current=True)]
    ).normalized_value == "quiet"
