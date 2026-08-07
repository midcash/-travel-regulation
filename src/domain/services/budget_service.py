"""M4 step nine: deterministic itinerary budget calculation."""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Final, NoReturn, Self

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from src.domain.errors import WorkflowError
from src.domain.models.candidates import Candidate, CandidatePoolResult, StayCandidate
from src.domain.models.enums import ErrorCategory, EvidenceStatus, EvidenceTtlCategory
from src.domain.models.evidence import EvidenceSnapshot
from src.domain.models.itinerary import (
    BudgetBreakdown,
    BudgetLine,
    ItineraryPlan,
    PlanBuffer,
)
from src.domain.models.trip_request import BudgetSemantics, TripRequest
from src.domain.models.value_objects import (
    CandidateId,
    EvidenceId,
    Money,
    PlanId,
    StableId,
    TraceId,
)
from src.domain.services.schedule_service import ScheduleResult

BUDGET_SCHEMA_VERSION: Final[str] = "m4-budget-v1"
BUDGET_STAGE: Final[str] = "budget_service"
_BUDGET_BUFFER_TYPE: Final[str] = "budget_contingency"


def _normalize_currency(value: str) -> str:
    """规范化并校验 ISO 4217 三字母货币代码。"""
    normalized = value.strip().upper()
    if len(normalized) != 3 or not normalized.isalpha():
        raise ValueError("currency must be a three-letter code")
    return normalized


class ExchangeRate(BaseModel):
    """一条带证据引用的确定性汇率。"""

    model_config = ConfigDict(extra="forbid", frozen=True, str_strip_whitespace=True)

    from_currency: str
    to_currency: str
    rate: Decimal = Field(gt=Decimal("0"))
    evidence_ref: EvidenceId

    @field_validator("from_currency", "to_currency")
    @classmethod
    def normalize_currencies(cls, value: str) -> str:
        """统一货币代码大小写并拒绝非法代码。"""
        return _normalize_currency(value)

    @field_validator("rate", mode="before")
    @classmethod
    def reject_float_rate(cls, value: object) -> object:
        """拒绝 float，避免汇率计算发生二进制精度损失。"""
        if isinstance(value, float):
            raise ValueError("exchange rate must be Decimal, int, or decimal string")
        return value

    @model_validator(mode="after")
    def validate_pair(self) -> Self:
        """同币种不需要汇率，必须由直接金额计算处理。"""
        if self.from_currency == self.to_currency:
            raise ValueError("exchange rate currencies must be different")
        return self


class BudgetContext(BaseModel):
    """BudgetService 的不可变输入快照。"""

    model_config = ConfigDict(extra="forbid", frozen=True, str_strip_whitespace=True)

    trace_id: TraceId
    as_of: datetime
    request: TripRequest
    candidate_pool: CandidatePoolResult
    evidence_snapshot: EvidenceSnapshot
    schedule_result: ScheduleResult
    target_currency: str | None = None
    exchange_rates: tuple[ExchangeRate, ...] = ()
    contingency_rate: Decimal = Field(default=Decimal("0"), ge=Decimal("0"), le=Decimal("1"))

    @field_validator("as_of")
    @classmethod
    def validate_as_of_timezone(cls, value: datetime) -> datetime:
        """预算证据的新鲜度判断必须使用带时区时间。"""
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("as_of must be timezone-aware")
        return value

    @field_validator("target_currency")
    @classmethod
    def normalize_target_currency(cls, value: str | None) -> str | None:
        """规范化可选的统一结算币种。"""
        return None if value is None else _normalize_currency(value)

    @field_validator("contingency_rate", mode="before")
    @classmethod
    def reject_float_contingency_rate(cls, value: object) -> object:
        """拒绝 float 缓冲比例，保持预算计算精确。"""
        if isinstance(value, float):
            raise ValueError("contingency_rate must be Decimal, int, or decimal string")
        return value

    @model_validator(mode="after")
    def validate_snapshot_alignment(self) -> Self:
        """确保排程、候选池和证据快照属于同一条可追踪链路。"""
        if self.schedule_result.trace_id != self.trace_id:
            raise ValueError("schedule result and budget context trace IDs differ")
        if self.candidate_pool.evidence_snapshot_id != self.evidence_snapshot.snapshot_id:
            raise ValueError("candidate pool and evidence snapshot differ")
        rate_keys = tuple((item.from_currency, item.to_currency) for item in self.exchange_rates)
        if len(rate_keys) != len(set(rate_keys)):
            raise ValueError("exchange rates must be unique by currency pair")
        return self


class BudgetLineResult(BaseModel):
    """预算计算中一项费用的来源金额、统一金额和证据引用。"""

    model_config = ConfigDict(extra="forbid", frozen=True, str_strip_whitespace=True)

    candidate_id: CandidateId
    category: str = Field(min_length=1, max_length=64)
    source_amount: Money
    amount: Money
    evidence_refs: tuple[EvidenceId, ...] = Field(min_length=1)

    @field_validator("evidence_refs")
    @classmethod
    def validate_unique_evidence_refs(
        cls, values: tuple[EvidenceId, ...]
    ) -> tuple[EvidenceId, ...]:
        """拒绝预算项中的重复证据引用。"""
        if len(values) != len(set(values)):
            raise ValueError("budget line evidence_refs must be unique")
        return values

    @model_validator(mode="after")
    def validate_amount_currencies(self) -> Self:
        """源金额和结果金额必须各自携带明确货币。"""
        if len(self.source_amount.currency) != 3 or len(self.amount.currency) != 3:
            raise ValueError("budget line currencies must be normalized")
        return self


class BudgetResult(BaseModel):
    """BudgetService 产出的可追踪预算结果。"""

    model_config = ConfigDict(extra="forbid", frozen=True, str_strip_whitespace=True)

    trace_id: TraceId
    plan_id: PlanId
    schema_version: str = BUDGET_SCHEMA_VERSION
    target_currency: str
    lines: tuple[BudgetLineResult, ...] = ()
    budget_breakdown: BudgetBreakdown
    buffer: PlanBuffer | None = None
    itinerary_plan: ItineraryPlan
    hard_budget_feasible: bool = True
    remaining_amount: Money | None = None
    price_evidence_refs: tuple[EvidenceId, ...] = ()
    exchange_rate_evidence_refs: tuple[EvidenceId, ...] = ()

    @field_validator("target_currency")
    @classmethod
    def validate_target_currency(cls, value: str) -> str:
        """保证结果中的统一币种为规范代码。"""
        return _normalize_currency(value)

    @model_validator(mode="after")
    def validate_result_alignment(self) -> Self:
        """保证预算结果与更新后的行程计划保持一致。"""
        if self.itinerary_plan.plan_id != self.plan_id:
            raise ValueError("budget result and itinerary plan IDs differ")
        if self.itinerary_plan.budget != self.budget_breakdown:
            raise ValueError("itinerary plan budget must equal budget breakdown")
        if self.budget_breakdown.total.currency != self.target_currency:
            raise ValueError("budget total must use target currency")
        return self

    @property
    def plan(self) -> ItineraryPlan:
        """向下游暴露已写入预算的行程计划。"""
        return self.itinerary_plan


class BudgetError(WorkflowError):
    """BudgetService 的 fail-fast 结构化错误。"""

    def __init__(
        self,
        trace_id: TraceId,
        code: str,
        safe_message: str,
        *,
        category: ErrorCategory = ErrorCategory.BUDGET,
        upstream_refs: tuple[StableId, ...] = (),
        cause: BaseException | None = None,
    ) -> None:
        super().__init__(
            trace_id=trace_id,
            stage=BUDGET_STAGE,
            category=category,
            code=code,
            safe_message=safe_message,
            upstream_refs=upstream_refs,
            retryable=False,
            cause=cause,
        )


class BudgetService:
    """使用候选价格和证据确定性计算行程预算。"""

    def calculate(self, context: BudgetContext) -> BudgetResult:
        """计算预算并将结果写入不可变 ItineraryPlan 副本。

        Args:
            context: 前一步排程结果、候选池和证据快照。

        Returns:
            BudgetResult: 带分项、缓冲和预算明细的结果。

        Raises:
            BudgetError: 价格、汇率、证据或硬预算约束不满足时抛出。
        """
        if not isinstance(context, BudgetContext):
            raise TypeError("context must be a BudgetContext")
        priced_candidates = self._collect_priced_candidates(context)
        target_currency = self._resolve_target_currency(context, priced_candidates)
        rate_by_pair = {
            (item.from_currency, item.to_currency): item for item in context.exchange_rates
        }
        line_results: list[BudgetLineResult] = []
        price_evidence_refs: list[EvidenceId] = []
        exchange_refs: list[EvidenceId] = []
        for candidate in priced_candidates:
            line, line_exchange_refs = self._build_line(
                context,
                candidate,
                target_currency=target_currency,
                rate_by_pair=rate_by_pair,
            )
            line_results.append(line)
            price_evidence_refs.extend(candidate.price.evidence_refs)  # type: ignore[union-attr]
            exchange_refs.extend(line_exchange_refs)

        base_total = sum((line.amount.amount for line in line_results), Decimal("0"))
        buffer_amount = base_total * context.contingency_rate
        budget_lines = tuple(
            BudgetLine(category=line.category, amount=line.amount) for line in line_results
        )
        buffer = None
        if buffer_amount > 0:
            buffer_money = Money(amount=buffer_amount, currency=target_currency)
            buffer = PlanBuffer(buffer_type=_BUDGET_BUFFER_TYPE, amount=buffer_money)
            budget_lines += (BudgetLine(category=_BUDGET_BUFFER_TYPE, amount=buffer_money),)
        total = Money(
            amount=base_total + buffer_amount,
            currency=target_currency,
        )
        breakdown = BudgetBreakdown(total=total, lines=budget_lines)
        remaining = self._validate_hard_budget(context, total)
        updated_plan = self._update_plan(
            context.schedule_result.plan,
            breakdown=breakdown,
            buffer=buffer,
            evidence_refs=tuple(
                _unique_refs(
                    (
                        *context.schedule_result.plan.evidence_refs,
                        *price_evidence_refs,
                        *exchange_refs,
                    )
                )
            ),
        )
        return BudgetResult(
            trace_id=context.trace_id,
            plan_id=updated_plan.plan_id,
            target_currency=target_currency,
            lines=tuple(line_results),
            budget_breakdown=breakdown,
            buffer=buffer,
            itinerary_plan=updated_plan,
            hard_budget_feasible=True,
            remaining_amount=remaining,
            price_evidence_refs=_unique_refs(price_evidence_refs),
            exchange_rate_evidence_refs=_unique_refs(exchange_refs),
        )

    def _collect_priced_candidates(self, context: BudgetContext) -> tuple[Candidate, ...]:
        """按排程项顺序收集候选并拒绝缺失价格。"""
        candidate_by_id = {
            candidate.candidate_id: candidate for candidate in context.candidate_pool.candidates
        }
        selected: list[Candidate] = []
        seen: set[CandidateId] = set()
        for item in context.schedule_result.plan.items:
            candidate = candidate_by_id.get(item.candidate_id)
            if candidate is None:
                _raise_budget_error(
                    context,
                    "BUDGET_CANDIDATE_MISSING",
                    "scheduled plan references a candidate outside the pool",
                    upstream_refs=(item.candidate_id,),
                )
            if item.candidate_id in seen:
                if isinstance(candidate, StayCandidate):
                    continue
                _raise_budget_error(
                    context,
                    "BUDGET_DUPLICATE_PLAN_CANDIDATE",
                    "scheduled plan contains a candidate more than once",
                    upstream_refs=(item.candidate_id,),
                )
            seen.add(item.candidate_id)
            if candidate.price is None:
                _raise_budget_error(
                    context,
                    "BUDGET_PRICE_MISSING",
                    "scheduled candidate has no verified price",
                    category=ErrorCategory.EVIDENCE,
                    upstream_refs=(candidate.candidate_id,),
                )
            self._validate_evidence(
                context,
                candidate.price.evidence_refs,
                category=ErrorCategory.EVIDENCE,
                upstream_refs=(candidate.candidate_id,),
            )
            selected.append(candidate)
        return tuple(selected)

    def _resolve_target_currency(
        self, context: BudgetContext, candidates: tuple[Candidate, ...]
    ) -> str:
        """从显式配置、请求预算或候选价格确定统一币种。"""
        budget_currencies = _budget_currencies(context.request)
        if context.target_currency is not None:
            if budget_currencies and context.target_currency not in budget_currencies:
                _raise_budget_error(
                    context,
                    "BUDGET_CURRENCY_MISMATCH",
                    "target currency differs from request budget currency",
                )
            return context.target_currency
        if budget_currencies:
            return budget_currencies[0]
        candidate_currencies = {
            candidate.price.total.currency for candidate in candidates if candidate.price
        }
        if len(candidate_currencies) == 1:
            return next(iter(candidate_currencies))
        if not candidate_currencies:
            _raise_budget_error(
                context,
                "BUDGET_TARGET_CURRENCY_REQUIRED",
                "target currency is required when the plan has no priced items",
            )
        _raise_budget_error(
            context,
            "BUDGET_TARGET_CURRENCY_REQUIRED",
            "target currency is required for multiple source currencies",
        )

    def _build_line(
        self,
        context: BudgetContext,
        candidate: Candidate,
        *,
        target_currency: str,
        rate_by_pair: dict[tuple[str, str], ExchangeRate],
    ) -> tuple[BudgetLineResult, tuple[EvidenceId, ...]]:
        """校验价格并将一项金额转换为统一币种。"""
        price = candidate.price
        if price is None:
            _raise_budget_error(
                context,
                "BUDGET_PRICE_MISSING",
                "scheduled candidate has no verified price",
                category=ErrorCategory.EVIDENCE,
                upstream_refs=(candidate.candidate_id,),
            )
        source_amount = price.total
        exchange_refs: tuple[EvidenceId, ...] = ()
        amount = source_amount
        if source_amount.currency != target_currency:
            rate = rate_by_pair.get((source_amount.currency, target_currency))
            if rate is None:
                _raise_budget_error(
                    context,
                    "BUDGET_EXCHANGE_RATE_MISSING",
                    "required exchange rate is missing",
                    category=ErrorCategory.EVIDENCE,
                    upstream_refs=(candidate.candidate_id, *price.evidence_refs),
                )
            self._validate_evidence(
                context,
                (rate.evidence_ref,),
                category=ErrorCategory.EVIDENCE,
                upstream_refs=(candidate.candidate_id, rate.evidence_ref),
                require_exchange_rate=True,
            )
            amount = Money(
                amount=source_amount.amount * rate.rate,
                currency=target_currency,
            )
            exchange_refs = (rate.evidence_ref,)
        return (
            BudgetLineResult(
                candidate_id=candidate.candidate_id,
                category=candidate.kind,
                source_amount=source_amount,
                amount=amount,
                evidence_refs=_unique_refs((*price.evidence_refs, *exchange_refs)),
            ),
            exchange_refs,
        )

    def _validate_evidence(
        self,
        context: BudgetContext,
        refs: tuple[EvidenceId, ...],
        *,
        category: ErrorCategory,
        upstream_refs: tuple[StableId, ...],
        require_exchange_rate: bool = False,
    ) -> None:
        """拒绝缺失、未验证、冲突或过期证据。"""
        evidence_by_id = {
            item.evidence_id: item for item in context.evidence_snapshot.evidence_items
        }
        for evidence_ref in refs:
            evidence = evidence_by_id.get(evidence_ref)
            if evidence is None:
                _raise_budget_error(
                    context,
                    "BUDGET_EVIDENCE_MISSING",
                    "budget input references missing evidence",
                    category=category,
                    upstream_refs=(*upstream_refs, evidence_ref),
                )
            if evidence.status is not EvidenceStatus.VERIFIED:
                _raise_budget_error(
                    context,
                    "BUDGET_EVIDENCE_NOT_VERIFIED",
                    "budget input evidence is not verified",
                    category=category,
                    upstream_refs=(*upstream_refs, evidence_ref),
                )
            if evidence_ref in context.evidence_snapshot.conflict_refs:
                _raise_budget_error(
                    context,
                    "BUDGET_EVIDENCE_CONFLICT",
                    "budget input evidence is conflicting",
                    category=category,
                    upstream_refs=(*upstream_refs, evidence_ref),
                )
            if evidence.valid_until is not None and evidence.valid_until <= context.as_of:
                _raise_budget_error(
                    context,
                    "BUDGET_EVIDENCE_EXPIRED",
                    "budget input evidence is expired",
                    category=category,
                    upstream_refs=(*upstream_refs, evidence_ref),
                )
            if (
                require_exchange_rate
                and evidence.ttl_category is not EvidenceTtlCategory.EXCHANGE_RATE
            ):
                _raise_budget_error(
                    context,
                    "BUDGET_EXCHANGE_EVIDENCE_INVALID",
                    "exchange rate must reference exchange-rate evidence",
                    category=category,
                    upstream_refs=(*upstream_refs, evidence_ref),
                )

    def _validate_hard_budget(self, context: BudgetContext, total: Money) -> Money | None:
        """校验 maximum/range 硬预算并返回可用余量。"""
        budget = context.request.budget
        if budget is None:
            return None
        budget_currency = _budget_currencies(context.request)[0]
        if total.currency != budget_currency:
            _raise_budget_error(
                context,
                "BUDGET_CURRENCY_MISMATCH",
                "calculated total differs from request budget currency",
            )
        if budget.semantics is BudgetSemantics.MAXIMUM:
            assert budget.maximum is not None
            if total.amount > budget.maximum.amount:
                _raise_budget_error(
                    context,
                    "BUDGET_MAXIMUM_EXCEEDED",
                    "calculated budget exceeds the hard maximum",
                )
            return Money(amount=budget.maximum.amount - total.amount, currency=total.currency)
        if budget.semantics is BudgetSemantics.RANGE:
            assert budget.minimum is not None and budget.maximum is not None
            if total.amount < budget.minimum.amount:
                _raise_budget_error(
                    context,
                    "BUDGET_RANGE_MINIMUM_NOT_MET",
                    "calculated budget is below the requested hard range",
                )
            if total.amount > budget.maximum.amount:
                _raise_budget_error(
                    context,
                    "BUDGET_RANGE_MAXIMUM_EXCEEDED",
                    "calculated budget exceeds the requested hard range",
                )
            return Money(amount=budget.maximum.amount - total.amount, currency=total.currency)
        return None

    def _update_plan(
        self,
        plan: ItineraryPlan,
        *,
        breakdown: BudgetBreakdown,
        buffer: PlanBuffer | None,
        evidence_refs: tuple[EvidenceId, ...],
    ) -> ItineraryPlan:
        """只复制更新 ItineraryPlan，不写入全局 TripState。"""
        buffers = tuple(item for item in plan.buffers if item.buffer_type != _BUDGET_BUFFER_TYPE)
        if buffer is not None:
            buffers += (buffer,)
        return plan.model_copy(
            update={
                "budget": breakdown,
                "buffers": buffers,
                "evidence_refs": evidence_refs,
            }
        )


def _budget_currencies(request: TripRequest) -> tuple[str, ...]:
    """读取请求预算中声明的统一币种。"""
    if request.budget is None:
        return ()
    amounts = (
        request.budget.minimum,
        request.budget.maximum,
        request.budget.target,
    )
    return tuple({money.currency for money in amounts if money is not None})


def _unique_refs(refs: tuple[EvidenceId, ...] | list[EvidenceId]) -> tuple[EvidenceId, ...]:
    """按首次出现顺序去重证据引用。"""
    return tuple(dict.fromkeys(refs))


def _raise_budget_error(
    context: BudgetContext,
    code: str,
    safe_message: str,
    *,
    category: ErrorCategory = ErrorCategory.BUDGET,
    upstream_refs: tuple[StableId, ...] = (),
) -> NoReturn:
    """抛出带追踪信息的预算阶段错误。"""
    raise BudgetError(
        trace_id=context.trace_id,
        code=code,
        safe_message=safe_message,
        category=category,
        upstream_refs=upstream_refs,
    )


__all__ = [
    "BUDGET_SCHEMA_VERSION",
    "BUDGET_STAGE",
    "BudgetContext",
    "BudgetError",
    "BudgetLineResult",
    "BudgetResult",
    "BudgetService",
    "ExchangeRate",
]
