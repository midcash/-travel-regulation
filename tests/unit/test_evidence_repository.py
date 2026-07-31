"""M3 EvidenceRepository and InMemory Registry tests."""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal

import pytest

from src.domain.models.enums import EvidenceStatus
from src.domain.models.evidence import EvidenceRegistration
from src.domain.models.value_objects import Money
from src.infrastructure.evidence.in_memory import InMemoryEvidenceRepository
from src.ports.evidence_repository import EvidenceRepository


def _registration(**overrides: object) -> EvidenceRegistration:
    values: dict[str, object] = {
        "entity_id": "hotel-1",
        "fact_type": "total_price",
        "value": Money(amount=Decimal("680"), currency="CNY"),
        "provider": "tuniu",
        "source": "hotel_mcp",
        "source_ref": "https://example.test/hotels/1",
        "observed_at": datetime(2026, 8, 1, 9, tzinfo=UTC),
        "valid_until": datetime(2026, 8, 1, 10, tzinfo=UTC),
        "status": EvidenceStatus.VERIFIED,
        "confidence": Decimal("0.9"),
        "raw_payload_ref": "payload:hotel-1",
        "query_fingerprint": "query:hangzhou-hotel",
    }
    values.update(overrides)
    return EvidenceRegistration(**values)


def test_in_memory_evidence_repository_implements_port_and_isolates_results() -> None:
    repository = InMemoryEvidenceRepository()
    assert isinstance(repository, EvidenceRepository)

    registered = repository.register(_registration())
    found = repository.find(entity_id="hotel-1")

    assert found == (registered,)
    assert found[0] is not registered
    assert registered.evidence_id.startswith("evidence:")


def test_in_memory_evidence_repository_registration_is_idempotent_and_stable() -> None:
    first_repository = InMemoryEvidenceRepository()
    second_repository = InMemoryEvidenceRepository()
    registration = _registration()

    first = first_repository.register(registration)
    repeated = first_repository.register(registration)
    second = second_repository.register(registration)

    assert first == repeated == second
    assert len(first_repository.find()) == 1


def test_in_memory_evidence_repository_filters_by_entity_fact_and_query() -> None:
    repository = InMemoryEvidenceRepository()
    price = repository.register(_registration())
    availability = repository.register(
        _registration(
            fact_type="availability",
            value=True,
            query_fingerprint="query:hangzhou-hotel-availability",
        )
    )
    other_entity = repository.register(
        _registration(
            entity_id="hotel-2",
            source_ref="https://example.test/hotels/2",
        )
    )

    assert repository.find(entity_id="hotel-1", fact_type="total_price") == (price,)
    assert repository.find(query_fingerprint="query:hangzhou-hotel-availability") == (
        availability,
    )
    assert repository.find(entity_id="hotel-2") == (other_entity,)
    assert repository.find(entity_id="hotel-missing") == ()


def test_in_memory_evidence_repository_preserves_conflicting_sources() -> None:
    repository = InMemoryEvidenceRepository()
    first = repository.register(_registration())
    conflict = repository.register(
        _registration(
            provider="amap",
            source="price_partner",
            source_ref="https://example.test/partner/hotels/1",
            value=Money(amount=Decimal("720"), currency="CNY"),
            observed_at=datetime(2026, 8, 1, 9, 5, tzinfo=UTC),
            valid_until=datetime(2026, 8, 1, 10, 5, tzinfo=UTC),
        )
    )

    assert repository.find(
        entity_id="hotel-1",
        fact_type="total_price",
        query_fingerprint="query:hangzhou-hotel",
    ) == (first, conflict)


def test_in_memory_evidence_repository_rejects_untyped_registration() -> None:
    repository = InMemoryEvidenceRepository()

    with pytest.raises(TypeError, match="EvidenceRegistration"):
        repository.register(object())  # type: ignore[arg-type]


def test_evidence_registration_rejects_invalid_time_window_before_storage() -> None:
    with pytest.raises(ValueError, match="valid_until"):
        _registration(valid_until=datetime(2026, 8, 1, 8, tzinfo=UTC))
    with pytest.raises(ValueError, match="timezone-aware"):
        _registration(observed_at=datetime(2026, 8, 1, 9))
