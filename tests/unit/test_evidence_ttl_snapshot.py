"""M3 Evidence Registry TTL 与快照语义测试。"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest
from pydantic import ValidationError

from src.domain.models.enums import EvidenceStatus, EvidenceTtlCategory
from src.domain.models.evidence import (
    EvidenceRegistration,
    EvidenceSnapshotQuery,
    EvidenceTtlPolicy,
)
from src.domain.models.value_objects import Money
from src.infrastructure.evidence.in_memory import InMemoryEvidenceRepository
from src.ports.evidence_repository import EvidenceRepository
from tests.support.clock_fakes import FakeClock


def _policy() -> EvidenceTtlPolicy:
    return EvidenceTtlPolicy(
        static_geography=timedelta(days=30),
        business_hours_policy=timedelta(hours=12),
        weather_forecast=timedelta(hours=2),
        transport_schedule=timedelta(minutes=15),
        quote_inventory=timedelta(minutes=5),
        exchange_rate=timedelta(hours=1),
    )


def _registration(**overrides: object) -> EvidenceRegistration:
    values: dict[str, object] = {
        "entity_id": "hotel-1",
        "fact_type": "total_price",
        "value": Money(amount=Decimal("680"), currency="CNY"),
        "provider": "tuniu",
        "source": "hotel_mcp",
        "source_ref": "https://example.test/hotels/1",
        "observed_at": datetime(2026, 8, 1, 9, tzinfo=UTC),
        "valid_until": None,
        "ttl_category": EvidenceTtlCategory.QUOTE_INVENTORY,
        "status": EvidenceStatus.VERIFIED,
        "confidence": Decimal("0.9"),
        "raw_payload_ref": "payload:hotel-1",
        "query_fingerprint": "query:hangzhou-hotel",
    }
    values.update(overrides)
    return EvidenceRegistration(**values)


def _repository(clock: FakeClock) -> InMemoryEvidenceRepository:
    return InMemoryEvidenceRepository(clock=clock, ttl_policy=_policy())


def test_repository_resolves_ttl_without_extending_supplier_expiry() -> None:
    clock = FakeClock(datetime(2026, 8, 1, 9, tzinfo=UTC))
    repository = _repository(clock)

    policy_limited = repository.register(_registration())
    supplier_limited = repository.register(
        _registration(
            source_ref="https://example.test/hotels/2",
            valid_until=datetime(2026, 8, 1, 9, 3, tzinfo=UTC),
        )
    )

    assert policy_limited.valid_until == datetime(2026, 8, 1, 9, 5, tzinfo=UTC)
    assert supplier_limited.valid_until == datetime(2026, 8, 1, 9, 3, tzinfo=UTC)
    assert clock.calls == []


def test_snapshot_marks_evidence_stale_at_exact_ttl_boundary() -> None:
    clock = FakeClock(datetime(2026, 8, 1, 9, tzinfo=UTC))
    repository = _repository(clock)
    repository.register(_registration())
    query = EvidenceSnapshotQuery(required_fact_types=("total_price",))

    before_expiry = repository.snapshot(query)
    clock.advance(timedelta(minutes=5))
    at_expiry = repository.snapshot(query)

    assert isinstance(repository, EvidenceRepository)
    assert before_expiry.evidence_items[0].status is EvidenceStatus.VERIFIED
    assert before_expiry.coverage == Decimal("1")
    assert before_expiry.freshness == Decimal("1")
    assert at_expiry.evidence_items[0].status is EvidenceStatus.STALE
    assert at_expiry.coverage == Decimal("0")
    assert at_expiry.freshness == Decimal("0")
    assert at_expiry.snapshot_id != before_expiry.snapshot_id


def test_snapshot_marks_conflicting_fresh_sources_and_preserves_all_references() -> None:
    clock = FakeClock(datetime(2026, 8, 1, 9, tzinfo=UTC))
    repository = _repository(clock)
    first = repository.register(_registration())
    second = repository.register(
        _registration(
            provider="amap",
            source="price_partner",
            source_ref="https://example.test/partner/hotels/1",
            value=Money(amount=Decimal("720"), currency="CNY"),
        )
    )

    snapshot = repository.snapshot(
        EvidenceSnapshotQuery(required_fact_types=("total_price",))
    )

    assert tuple(item.status for item in snapshot.evidence_items) == (
        EvidenceStatus.CONFLICTING,
        EvidenceStatus.CONFLICTING,
    )
    assert snapshot.conflict_refs == (first.evidence_id, second.evidence_id)
    assert snapshot.coverage == Decimal("0")
    assert snapshot.freshness == Decimal("1")


def test_snapshot_does_not_treat_stale_source_as_current_conflict() -> None:
    clock = FakeClock(datetime(2026, 8, 1, 9, 10, tzinfo=UTC))
    repository = _repository(clock)
    repository.register(
        _registration(
            value=Money(amount=Decimal("680"), currency="CNY"),
            observed_at=datetime(2026, 8, 1, 9, tzinfo=UTC),
        )
    )
    current = repository.register(
        _registration(
            source_ref="https://example.test/hotels/current",
            value=Money(amount=Decimal("720"), currency="CNY"),
            observed_at=datetime(2026, 8, 1, 9, 10, tzinfo=UTC),
        )
    )

    snapshot = repository.snapshot(EvidenceSnapshotQuery())

    assert tuple(item.status for item in snapshot.evidence_items) == (
        EvidenceStatus.STALE,
        EvidenceStatus.VERIFIED,
    )
    assert snapshot.conflict_refs == ()
    assert snapshot.evidence_items[1].evidence_id == current.evidence_id


def test_snapshot_reports_missing_requirements_and_stable_content_id() -> None:
    clock = FakeClock(datetime(2026, 8, 1, 9, tzinfo=UTC))
    repository = _repository(clock)
    repository.register(_registration())
    query = EvidenceSnapshotQuery(
        entity_id="hotel-1",
        required_fact_types=("total_price", "availability"),
    )

    first = repository.snapshot(query)
    repeated = repository.snapshot(query)

    assert first.snapshot_id == repeated.snapshot_id
    assert first.coverage == Decimal("0.5")
    assert first.missing_fact_types == ("availability",)
    with pytest.raises(ValidationError):
        first.coverage = Decimal("0")  # type: ignore[misc]


def test_snapshot_rejects_untyped_query_and_naive_clock_time() -> None:
    repository = _repository(FakeClock(datetime(2026, 8, 1, 9, tzinfo=UTC)))

    with pytest.raises(TypeError, match="EvidenceSnapshotQuery"):
        repository.snapshot(object())  # type: ignore[arg-type]

    class NaiveClock:
        def now(self) -> datetime:
            return datetime(2026, 8, 1, 9)

    naive_repository = InMemoryEvidenceRepository(clock=NaiveClock(), ttl_policy=_policy())
    with pytest.raises(ValueError, match="timezone-aware"):
        naive_repository.snapshot(EvidenceSnapshotQuery())
