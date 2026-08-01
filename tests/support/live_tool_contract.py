"""Shared assertions and redacted reporting for M3 live tool contracts."""

from __future__ import annotations

import json
import os
from collections.abc import Callable
from dataclasses import asdict, dataclass
from pathlib import Path
from time import perf_counter
from typing import TypeVar

from src.domain.models.provider import ProviderResultBase

ResultT = TypeVar("ResultT", bound=ProviderResultBase)
REPORT_PATH = Path("evaluation/reports/live-tool-contract.json")
REQUIRED_PROVIDERS = ("amap", "tuniu")
REQUIRED_SCENARIOS = ("normal", "empty")


@dataclass(frozen=True, slots=True)
class LiveToolRecord:
    """One safe, low-cardinality observation from a live contract call."""

    provider: str
    operation: str
    scenario: str
    status: str
    outcome: str
    schema_version: str | None
    latency_ms: int
    cost: float | None
    cost_status: str
    call_count: int
    failure_type: str | None


_records: list[LiveToolRecord] = []


def reset_records() -> None:
    """Clear process-local records between report tests."""
    _records.clear()


def assert_provider_result_contract(
    result: ProviderResultBase,
    *,
    provider: str,
    operation: str,
    source_ref: str,
    api_key: str,
) -> None:
    """Apply the same normalized-result assertions to Fake and live adapters."""
    assert result.provider == provider
    assert result.operation == operation
    assert result.source_ref == source_ref
    assert result.schema_version == "m3.provider.v1"
    items = getattr(result, "items", ())
    assert items
    assert all(item.external_text_trust == "untrusted" for item in items)
    assert api_key not in result.model_dump_json()


def execute_live_call(
    *,
    provider: str,
    operation: str,
    scenario: str,
    call: Callable[[], ResultT],
    request_count: Callable[[], int],
    expected_exception: type[Exception] | None = None,
) -> ResultT | None:
    """Run one live call and record only safe contract metadata."""
    started = perf_counter()
    try:
        result = call()
    except Exception as exc:
        latency_ms = _elapsed_ms(started)
        count = request_count()
        if expected_exception is not None and isinstance(exc, expected_exception):
            _records.append(
                LiveToolRecord(
                    provider=provider,
                    operation=operation,
                    scenario=scenario,
                    status="success",
                    outcome="expected_failure",
                    schema_version=None,
                    latency_ms=latency_ms,
                    cost=None,
                    cost_status="not_exposed_by_provider_contract",
                    call_count=count,
                    failure_type=expected_exception.__name__,
                )
            )
            return None
        _records.append(
            LiveToolRecord(
                provider=provider,
                operation=operation,
                scenario=scenario,
                status="failure",
                outcome="unexpected_failure",
                schema_version=None,
                latency_ms=latency_ms,
                cost=None,
                cost_status="not_exposed_by_provider_contract",
                call_count=count,
                failure_type=type(exc).__name__,
            )
        )
        raise

    _records.append(
        LiveToolRecord(
            provider=provider,
            operation=operation,
            scenario=scenario,
            status="success",
            outcome="success",
            schema_version=result.schema_version,
            latency_ms=_elapsed_ms(started),
            cost=None,
            cost_status="not_exposed_by_provider_contract",
            call_count=request_count(),
            failure_type=None,
        )
    )
    return result


def write_report(*, exit_status: int) -> None:
    """Write a redacted report after an explicitly selected live-tool run."""
    records = tuple(_records)
    missing_keys = tuple(
        provider
        for provider in REQUIRED_PROVIDERS
        if not os.environ.get(f"{provider.upper()}_API_KEY")
    )
    expected_keys = {
        (provider, scenario)
        for provider in REQUIRED_PROVIDERS
        if provider not in missing_keys
        for scenario in REQUIRED_SCENARIOS
    }
    recorded_keys = {(record.provider, record.scenario) for record in records}
    records_valid = all(
        record.status == "success" and record.call_count == 1 for record in records
    )
    if exit_status != 0 or not records_valid:
        status = "FAILED"
    elif missing_keys or expected_keys - recorded_keys:
        status = "PENDING_MANUAL_ACCEPTANCE"
    else:
        status = "SUCCESS"

    report = {
        "stage": "M3",
        "status": status,
        "contract": "live_tool",
        "required_providers": REQUIRED_PROVIDERS,
        "missing_provider_keys": missing_keys,
        "network_calls": sum(record.call_count for record in records),
        "calls": [asdict(record) for record in records],
        "redaction": {
            "raw_payloads": False,
            "credentials": False,
            "failure_summary": "exception type only",
        },
    }
    REPORT_PATH.parent.mkdir(parents=True, exist_ok=True)
    REPORT_PATH.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n")


def _elapsed_ms(started: float) -> int:
    """Return a non-negative monotonic duration in milliseconds."""
    return max(0, int((perf_counter() - started) * 1000))
