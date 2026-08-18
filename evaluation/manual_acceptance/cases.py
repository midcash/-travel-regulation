from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from evaluation.manual_acceptance.contracts import (
    BusinessTransitionBaseline,
    HumanDecision,
    ManualCase,
)


class ManualCaseError(ValueError):
    """A manual-acceptance case does not satisfy its frozen contract."""


_REQUIRED_FIELDS = frozenset(
    {
        "case_id",
        "stage",
        "input",
        "reference_now",
        "expected_stage_behavior",
        "expected_key_fields",
        "expected_failure_or_success_semantics",
        "human_assertions",
        "historical_contract_acceptance",
        "business_transition_baseline",
        "required_outputs",
        "mutation_target",
        "independent_review_prompt",
    }
)


def load_case(path: Path) -> ManualCase:
    """Load one frozen manual case without accepting runtime output fields."""
    try:
        raw: Any = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ManualCaseError(f"cannot load manual case: {path}") from exc
    if not isinstance(raw, dict) or set(raw) != _REQUIRED_FIELDS:
        raise ManualCaseError(f"manual case schema mismatch: {path}")
    try:
        case = ManualCase(
            case_id=_required_text(raw, "case_id"),
            stage=_required_text(raw, "stage"),
            input=_required_text(raw, "input"),
            reference_now=_required_text(raw, "reference_now"),
            expected_stage_behavior=_required_text(raw, "expected_stage_behavior"),
            expected_key_fields=_required_object(raw, "expected_key_fields"),
            expected_failure_or_success_semantics=_required_text(
                raw, "expected_failure_or_success_semantics"
            ),
            human_assertions=_required_texts(raw, "human_assertions"),
            historical_contract_acceptance=HumanDecision(
                _required_text(raw, "historical_contract_acceptance")
            ),
            business_transition_baseline=BusinessTransitionBaseline(
                _required_text(raw, "business_transition_baseline")
            ),
            required_outputs=_required_texts(raw, "required_outputs"),
            mutation_target=_required_text(raw, "mutation_target"),
            independent_review_prompt=_required_text(raw, "independent_review_prompt"),
        )
    except (TypeError, ValueError) as exc:
        raise ManualCaseError(f"invalid manual case: {path}") from exc
    return case


def _required_text(raw: dict[str, Any], field: str) -> str:
    value = raw[field]
    if not isinstance(value, str) or not value.strip():
        raise ManualCaseError(f"{field} must be a non-empty string")
    return value


def _required_texts(raw: dict[str, Any], field: str) -> tuple[str, ...]:
    value = raw[field]
    if (
        not isinstance(value, list)
        or not value
        or not all(isinstance(item, str) and item.strip() for item in value)
    ):
        raise ManualCaseError(f"{field} must be a non-empty string list")
    return tuple(value)


def _required_object(raw: dict[str, Any], field: str) -> dict[str, Any]:
    value = raw[field]
    if not isinstance(value, dict) or not value:
        raise ManualCaseError(f"{field} must be a non-empty object")
    return value
