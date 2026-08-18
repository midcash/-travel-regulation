from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml  # type: ignore[import-untyped]

from evaluation.manual_acceptance.contracts import (
    BusinessTransitionBaseline,
    HumanDecision,
    IndependentReviewResult,
    ManualCase,
    MutationResult,
)


class HumanReviewError(ValueError):
    """The human review record is missing or malformed."""


@dataclass(frozen=True, slots=True)
class HumanReview:
    stage: str
    case_id: str
    run_id: str
    reviewer: str
    reviewed_at: str
    checked_assertions: tuple[str, ...]
    observed_differences: tuple[str, ...]
    mutation_result: MutationResult
    independent_review_result: IndependentReviewResult
    historical_contract_acceptance: HumanDecision
    business_transition_baseline: BusinessTransitionBaseline
    decision: HumanDecision
    reason: str


def render_human_review(case: ManualCase, *, run_id: str) -> str:
    """Create a pending, human-editable review record."""
    fields = {
        "stage": case.stage,
        "case_id": case.case_id,
        "run_id": run_id,
        "reviewer": "PENDING",
        "reviewed_at": "PENDING",
        "checked_assertions": [],
        "observed_differences": [],
        "mutation_result": MutationResult.NOT_RUN.value,
        "independent_review_result": IndependentReviewResult.NOT_RUN.value,
        "historical_contract_acceptance": HumanDecision.PENDING.value,
        "business_transition_baseline": case.business_transition_baseline.value,
        "decision": HumanDecision.PENDING.value,
        "reason": "PENDING: complete this record after manual and independent review.",
    }
    lines = ["---"]
    for key, value in fields.items():
        rendered = json.dumps(value, ensure_ascii=False) if isinstance(value, list | str) else value
        lines.append(f"{key}: {rendered}")
    lines.extend(
        [
            "---",
            "",
            "## Human assertions",
            "",
            *[f"- {assertion}" for assertion in case.human_assertions],
            "",
            "## Mutation target",
            "",
            case.mutation_target,
            "",
            "## Independent review prompt",
            "",
            case.independent_review_prompt,
            "",
        ]
    )
    return "\n".join(lines)


def parse_human_review(path: Path) -> HumanReview:
    """Parse only the structured front matter used by ``verify``."""
    try:
        content = path.read_text(encoding="utf-8")
    except OSError as exc:
        raise HumanReviewError(f"cannot read human review: {path}") from exc
    if not content.startswith("---\n"):
        raise HumanReviewError("human review must start with YAML front matter")
    try:
        closing_marker = content.find("\n---", 4)
        if closing_marker < 0:
            raise ValueError("missing closing front matter marker")
        front_matter = content[4:closing_marker]
        raw: Any = yaml.safe_load(front_matter)
    except (ValueError, yaml.YAMLError) as exc:
        raise HumanReviewError("invalid human review front matter") from exc
    if not isinstance(raw, dict):
        raise HumanReviewError("human review front matter must be an object")
    try:
        return HumanReview(
            stage=_text(raw, "stage"),
            case_id=_text(raw, "case_id"),
            run_id=_text(raw, "run_id"),
            reviewer=_text(raw, "reviewer"),
            reviewed_at=_text(raw, "reviewed_at"),
            checked_assertions=_texts(raw, "checked_assertions"),
            observed_differences=_texts(raw, "observed_differences"),
            mutation_result=MutationResult(_text(raw, "mutation_result")),
            independent_review_result=IndependentReviewResult(
                _text(raw, "independent_review_result")
            ),
            historical_contract_acceptance=HumanDecision(
                _text(raw, "historical_contract_acceptance")
            ),
            business_transition_baseline=BusinessTransitionBaseline(
                _text(raw, "business_transition_baseline")
            ),
            decision=HumanDecision(_text(raw, "decision")),
            reason=_text(raw, "reason"),
        )
    except (TypeError, ValueError) as exc:
        raise HumanReviewError("invalid human review field") from exc


def _text(raw: dict[str, Any], field: str) -> str:
    value = raw.get(field)
    if not isinstance(value, str) or not value.strip():
        raise HumanReviewError(f"{field} must be a non-empty string")
    return value.strip()


def _texts(raw: dict[str, Any], field: str) -> tuple[str, ...]:
    value = raw.get(field)
    if not isinstance(value, list) or not all(isinstance(item, str) for item in value):
        raise HumanReviewError(f"{field} must be a string list")
    return tuple(item.strip() for item in value if item.strip())
