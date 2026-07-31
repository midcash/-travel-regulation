from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from src.ports.clock import Clock, SystemClock
from tests.support.clock_fakes import FakeClock


def test_system_clock_implements_port_and_returns_utc_time() -> None:
    clock = SystemClock()

    current = clock.now()

    assert isinstance(clock, Clock)
    assert current.tzinfo == UTC


def test_fake_clock_implements_port_and_defaults_to_stable_utc_time() -> None:
    clock = FakeClock()

    assert isinstance(clock, Clock)
    assert clock.now() == datetime(2026, 7, 1, tzinfo=UTC)


def test_fake_clock_advances_deterministically() -> None:
    clock = FakeClock(datetime(2026, 7, 30, 12, tzinfo=UTC))

    assert clock.advance(timedelta(minutes=15)) == datetime(
        2026, 7, 30, 12, 15, tzinfo=UTC
    )
    assert clock.now() == datetime(2026, 7, 30, 12, 15, tzinfo=UTC)
    assert len(clock.calls) == 1


def test_fake_clock_set_rejects_naive_datetime() -> None:
    clock = FakeClock()

    with pytest.raises(ValueError, match="timezone-aware"):
        clock.set(datetime(2026, 7, 30, 12))
