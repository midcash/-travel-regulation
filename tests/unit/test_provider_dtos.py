from __future__ import annotations

from datetime import UTC, date, datetime
from decimal import Decimal

import pytest
from pydantic import ValidationError

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
from src.domain.models.value_objects import DateRange, GeoPoint, Money


def _observed_at() -> datetime:
    return datetime(2026, 8, 1, 9, tzinfo=UTC)


def _date_range() -> DateRange:
    return DateRange(start=date(2026, 8, 1), end=date(2026, 8, 3))


def test_geo_query_and_result_are_frozen_typed_contracts() -> None:
    query = GeoQuery(
        query_id="geo-query-1",
        trace_id="trace-1",
        text="Hangzhou West Lake",
        constraint_refs=("constraint-1",),
    )
    result = GeoProviderResult(
        query_id=query.query_id,
        provider="amap",
        observed_at=_observed_at(),
        source_ref="https://provider.example/geo/1",
        items=(
            GeoResultItem(
                entity_id="geo-1",
                name="West Lake",
                location=GeoPoint(latitude=30.25, longitude=120.13),
                confidence=Decimal("0.95"),
            ),
        ),
    )

    assert query.timeout_seconds == Decimal("15")
    assert result.operation == "geo_search"
    with pytest.raises(ValidationError):
        GeoQuery(
            query_id="geo-query-2",
            trace_id="trace-1",
            text="Hangzhou",
            constraint_refs=("constraint-1", "constraint-1"),
        )
    with pytest.raises(ValidationError):
        GeoProviderResult(
            query_id=query.query_id,
            provider="amap",
            observed_at=_observed_at(),
            source_ref="https://provider.example/geo/1",
            items=(),
        )


def test_transport_query_and_result_validate_time_windows() -> None:
    query = TransportQuery(
        query_id="transport-query-1",
        trace_id="trace-1",
        origin="Shanghai",
        destination="Hangzhou",
        departure_after=datetime(2026, 8, 1, 8, tzinfo=UTC),
        arrival_before=datetime(2026, 8, 1, 12, tzinfo=UTC),
        travelers=2,
    )
    result = TransportProviderResult(
        query_id=query.query_id,
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
                departure_at=datetime(2026, 8, 1, 9, tzinfo=UTC),
                arrival_at=datetime(2026, 8, 1, 10, tzinfo=UTC),
                total_price=Money(amount=Decimal("120"), currency="CNY"),
                source_ref="https://provider.example/transport/1",
            ),
        ),
    )

    assert result.items[0].total_price == Money(amount=Decimal("120"), currency="CNY")
    with pytest.raises(ValidationError, match="timezone-aware"):
        TransportQuery(
            query_id="transport-query-2",
            trace_id="trace-1",
            origin="Shanghai",
            destination="Hangzhou",
            departure_after=datetime(2026, 8, 1, 8),
        )
    with pytest.raises(ValidationError, match="arrival_at"):
        TransportResultItem(
            entity_id="transport-2",
            mode="rail",
            name="G124",
            origin="Shanghai",
            destination="Hangzhou",
            departure_at=datetime(2026, 8, 1, 10, tzinfo=UTC),
            arrival_at=datetime(2026, 8, 1, 9, tzinfo=UTC),
            source_ref="https://provider.example/transport/2",
        )


def test_stay_query_and_result_validate_price_and_stay_window() -> None:
    query = StayQuery(
        query_id="stay-query-1",
        trace_id="trace-1",
        destination="Hangzhou",
        date_range=_date_range(),
        travelers=2,
        max_total_price=Money(amount=Decimal("1200"), currency="cny"),
    )
    result = StayProviderResult(
        query_id=query.query_id,
        provider="tuniu",
        observed_at=_observed_at(),
        source_ref="https://provider.example/stay/1",
        items=(
            StayResultItem(
                entity_id="stay-1",
                name="Lake Hotel",
                area="West Lake",
                check_in=datetime(2026, 8, 1, 15, tzinfo=UTC),
                check_out=datetime(2026, 8, 3, 11, tzinfo=UTC),
                total_price=Money(amount=Decimal("900"), currency="CNY"),
                source_ref="https://provider.example/stay/1",
            ),
        ),
    )

    assert query.max_total_price == Money(amount=Decimal("1200"), currency="CNY")
    assert result.items[0].area == "West Lake"
    with pytest.raises(ValidationError, match="check_out"):
        StayResultItem(
            entity_id="stay-2",
            name="Bad Hotel",
            area="West Lake",
            check_in=datetime(2026, 8, 3, 11, tzinfo=UTC),
            check_out=datetime(2026, 8, 3, 11, tzinfo=UTC),
            source_ref="https://provider.example/stay/2",
        )


def test_place_query_and_result_reject_provider_payload_leakage() -> None:
    query = PlaceQuery(
        query_id="place-query-1",
        trace_id="trace-1",
        destination="Hangzhou",
        category="scenic",
        date_range=_date_range(),
        center=GeoPoint(latitude=30.25, longitude=120.13),
        radius_meters=5000,
    )
    result = PlaceProviderResult(
        query_id=query.query_id,
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

    assert result.items[0].tags == ()
    with pytest.raises(ValidationError):
        PlaceProviderResult(
            query_id=query.query_id,
            provider="amap",
            observed_at=_observed_at(),
            source_ref="https://provider.example/place/1",
            items=(
                {
                    "entity_id": "place-raw",
                    "name": "Raw",
                    "category": "scenic",
                    "source_ref": "https://provider.example/place/raw",
                    "raw_payload": {"must_not": "leak"},
                },
            ),
        )


def test_context_query_and_result_validate_types_and_validity_window() -> None:
    query = ContextQuery(
        query_id="context-query-1",
        trace_id="trace-1",
        scope="trip-1",
        date_range=_date_range(),
        context_types=("weather", "policy"),
    )
    result = ContextProviderResult(
        query_id=query.query_id,
        provider="amap",
        observed_at=_observed_at(),
        source_ref="https://provider.example/context/1",
        items=(
            ContextResultItem(
                entity_id="context-1",
                context_type="weather",
                summary="Rain expected in the afternoon.",
                valid_from=datetime(2026, 8, 1, tzinfo=UTC),
                valid_until=datetime(2026, 8, 2, tzinfo=UTC),
                source_ref="https://provider.example/context/1",
            ),
        ),
    )

    assert result.operation == "context_search"
    with pytest.raises(ValidationError, match="unique"):
        ContextQuery(
            query_id="context-query-2",
            trace_id="trace-1",
            scope="trip-1",
            context_types=("weather", "weather"),
        )
    with pytest.raises(ValidationError, match="valid_until"):
        ContextResultItem(
            entity_id="context-2",
            context_type="weather",
            summary="Invalid window.",
            valid_from=datetime(2026, 8, 2, tzinfo=UTC),
            valid_until=datetime(2026, 8, 1, tzinfo=UTC),
            source_ref="https://provider.example/context/2",
        )


def test_provider_base_rejects_float_timeout_and_naive_observed_at() -> None:
    with pytest.raises(ValidationError, match="timeout_seconds"):
        GeoQuery(
            query_id="geo-query-float-timeout",
            trace_id="trace-1",
            text="Hangzhou",
            timeout_seconds=1.5,
        )
    with pytest.raises(ValidationError, match="observed_at"):
        GeoProviderResult(
            query_id="geo-query-1",
            provider="amap",
            observed_at=datetime(2026, 8, 1, 9),
            source_ref="https://provider.example/geo/1",
            items=(
                GeoResultItem(
                    entity_id="geo-1",
                    name="West Lake",
                    location=GeoPoint(latitude=30.25, longitude=120.13),
                    confidence=Decimal("0.95"),
                ),
            ),
        )
