from __future__ import annotations

from datetime import UTC, date, datetime
from decimal import Decimal
from typing import Any

import pytest

from src.domain.models.provider import (
    GeoProviderResult,
    GeoResultItem,
    PlaceProviderResult,
    PlaceResultItem,
    StayProviderResult,
    StayResultItem,
    TransportProviderResult,
    TransportResultItem,
)
from src.domain.models.value_objects import GeoPoint
from src.tool import knowledge
from tests.support.clock_fakes import FakeClock
from tests.support.provider_fakes import (
    FakeGeoProvider,
    FakePlaceProvider,
    FakeStayProvider,
    FakeTransportProvider,
)


def _observed_at() -> datetime:
    return datetime(2026, 8, 1, 9, tzinfo=UTC)


def _run(coroutine: Any) -> Any:
    """无事件循环地驱动无挂起的 Provider Fake 协程。"""
    try:
        coroutine.send(None)
    except StopIteration as completed:
        return completed.value
    coroutine.close()
    raise AssertionError("Provider Fake coroutine unexpectedly suspended")


def _install(
    monkeypatch: pytest.MonkeyPatch,
    facade: knowledge.KnowledgeFacade,
) -> None:
    monkeypatch.setattr(knowledge, "_legacy_facade", None)
    knowledge.configure_legacy_facade(facade)


def test_amap_entrypoint_delegates_to_configured_geo_port(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    clock = FakeClock(_observed_at())
    geo = FakeGeoProvider(
        [
            GeoProviderResult(
                query_id="provider-geo-1",
                provider="amap",
                observed_at=_observed_at(),
                source_ref="https://provider.example/geo/1",
                items=(
                    GeoResultItem(
                        entity_id="place-1",
                        name="West Lake",
                        address="Hangzhou West Lake",
                        location=GeoPoint(latitude=30.25, longitude=120.13),
                        confidence=Decimal("0.9"),
                    ),
                ),
            )
        ]
    )
    facade = knowledge.KnowledgeFacade(
        clock=clock,
        trace_id="trace-knowledge-1",
        timeout_seconds=Decimal("7.5"),
        geo_provider=geo,
        synchronous_runner=_run,
    )
    _install(monkeypatch, facade)

    result = knowledge._exec_amap_geocode("Hangzhou West Lake")

    assert result == {
        "lat": 30.25,
        "lng": 120.13,
        "display_name": "Hangzhou West Lake",
        "source_ref": "https://provider.example/geo/1",
    }
    assert len(geo.calls) == 1
    query, timeout = geo.calls[0]
    assert query.text == "Hangzhou West Lake"
    assert query.trace_id == "trace-knowledge-1"
    assert query.timeout_seconds == Decimal("7.5")
    assert query.query_id.startswith("legacy-knowledge.amap_geocode:")
    assert timeout == Decimal("7.5")
    assert clock.calls == [_observed_at()]


def test_legacy_registry_delegates_travel_searches_to_typed_ports(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    clock = FakeClock(_observed_at())
    stay = FakeStayProvider(
        [
            StayProviderResult(
                query_id="provider-stay-1",
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
        ]
    )
    transport = FakeTransportProvider(
        [
            TransportProviderResult(
                query_id="provider-transport-1",
                provider="tuniu",
                observed_at=_observed_at(),
                source_ref="https://provider.example/transport/1",
                items=(
                    TransportResultItem(
                        entity_id="transport-1",
                        mode="rail",
                        name="G123",
                        origin="Shanghai",
                        destination="Hangzhou",
                        source_ref="https://provider.example/transport/1",
                    ),
                ),
            )
        ]
    )
    place = FakePlaceProvider(
        [
            PlaceProviderResult(
                query_id="provider-place-1",
                provider="tuniu",
                observed_at=_observed_at(),
                source_ref="https://provider.example/place/1",
                items=(
                    PlaceResultItem(
                        entity_id="ticket-1",
                        name="West Lake ticket",
                        category="ticket",
                        source_ref="https://provider.example/place/1",
                    ),
                ),
            )
        ]
    )
    facade = knowledge.KnowledgeFacade(
        clock=clock,
        trace_id="trace-knowledge-1",
        timeout_seconds=Decimal("5"),
        stay_provider=stay,
        transport_provider=transport,
        place_provider=place,
        synchronous_runner=_run,
    )
    _install(monkeypatch, facade)

    hotel = knowledge.TOOL_EXECUTORS["tuniu_hotel_search"](
        "Hangzhou",
        "2026-08-10",
        "2026-08-12",
    )
    transport_result = knowledge.TOOL_EXECUTORS["tuniu_flight_search"](
        "Shanghai",
        "Hangzhou",
        "2026-08-10",
    )
    ticket = knowledge.TOOL_EXECUTORS["tuniu_ticket_search"]("West Lake", "Hangzhou")

    assert hotel["operation"] == "stay_search"
    assert hotel["items"] == [
        {
            "entity_id": "hotel-1",
            "name": "Lake Hotel",
            "area": "West Lake",
            "location": None,
            "check_in": None,
            "check_out": None,
            "total_price": None,
            "refundable": None,
            "source_ref": "https://provider.example/stay/1",
            "external_text_trust": "untrusted",
        }
    ]
    assert transport_result["operation"] == "transport_search"
    assert transport_result["items"][0]["name"] == "G123"
    assert ticket["operation"] == "place_search"
    assert ticket["items"][0]["category"] == "ticket"

    stay_query, stay_timeout = stay.calls[0]
    transport_query, transport_timeout = transport.calls[0]
    place_query, place_timeout = place.calls[0]
    assert stay_query.destination == "Hangzhou"
    assert stay_query.date_range.start == date(2026, 8, 10)
    assert stay_query.date_range.end == date(2026, 8, 12)
    assert transport_query.origin == "Shanghai"
    assert transport_query.destination == "Hangzhou"
    assert transport_query.departure_after == datetime(2026, 8, 10, tzinfo=UTC)
    assert place_query.destination == "West Lake"
    assert place_query.category == "ticket"
    assert (stay_timeout, transport_timeout, place_timeout) == (Decimal("5"),) * 3
    assert clock.calls == [_observed_at()] * 3


def test_tool_registry_remains_allowlisted() -> None:
    assert set(knowledge.TOOL_EXECUTORS) == knowledge.ALLOWED_TOOLS
    assert {item["function"]["name"] for item in knowledge.TOOLS} == knowledge.ALLOWED_TOOLS
