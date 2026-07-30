from __future__ import annotations

from datetime import date
from decimal import Decimal

import pytest

from src.domain.models.constraint import Constraint, ConstraintSource
from src.domain.models.enums import ConstraintHardness
from src.domain.models.value_objects import DateRange, Money
from src.domain.services.constraint_service import (
    _date_value,
    _merge_multi,
    _money,
    _NormalizedConstraint,
    _place,
    _traveler_count,
    _value,
    _value_key,
)


@pytest.mark.parametrize(
    ("category", "value"),
    [
        ("date", date(2026, 8, 1)),
        ("date_range", date(2026, 8, 1)),
        ("budget", 100),
        ("travelers", 2),
        ("preference", "quiet"),
        ("preference", 1.5),
        ("preference", True),
        ("preference", 3),
        ("preference", Decimal("2.5")),
        ("preference", date(2026, 8, 1)),
        ("preference", Money(amount=Decimal("10"), currency="CNY")),
        ("preference", DateRange(start=date(2026, 8, 1), end=date(2026, 8, 2))),
    ],
)
def test_constraint_service_value_dispatch_covers_supported_types(
    category: str,
    value: object,
) -> None:
    normalized = _value(
        category,
        value,
        reference_date=date(2026, 7, 30),
        default_currency="CNY",
    )
    assert normalized is not None


@pytest.mark.parametrize(
    "value",
    [
        "2026年8月1日",
        "2026年8月1日至2026年8月3日",
        "August 1",
        "August 1 to August 3",
        "next weekend",
        "下周一",
    ],
)
def test_constraint_service_date_parser_covers_single_and_relative_forms(value: str) -> None:
    assert _date_value(value, reference_date=date(2026, 7, 30))


def test_constraint_service_money_traveler_place_and_key_edge_branches() -> None:
    with pytest.raises(TypeError):
        _money(False, default_currency="CNY")
    with pytest.raises(ValueError):
        _money(0, default_currency="CNY")
    with pytest.raises(ValueError):
        _money("no amount", default_currency="CNY")
    with pytest.raises(ValueError):
        _money("1 USD", default_currency="invalid")

    with pytest.raises(ValueError):
        _traveler_count("0")
    with pytest.raises(TypeError):
        _traveler_count(object())
    with pytest.raises(ValueError):
        _place("")

    model = Constraint(
        id="constraint:key",
        category="destination",
        normalized_value="Hangzhou",
        hardness=ConstraintHardness.SOFT,
        priority=1,
        scope="trip",
        source=ConstraintSource.USER,
        confidence=Decimal("0.8"),
    )
    assert _value_key(model).startswith("{")
    assert _value_key(date(2026, 8, 1)) == "2026-08-01"
    assert _value_key(Decimal("1.5")) == "1.5"


def test_constraint_service_merge_multi_handles_tuple_and_single_values() -> None:
    first = _NormalizedConstraint(
        category="preference",
        normalized_value=("quiet", "walkable"),
        hardness=ConstraintHardness.SOFT,
        scope="trip",
        source=ConstraintSource.USER,
        confidence=Decimal("0.8"),
        user_confirmed=False,
        is_current=True,
    )
    second = _NormalizedConstraint(
        category="preference",
        normalized_value="quiet",
        hardness=ConstraintHardness.ASSUMPTION,
        scope="trip",
        source=ConstraintSource.ASSUMPTION,
        confidence=Decimal("0.5"),
        user_confirmed=False,
        is_current=False,
    )

    merged = _merge_multi([first, second])

    assert merged.normalized_value == ("quiet", "walkable")
    assert merged.confidence == Decimal("0.8")
