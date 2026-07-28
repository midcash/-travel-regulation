from __future__ import annotations

from decimal import Decimal

import pytest
from pydantic import ValidationError

from src.domain.models.trip_request import BudgetSemantics, BudgetSpec
from src.domain.models.value_objects import Money


def test_budget_spec_rejects_zero_amount() -> None:
    with pytest.raises(ValidationError, match="positive"):
        BudgetSpec(
            semantics=BudgetSemantics.MAXIMUM,
            maximum=Money(amount=Decimal("0"), currency="CNY"),
        )
