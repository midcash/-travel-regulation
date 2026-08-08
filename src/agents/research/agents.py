"""M4 step six: five read-only Research Agents."""

from __future__ import annotations

import asyncio
import hashlib
import json
import re
from collections.abc import Mapping
from datetime import UTC, date, datetime, time, timedelta, timezone
from decimal import Decimal
from typing import ClassVar, Final
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from pydantic import BaseModel, ValidationError

from src.domain.errors import WorkflowError
from src.domain.models.candidates import CandidateProvenance
from src.domain.models.enums import ErrorCategory, EvidenceStatus, EvidenceTtlCategory
from src.domain.models.evidence import EvidenceRegistration, EvidenceValue
from src.domain.models.provider import (
    ContextProviderResult,
    ContextQuery,
    PlaceProviderResult,
    PlaceQuery,
    StayProviderResult,
    StayQuery,
    TransportProviderResult,
    TransportQuery,
)
from src.domain.models.trip_request import BudgetSemantics
from src.domain.models.value_objects import DateRange, Money, StableId
from src.obs.trace import trace_named_span
from src.ports.tool_errors import ToolEmptyResultError, ToolError
from src.ports.tool_provider import (
    ContextProvider,
    PlaceProvider,
    StayProvider,
    TransportProvider,
)

from .contracts import AgentContext, AgentResult, AgentSummary, CandidateDraft, EvidenceDraft

_MAX_TEXT_LENGTH: Final[int] = 2048
_PROMPT_INJECTION_PATTERN: Final[re.Pattern[str]] = re.compile(
    "(?:\u5ffd\u7565(?:\u4e4b\u524d|\u4e0a\u6587|\u6240\u6709)?(?:\u7684)?"
    "(?:\u6307\u4ee4|\u89c4\u5219|\u63d0\u793a)|"
    r"(?:ignore|disregard|forget)\s+(?:all\s+)?(?:previous|prior|above)|"
    r"(?:system\s+prompt|developer\s+message|reveal\s+(?:your\s+)?prompt))",
    re.IGNORECASE,
)
_FLIGHT_MODE_TERMS: Final[tuple[str, ...]] = (
    "flight", "airplane", "plane", "飞机", "航班", "机票"
)
_TRAIN_MODE_TERMS: Final[tuple[str, ...]] = (
    "train", "rail", "high-speed rail", "火车", "高铁", "动车"
)


class ResearchAgentError(WorkflowError):
    """Safe structured failure raised by a Research Agent."""

    def __init__(
        self,
        context: AgentContext,
        code: str,
        category: ErrorCategory,
        safe_message: str,
        *,
        upstream_refs: tuple[StableId, ...] = (),
        retryable: bool = False,
        cause: BaseException | None = None,
    ) -> None:
        self.task_id = context.task_spec.task_id
        super().__init__(
            context.trace_id,
            "research_agent",
            category,
            code,
            safe_message,
            upstream_refs=(context.task_spec.task_id, *upstream_refs),
            retryable=retryable,
            cause=cause,
        )


class _ResearchAgentBase:
    """Shared budget, allowlist, timeout, and error boundary."""

    capability: ClassVar[str]
    agent_type: ClassVar[str]
    task_type: ClassVar[str]
    expected_output_type: ClassVar[str]
    required_tool: ClassVar[str]
    result_type: ClassVar[type[BaseModel]]

    def __init__(self, provider: object) -> None:
        self._provider = provider

    async def run(self, context: AgentContext) -> AgentResult:
        """Execute one budgeted provider research call."""
        if not isinstance(context, AgentContext):
            raise TypeError("context must be an AgentContext")
        self._validate_context(context)
        timeout_seconds = min(
            context.budget.timeout_seconds,
            Decimal(str(context.task_spec.timeout)),
        )
        query = self._build_query(context, timeout_seconds=timeout_seconds)
        query_id = query.query_id
        attributes = {
            "workflow.trace_id": context.trace_id,
            "workflow.task_id": context.task_spec.task_id,
            "research.agent_type": self.agent_type,
            "research.capability": self.capability,
            "research.query_id": query_id,
        }
        with trace_named_span("research.agent", attributes=attributes) as span:
            try:
                raw_result = await asyncio.wait_for(
                    self._search(query, timeout_seconds=timeout_seconds),
                    timeout=float(timeout_seconds),
                )
                if not isinstance(raw_result, self.result_type):
                    raise ResearchAgentError(
                        context,
                        "RESEARCH_RESULT_SCHEMA_INVALID",
                        ErrorCategory.VALIDATION,
                        "research provider returned an invalid result schema",
                        upstream_refs=(query_id,),
                    )
                if not raw_result.items:
                    raise ToolEmptyResultError(
                        provider="research_agent",
                        operation=self.required_tool,
                        safe_message="research provider returned no usable results",
                        trace_id=context.trace_id,
                        query_id=query_id,
                    )
                result = self._build_result(context, query, raw_result)
            except asyncio.CancelledError:
                raise
            except ResearchAgentError:
                raise
            except ToolError as exc:
                raise ResearchAgentError(
                    context,
                    exc.code,
                    ErrorCategory.TOOL,
                    exc.safe_message,
                    upstream_refs=(exc.query_id or query_id,),
                    retryable=exc.retryable,
                    cause=exc,
                ) from exc
            except TimeoutError as exc:
                raise ResearchAgentError(
                    context,
                    "RESEARCH_TIMEOUT",
                    ErrorCategory.TIMEOUT,
                    "research agent timed out",
                    upstream_refs=(query_id,),
                    cause=exc,
                ) from exc
            except ValidationError as exc:
                raise ResearchAgentError(
                    context,
                    "RESEARCH_OUTPUT_SCHEMA_INVALID",
                    ErrorCategory.VALIDATION,
                    "research agent output failed schema validation",
                    upstream_refs=(query_id,),
                    cause=exc,
                ) from exc
            except Exception as exc:
                raise ResearchAgentError(
                    context,
                    "RESEARCH_PROVIDER_ERROR",
                    ErrorCategory.TOOL,
                    "research provider call failed",
                    upstream_refs=(query_id,),
                    cause=exc,
                ) from exc
            span.set_attribute("research.provider", result.summary.provider)
            span.set_attribute("research.evidence_draft_count", len(result.evidence_drafts))
            span.set_attribute("research.candidate_draft_count", len(result.candidate_drafts))
            return result

    def _validate_context(self, context: AgentContext) -> None:
        """Validate task type and tool allowlist."""
        task = context.task_spec
        if task.capability != self.capability:
            raise ResearchAgentError(
                context,
                "RESEARCH_CAPABILITY_MISMATCH",
                ErrorCategory.VALIDATION,
                "task capability does not match research agent",
            )
        if (
            task.task_type != self.task_type
            or task.expected_output_type != self.expected_output_type
        ):
            raise ResearchAgentError(
                context,
                "RESEARCH_TASK_SCHEMA_MISMATCH",
                ErrorCategory.VALIDATION,
                "task specification does not match research agent",
            )
        accepted_tools = {
            self.capability,
            self.required_tool,
            f"provider.{self.required_tool}",
        }
        if not accepted_tools.intersection(context.allowed_tools):
            raise ResearchAgentError(
                context,
                "RESEARCH_TOOL_NOT_ALLOWED",
                ErrorCategory.SECURITY,
                "research agent is not allowed to call this tool",
            )
        if task.tool_call_budget < 1 or context.budget.max_tool_calls < 1:
            raise ResearchAgentError(
                context,
                "BUDGET_EXHAUSTED",
                ErrorCategory.BUDGET,
                "research agent tool-call budget was exhausted",
            )

    async def _search(self, query: object, *, timeout_seconds: Decimal) -> object:
        """Call one capability-specific provider port."""
        raise NotImplementedError

    def _build_query(self, context: AgentContext, *, timeout_seconds: Decimal) -> object:
        """Build a typed provider query."""
        raise NotImplementedError

    def _build_result(self, context: AgentContext, query: object, result: object) -> AgentResult:
        """Convert a provider result into read-only drafts."""
        raise NotImplementedError


def _query_id(capability: str, task_id: StableId, fields: Mapping[str, object]) -> StableId:
    """Create a stable query ID without exposing raw provider payloads."""
    canonical = json.dumps(fields, ensure_ascii=True, sort_keys=True, default=str)
    digest = hashlib.sha256(canonical.encode("utf-8")).hexdigest()[:32]
    return f"query:{capability}:{task_id}:{digest}"


def _query_fingerprint(query: object) -> StableId:
    """Create the evidence deduplication fingerprint for a typed query."""
    if not isinstance(query, BaseModel):
        raise TypeError("query must be a Pydantic model")
    payload = query.model_dump(mode="json")
    payload.pop("query_id", None)
    canonical = json.dumps(payload, ensure_ascii=True, sort_keys=True, default=str)
    digest = hashlib.sha256(canonical.encode("utf-8")).hexdigest()
    return f"query-fingerprint:{digest}"


def _draft_id(task_id: StableId, entity_id: StableId, fact_type: str) -> StableId:
    """Create an order-independent evidence draft ID."""
    return f"evidence-draft:{task_id}:{entity_id}:{fact_type}"


def _candidate_id(kind: str, entity_id: StableId) -> StableId:
    """Create a deterministic candidate draft ID."""
    return f"candidate:{kind}:{entity_id}"


def _constraint_refs(context: AgentContext) -> tuple[StableId, ...]:
    """Return stable IDs from the frozen constraint snapshot."""
    return tuple(constraint.id for constraint in context.constraint_snapshot.constraints)


def _destination(context: AgentContext) -> str:
    """Use the first request destination as this provider query scope."""
    return context.request.destinations[0]


def _date_range(context: AgentContext) -> DateRange:
    """Require explicit dates; never estimate a missing date."""
    if context.request.date_range is None:
        raise ResearchAgentError(
            context,
            "RESEARCH_DATE_REQUIRED",
            ErrorCategory.VALIDATION,
            "research query requires an explicit date range",
        )
    return context.request.date_range


def _timezone(context: AgentContext) -> timezone | ZoneInfo:
    """Return an available timezone without requiring a system tzdata package."""
    try:
        return ZoneInfo(context.timezone)
    except ZoneInfoNotFoundError:
        fixed_offsets = {
            "UTC": UTC,
            "Asia/Shanghai": timezone(timedelta(hours=8), "Asia/Shanghai"),
        }
        fixed = fixed_offsets.get(context.timezone)
        if fixed is None:
            raise ResearchAgentError(
                context,
                "RESEARCH_TIMEZONE_UNAVAILABLE",
                ErrorCategory.VALIDATION,
                "requested timezone data is unavailable",
            ) from None
        return fixed


def _date_start(context: AgentContext, date_value: date) -> datetime:
    """Convert a date bound to a local timezone day boundary."""
    return datetime.combine(date_value, time.min, tzinfo=_timezone(context))


def _constraint_text(context: AgentContext, categories: set[str]) -> str | None:
    """Read an explicit text constraint without guessing through an LLM."""
    for constraint in context.constraint_snapshot.constraints:
        if constraint.category in categories and isinstance(constraint.normalized_value, str):
            return constraint.normalized_value
    return None


def _transport_mode(context: AgentContext) -> str:
    """Choose one transport mode from explicit text, defaulting to train."""
    values = [*context.request.preferences, *context.request.explicit_exclusions]
    for constraint in context.constraint_snapshot.constraints:
        if constraint.category.casefold() in {"mode", "transport", "transport_mode"}:
            value = constraint.normalized_value
            if isinstance(value, str):
                values.append(value)
            elif isinstance(value, tuple) and all(isinstance(item, str) for item in value):
                values.extend(value)

    normalized = tuple(value.casefold() for value in values)
    flight_requested = any(
        term.casefold() in value for value in normalized for term in _FLIGHT_MODE_TERMS
    )
    train_requested = any(
        term.casefold() in value for value in normalized for term in _TRAIN_MODE_TERMS
    )
    if flight_requested and train_requested:
        raise ValueError("transport mode constraints are ambiguous")
    if flight_requested:
        return "flight"
    return "train"


def _maximum_budget(context: AgentContext) -> Money | None:
    """Pass only an explicit maximum or range upper bound to stay search."""
    budget = context.request.budget
    if budget is None:
        return None
    if budget.semantics in {BudgetSemantics.MAXIMUM, BudgetSemantics.RANGE}:
        return budget.maximum
    return None


def _safe_external_text(context: AgentContext, value: str, field_name: str) -> str:
    """Reject unsafe provider text before later prompt construction."""
    if not value or len(value) > _MAX_TEXT_LENGTH:
        raise ResearchAgentError(
            context,
            "RESEARCH_EXTERNAL_TEXT_INVALID",
            ErrorCategory.VALIDATION,
            f"provider {field_name} is invalid",
        )
    if any(ord(character) < 32 and character not in "\t\n\r" for character in value):
        raise ResearchAgentError(
            context,
            "RESEARCH_EXTERNAL_TEXT_INVALID",
            ErrorCategory.SECURITY,
            "provider text contains unsupported control characters",
        )
    if _PROMPT_INJECTION_PATTERN.search(value):
        raise ResearchAgentError(
            context,
            "RESEARCH_PROMPT_INJECTION",
            ErrorCategory.SECURITY,
            "provider text contains prompt injection content",
        )
    return value


def _registration(
    context: AgentContext,
    query: object,
    *,
    entity_id: StableId,
    fact_type: str,
    value: EvidenceValue,
    provider: str,
    source: str,
    source_ref: str,
    observed_at: datetime,
    ttl_category: EvidenceTtlCategory,
    raw_payload_ref: StableId | None = None,
    valid_until: datetime | None = None,
) -> EvidenceDraft:
    """Build one EvidenceRegistration without writing to storage."""
    registration = EvidenceRegistration(
        entity_id=entity_id,
        fact_type=fact_type,
        value=value,
        provider=provider,
        source=source,
        source_ref=source_ref,
        observed_at=observed_at,
        valid_until=valid_until,
        ttl_category=ttl_category,
        status=EvidenceStatus.VERIFIED,
        confidence=Decimal("1"),
        raw_payload_ref=raw_payload_ref,
        query_fingerprint=_query_fingerprint(query),
        constraint_refs=_constraint_refs(context),
    )
    return EvidenceDraft(
        draft_id=_draft_id(context.task_spec.task_id, entity_id, fact_type),
        registration=registration,
    )


def _provenance(
    provider: str,
    entity_id: StableId,
    source_ref: str,
) -> tuple[CandidateProvenance, ...]:
    """Build candidate provenance fields."""
    return (CandidateProvenance(provider=provider, entity_id=entity_id, source_ref=source_ref),)


def _result(
    context: AgentContext,
    *,
    agent_type: str,
    provider: str,
    query_id: StableId,
    evidence_drafts: list[EvidenceDraft],
    candidate_drafts: list[CandidateDraft],
) -> AgentResult:
    """Build a result using stable draft ordering."""
    evidence = tuple(sorted(evidence_drafts, key=lambda draft: draft.draft_id))
    candidates = tuple(sorted(candidate_drafts, key=lambda draft: draft.candidate_id))
    draft_ids = tuple(draft.draft_id for draft in evidence) + tuple(
        draft.candidate_id for draft in candidates
    )
    return AgentResult(
        task_id=context.task_spec.task_id,
        agent_type=agent_type,
        summary=AgentSummary(
            agent_type=agent_type,
            provider=provider,
            query_id=query_id,
            evidence_draft_count=len(evidence),
            candidate_draft_count=len(candidates),
        ),
        evidence_drafts=evidence,
        candidate_drafts=candidates,
        draft_ids=draft_ids,
        metrics={
            "tool_calls": 1.0,
            "model_calls": 0.0,
            "evidence_draft_count": float(len(evidence)),
            "candidate_draft_count": float(len(candidates)),
        },
    )


class TransportResearchAgent(_ResearchAgentBase):
    """Research transport candidates and transfer windows."""

    capability = "transport"
    agent_type = "transport_research"
    task_type = "transport_research"
    expected_output_type = "CandidateDraft"
    required_tool = "transport_search"
    result_type = TransportProviderResult

    def __init__(self, provider: TransportProvider) -> None:
        super().__init__(provider)

    async def _search(self, query: object, *, timeout_seconds: Decimal) -> TransportProviderResult:
        """Call the TransportProvider port."""
        if not isinstance(query, TransportQuery):
            raise TypeError("transport agent requires TransportQuery")
        return await self._provider.search(query, timeout_seconds=timeout_seconds)

    def _build_query(self, context: AgentContext, *, timeout_seconds: Decimal) -> TransportQuery:
        """Build a transport query from explicit dates and traveler count."""
        date_range = _date_range(context)
        fields: dict[str, object] = {
            "trace_id": context.trace_id,
            "locale": context.locale,
            "timeout_seconds": timeout_seconds,
            "constraint_refs": _constraint_refs(context),
            "origin": context.request.origin,
            "destination": _destination(context),
            "mode": _transport_mode(context),
            "departure_after": _date_start(context, date_range.start),
            "arrival_before": None,
            "travelers": context.request.travelers.total_count,
            "max_results": context.budget.max_results,
        }
        return TransportQuery(
            query_id=_query_id(self.capability, context.task_spec.task_id, fields),
            **fields,
        )

    def _build_result(
        self,
        context: AgentContext,
        query: TransportQuery,
        result: TransportProviderResult,
    ) -> AgentResult:
        """Convert transport provider items to evidence and candidate drafts."""
        evidence_drafts: list[EvidenceDraft] = []
        candidates: list[CandidateDraft] = []
        for item in sorted(result.items, key=lambda value: value.entity_id):
            name = _safe_external_text(context, item.name, "transport name")
            mode = _safe_external_text(context, item.mode, "transport mode")
            origin = _safe_external_text(context, item.origin, "transport origin")
            destination = _safe_external_text(context, item.destination, "transport destination")
            schedule_values = [mode, name, origin, destination]
            if item.departure_station is not None:
                schedule_values.append(f"departure_station={item.departure_station}")
            if item.arrival_station is not None:
                schedule_values.append(f"arrival_station={item.arrival_station}")
            if item.departure_at is not None:
                schedule_values.append(f"departure_at={item.departure_at.isoformat()}")
            if item.arrival_at is not None:
                schedule_values.append(f"arrival_at={item.arrival_at.isoformat()}")
            schedule = _registration(
                context,
                query,
                entity_id=item.entity_id,
                fact_type="transport_schedule",
                value=tuple(schedule_values),
                provider=result.provider,
                source=result.operation,
                source_ref=item.source_ref,
                observed_at=result.observed_at,
                ttl_category=EvidenceTtlCategory.TRANSPORT_SCHEDULE,
                raw_payload_ref=result.raw_payload_ref,
            )
            evidence_drafts.append(schedule)
            refs = [schedule.draft_id]
            price_ref: StableId | None = None
            if item.total_price is not None:
                price = _registration(
                    context,
                    query,
                    entity_id=item.entity_id,
                    fact_type="transport_total_price",
                    value=item.total_price,
                    provider=result.provider,
                    source=result.operation,
                    source_ref=item.source_ref,
                    observed_at=result.observed_at,
                    ttl_category=EvidenceTtlCategory.QUOTE_INVENTORY,
                    raw_payload_ref=result.raw_payload_ref,
                )
                evidence_drafts.append(price)
                refs.append(price.draft_id)
                price_ref = price.draft_id
            candidates.append(
                CandidateDraft(
                    candidate_id=_candidate_id("transport", item.entity_id),
                    kind="transport",
                    entity_id=item.entity_id,
                    name=name,
                    evidence_draft_refs=tuple(refs),
                    price_evidence_draft_ref=price_ref,
                    provenance=_provenance(result.provider, item.entity_id, item.source_ref),
                    timezone=context.timezone,
                    price=item.total_price,
                    mode=mode,
                    origin=origin,
                    destination=destination,
                    departure_at=item.departure_at,
                    arrival_at=item.arrival_at,
                )
            )
        return _result(
            context,
            agent_type=self.agent_type,
            provider=result.provider,
            query_id=query.query_id,
            evidence_drafts=evidence_drafts,
            candidate_drafts=candidates,
        )


class StayResearchAgent(_ResearchAgentBase):
    """Research stay areas, total prices, windows, and terms evidence."""

    capability = "stay"
    agent_type = "stay_research"
    task_type = "stay_research"
    expected_output_type = "CandidateDraft"
    required_tool = "stay_search"
    result_type = StayProviderResult

    def __init__(self, provider: StayProvider) -> None:
        super().__init__(provider)

    async def _search(self, query: object, *, timeout_seconds: Decimal) -> StayProviderResult:
        """Call the StayProvider port."""
        if not isinstance(query, StayQuery):
            raise TypeError("stay agent requires StayQuery")
        return await self._provider.search(query, timeout_seconds=timeout_seconds)

    def _build_query(self, context: AgentContext, *, timeout_seconds: Decimal) -> StayQuery:
        """Build a stay query from explicit dates, travelers, and budget."""
        date_range = _date_range(context)
        area = context.stay_area or _constraint_text(context, {"hotel_area", "stay_area"})
        fields: dict[str, object] = {
            "trace_id": context.trace_id,
            "locale": context.locale,
            "timeout_seconds": timeout_seconds,
            "constraint_refs": _constraint_refs(context),
            "destination": _destination(context),
            "date_range": date_range,
            "travelers": context.request.travelers.total_count,
            "area": area,
            "max_total_price": _maximum_budget(context),
            "max_results": context.budget.max_results,
        }
        return StayQuery(
            query_id=_query_id(self.capability, context.task_spec.task_id, fields),
            **fields,
        )

    def _build_result(
        self,
        context: AgentContext,
        query: StayQuery,
        result: StayProviderResult,
    ) -> AgentResult:
        """Convert stay provider items to evidence and candidate drafts."""
        evidence_drafts: list[EvidenceDraft] = []
        candidates: list[CandidateDraft] = []
        for item in sorted(result.items, key=lambda value: value.entity_id):
            name = _safe_external_text(context, item.name, "stay name")
            area = _safe_external_text(context, item.area, "stay area")
            window_values = [name, area]
            if item.check_in is not None:
                window_values.append(f"check_in={item.check_in.isoformat()}")
            if item.check_out is not None:
                window_values.append(f"check_out={item.check_out.isoformat()}")
            if item.refundable is not None:
                window_values.append(f"refundable={item.refundable}")
            window = _registration(
                context,
                query,
                entity_id=item.entity_id,
                fact_type="stay_option",
                value=tuple(window_values),
                provider=result.provider,
                source=result.operation,
                source_ref=item.source_ref,
                observed_at=result.observed_at,
                ttl_category=EvidenceTtlCategory.QUOTE_INVENTORY,
                raw_payload_ref=result.raw_payload_ref,
            )
            evidence_drafts.append(window)
            refs = [window.draft_id]
            price_ref: StableId | None = None
            if item.total_price is not None:
                price = _registration(
                    context,
                    query,
                    entity_id=item.entity_id,
                    fact_type="stay_total_price",
                    value=item.total_price,
                    provider=result.provider,
                    source=result.operation,
                    source_ref=item.source_ref,
                    observed_at=result.observed_at,
                    ttl_category=EvidenceTtlCategory.QUOTE_INVENTORY,
                    raw_payload_ref=result.raw_payload_ref,
                )
                evidence_drafts.append(price)
                refs.append(price.draft_id)
                price_ref = price.draft_id
            candidates.append(
                CandidateDraft(
                    candidate_id=_candidate_id("stay", item.entity_id),
                    kind="stay",
                    entity_id=item.entity_id,
                    name=name,
                    evidence_draft_refs=tuple(refs),
                    price_evidence_draft_ref=price_ref,
                    provenance=_provenance(result.provider, item.entity_id, item.source_ref),
                    timezone=context.timezone,
                    location=item.location,
                    price=item.total_price,
                    area=area,
                    check_in=item.check_in,
                    check_out=item.check_out,
                )
            )
        return _result(
            context,
            agent_type=self.agent_type,
            provider=result.provider,
            query_id=query.query_id,
            evidence_drafts=evidence_drafts,
            candidate_drafts=candidates,
        )


class PlaceResearchAgent(_ResearchAgentBase):
    """Research places and activities without assigning a visit date."""

    capability = "place"
    agent_type = "place_research"
    task_type = "place_research"
    expected_output_type = "CandidateDraft"
    required_tool = "place_search"
    result_type = PlaceProviderResult

    def __init__(self, provider: PlaceProvider) -> None:
        super().__init__(provider)

    async def _search(self, query: object, *, timeout_seconds: Decimal) -> PlaceProviderResult:
        """Call the PlaceProvider port."""
        if not isinstance(query, PlaceQuery):
            raise TypeError("place agent requires PlaceQuery")
        return await self._provider.search(query, timeout_seconds=timeout_seconds)

    def _build_query(self, context: AgentContext, *, timeout_seconds: Decimal) -> PlaceQuery:
        """Build a place query from an explicit category and date range."""
        category = context.place_category or _constraint_text(
            context, {"place_category", "category"}
        )
        if category is None:
            raise ResearchAgentError(
                context,
                "RESEARCH_PLACE_CATEGORY_REQUIRED",
                ErrorCategory.VALIDATION,
                "place research requires an explicit category",
            )
        fields: dict[str, object] = {
            "trace_id": context.trace_id,
            "locale": context.locale,
            "timeout_seconds": timeout_seconds,
            "constraint_refs": _constraint_refs(context),
            "destination": _destination(context),
            "category": category,
            "date_range": context.request.date_range,
            "center": None,
            "radius_meters": None,
            "max_results": context.budget.max_results,
        }
        return PlaceQuery(
            query_id=_query_id(self.capability, context.task_spec.task_id, fields),
            **fields,
        )

    def _build_result(
        self,
        context: AgentContext,
        query: PlaceQuery,
        result: PlaceProviderResult,
    ) -> AgentResult:
        """Convert place provider items to evidence and candidate drafts."""
        evidence_drafts: list[EvidenceDraft] = []
        candidates: list[CandidateDraft] = []
        for item in sorted(result.items, key=lambda value: value.entity_id):
            name = _safe_external_text(context, item.name, "place name")
            category = _safe_external_text(context, item.category, "place category")
            tags = tuple(_safe_external_text(context, tag, "place tag") for tag in item.tags)
            address = (
                _safe_external_text(context, item.address, "place address")
                if item.address is not None
                else None
            )
            profile_values = [name, category, *tags]
            if address is not None:
                profile_values.append(address)
            profile = _registration(
                context,
                query,
                entity_id=item.entity_id,
                fact_type="place_profile",
                value=tuple(profile_values),
                provider=result.provider,
                source=result.operation,
                source_ref=item.source_ref,
                observed_at=result.observed_at,
                ttl_category=EvidenceTtlCategory.STATIC_GEOGRAPHY,
                raw_payload_ref=result.raw_payload_ref,
            )
            evidence_drafts.append(profile)
            refs = [profile.draft_id]
            if item.location is not None:
                location = _registration(
                    context,
                    query,
                    entity_id=item.entity_id,
                    fact_type="place_location",
                    value=item.location,
                    provider=result.provider,
                    source=result.operation,
                    source_ref=item.source_ref,
                    observed_at=result.observed_at,
                    ttl_category=EvidenceTtlCategory.STATIC_GEOGRAPHY,
                    raw_payload_ref=result.raw_payload_ref,
                )
                evidence_drafts.append(location)
                refs.append(location.draft_id)
            price_ref: StableId | None = None
            if item.total_price is not None:
                price = _registration(
                    context,
                    query,
                    entity_id=item.entity_id,
                    fact_type="place_total_price",
                    value=item.total_price,
                    provider=result.provider,
                    source=result.operation,
                    source_ref=item.source_ref,
                    observed_at=result.observed_at,
                    ttl_category=EvidenceTtlCategory.QUOTE_INVENTORY,
                    raw_payload_ref=result.raw_payload_ref,
                )
                evidence_drafts.append(price)
                refs.append(price.draft_id)
                price_ref = price.draft_id
            candidates.append(
                CandidateDraft(
                    candidate_id=_candidate_id("place", item.entity_id),
                    kind="place",
                    entity_id=item.entity_id,
                    name=name,
                    evidence_draft_refs=tuple(refs),
                    price_evidence_draft_ref=price_ref,
                    provenance=_provenance(result.provider, item.entity_id, item.source_ref),
                    timezone=context.timezone,
                    tags=tags,
                    location=item.location,
                    price=item.total_price,
                    category=category,
                    address=address,
                )
            )
        return _result(
            context,
            agent_type=self.agent_type,
            provider=result.provider,
            query_id=query.query_id,
            evidence_drafts=evidence_drafts,
            candidate_drafts=candidates,
        )


class ContextPolicyAgent(_ResearchAgentBase):
    """Research weather, events, exchange rates, policy, and safety facts."""

    capability = "context"
    agent_type = "context_policy_research"
    task_type = "context_research"
    expected_output_type = "EvidenceDraft"
    required_tool = "context_search"
    result_type = ContextProviderResult

    def __init__(self, provider: ContextProvider) -> None:
        super().__init__(provider)

    async def _search(self, query: object, *, timeout_seconds: Decimal) -> ContextProviderResult:
        """Call the ContextProvider port."""
        if not isinstance(query, ContextQuery):
            raise TypeError("context agent requires ContextQuery")
        return await self._provider.search(query, timeout_seconds=timeout_seconds)

    def _build_query(self, context: AgentContext, *, timeout_seconds: Decimal) -> ContextQuery:
        """Build a context query only from explicit context types."""
        if not context.context_types:
            raise ResearchAgentError(
                context,
                "RESEARCH_CONTEXT_TYPES_REQUIRED",
                ErrorCategory.VALIDATION,
                "context research requires explicit context types",
            )
        fields: dict[str, object] = {
            "trace_id": context.trace_id,
            "locale": context.locale,
            "timeout_seconds": timeout_seconds,
            "constraint_refs": _constraint_refs(context),
            "scope": context.request.trip_id,
            "date_range": context.request.date_range,
            "context_types": context.context_types,
        }
        return ContextQuery(
            query_id=_query_id(self.capability, context.task_spec.task_id, fields),
            **fields,
        )

    def _build_result(
        self,
        context: AgentContext,
        query: ContextQuery,
        result: ContextProviderResult,
    ) -> AgentResult:
        """Convert context provider items to evidence drafts."""
        evidence_drafts: list[EvidenceDraft] = []
        for item in sorted(result.items, key=lambda value: value.entity_id):
            summary = _safe_external_text(context, item.summary, "context summary")
            context_type = _safe_external_text(context, item.context_type, "context type")
            values = [context_type, summary]
            if item.valid_from is not None:
                values.append(f"valid_from={item.valid_from.isoformat()}")
            if item.valid_until is not None:
                values.append(f"valid_until={item.valid_until.isoformat()}")
            if item.severity is not None:
                values.append(_safe_external_text(context, item.severity, "context severity"))
            evidence_drafts.append(
                _registration(
                    context,
                    query,
                    entity_id=item.entity_id,
                    fact_type=f"context_{context_type}",
                    value=tuple(values),
                    provider=result.provider,
                    source=result.operation,
                    source_ref=item.source_ref,
                    observed_at=result.observed_at,
                    valid_until=item.valid_until,
                    ttl_category=_context_ttl_category(context_type),
                    raw_payload_ref=result.raw_payload_ref,
                )
            )
        return _result(
            context,
            agent_type=self.agent_type,
            provider=result.provider,
            query_id=query.query_id,
            evidence_drafts=evidence_drafts,
            candidate_drafts=[],
        )


def _context_ttl_category(context_type: str) -> EvidenceTtlCategory:
    """Choose an existing M3 TTL category for a context fact."""
    normalized = context_type.casefold()
    if normalized == "weather":
        return EvidenceTtlCategory.WEATHER_FORECAST
    if normalized in {"exchange_rate", "currency", "\u6c47\u7387"}:
        return EvidenceTtlCategory.EXCHANGE_RATE
    return EvidenceTtlCategory.BUSINESS_HOURS_POLICY


__all__ = [
    "ContextPolicyAgent",
    "PlaceResearchAgent",
    "ResearchAgentError",
    "StayResearchAgent",
    "TransportResearchAgent",
]
