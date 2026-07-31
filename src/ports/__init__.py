"""Application layer port contracts."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Protocol, runtime_checkable


@runtime_checkable
class Clock(Protocol):
    """Provide the current time for deterministic call sites."""

    def now(self) -> datetime:
        """Return the current time."""


class SystemClock:
    """Default production clock."""

    def now(self) -> datetime:
        """Return the current UTC time."""
        return datetime.now(UTC)
