"""Explicit-response Fakes for M3 provider ports."""

from __future__ import annotations

from decimal import Decimal

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


class FakeProviderNotConfiguredError(RuntimeError):
    """The Fake has no explicit response for a provider call."""


class _ResponseQueue:
    """Consume explicitly configured responses without fallback behavior."""

    def __init__(self, responses: list[object] | None) -> None:
        self._responses = list(responses or [])

    async def next(self, provider_name: str) -> object:
        """Return the next response or propagate its explicitly injected error."""
        if not self._responses:
            raise FakeProviderNotConfiguredError(
                f"Fake {provider_name} provider 未配置响应"
            )
        response = self._responses.pop(0)
        if isinstance(response, BaseException):
            raise response
        return response


class FakeGeoProvider:
    """Fake GeoProvider with explicit responses and call recording."""

    def __init__(self, responses: list[GeoProviderResult | BaseException] | None = None) -> None:
        self._responses = _ResponseQueue(responses)
        self.calls: list[tuple[GeoQuery, Decimal]] = []

    async def search(self, query: GeoQuery, *, timeout_seconds: Decimal) -> GeoProviderResult:
        """Return the next configured geographic result."""
        self.calls.append((query, timeout_seconds))
        response = await self._responses.next("Geo")
        if not isinstance(response, GeoProviderResult):
            raise TypeError("Fake Geo provider response must be GeoProviderResult")
        return response


class FakeTransportProvider:
    """Fake TransportProvider with explicit responses and call recording."""

    def __init__(
        self, responses: list[TransportProviderResult | BaseException] | None = None
    ) -> None:
        self._responses = _ResponseQueue(responses)
        self.calls: list[tuple[TransportQuery, Decimal]] = []

    async def search(
        self, query: TransportQuery, *, timeout_seconds: Decimal
    ) -> TransportProviderResult:
        """Return the next configured transport result."""
        self.calls.append((query, timeout_seconds))
        response = await self._responses.next("Transport")
        if not isinstance(response, TransportProviderResult):
            raise TypeError("Fake Transport provider response must be TransportProviderResult")
        return response


class FakeStayProvider:
    """Fake StayProvider with explicit responses and call recording."""

    def __init__(self, responses: list[StayProviderResult | BaseException] | None = None) -> None:
        self._responses = _ResponseQueue(responses)
        self.calls: list[tuple[StayQuery, Decimal]] = []

    async def search(self, query: StayQuery, *, timeout_seconds: Decimal) -> StayProviderResult:
        """Return the next configured stay result."""
        self.calls.append((query, timeout_seconds))
        response = await self._responses.next("Stay")
        if not isinstance(response, StayProviderResult):
            raise TypeError("Fake Stay provider response must be StayProviderResult")
        return response


class FakePlaceProvider:
    """Fake PlaceProvider with explicit responses and call recording."""

    def __init__(self, responses: list[PlaceProviderResult | BaseException] | None = None) -> None:
        self._responses = _ResponseQueue(responses)
        self.calls: list[tuple[PlaceQuery, Decimal]] = []

    async def search(self, query: PlaceQuery, *, timeout_seconds: Decimal) -> PlaceProviderResult:
        """Return the next configured place result."""
        self.calls.append((query, timeout_seconds))
        response = await self._responses.next("Place")
        if not isinstance(response, PlaceProviderResult):
            raise TypeError("Fake Place provider response must be PlaceProviderResult")
        return response


class FakeContextProvider:
    """Fake ContextProvider with explicit responses and call recording."""

    def __init__(
        self, responses: list[ContextProviderResult | BaseException] | None = None
    ) -> None:
        self._responses = _ResponseQueue(responses)
        self.calls: list[tuple[ContextQuery, Decimal]] = []

    async def search(
        self, query: ContextQuery, *, timeout_seconds: Decimal
    ) -> ContextProviderResult:
        """Return the next configured context result."""
        self.calls.append((query, timeout_seconds))
        response = await self._responses.next("Context")
        if not isinstance(response, ContextProviderResult):
            raise TypeError("Fake Context provider response must be ContextProviderResult")
        return response
