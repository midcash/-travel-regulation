from __future__ import annotations

from decimal import Decimal

import pytest
from pydantic import TypeAdapter, ValidationError

from src.domain.models.candidates import (
    Candidate,
    ContextCandidate,
    PlaceCandidate,
    StayCandidate,
    TransportCandidate,
)
from src.domain.models.value_objects import Money


def test_candidate_union_selects_each_discriminator_variant() -> None:
    adapter = TypeAdapter(Candidate)

    transport = adapter.validate_python(
        {
            "kind": "transport",
            "candidate_id": "transport-1",
            "name": "高铁",
            "evidence_refs": ["evidence-1"],
            "mode": "rail",
            "origin": "上海",
            "destination": "杭州",
        }
    )
    stay = StayCandidate(
        candidate_id="stay-1",
        name="西湖酒店",
        area="西湖",
        total_price=Money(amount=Decimal("800"), currency="CNY"),
    )
    place = PlaceCandidate(candidate_id="place-1", name="西湖", category="scenic")
    context = ContextCandidate(
        candidate_id="context-1", name="展会影响", context_type="event", scope="trip-1"
    )

    assert isinstance(transport, TransportCandidate)
    assert isinstance(adapter.validate_python(stay.model_dump()), StayCandidate)
    assert isinstance(adapter.validate_python(place.model_dump()), PlaceCandidate)
    assert isinstance(adapter.validate_python(context.model_dump()), ContextCandidate)


def test_candidate_union_rejects_unknown_kind_and_unknown_fields() -> None:
    adapter = TypeAdapter(Candidate)

    with pytest.raises(ValidationError):
        adapter.validate_python({"kind": "flight", "candidate_id": "candidate-1", "name": "x"})
    with pytest.raises(ValidationError):
        adapter.validate_python(
            {
                "kind": "place",
                "candidate_id": "place-1",
                "name": "景点",
                "category": "scenic",
                "raw_response": {"unsafe": True},
            }
        )


def test_transport_candidate_defaults_to_transport_discriminator() -> None:
    transport = TransportCandidate(
        candidate_id="transport-1",
        name="高铁",
        mode="rail",
        origin="上海",
        destination="杭州",
    )

    assert transport.kind == "transport"
