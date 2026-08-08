"""M4 Live Vertical Slice redacted report contracts."""

from __future__ import annotations

import json
import os
from dataclasses import asdict, dataclass
from pathlib import Path

REPORT_PATH = Path("evaluation/reports/M4-live-vertical-slice.json")
SCHEMA_VERSION = "m4.live-vertical-slice.v1"
PROMPT_VERSION = "m4-itinerary-composer-v2"
EXPECTED_RUNS: tuple[tuple[str, int], ...] = (
    ("m4-live-normal", 1),
    ("m4-live-normal", 2),
    ("m4-live-constraint", 1),
    ("m4-live-complex", 1),
)


@dataclass(frozen=True, slots=True)
class M4LiveObservation:
    """One safe observation from a manually executed live case."""

    case_id: str
    repetition: int
    status: str
    trace_id: str | None
    model: str | None
    providers: tuple[str, ...]
    llm_calls: int
    input_tokens: int
    output_tokens: int
    latency_ms: int
    tool_calls: int
    model_calls: int
    graph_task_count: int
    candidate_count: int
    plan_count: int
    references_complete: bool
    hard_constraints_complete: bool
    hard_budget_within_limit: bool
    failure_type: str | None = None


def build_report(
    observations: tuple[M4LiveObservation, ...],
    *,
    exit_status: int,
    configured_providers: tuple[str, ...],
    model: str | None,
    failure_summary: str | None = None,
    run_executed: bool = True,
) -> dict[str, object]:
    """Build a redacted M4 live report without credentials or raw payloads."""
    expected_keys = set(EXPECTED_RUNS)
    observed_keys = {(item.case_id, item.repetition) for item in observations}
    missing_credentials = tuple(
        name for name in ("DEEPSEEK_API_KEY", "TUNIU_API_KEY") if not os.environ.get(name)
    )
    all_observations_valid = all(
        item.status == "success"
        and item.references_complete
        and item.hard_constraints_complete
        and item.hard_budget_within_limit
        and item.failure_type is None
        for item in observations
    )
    if not run_executed:
        status = "PENDING_MANUAL_ACCEPTANCE"
    elif (
        exit_status == 0
        and not missing_credentials
        and observed_keys == expected_keys
        and all_observations_valid
    ):
        status = "SUCCESS"
    else:
        status = "FAILED"

    return {
        "stage": "M4",
        "status": status,
        "gate": "live_vertical_slice",
        "schema_version": SCHEMA_VERSION,
        "prompt_version": PROMPT_VERSION,
        "model": model,
        "configured_providers": configured_providers,
        "expected_runs": [
            {"case_id": case_id, "repetition": repetition} for case_id, repetition in EXPECTED_RUNS
        ],
        "budget": {
            "retry_count": 0,
            "cache_reads": False,
            "fallbacks": False,
            "partial_success": False,
            "fixed_per_case": True,
        },
        "observations": [asdict(item) for item in observations],
        "failure_summary": failure_summary,
        "missing_credentials": missing_credentials,
        "redaction": {
            "raw_payloads": False,
            "credentials": False,
            "full_prompts": False,
            "pii": False,
            "failure_summary": "exception type only",
        },
    }


def write_report(report: dict[str, object], *, path: Path = REPORT_PATH) -> None:
    """Persist one explicitly requested redacted report."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
