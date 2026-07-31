"""Capability-specific provider ports for M3 tool access."""

from __future__ import annotations

from decimal import Decimal
from typing import Protocol, runtime_checkable

from src.domain.models.provider import (
    ContextProviderResult,
    ContextQuery,
    GeoProviderResult,
    GeoQuery,
    PlaceProviderResult,
    PlaceQuery,
    StayProviderResult,
    StayQuery,
    TransportProviderResult,
    TransportQuery,
)


@runtime_checkable
class GeoProvider(Protocol):
    """Provide normalized geographic search results."""

    async def search(
        self, query: GeoQuery, *, timeout_seconds: Decimal
    ) -> GeoProviderResult:
        """Search geographic entities with an explicit timeout budget."""
        ...


@runtime_checkable
class TransportProvider(Protocol):
    """Provide normalized transport options."""

    async def search(
        self, query: TransportQuery, *, timeout_seconds: Decimal
    ) -> TransportProviderResult:
        """Search transport options with an explicit timeout budget."""
        ...


@runtime_checkable
class StayProvider(Protocol):
    """Provide normalized stay options."""

    async def search(
        self, query: StayQuery, *, timeout_seconds: Decimal
    ) -> StayProviderResult:
        """Search stay options with an explicit timeout budget."""
        ...


@runtime_checkable
class PlaceProvider(Protocol):
    """Provide normalized places and activities."""

    async def search(
        self, query: PlaceQuery, *, timeout_seconds: Decimal
    ) -> PlaceProviderResult:
        """Search places with an explicit timeout budget."""
        ...


@runtime_checkable
class ContextProvider(Protocol):
    """Provide normalized contextual facts."""

    async def search(
        self, query: ContextQuery, *, timeout_seconds: Decimal
    ) -> ContextProviderResult:
        """Search contextual facts with an explicit timeout budget."""
        ...
