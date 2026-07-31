from __future__ import annotations

from decimal import Decimal

import pytest
from pydantic import TypeAdapter, ValidationError

from src.domain.models.candidates import (
    Candidate,
    CandidatePrice,
    CandidateProvenance,
    CandidateRating,
    ContextCandidate,
    PlaceCandidate,
    StayCandidate,
    TransportCandidate,
)
from src.domain.models.value_objects import Money


def _provenance(entity_id: str = "entity-1") -> CandidateProvenance:
    return CandidateProvenance(
        provider="provider-a",
        entity_id=entity_id,
        source_ref=f"https://provider.example/items/{entity_id}",
    )


def _common(
    candidate_id: str = "candidate-1",
    entity_id: str = "entity-1",
    *,
    name: str = "West Lake",
    timezone: str = "Asia/Shanghai",
) -> dict[str, object]:
    return {
        "candidate_id": candidate_id,
        "name": name,
        "evidence_refs": ("evidence-1",),
        "provenance": (_provenance(entity_id),),
        "timezone": timezone,
    }


def test_candidate_union_selects_each_discriminator_variant() -> None:
    adapter = TypeAdapter(Candidate)

    transport = adapter.validate_python(
        {
            "kind": "transport",
                **_common("transport-1", "transport-entity-1", name="High-speed rail"),
            "mode": "rail",
            "origin": "Shanghai",
            "destination": "Hangzhou",
        }
    )
    stay = StayCandidate(
        **_common("stay-1", "stay-entity-1", name="West Lake Hotel"),
        area="West Lake",
        price=CandidatePrice(
            total=Money(amount=Decimal("800"), currency="CNY"),
            inclusions=("breakfast",),
            evidence_refs=("evidence-1",),
        ),
    )
    place = PlaceCandidate(
        **_common("place-1", "place-entity-1"), category="scenic"
    )
    context = ContextCandidate(
        **_common("context-1", "context-entity-1", name="Event impact"),
        context_type="event",
        scope="trip-1",
    )

    assert isinstance(transport, TransportCandidate)
    assert isinstance(adapter.validate_python(stay.model_dump()), StayCandidate)
    assert isinstance(adapter.validate_python(place.model_dump()), PlaceCandidate)
    assert isinstance(adapter.validate_python(context.model_dump()), ContextCandidate)


def test_candidate_contract_requires_traceable_evidence_and_normalized_metadata() -> None:
    with pytest.raises(ValidationError):
        PlaceCandidate(candidate_id="place-1", name="West Lake", category="scenic")
    with pytest.raises(ValidationError, match="IANA timezone"):
        PlaceCandidate(
            **_common(timezone="China Standard Time"), category="scenic"
        )
    with pytest.raises(ValidationError, match="must belong to candidate"):
        StayCandidate(
            **_common(),
            area="West Lake",
            price=CandidatePrice(
                total=Money(amount=Decimal("800"), currency="CNY"),
                evidence_refs=("evidence-other",),
            ),
        )


def test_candidate_rating_preserves_source_scale_and_rejects_invalid_values() -> None:
    rating = CandidateRating(
        value=Decimal("4.6"),
        scale=Decimal("5"),
        source="provider-a",
        evidence_refs=("evidence-1",),
    )

    assert rating.source == "provider-a"
    assert rating.scale == Decimal("5")
    with pytest.raises(ValidationError, match="must not be float"):
        CandidateRating(
            value=4.6,
            scale=Decimal("5"),
            source="provider-a",
            evidence_refs=("evidence-1",),
        )
    with pytest.raises(ValidationError, match="must not exceed"):
        CandidateRating(
            value=Decimal("6"),
            scale=Decimal("5"),
            source="provider-a",
            evidence_refs=("evidence-1",),
        )


def test_candidate_union_rejects_unknown_kind_and_unknown_fields() -> None:
    adapter = TypeAdapter(Candidate)

    with pytest.raises(ValidationError):
        adapter.validate_python(
            {"kind": "flight", **_common(), "name": "Unknown"}
        )
    with pytest.raises(ValidationError):
        adapter.validate_python(
            {
                "kind": "place",
                **_common("place-1", "place-entity-1"),
                "category": "scenic",
                "raw_response": {"unsafe": True},
            }
        )


def test_transport_candidate_defaults_to_transport_discriminator() -> None:
    transport = TransportCandidate(
        **_common("transport-1", "transport-entity-1", name="High-speed rail"),
        mode="rail",
        origin="Shanghai",
        destination="Hangzhou",
    )

    assert transport.kind == "transport"
