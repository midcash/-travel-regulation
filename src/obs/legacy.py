"""Legacy planner review and revision observation helpers."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field

from src.obs.log import get_logger

logger = get_logger(__name__)


@dataclass(frozen=True, slots=True)
class LegacyReviewObservation:
    """Safe references emitted for one legacy review round."""

    round: int
    l1_issue_refs: tuple[str, ...]
    l2_issue_refs: tuple[str, ...]
    issue_refs: tuple[str, ...]
    issue_summary_ref: str | None
    trigger_sources: tuple[str, ...]


@dataclass(slots=True)
class IssueReferenceRegistry:
    """Map issue text to opaque, run-local references without storing the text."""

    _issue_refs: dict[tuple[str, str], str] = field(default_factory=dict)
    _summary_refs: dict[tuple[str, ...], str] = field(default_factory=dict)
    _next_issue: int = 1
    _next_summary: int = 1

    def references(self, source: str, issues: Sequence[str]) -> tuple[str, ...]:
        """Return stable references for issues from one review source."""
        return tuple(self._reference(source, issue) for issue in issues)

    def summary_reference(self, issue_refs: Sequence[str]) -> str | None:
        """Return an opaque reference for a bounded set of review issues."""
        normalized = tuple(issue_refs)
        if not normalized:
            return None
        if normalized not in self._summary_refs:
            self._summary_refs[normalized] = f"legacy-summary-{self._next_summary:04d}"
            self._next_summary += 1
        return self._summary_refs[normalized]

    def _reference(self, source: str, issue: str) -> str:
        key = (source, issue)
        reference = self._issue_refs.get(key)
        if reference is None:
            reference = f"legacy-issue-{self._next_issue:04d}"
            self._next_issue += 1
            self._issue_refs[key] = reference
        return reference


def record_legacy_review(
    registry: IssueReferenceRegistry,
    *,
    round: int,
    l1_issues: Sequence[str],
    l2_passed: bool,
    l2_issues: Sequence[str],
    duration_ms: int,
) -> LegacyReviewObservation:
    """Emit a safe review-completed event and return its issue references."""
    l1_issue_refs = registry.references("l1", l1_issues)
    l2_issue_refs = registry.references("l2", l2_issues)
    issue_refs = l1_issue_refs + l2_issue_refs
    trigger_sources = tuple(
        source for source, refs in (("l1", l1_issue_refs), ("l2", l2_issue_refs)) if refs
    )
    observation = LegacyReviewObservation(
        round=round,
        l1_issue_refs=l1_issue_refs,
        l2_issue_refs=l2_issue_refs,
        issue_refs=issue_refs,
        issue_summary_ref=registry.summary_reference(issue_refs),
        trigger_sources=trigger_sources,
    )
    logger.info(
        "legacy_review_completed",
        stage="legacy_critic",
        status="completed",
        duration_ms=duration_ms,
        round=round,
        l1_passed=not l1_issue_refs,
        l1_issue_count=len(l1_issue_refs),
        l1_issue_refs=list(l1_issue_refs),
        l2_passed=l2_passed,
        l2_issue_count=len(l2_issue_refs),
        l2_issue_refs=list(l2_issue_refs),
        issue_refs=list(issue_refs),
        issue_summary_ref=observation.issue_summary_ref,
    )
    return observation


def record_legacy_revision_requested(observation: LegacyReviewObservation) -> None:
    """Emit the safe reason references that triggered one revision."""
    logger.info(
        "legacy_revision_requested",
        stage="legacy_revision",
        status="requested",
        duration_ms=0,
        round=observation.round,
        trigger_sources=list(observation.trigger_sources),
        issue_refs=list(observation.issue_refs),
        issue_summary_ref=observation.issue_summary_ref,
    )


def record_legacy_revision_completed(
    *,
    round: int,
    duration_ms: int,
    output_chars: int,
) -> None:
    """Emit revision completion metadata without the generated plan."""
    logger.info(
        "legacy_revision_completed",
        stage="legacy_revision",
        status="completed",
        duration_ms=duration_ms,
        round=round,
        output_chars=output_chars,
    )


def record_legacy_revision_exhausted(observation: LegacyReviewObservation) -> None:
    """Emit unresolved issue references before preserving fail-fast behavior."""
    logger.warning(
        "legacy_revision_exhausted",
        stage="legacy_revision",
        status="failed",
        duration_ms=0,
        round=observation.round,
        trigger_sources=list(observation.trigger_sources),
        issue_refs=list(observation.issue_refs),
        issue_summary_ref=observation.issue_summary_ref,
    )
