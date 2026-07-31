from __future__ import annotations

from datetime import UTC, date, datetime
from decimal import Decimal
from typing import Any

import pytest

from src.domain.models.provider import (
    ContextProviderResult,
    ContextQuery,
    ContextResultItem,
    GeoProviderResult,
    GeoQuery,
    GeoResultItem,
    PlaceProviderResult,
    PlaceQuery,
    PlaceResultItem,
    StayProviderResult,
    StayQuery,
    StayResultItem,
    TransportProviderResult,
    TransportQuery,
    TransportResultItem,
)
from src.domain.models.value_objects import DateRange, GeoPoint
from src.ports.tool_provider import (
    ContextProvider,
    GeoProvider,
    PlaceProvider,
    StayProvider,
    TransportProvider,
)
from tests.support.provider_fakes import (
    FakeContextProvider,
    FakeGeoProvider,
    FakePlaceProvider,
    FakeProviderNotConfiguredError,
    FakeStayProvider,
    FakeTransportProvider,
)


def _observed_at() -> datetime:
    return datetime(2026, 8, 1, 9, tzinfo=UTC)


def _run(coroutine: Any) -> Any:
    """Drive a Fake coroutine without creating a socket-backed event loop."""
    try:
        coroutine.send(None)
    except StopIteration as completed:
        return completed.value
    raise AssertionError("Provider Fake unexpectedly suspended")


def test_provider_fakes_implement_capability_ports_and_preserve_timeout() -> None:
    geo_query = GeoQuery(query_id="geo-1", trace_id="trace-1", text="West Lake")
    geo_result = GeoProviderResult(
        query_id="geo-1",
        provider="amap",
        observed_at=_observed_at(),
        source_ref="https://provider.example/geo/1",
        items=(
            GeoResultItem(
                entity_id="place-1",
                name="West Lake",
                location=GeoPoint(latitude=30.25, longitude=120.13),
                confidence=Decimal("0.9"),
            ),
        ),
    )
    transport_query = TransportQuery(
        query_id="transport-1",
        trace_id="trace-1",
        origin="Shanghai",
        destination="Hangzhou",
    )
    transport_result = TransportProviderResult(
        query_id="transport-1",
        provider="tuniu",
        observed_at=_observed_at(),
        source_ref="https://provider.example/transport/1",
        items=(
            TransportResultItem(
                entity_id="train-1",
                mode="rail",
                name="G123",
                origin="Shanghai",
                destination="Hangzhou",
                source_ref="https://provider.example/transport/1",
            ),
        ),
    )
    stay_query = StayQuery(
        query_id="stay-1",
        trace_id="trace-1",
        destination="Hangzhou",
        date_range=DateRange(start=date(2026, 8, 1), end=date(2026, 8, 3)),
    )
    stay_result = StayProviderResult(
        query_id="stay-1",
        provider="tuniu",
        observed_at=_observed_at(),
        source_ref="https://provider.example/stay/1",
        items=(
            StayResultItem(
                entity_id="hotel-1",
                name="Lake Hotel",
                area="West Lake",
                source_ref="https://provider.example/stay/1",
            ),
        ),
    )
    place_query = PlaceQuery(
        query_id="place-1",
        trace_id="trace-1",
        destination="Hangzhou",
        category="scenic",
    )
    place_result = PlaceProviderResult(
        query_id="place-1",
        provider="amap",
        observed_at=_observed_at(),
        source_ref="https://provider.example/place/1",
        items=(
            PlaceResultItem(
                entity_id="place-1",
                name="West Lake",
                category="scenic",
                source_ref="https://provider.example/place/1",
            ),
        ),
    )
    context_query = ContextQuery(
        query_id="context-1",
        trace_id="trace-1",
        scope="trip-1",
        context_types=("weather",),
    )
    context_result = ContextProviderResult(
        query_id="context-1",
        provider="amap",
        observed_at=_observed_at(),
        source_ref="https://provider.example/context/1",
        items=(
            ContextResultItem(
                entity_id="context-1",
                context_type="weather",
                summary="Clear",
                source_ref="https://provider.example/context/1",
            ),
        ),
    )

    geo = FakeGeoProvider([geo_result])
    transport = FakeTransportProvider([transport_result])
    stay = FakeStayProvider([stay_result])
    place = FakePlaceProvider([place_result])
    context = FakeContextProvider([context_result])
    timeout = Decimal("3.5")

    assert isinstance(geo, GeoProvider)
    assert isinstance(transport, TransportProvider)
    assert isinstance(stay, StayProvider)
    assert isinstance(place, PlaceProvider)
    assert isinstance(context, ContextProvider)
    assert _run(geo.search(geo_query, timeout_seconds=timeout)) == geo_result
    assert _run(transport.search(transport_query, timeout_seconds=timeout)) == transport_result
    assert _run(stay.search(stay_query, timeout_seconds=timeout)) == stay_result
    assert _run(place.search(place_query, timeout_seconds=timeout)) == place_result
    assert _run(context.search(context_query, timeout_seconds=timeout)) == context_result
    assert geo.calls == [(geo_query, timeout)]
    assert transport.calls == [(transport_query, timeout)]
    assert stay.calls == [(stay_query, timeout)]
    assert place.calls == [(place_query, timeout)]
    assert context.calls == [(context_query, timeout)]


def test_provider_fake_fails_fast_when_response_is_not_configured() -> None:
    query = GeoQuery(query_id="geo-1", trace_id="trace-1", text="West Lake")
    provider = FakeGeoProvider()

    with pytest.raises(FakeProviderNotConfiguredError, match="未配置响应"):
        _run(provider.search(query, timeout_seconds=Decimal("1")))

    assert len(provider.calls) == 1


def test_provider_fake_propagates_explicit_failure_without_fallback() -> None:
    query = GeoQuery(query_id="geo-1", trace_id="trace-1", text="West Lake")
    failure = RuntimeError("provider offline")
    provider = FakeGeoProvider([failure])

    with pytest.raises(RuntimeError, match="provider offline"):
        _run(provider.search(query, timeout_seconds=Decimal("1")))

    assert len(provider.calls) == 1


def test_provider_fake_rejects_non_result_response() -> None:
    query = GeoQuery(query_id="geo-1", trace_id="trace-1", text="West Lake")
    provider = FakeGeoProvider([{"items": []}])  # type: ignore[list-item]

    with pytest.raises(TypeError, match="GeoProviderResult"):
        _run(provider.search(query, timeout_seconds=Decimal("1")))
