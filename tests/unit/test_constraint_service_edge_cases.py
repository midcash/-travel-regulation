from __future__ import annotations

from datetime import UTC, date, datetime
from decimal import Decimal
from unittest.mock import patch

import pytest

from src.domain.errors import WorkflowError
from src.domain.models.constraint import ConstraintSnapshot, ConstraintSource
from src.domain.models.enums import ConstraintHardness
from src.domain.models.interpretation import ConstraintCandidate, InterpretationResult
from src.domain.models.value_objects import DateRange, Money
from src.domain.services.constraint_service import (
    ConstraintObservation,
    ConstraintService,
    _date_value,
    _find_currency,
    _money,
    _place,
    _traveler_count,
    _value,
    _value_key,
)


def _candidate(category: str, value: object) -> ConstraintCandidate:
    return ConstraintCandidate(
        category=category,
        value=value,
        hardness=ConstraintHardness.SOFT,
        scope="trip",
        confidence=Decimal("0.8"),
    )


def _interpretation(*items: ConstraintCandidate) -> InterpretationResult:
    return InterpretationResult(
        mode_hint=None,
        extracted_entities=(),
        constraint_candidates=tuple(items),
        explicit_questions=(),
        references_to_current_plan=(),
        field_confidence={},
        overall_confidence=Decimal("0.8"),
        safety_flags=(),
    )


def _build(*items: ConstraintCandidate, **kwargs: object) -> ConstraintSnapshot:
    return ConstraintService().build_snapshot(
        _interpretation(*items),
        request_id="request:edge",
        trace_id="trace:edge",
        created_at=datetime(2026, 7, 30, tzinfo=UTC),
        reference_date=date(2026, 7, 30),
        **kwargs,
    )


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("2026-08-01", date(2026, 8, 1)),
        ("2026-08-01/2026-08-03", DateRange(start=date(2026, 8, 1), end=date(2026, 8, 3))),
        ("2026年8月1日至8月3日", DateRange(start=date(2026, 8, 1), end=date(2026, 8, 3))),
        ("August 1 to August 3, 2026", DateRange(start=date(2026, 8, 1), end=date(2026, 8, 3))),
        ("today", date(2026, 7, 30)),
        ("tomorrow", date(2026, 7, 31)),
        ("weekend", DateRange(start=date(2026, 8, 1), end=date(2026, 8, 2))),
        ("next weekend", DateRange(start=date(2026, 8, 8), end=date(2026, 8, 9))),
    ],
)
def test_constraint_service_supports_date_expression_variants(
    value: str,
    expected: object,
) -> None:
    assert _date_value(value, reference_date=date(2026, 7, 30)) == expected


def test_constraint_service_supports_relative_weekday_and_cross_year_ranges() -> None:
    assert _date_value("下周一", reference_date=date(2026, 7, 30)) == date(2026, 8, 3)
    assert _date_value("December 31 to January 2", reference_date=date(2026, 7, 30)) == DateRange(
        start=date(2026, 12, 31),
        end=date(2027, 1, 2),
    )


@pytest.mark.parametrize(
    "value",
    ["August 1", "not-a-date", 1, True],
)
def test_constraint_service_rejects_date_without_resolvable_year_or_type(value: object) -> None:
    with pytest.raises((TypeError, ValueError)):
        _date_value(value, reference_date=None)


def test_constraint_service_normalizes_money_currency_travelers_and_places() -> None:
    assert _money(100, default_currency="CNY") == Money(amount=Decimal("100"), currency="CNY")
    assert _money(100.5, default_currency="USD") == Money(
        amount=Decimal("100.5"),
        currency="USD",
    )
    assert _money("1,200 USD", default_currency="CNY") == Money(
        amount=Decimal("1200"),
        currency="USD",
    )
    assert _find_currency("$20") == "USD"
    assert _find_currency("euro 20") == "EUR"
    assert _find_currency("yen 20") == "JPY"
    assert _find_currency("no currency") is None
    assert _traveler_count(2) == 2
    assert _traveler_count("2 adults") == 2
    assert _traveler_count("两") == 2
    assert _place(("Hangzhou", "Hangzhou", "Suzhou")) == ("Hangzhou", "Suzhou")


@pytest.mark.parametrize(
    ("category", "value", "expected"),
    [
        ("currency", "USD", "USD"),
        ("preference", ("quiet", "quiet"), ("quiet",)),
        ("preference", "  quiet hotel ", "quiet hotel"),
        ("preference", 1.25, Decimal("1.25")),
        ("preference", True, True),
        ("preference", 3, 3),
        ("preference", Decimal("2.5"), Decimal("2.5")),
        ("preference", date(2026, 8, 1), date(2026, 8, 1)),
        ("preference", Money(amount=Decimal("10"), currency="CNY"), Money(
            amount=Decimal("10"),
            currency="CNY",
        )),
        ("preference", DateRange(start=date(2026, 8, 1), end=date(2026, 8, 2)), DateRange(
            start=date(2026, 8, 1),
            end=date(2026, 8, 2),
        )),
    ],
)
def test_constraint_service_normalizes_generic_constraint_values(
    category: str,
    value: object,
    expected: object,
) -> None:
    assert _value(category, value, reference_date=None, default_currency="CNY") == expected


@pytest.mark.parametrize(
    "value",
    [False, 0, -1, "not-a-number"],
)
def test_constraint_service_rejects_invalid_money_and_traveler_values(value: object) -> None:
    with pytest.raises((TypeError, ValueError)):
        _money(value, default_currency="CNY")

    with pytest.raises((TypeError, ValueError)):
        _traveler_count(value)


def test_constraint_service_rejects_invalid_context_and_snapshot_contracts() -> None:
    with pytest.raises(WorkflowError, match="currency"):
        _build(_candidate("budget", "100"), default_currency="invalid")

    with patch(
        "src.domain.services.constraint_service.ConstraintSnapshot",
        side_effect=ValueError("snapshot contract"),
    ):
        with pytest.raises(WorkflowError, match="snapshot contract"):
            _build(_candidate("destination", "Hangzhou"))


def test_constraint_service_prefers_current_user_observation_and_exposes_keys() -> None:
    snapshot = _build(
        _candidate("budget", "1000"),
        context_observations=(
            ConstraintObservation(
                candidate=_candidate("budget", "1000"),
                source=ConstraintSource.PROFILE,
            ),
        ),
    )
    value = snapshot.constraints[0].normalized_value
    assert _value_key(value) == '{"amount": "1000", "currency": "CNY"}'
    assert snapshot.constraints[0].source is ConstraintSource.USER


def test_constraint_service_rejects_invalid_normalized_domain_contract() -> None:
    with patch(
        "src.domain.services.constraint_service.Constraint",
        side_effect=ValueError("constraint contract"),
    ):
        with pytest.raises(WorkflowError, match="normalized constraint"):
            _build(_candidate("destination", "Hangzhou"))


def test_constraint_service_rejects_empty_places_and_unsupported_values() -> None:
    with pytest.raises(ValueError):
        _place(())
    with pytest.raises(ValueError):
        _place((" ",))
    with pytest.raises(TypeError):
        _place(1)
    with pytest.raises(TypeError):
        _value("preference", object(), reference_date=None, default_currency="CNY")
