from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest
from pydantic import ValidationError

from src.domain.models.enums import EvidenceStatus
from src.domain.models.evidence import EvidenceItem, EvidenceRegistration, EvidenceSnapshot
from src.domain.models.value_objects import DateRange, Money


def _evidence(evidence_id: str = "evidence-1", **overrides: object) -> EvidenceItem:
    values: dict[str, object] = {
        "evidence_id": evidence_id,
        "entity_id": "candidate-1",
        "fact_type": "price",
        "value": Money(amount=Decimal("120"), currency="CNY"),
        "provider": "tuniu",
        "source": "supplier",
        "source_ref": "https://example.test/items/1",
        "observed_at": datetime(2026, 8, 1, 9, tzinfo=UTC),
        "valid_until": datetime(2026, 8, 2, 9, tzinfo=UTC),
        "status": EvidenceStatus.VERIFIED,
        "confidence": Decimal("0.95"),
        "raw_payload_ref": "raw-payload-1",
        "query_fingerprint": "query:hotel-1",
    }
    values.update(overrides)
    return EvidenceItem(**values)


def test_evidence_item_accepts_typed_value_and_round_trips() -> None:
    item = _evidence(constraint_refs=("constraint-1",))

    assert item.value == Money(amount=Decimal("120"), currency="CNY")
    assert EvidenceItem.model_validate_json(item.model_dump_json()) == item


def test_evidence_item_rejects_raw_response_and_invalid_validity_window() -> None:
    with pytest.raises(ValidationError):
        _evidence(value={"raw_supplier_response": "must not cross contract"})
    with pytest.raises(ValidationError, match="valid_until"):
        _evidence(valid_until=datetime(2026, 8, 1, 8, tzinfo=UTC))
    with pytest.raises(ValidationError):
        _evidence(constraint_refs=("constraint-1", "constraint-1"))
    with pytest.raises(ValidationError, match="timezone-aware"):
        _evidence(observed_at=datetime(2026, 8, 1, 9))


def test_evidence_registration_requires_traceable_provider_query_and_schema_fields() -> None:
    item = _evidence()
    registration = EvidenceRegistration(**item.model_dump(exclude={"evidence_id"}))

    registered = registration.to_item("evidence-generated-1")

    assert registered.evidence_id == "evidence-generated-1"
    assert registered.provider == "tuniu"
    assert registered.query_fingerprint == "query:hotel-1"
    assert registered.raw_payload_ref == "raw-payload-1"
    assert registered.schema_version == "m3.evidence.v1"
    with pytest.raises(ValidationError):
        EvidenceRegistration(**registration.model_dump(), raw_payload={"unsafe": True})


def test_evidence_snapshot_rejects_unknown_conflict_references() -> None:
    evidence = _evidence()
    snapshot = EvidenceSnapshot(
        snapshot_id="evidence-snapshot-1",
        created_at=evidence.observed_at + timedelta(minutes=1),
        evidence_items=(evidence,),
        coverage=Decimal("1"),
        freshness=Decimal("0.9"),
        conflict_refs=(evidence.evidence_id,),
    )

    assert snapshot.conflict_refs == ("evidence-1",)
    with pytest.raises(ValidationError, match="must reference"):
        EvidenceSnapshot(
            snapshot_id="evidence-snapshot-2",
            created_at=evidence.observed_at,
            evidence_items=(evidence,),
            conflict_refs=("evidence-unknown",),
        )


def test_evidence_value_union_accepts_date_range() -> None:
    item = _evidence(
        fact_type="travel_window",
        value=DateRange(start=datetime(2026, 8, 1).date(), end=datetime(2026, 8, 3).date()),
    )

    assert item.fact_type == "travel_window"
