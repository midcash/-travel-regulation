"""Clock test doubles."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta


class FakeClock:
    """Deterministic clock for tests and failure injection."""

    def __init__(self, current: datetime | None = None) -> None:
        self._current = current or datetime(2026, 7, 1, tzinfo=UTC)
        if self._current.tzinfo is None:
            raise ValueError("FakeClock requires timezone-aware datetime")
        self.calls: list[datetime] = []

    def now(self) -> datetime:
        """Return the configured current time and record the call."""
        self.calls.append(self._current)
        return self._current

    def set(self, current: datetime) -> None:
        """Set the current time explicitly."""
        if current.tzinfo is None:
            raise ValueError("FakeClock requires timezone-aware datetime")
        self._current = current

    def advance(self, delta: timedelta) -> datetime:
        """Advance the current time and return the new value."""
        self._current = self._current + delta
        return self._current
