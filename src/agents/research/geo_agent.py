"""M4 geographic Research Agent."""

from __future__ import annotations

import asyncio
from decimal import Decimal

from pydantic import ValidationError

from src.domain.models.enums import ErrorCategory, EvidenceTtlCategory
from src.domain.models.provider import GeoProviderResult, GeoQuery
from src.ports.tool_errors import ToolEmptyResultError, ToolError
from src.ports.tool_provider import GeoProvider

from .agents import (
    ResearchAgentError,
    _constraint_refs,
    _query_id,
    _registration,
    _ResearchAgentBase,
    _safe_external_text,
)
from .contracts import AgentContext, AgentResult, AgentSummary, EvidenceDraft


class GeoResearchAgent(_ResearchAgentBase):
    """Resolve every trip location into verified geographic evidence."""

    capability = "geo"
    agent_type = "geo_research"
    task_type = "geo_research"
    expected_output_type = "EvidenceDraft"
    required_tool = "geo_search"
    result_type = GeoProviderResult

    def __init__(self, provider: GeoProvider) -> None:
        super().__init__(provider)

    async def _search(self, query: object, *, timeout_seconds: Decimal) -> GeoProviderResult:
        """Call the GeoProvider port for one location."""
        if not isinstance(query, GeoQuery):
            raise TypeError("geo agent requires GeoQuery")
        return await self._provider.search(query, timeout_seconds=timeout_seconds)

    async def run(self, context: AgentContext) -> AgentResult:
        """Resolve locations sequentially without returning partial success."""
        if not isinstance(context, AgentContext):
            raise TypeError("context must be an AgentContext")
        self._validate_context(context)
        locations = tuple(dict.fromkeys((context.request.origin, *context.request.destinations)))
        if not locations:
            raise ResearchAgentError(
                context,
                "RESEARCH_GEO_LOCATIONS_REQUIRED",
                ErrorCategory.VALIDATION,
                "geo research requires at least one location",
            )
        if len(locations) > context.budget.max_tool_calls:
            raise ResearchAgentError(
                context,
                "BUDGET_EXHAUSTED",
                ErrorCategory.BUDGET,
                "geo research location count exceeds the tool-call budget",
            )

        timeout_seconds = min(
            context.budget.timeout_seconds,
            Decimal(str(context.task_spec.timeout)),
        )
        queries = tuple(
            _geo_query(context, location, timeout_seconds=timeout_seconds)
            for location in locations
        )
        aggregate_query_id = _query_id(
            self.capability,
            context.task_spec.task_id,
            {"locations": locations, "timeout_seconds": timeout_seconds},
        )
        evidence_drafts: list[EvidenceDraft] = []
        provider_name: str | None = None
        for index, query in enumerate(queries):
            result = await self._run_geo_query(
                context,
                query,
                timeout_seconds=timeout_seconds,
            )
            provider_name = provider_name or result.provider
            for item in sorted(result.items, key=lambda value: value.entity_id):
                name = _safe_external_text(context, item.name, "geo name")
                address = (
                    _safe_external_text(context, item.address, "geo address")
                    if item.address is not None
                    else None
                )
                profile_values = [name]
                if address is not None:
                    profile_values.append(address)
                evidence_drafts.extend(
                    (
                        _registration(
                            context,
                            query,
                            entity_id=item.entity_id,
                            fact_type=f"geo_profile_{index}",
                            value=tuple(profile_values),
                            provider=result.provider,
                            source=result.operation,
                            source_ref=result.source_ref,
                            observed_at=result.observed_at,
                            ttl_category=EvidenceTtlCategory.STATIC_GEOGRAPHY,
                            raw_payload_ref=result.raw_payload_ref,
                        ),
                        _registration(
                            context,
                            query,
                            entity_id=item.entity_id,
                            fact_type=f"geo_location_{index}",
                            value=item.location,
                            provider=result.provider,
                            source=result.operation,
                            source_ref=result.source_ref,
                            observed_at=result.observed_at,
                            ttl_category=EvidenceTtlCategory.STATIC_GEOGRAPHY,
                            raw_payload_ref=result.raw_payload_ref,
                        ),
                    )
                )

        evidence = tuple(sorted(evidence_drafts, key=lambda draft: draft.draft_id))
        return AgentResult(
            task_id=context.task_spec.task_id,
            agent_type=self.agent_type,
            summary=AgentSummary(
                agent_type=self.agent_type,
                provider=provider_name or "geo",
                query_id=aggregate_query_id,
                evidence_draft_count=len(evidence),
                candidate_draft_count=0,
            ),
            evidence_drafts=evidence,
            candidate_drafts=(),
            draft_ids=tuple(draft.draft_id for draft in evidence),
            metrics={
                "tool_calls": float(len(queries)),
                "model_calls": 0.0,
                "evidence_draft_count": float(len(evidence)),
                "candidate_draft_count": 0.0,
            },
        )

    async def _run_geo_query(
        self,
        context: AgentContext,
        query: GeoQuery,
        *,
        timeout_seconds: Decimal,
    ) -> GeoProviderResult:
        """Execute one Geo query and preserve the standard error taxonomy."""
        try:
            result = await asyncio.wait_for(
                self._search(query, timeout_seconds=timeout_seconds),
                timeout=float(timeout_seconds),
            )
            if not isinstance(result, GeoProviderResult):
                raise ResearchAgentError(
                    context,
                    "RESEARCH_RESULT_SCHEMA_INVALID",
                    ErrorCategory.VALIDATION,
                    "research provider returned an invalid result schema",
                    upstream_refs=(query.query_id,),
                )
            if not result.items:
                raise ToolEmptyResultError(
                    provider="research_agent",
                    operation=self.required_tool,
                    safe_message="research provider returned no usable results",
                    trace_id=context.trace_id,
                    query_id=query.query_id,
                )
            return result
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
                upstream_refs=(exc.query_id or query.query_id,),
                retryable=exc.retryable,
                cause=exc,
            ) from exc
        except TimeoutError as exc:
            raise ResearchAgentError(
                context,
                "RESEARCH_TIMEOUT",
                ErrorCategory.TIMEOUT,
                "research agent timed out",
                upstream_refs=(query.query_id,),
                cause=exc,
            ) from exc
        except ValidationError as exc:
            raise ResearchAgentError(
                context,
                "RESEARCH_OUTPUT_SCHEMA_INVALID",
                ErrorCategory.VALIDATION,
                "research agent output failed schema validation",
                upstream_refs=(query.query_id,),
                cause=exc,
            ) from exc
        except Exception as exc:
            raise ResearchAgentError(
                context,
                "RESEARCH_PROVIDER_ERROR",
                ErrorCategory.TOOL,
                "research provider call failed",
                upstream_refs=(query.query_id,),
                cause=exc,
            ) from exc


def _geo_query(
    context: AgentContext,
    location: str,
    *,
    timeout_seconds: Decimal,
) -> GeoQuery:
    """Build one deterministic geographic query from a location string."""
    fields: dict[str, object] = {
        "trace_id": context.trace_id,
        "locale": context.locale,
        "timeout_seconds": timeout_seconds,
        "constraint_refs": _constraint_refs(context),
        "text": location,
        "region": None,
    }
    return GeoQuery(
        query_id=_query_id("geo", context.task_spec.task_id, fields),
        **fields,
    )


__all__ = ["GeoResearchAgent"]
