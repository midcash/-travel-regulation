"""Provider query and result DTO contracts for M3."""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Literal, Self

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from src.domain.models.value_objects import (
    ConstraintId,
    DateRange,
    GeoPoint,
    Money,
    StableId,
    TraceId,
)

_PROVIDER_SCHEMA_VERSION = "m3.provider.v1"


class ProviderQueryBase(BaseModel):
    """Fields shared by all provider query DTOs."""

    model_config = ConfigDict(extra="forbid", frozen=True, str_strip_whitespace=True)

    query_id: StableId
    trace_id: TraceId
    locale: str = Field(default="zh-CN", min_length=2, max_length=16)
    timeout_seconds: Decimal = Field(default=Decimal("15"), gt=Decimal("0"))
    constraint_refs: tuple[ConstraintId, ...] = ()

    @field_validator("timeout_seconds", mode="before")
    @classmethod
    def reject_float_timeout(cls, value: object) -> object:
        """Avoid binary float drift in timeout budgets."""
        if isinstance(value, float):
            raise ValueError("timeout_seconds must be Decimal, int, or decimal string")
        return value

    @field_validator("constraint_refs")
    @classmethod
    def validate_constraint_refs(cls, values: tuple[ConstraintId, ...]) -> tuple[ConstraintId, ...]:
        """Constraint references must be stable and unique."""
        if len(values) != len(set(values)):
            raise ValueError("constraint_refs must be unique")
        return values


class ProviderResultBase(BaseModel):
    """Fields shared by all successful provider result DTOs."""

    model_config = ConfigDict(extra="forbid", frozen=True, str_strip_whitespace=True)

    query_id: StableId
    provider: str = Field(min_length=1, max_length=64)
    operation: str = Field(min_length=1, max_length=64)
    observed_at: datetime
    source_ref: str = Field(min_length=1, max_length=2048)
    raw_payload_ref: StableId | None = None
    schema_version: str = Field(default=_PROVIDER_SCHEMA_VERSION, min_length=1, max_length=64)

    @field_validator("observed_at")
    @classmethod
    def validate_observed_at_timezone(cls, value: datetime) -> datetime:
        """Provider observations must carry timezone information."""
        if value.tzinfo is None:
            raise ValueError("observed_at must be timezone-aware")
        return value


class GeoQuery(ProviderQueryBase):
    """Geocoding or location search query."""

    text: str = Field(min_length=1, max_length=256)
    region: str | None = Field(default=None, min_length=1, max_length=128)


class GeoResultItem(BaseModel):
    """Single normalized geographic entity returned by a provider."""

    model_config = ConfigDict(extra="forbid", frozen=True, str_strip_whitespace=True)

    entity_id: StableId
    name: str = Field(min_length=1, max_length=256)
    location: GeoPoint
    address: str | None = Field(default=None, min_length=1, max_length=512)
    confidence: Decimal = Field(ge=Decimal("0"), le=Decimal("1"))
    external_text_trust: Literal["untrusted"] = "untrusted"


class GeoProviderResult(ProviderResultBase):
    """Successful geographic provider result."""

    operation: str = "geo_search"
    items: tuple[GeoResultItem, ...] = Field(min_length=1)


class TransportQuery(ProviderQueryBase):
    """Transport option search query."""

    origin: str = Field(min_length=1, max_length=256)
    destination: str = Field(min_length=1, max_length=256)
    departure_after: datetime | None = None
    arrival_before: datetime | None = None
    travelers: int = Field(default=1, ge=1, le=20)
    max_results: int = Field(default=20, ge=1, le=100)

    @model_validator(mode="after")
    def validate_time_window(self) -> Self:
        """Transport query time bounds must be timezone-aware and ordered."""
        for value in (self.departure_after, self.arrival_before):
            if value is not None and value.tzinfo is None:
                raise ValueError("transport time bounds must be timezone-aware")
        if (
            self.departure_after is not None
            and self.arrival_before is not None
            and self.arrival_before < self.departure_after
        ):
            raise ValueError("arrival_before must not be earlier than departure_after")
        return self


class TransportResultItem(BaseModel):
    """Single normalized transport option returned by a provider."""

    model_config = ConfigDict(extra="forbid", frozen=True, str_strip_whitespace=True)

    entity_id: StableId
    mode: str = Field(min_length=1, max_length=64)
    name: str = Field(min_length=1, max_length=256)
    origin: str = Field(min_length=1, max_length=256)
    destination: str = Field(min_length=1, max_length=256)
    departure_at: datetime | None = None
    arrival_at: datetime | None = None
    total_price: Money | None = None
    source_ref: str = Field(min_length=1, max_length=2048)

    @model_validator(mode="after")
    def validate_schedule(self) -> Self:
        """Transport result schedule must be timezone-aware and ordered."""
        for value in (self.departure_at, self.arrival_at):
            if value is not None and value.tzinfo is None:
                raise ValueError("transport result times must be timezone-aware")
        if (
            self.departure_at is not None
            and self.arrival_at is not None
            and self.arrival_at < self.departure_at
        ):
            raise ValueError("arrival_at must not be earlier than departure_at")
        return self


class TransportProviderResult(ProviderResultBase):
    """Successful transport provider result."""

    operation: str = "transport_search"
    items: tuple[TransportResultItem, ...] = Field(min_length=1)


class StayQuery(ProviderQueryBase):
    """Stay or hotel availability query."""

    destination: str = Field(min_length=1, max_length=256)
    date_range: DateRange
    travelers: int = Field(default=1, ge=1, le=20)
    area: str | None = Field(default=None, min_length=1, max_length=256)
    max_total_price: Money | None = None
    max_results: int = Field(default=20, ge=1, le=100)


class StayResultItem(BaseModel):
    """Single normalized stay option returned by a provider."""

    model_config = ConfigDict(extra="forbid", frozen=True, str_strip_whitespace=True)

    entity_id: StableId
    name: str = Field(min_length=1, max_length=256)
    area: str = Field(min_length=1, max_length=256)
    location: GeoPoint | None = None
    check_in: datetime | None = None
    check_out: datetime | None = None
    total_price: Money | None = None
    refundable: bool | None = None
    source_ref: str = Field(min_length=1, max_length=2048)

    @model_validator(mode="after")
    def validate_stay_window(self) -> Self:
        """Stay result dates must be timezone-aware and ordered."""
        for value in (self.check_in, self.check_out):
            if value is not None and value.tzinfo is None:
                raise ValueError("stay result times must be timezone-aware")
        if (
            self.check_in is not None
            and self.check_out is not None
            and self.check_out <= self.check_in
        ):
            raise ValueError("check_out must be later than check_in")
        return self


class StayProviderResult(ProviderResultBase):
    """Successful stay provider result."""

    operation: str = "stay_search"
    items: tuple[StayResultItem, ...] = Field(min_length=1)


class PlaceQuery(ProviderQueryBase):
    """Place, POI, restaurant, ticket, or activity search query."""

    destination: str = Field(min_length=1, max_length=256)
    category: str = Field(min_length=1, max_length=64)
    date_range: DateRange | None = None
    center: GeoPoint | None = None
    radius_meters: int | None = Field(default=None, ge=1, le=50000)
    max_results: int = Field(default=20, ge=1, le=100)


class PlaceResultItem(BaseModel):
    """Single normalized place option returned by a provider."""

    model_config = ConfigDict(extra="forbid", frozen=True, str_strip_whitespace=True)

    entity_id: StableId
    name: str = Field(min_length=1, max_length=256)
    category: str = Field(min_length=1, max_length=64)
    location: GeoPoint | None = None
    address: str | None = Field(default=None, min_length=1, max_length=512)
    tags: tuple[str, ...] = ()
    source_ref: str = Field(min_length=1, max_length=2048)


class PlaceProviderResult(ProviderResultBase):
    """Successful place provider result."""

    operation: str = "place_search"
    items: tuple[PlaceResultItem, ...] = Field(min_length=1)


class ContextQuery(ProviderQueryBase):
    """Context query for weather, events, policies, or safety notes."""

    scope: StableId
    date_range: DateRange | None = None
    context_types: tuple[str, ...] = Field(min_length=1)

    @field_validator("context_types")
    @classmethod
    def validate_context_types(cls, values: tuple[str, ...]) -> tuple[str, ...]:
        """Context types must be non-empty and unique."""
        if any(not value for value in values):
            raise ValueError("context_types must not contain empty values")
        if len(values) != len(set(values)):
            raise ValueError("context_types must be unique")
        return values


class ContextResultItem(BaseModel):
    """Single normalized context fact returned by a provider."""

    model_config = ConfigDict(extra="forbid", frozen=True, str_strip_whitespace=True)

    entity_id: StableId
    context_type: str = Field(min_length=1, max_length=64)
    summary: str = Field(min_length=1, max_length=1024)
    valid_from: datetime | None = None
    valid_until: datetime | None = None
    severity: str | None = Field(default=None, min_length=1, max_length=64)
    source_ref: str = Field(min_length=1, max_length=2048)

    @model_validator(mode="after")
    def validate_validity_window(self) -> Self:
        """Context validity windows must be timezone-aware and ordered."""
        for value in (self.valid_from, self.valid_until):
            if value is not None and value.tzinfo is None:
                raise ValueError("context validity times must be timezone-aware")
        if (
            self.valid_from is not None
            and self.valid_until is not None
            and self.valid_until < self.valid_from
        ):
            raise ValueError("valid_until must not be earlier than valid_from")
        return self


class ContextProviderResult(ProviderResultBase):
    """Successful context provider result."""

    operation: str = "context_search"
    items: tuple[ContextResultItem, ...] = Field(min_length=1)
