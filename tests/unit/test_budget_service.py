"""M4 step nine: BudgetService deterministic calculation tests."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta, timezone
from decimal import Decimal

import pytest
from pydantic import ValidationError

from src.domain.models.candidates import (
    CandidatePoolResult,
    CandidatePrice,
    CandidateProvenance,
    PlaceCandidate,
)
from src.domain.models.enums import EvidenceStatus, EvidenceTtlCategory, WorkflowStatus
from src.domain.models.evidence import EvidenceItem, EvidenceSnapshot
from src.domain.models.itinerary import ItineraryDay, ItineraryPlan, PlanBuffer, PlanItem
from src.domain.models.trip_request import BudgetSemantics, BudgetSpec, TravelerProfile, TripRequest
from src.domain.models.value_objects import DateRange, GeoPoint, Money
from src.domain.services.budget_service import (
    BudgetContext,
    BudgetError,
    BudgetService,
    ExchangeRate,
)
from src.domain.services.schedule_service import ScheduleResult

AS_OF = datetime(2026, 8, 6, 12, tzinfo=UTC)
LOCAL = timezone(timedelta(hours=8))


def _evidence(
    evidence_id: str,
    *,
    category: EvidenceTtlCategory = EvidenceTtlCategory.QUOTE_INVENTORY,
    status: EvidenceStatus = EvidenceStatus.VERIFIED,
    valid_until: datetime | None = AS_OF + timedelta(days=1),
) -> EvidenceItem:
    return EvidenceItem(
        evidence_id=evidence_id,
        entity_id=f"entity:{evidence_id}",
        fact_type="price" if category is EvidenceTtlCategory.QUOTE_INVENTORY else "exchange_rate",
        value=Decimal("1"),
        provider="fake-provider",
        source="fake-source",
        source_ref=f"source:{evidence_id}",
        observed_at=AS_OF - timedelta(hours=1),
        valid_until=valid_until,
        ttl_category=category,
        status=status,
        confidence=Decimal("1"),
        query_fingerprint=f"query:{evidence_id}",
    )


def _candidate(
    candidate_id: str = "candidate:place",
    *,
    amount: str = "100",
    currency: str = "CNY",
    price_evidence: str | None = None,
) -> PlaceCandidate:
    price_ref = price_evidence or f"evidence:price:{candidate_id.split(':')[-1]}"
    return PlaceCandidate(
        candidate_id=candidate_id,
        name="verified place",
        evidence_refs=(price_ref,),
        provenance=(
            CandidateProvenance(
                provider="fake-provider",
                entity_id=f"entity:{candidate_id}",
                source_ref=f"source:{candidate_id}",
            ),
        ),
        timezone="Asia/Shanghai",
        location=GeoPoint(latitude=30.25, longitude=120.16),
        category="scenic",
        price=CandidatePrice(
            total=Money(amount=Decimal(amount), currency=currency),
            evidence_refs=(price_ref,),
        ),
    )


def _unpriced_candidate(candidate_id: str = "candidate:place") -> PlaceCandidate:
    return PlaceCandidate(
        candidate_id=candidate_id,
        name="unpriced place",
        evidence_refs=(f"evidence:place:{candidate_id.split(':')[-1]}",),
        provenance=(
            CandidateProvenance(
                provider="fake-provider",
                entity_id=f"entity:{candidate_id}",
                source_ref=f"source:{candidate_id}",
            ),
        ),
        timezone="Asia/Shanghai",
        category="scenic",
    )


def _schedule_result(
    candidates: tuple[PlaceCandidate, ...],
    *,
    trace_id: str = "trace:budget",
    buffers: tuple[PlanBuffer, ...] = (),
    unknown_candidate: str | None = None,
) -> ScheduleResult:
    candidate_ids = tuple(candidate.candidate_id for candidate in candidates)
    if unknown_candidate is not None:
        candidate_ids += (unknown_candidate,)
    items = tuple(
        PlanItem(
            plan_item_id=f"plan-item:{index}",
            candidate_id=candidate_id,
            day_number=1,
            title=candidate_id,
            start_at=datetime(2026, 8, 10, 9 + index, tzinfo=LOCAL),
            end_at=datetime(2026, 8, 10, 10 + index, tzinfo=LOCAL),
            evidence_refs=(f"evidence:item:{index}",),
        )
        for index, candidate_id in enumerate(candidate_ids)
    )
    plan = ItineraryPlan(
        plan_id="plan:budget",
        version=1,
        status=WorkflowStatus.DRAFTING,
        date_range=DateRange(start="2026-08-10", end="2026-08-10"),
        days=(
            ItineraryDay(
                day_number=1,
                date="2026-08-10",
                item_refs=tuple(item.plan_item_id for item in items),
            ),
        ),
        items=items,
        buffers=buffers,
    )
    return ScheduleResult(
        trace_id=trace_id,
        plan_candidate_id=plan.plan_id,
        variant="balanced",
        itinerary_plan=plan,
        total_flex_buffer_minutes=0,
    )


def _context(
    *candidates: PlaceCandidate,
    budget: BudgetSpec | None = None,
    target_currency: str | None = None,
    exchange_rates: tuple[ExchangeRate, ...] = (),
    evidence_items: tuple[EvidenceItem, ...] | None = None,
    contingency_rate: Decimal = Decimal("0"),
    schedule_result: ScheduleResult | None = None,
    trace_id: str | None = None,
) -> BudgetContext:
    schedule_result = schedule_result or _schedule_result(tuple(candidates))
    refs = {evidence_ref for candidate in candidates for evidence_ref in candidate.evidence_refs}
    refs.update(rate.evidence_ref for rate in exchange_rates)
    if evidence_items is None:
        exchange_refs = {rate.evidence_ref for rate in exchange_rates}
        evidence_items = tuple(
            _evidence(
                ref,
                category=(
                    EvidenceTtlCategory.EXCHANGE_RATE
                    if ref in exchange_refs
                    else EvidenceTtlCategory.QUOTE_INVENTORY
                ),
            )
            for ref in sorted(refs)
        )
    request = TripRequest(
        request_id="request:budget",
        trip_id="trip:budget",
        session_id="session:budget",
        origin="origin",
        destinations=("destination",),
        date_range=DateRange(start="2026-08-10", end="2026-08-10"),
        travelers=TravelerProfile(adults=2),
        budget=budget,
        timezone="Asia/Shanghai",
    )
    return BudgetContext(
        trace_id=trace_id or schedule_result.trace_id,
        as_of=AS_OF,
        request=request,
        candidate_pool=CandidatePoolResult(
            evidence_snapshot_id="evidence-snapshot:budget",
            constraint_snapshot_version=1,
            candidates=candidates,
        ),
        evidence_snapshot=EvidenceSnapshot(
            snapshot_id="evidence-snapshot:budget",
            created_at=AS_OF,
            evidence_items=evidence_items,
            coverage=Decimal("1"),
            freshness=Decimal("1"),
        ),
        schedule_result=schedule_result,
        target_currency=target_currency,
        exchange_rates=exchange_rates,
        contingency_rate=contingency_rate,
    )


def _maximum(amount: str = "1000", currency: str = "CNY") -> BudgetSpec:
    return BudgetSpec(
        semantics=BudgetSemantics.MAXIMUM,
        maximum=Money(amount=Decimal(amount), currency=currency),
    )


def test_budget_calculates_exact_lines_total_and_contingency() -> None:
    candidate = _candidate(amount="100.25")
    result = BudgetService().calculate(
        _context(candidate, budget=_maximum(), contingency_rate=Decimal("0.10"))
    )

    assert result.target_currency == "CNY"
    assert result.lines[0].amount == Money(amount=Decimal("100.25"), currency="CNY")
    assert result.buffer is not None
    assert result.buffer.amount == Money(amount=Decimal("10.025"), currency="CNY")
    assert result.budget_breakdown.total == Money(amount=Decimal("110.275"), currency="CNY")
    assert result.plan.budget == result.budget_breakdown
    assert result.remaining_amount == Money(amount=Decimal("889.725"), currency="CNY")


def test_budget_converts_currency_with_verified_exchange_evidence() -> None:
    candidate = _candidate(amount="12.50", currency="USD")
    rate = ExchangeRate(
        from_currency="USD",
        to_currency="CNY",
        rate=Decimal("7.2"),
        evidence_ref="evidence:fx:usd-cny",
    )
    result = BudgetService().calculate(
        _context(candidate, budget=_maximum(), exchange_rates=(rate,))
    )

    assert result.lines[0].source_amount == Money(amount=Decimal("12.50"), currency="USD")
    assert result.lines[0].amount == Money(amount=Decimal("90.00"), currency="CNY")
    assert result.lines[0].evidence_refs == (
        "evidence:price:place",
        "evidence:fx:usd-cny",
    )
    assert result.exchange_rate_evidence_refs == ("evidence:fx:usd-cny",)


def test_budget_output_is_deterministic_and_preserves_schedule_buffers() -> None:
    candidate = _candidate()
    schedule = _schedule_result(
        (candidate,),
        buffers=(PlanBuffer(buffer_type="transfer", minutes=15),),
    )
    context = _context(candidate, budget=_maximum(), schedule_result=schedule)

    first = BudgetService().calculate(context)
    second = BudgetService().calculate(context)

    assert first.model_dump(mode="json") == second.model_dump(mode="json")
    assert first.plan.buffers[0] == PlanBuffer(buffer_type="transfer", minutes=15)
    assert first.plan is not schedule.plan
    assert schedule.plan.budget is None


def test_budget_rejects_missing_price_without_partial_success() -> None:
    candidate = _unpriced_candidate()

    with pytest.raises(BudgetError) as error:
        BudgetService().calculate(_context(candidate, budget=_maximum()))

    assert error.value.stage == "budget_service"
    assert error.value.payload.code == "BUDGET_PRICE_MISSING"
    assert error.value.trace_id == "trace:budget"


def test_budget_rejects_missing_price_evidence() -> None:
    candidate = _candidate(price_evidence="evidence:price:not-in-snapshot")

    with pytest.raises(BudgetError, match="missing evidence") as error:
        BudgetService().calculate(_context(candidate, budget=_maximum(), evidence_items=()))

    assert error.value.payload.code == "BUDGET_EVIDENCE_MISSING"


@pytest.mark.parametrize(
    ("status", "code"),
    [
        (EvidenceStatus.STALE, "BUDGET_EVIDENCE_NOT_VERIFIED"),
        (EvidenceStatus.CONFLICTING, "BUDGET_EVIDENCE_NOT_VERIFIED"),
    ],
)
def test_budget_rejects_unverified_price_evidence(status: EvidenceStatus, code: str) -> None:
    candidate = _candidate()
    evidence = _evidence(candidate.evidence_refs[0], status=status)

    with pytest.raises(BudgetError) as error:
        BudgetService().calculate(
            _context(candidate, budget=_maximum(), evidence_items=(evidence,))
        )

    assert error.value.payload.code == code


def test_budget_rejects_expired_price_evidence() -> None:
    candidate = _candidate()
    evidence = _evidence(
        candidate.evidence_refs[0],
        valid_until=AS_OF,
    )

    with pytest.raises(BudgetError) as error:
        BudgetService().calculate(
            _context(candidate, budget=_maximum(), evidence_items=(evidence,))
        )

    assert error.value.payload.code == "BUDGET_EVIDENCE_EXPIRED"


def test_budget_rejects_missing_exchange_rate() -> None:
    candidate = _candidate(amount="10", currency="USD")

    with pytest.raises(BudgetError) as error:
        BudgetService().calculate(_context(candidate, budget=_maximum(), target_currency="CNY"))

    assert error.value.payload.code == "BUDGET_EXCHANGE_RATE_MISSING"
    assert "evidence:price:place" in error.value.payload.upstream_refs


def test_budget_rejects_invalid_exchange_evidence() -> None:
    candidate = _candidate(amount="10", currency="USD")
    rate = ExchangeRate(
        from_currency="USD",
        to_currency="CNY",
        rate=Decimal("7"),
        evidence_ref="evidence:fx:usd-cny",
    )
    evidence = _evidence(
        rate.evidence_ref,
        category=EvidenceTtlCategory.QUOTE_INVENTORY,
    )

    with pytest.raises(BudgetError) as error:
        BudgetService().calculate(
            _context(
                candidate,
                budget=_maximum(),
                exchange_rates=(rate,),
                evidence_items=(
                    _evidence(candidate.evidence_refs[0]),
                    evidence,
                ),
            )
        )

    assert error.value.payload.code == "BUDGET_EXCHANGE_EVIDENCE_INVALID"


def test_budget_rejects_hard_maximum_including_buffer() -> None:
    candidate = _candidate(amount="100")

    with pytest.raises(BudgetError) as error:
        BudgetService().calculate(
            _context(
                candidate,
                budget=_maximum("100"),
                contingency_rate=Decimal("0.01"),
            )
        )

    assert error.value.payload.code == "BUDGET_MAXIMUM_EXCEEDED"


@pytest.mark.parametrize(
    ("amount", "code"),
    [
        ("40", "BUDGET_RANGE_MINIMUM_NOT_MET"),
        ("101", "BUDGET_RANGE_MAXIMUM_EXCEEDED"),
    ],
)
def test_budget_enforces_hard_range(amount: str, code: str) -> None:
    budget = BudgetSpec(
        semantics=BudgetSemantics.RANGE,
        minimum=Money(amount=Decimal("50"), currency="CNY"),
        maximum=Money(amount=Decimal("100"), currency="CNY"),
    )

    with pytest.raises(BudgetError) as error:
        BudgetService().calculate(_context(_candidate(amount=amount), budget=budget))

    assert error.value.payload.code == code


def test_budget_target_semantics_is_reported_without_hard_limit_failure() -> None:
    budget = BudgetSpec(
        semantics=BudgetSemantics.TARGET,
        target=Money(amount=Decimal("100"), currency="CNY"),
    )
    result = BudgetService().calculate(_context(_candidate(amount="10"), budget=budget))

    assert result.hard_budget_feasible is True
    assert result.remaining_amount is None


def test_budget_requires_explicit_target_for_multiple_currencies() -> None:
    first = _candidate("candidate:first", amount="10", currency="USD")
    second = _candidate("candidate:second", amount="20", currency="EUR")

    with pytest.raises(BudgetError) as error:
        BudgetService().calculate(
            _context(first, second, schedule_result=_schedule_result((first, second)))
        )

    assert error.value.payload.code == "BUDGET_TARGET_CURRENCY_REQUIRED"


def test_budget_rejects_currency_mismatch_with_request_budget() -> None:
    candidate = _candidate(amount="10", currency="CNY")

    with pytest.raises(BudgetError) as error:
        BudgetService().calculate(
            _context(candidate, budget=_maximum(currency="USD"), target_currency="CNY")
        )

    assert error.value.payload.code == "BUDGET_CURRENCY_MISMATCH"


def test_budget_rejects_unknown_scheduled_candidate() -> None:
    candidate = _candidate()
    schedule = _schedule_result((candidate,), unknown_candidate="candidate:unknown")

    with pytest.raises(BudgetError) as error:
        BudgetService().calculate(_context(candidate, budget=_maximum(), schedule_result=schedule))

    assert error.value.payload.code == "BUDGET_CANDIDATE_MISSING"


def test_budget_rejects_duplicate_scheduled_candidate() -> None:
    candidate = _candidate()
    schedule = _schedule_result((candidate, candidate))

    with pytest.raises(BudgetError) as error:
        BudgetService().calculate(_context(candidate, budget=_maximum(), schedule_result=schedule))

    assert error.value.payload.code == "BUDGET_DUPLICATE_PLAN_CANDIDATE"


def test_budget_context_requires_matching_trace_and_rate_pairs() -> None:
    candidate = _candidate()
    schedule = _schedule_result((candidate,), trace_id="trace:other")

    with pytest.raises(ValidationError, match="trace IDs differ"):
        _context(
            candidate,
            budget=_maximum(),
            schedule_result=schedule,
            trace_id="trace:budget",
        )

    with pytest.raises(ValidationError, match="exchange rates must be unique"):
        _context(
            candidate,
            budget=_maximum(),
            target_currency="CNY",
            exchange_rates=(
                ExchangeRate(
                    from_currency="USD",
                    to_currency="CNY",
                    rate=Decimal("7"),
                    evidence_ref="evidence:fx:one",
                ),
                ExchangeRate(
                    from_currency="USD",
                    to_currency="CNY",
                    rate=Decimal("7.1"),
                    evidence_ref="evidence:fx:two",
                ),
            ),
        )


def test_budget_dtos_reject_float_amount_rate_and_contingency() -> None:
    with pytest.raises(ValidationError):
        ExchangeRate(
            from_currency="USD",
            to_currency="CNY",
            rate=7.0,
            evidence_ref="evidence:fx",
        )
    with pytest.raises(ValidationError):
        payload = _context(_candidate(), budget=_maximum()).model_dump()
        payload["contingency_rate"] = 0.1
        BudgetContext.model_validate(payload)


def test_budget_rejects_invalid_exchange_rate_pair() -> None:
    with pytest.raises(ValidationError, match="different"):
        ExchangeRate(
            from_currency="CNY",
            to_currency="CNY",
            rate=Decimal("1"),
            evidence_ref="evidence:fx",
        )
