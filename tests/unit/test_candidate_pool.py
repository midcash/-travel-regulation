"""M3 Candidate Normalizer 与 Candidate Pool 行为测试。"""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta, timezone
from decimal import Decimal

import pytest

from src.domain.models.candidates import (
    CandidatePrice,
    CandidateProvenance,
    CandidateRating,
    ContextCandidate,
    PlaceCandidate,
    StayCandidate,
    TransportCandidate,
)
from src.domain.models.constraint import Constraint, ConstraintSnapshot, ConstraintSource
from src.domain.models.enums import (
    CandidateRejectCode,
    ConstraintHardness,
    EvidenceStatus,
    EvidenceTtlCategory,
)
from src.domain.models.evidence import EvidenceItem, EvidenceSnapshot
from src.domain.models.value_objects import DateRange, Money
from src.domain.services.candidate_pool import CandidateNormalizer, CandidatePool


def _evidence(
    evidence_id: str,
    *,
    status: EvidenceStatus = EvidenceStatus.VERIFIED,
) -> EvidenceItem:
    return EvidenceItem(
        evidence_id=evidence_id,
        entity_id="entity-1",
        fact_type="candidate_fact",
        value="verified candidate fact",
        provider="provider-a",
        source="supplier",
        source_ref=f"https://provider.example/evidence/{evidence_id}",
        observed_at=datetime(2026, 8, 1, 9, tzinfo=UTC),
        valid_until=datetime(2026, 8, 2, 9, tzinfo=UTC),
        ttl_category=EvidenceTtlCategory.STATIC_GEOGRAPHY,
        status=status,
        confidence=Decimal("0.9"),
        query_fingerprint="query-candidate-1",
    )


def _evidence_snapshot(*items: EvidenceItem) -> EvidenceSnapshot:
    return EvidenceSnapshot(
        snapshot_id="evidence-snapshot-candidate-1",
        created_at=datetime(2026, 8, 1, 10, tzinfo=UTC),
        evidence_items=items,
    )


def _constraint(
    constraint_id: str,
    category: str,
    normalized_value: object,
) -> Constraint:
    return Constraint(
        id=constraint_id,
        category=category,
        normalized_value=normalized_value,
        hardness=ConstraintHardness.HARD,
        priority=100,
        scope="trip",
        source=ConstraintSource.USER,
        confidence=Decimal("1"),
    )


def _constraints(*constraints: Constraint) -> ConstraintSnapshot:
    return ConstraintSnapshot(
        version=1,
        created_at=datetime(2026, 8, 1, 8, tzinfo=UTC),
        request_id="request-candidate-1",
        constraints=constraints,
    )


def _provenance(provider: str, entity_id: str) -> CandidateProvenance:
    return CandidateProvenance(
        provider=provider,
        entity_id=entity_id,
        source_ref=f"https://{provider}.example/items/{entity_id}",
    )


def _place(
    candidate_id: str,
    evidence_refs: tuple[str, ...],
    provenance: CandidateProvenance,
    *,
    tags: tuple[str, ...] = (),
) -> PlaceCandidate:
    return PlaceCandidate(
        candidate_id=candidate_id,
        name="West Lake",
        evidence_refs=evidence_refs,
        provenance=(provenance,),
        timezone="Asia/Shanghai",
        tags=tags,
        category="scenic",
    )


def test_normalizer_assigns_stable_id_and_converts_times_to_candidate_timezone() -> None:
    candidate = TransportCandidate(
        candidate_id="supplier-transport-1",
        name="G123",
        evidence_refs=("evidence-1",),
        provenance=(_provenance("provider-a", "transport-1"),),
        timezone="Asia/Shanghai",
        mode="rail",
        origin="Shanghai",
        destination="Hangzhou",
        departure_at=datetime(2026, 8, 1, 9, tzinfo=timezone(timedelta(hours=8))),
        arrival_at=datetime(2026, 8, 1, 10, tzinfo=timezone(timedelta(hours=8))),
        price=CandidatePrice(
            total=Money(amount=Decimal("120"), currency="CNY"),
            inclusions=("Seat", "seat"),
            evidence_refs=("evidence-1",),
        ),
    )

    normalized = CandidateNormalizer().normalize(candidate)

    assert normalized.candidate_id.startswith("candidate:transport:")
    assert isinstance(normalized, TransportCandidate)
    assert normalized.departure_at == datetime(2026, 8, 1, 1, tzinfo=UTC)
    assert normalized.departure_at.tzinfo is not None
    assert normalized.timezone == "UTC"
    assert normalized.price is not None
    assert normalized.price.inclusions == ("seat",)


def test_pool_deduplicates_equivalent_candidates_and_preserves_all_provenance() -> None:
    first = _place(
        "supplier-a-1",
        ("evidence-1",),
        _provenance("provider-a", "place-1"),
        tags=("Scenic",),
    ).model_copy(
        update={
            "price": CandidatePrice(
                total=Money(amount=Decimal("20"), currency="CNY"),
                evidence_refs=("evidence-1",),
            ),
            "rating": CandidateRating(
                value=Decimal("4.8"),
                scale=Decimal("5"),
                source="provider-rating",
                evidence_refs=("evidence-1",),
            ),
        }
    )
    second = _place(
        "supplier-b-1",
        ("evidence-2",),
        _provenance("provider-b", "place-9"),
        tags=("scenic",),
    ).model_copy(
        update={
            "price": CandidatePrice(
                total=Money(amount=Decimal("20"), currency="CNY"),
                evidence_refs=("evidence-2",),
            ),
            "rating": CandidateRating(
                value=Decimal("4.8"),
                scale=Decimal("5"),
                source="provider-rating",
                evidence_refs=("evidence-2",),
            ),
        }
    )

    result = CandidatePool().build(
        (second, first),
        evidence_snapshot=_evidence_snapshot(_evidence("evidence-1"), _evidence("evidence-2")),
        constraint_snapshot=_constraints(),
    )

    assert len(result.candidates) == 1
    merged = result.candidates[0]
    assert merged.evidence_refs == ("evidence-1", "evidence-2")
    assert tuple(item.provider for item in merged.provenance) == ("provider-a", "provider-b")
    assert merged.price is not None
    assert merged.price.evidence_refs == ("evidence-1", "evidence-2")
    assert merged.rating is not None
    assert merged.rating.evidence_refs == ("evidence-1", "evidence-2")
    assert result.rejected == ()


def test_pool_rejects_missing_or_non_verified_evidence_with_explicit_reasons() -> None:
    stale_candidate = _place(
        "supplier-a-1", ("evidence-stale",), _provenance("provider-a", "place-1")
    )
    absent_candidate = _place(
        "supplier-b-1", ("evidence-absent",), _provenance("provider-b", "place-2")
    )

    result = CandidatePool().build(
        (stale_candidate, absent_candidate),
        evidence_snapshot=_evidence_snapshot(
            _evidence("evidence-stale", status=EvidenceStatus.STALE)
        ),
        constraint_snapshot=_constraints(),
    )

    assert result.candidates == ()
    assert len(result.rejected) == 1
    assert {reason.code for reason in result.rejected[0].reasons} == {
        CandidateRejectCode.EVIDENCE_MISSING,
        CandidateRejectCode.EVIDENCE_NOT_VERIFIED,
    }


def test_pool_prunes_hard_price_and_date_violations_without_silent_drop() -> None:
    candidate = StayCandidate(
        candidate_id="supplier-stay-1",
        name="West Lake Hotel",
        evidence_refs=("evidence-1",),
        provenance=(_provenance("provider-a", "stay-1"),),
        timezone="Asia/Shanghai",
        area="West Lake",
        check_in=datetime(2026, 8, 2, 15, tzinfo=UTC),
        check_out=datetime(2026, 8, 5, 11, tzinfo=UTC),
        price=CandidatePrice(
            total=Money(amount=Decimal("900"), currency="CNY"),
            evidence_refs=("evidence-1",),
        ),
    )
    budget = _constraint(
        "constraint-budget-1", "budget", Money(amount=Decimal("800"), currency="CNY")
    )
    travel_dates = _constraint(
        "constraint-date-1",
        "date_range",
        DateRange(start=date(2026, 8, 1), end=date(2026, 8, 3)),
    )

    result = CandidatePool().build(
        (candidate,),
        evidence_snapshot=_evidence_snapshot(_evidence("evidence-1")),
        constraint_snapshot=_constraints(budget, travel_dates),
    )

    assert result.candidates == ()
    assert len(result.rejected) == 1
    reasons = result.rejected[0].reasons
    assert {reason.constraint_ref for reason in reasons} == {
        "constraint-budget-1",
        "constraint-date-1",
    }
    assert {reason.code for reason in reasons} == {CandidateRejectCode.HARD_CONSTRAINT_VIOLATION}


def test_pool_surfaces_hard_constraints_deferred_to_later_planning_stages() -> None:
    candidate = _place(
        "supplier-a-1", ("evidence-1",), _provenance("provider-a", "place-1")
    )
    travelers = _constraint("constraint-travelers-1", "travelers", 2)

    result = CandidatePool().build(
        (candidate,),
        evidence_snapshot=_evidence_snapshot(_evidence("evidence-1")),
        constraint_snapshot=_constraints(travelers),
    )

    assert len(result.candidates) == 1
    assert result.deferred_hard_constraint_refs == ("constraint-travelers-1",)


def test_pool_rejects_type_specific_hard_constraints_with_constraint_references() -> None:
    transport = TransportCandidate(
        candidate_id="transport-1",
        name="G123",
        evidence_refs=("evidence-1",),
        provenance=(_provenance("provider-a", "transport-1"),),
        timezone="Asia/Shanghai",
        mode="rail",
        origin="Shanghai",
        destination="Hangzhou",
    )
    stay = StayCandidate(
        candidate_id="stay-1",
        name="Lake Hotel",
        evidence_refs=("evidence-1",),
        provenance=(_provenance("provider-a", "stay-1"),),
        timezone="Asia/Shanghai",
        area="West Lake",
    )
    place = _place(
        "place-1",
        ("evidence-1",),
        _provenance("provider-a", "place-1"),
        tags=("Crowded",),
    )
    context = ContextCandidate(
        candidate_id="context-1",
        name="Weather alert",
        evidence_refs=("evidence-1",),
        provenance=(_provenance("provider-a", "context-1"),),
        timezone="Asia/Shanghai",
        context_type="weather",
        scope="trip-candidate-1",
    )
    constraints = _constraints(
        _constraint("constraint-kind", "candidate_kind", "transport"),
        _constraint("constraint-mode", "mode", "flight"),
        _constraint("constraint-origin", "origin", "Beijing"),
        _constraint("constraint-destination", "destination", "Suzhou"),
        _constraint("constraint-area", "stay_area", "Downtown"),
        _constraint("constraint-category", "category", "restaurant"),
        _constraint("constraint-context", "context_type", "event"),
        _constraint("constraint-exclusion", "exclusion", ("crowded", "noisy")),
    )

    result = CandidatePool().build(
        (transport, stay, place, context),
        evidence_snapshot=_evidence_snapshot(_evidence("evidence-1")),
        constraint_snapshot=constraints,
    )

    assert result.candidates == ()
    assert len(result.rejected) == 4
    assert all(
        reason.code is CandidateRejectCode.HARD_CONSTRAINT_VIOLATION
        for rejection in result.rejected
        for reason in rejection.reasons
    )


def test_pool_reports_missing_candidate_data_and_invalid_hard_constraint_values() -> None:
    unpriced = _place(
        "place-unpriced", ("evidence-1",), _provenance("provider-a", "place-unpriced")
    )
    priced = _place(
        "place-priced", ("evidence-1",), _provenance("provider-a", "place-priced")
    ).model_copy(
        update={
            "price": CandidatePrice(
                total=Money(amount=Decimal("20"), currency="USD"),
                evidence_refs=("evidence-1",),
            )
        }
    )
    unscheduled = TransportCandidate(
        candidate_id="transport-unscheduled",
        name="G123",
        evidence_refs=("evidence-1",),
        provenance=(_provenance("provider-a", "transport-unscheduled"),),
        timezone="Asia/Shanghai",
        mode="rail",
        origin="Shanghai",
        destination="Hangzhou",
    )
    constraints = _constraints(
        _constraint("constraint-budget", "budget", Money(amount=Decimal("10"), currency="CNY")),
        _constraint("constraint-currency", "currency", "CNY"),
        _constraint("constraint-date", "date", date(2026, 8, 1)),
    )

    result = CandidatePool().build(
        (unpriced, priced, unscheduled),
        evidence_snapshot=_evidence_snapshot(_evidence("evidence-1")),
        constraint_snapshot=constraints,
    )

    assert result.candidates == ()
    assert any(
        CandidateRejectCode.HARD_CONSTRAINT_DATA_MISSING
        in {reason.code for reason in rejection.reasons}
        for rejection in result.rejected
    )
    assert any(
        CandidateRejectCode.HARD_CONSTRAINT_VIOLATION
        in {reason.code for reason in rejection.reasons}
        for rejection in result.rejected
    )


def test_pool_and_normalizer_reject_untyped_inputs() -> None:
    pool = CandidatePool()

    with pytest.raises(TypeError, match="CandidateNormalizer"):
        CandidatePool(object())  # type: ignore[arg-type]
    with pytest.raises(TypeError, match="supported Candidate"):
        CandidateNormalizer().normalize(object())  # type: ignore[arg-type]
    with pytest.raises(TypeError, match="candidates must be a tuple"):
        pool.build(  # type: ignore[arg-type]
            [],
            evidence_snapshot=_evidence_snapshot(),
            constraint_snapshot=_constraints(),
        )
    with pytest.raises(TypeError, match="EvidenceSnapshot"):
        pool.build(  # type: ignore[arg-type]
            (), evidence_snapshot=object(), constraint_snapshot=_constraints()
        )
    with pytest.raises(TypeError, match="ConstraintSnapshot"):
        pool.build(  # type: ignore[arg-type]
            (), evidence_snapshot=_evidence_snapshot(), constraint_snapshot=object()
        )
