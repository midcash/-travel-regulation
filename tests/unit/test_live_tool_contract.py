from __future__ import annotations

import json
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path

import pytest

from src.domain.models.provider import GeoProviderResult, GeoResultItem
from src.domain.models.value_objects import GeoPoint
from src.ports.tool_errors import ToolEmptyResultError
from tests.support import live_tool_contract as live_support


def _result() -> GeoProviderResult:
    return GeoProviderResult(
        query_id="live-test-query",
        provider="amap",
        operation="geo_search",
        observed_at=datetime(2026, 8, 1, 9, tzinfo=UTC),
        source_ref="https://mock.example/amap",
        items=(
            GeoResultItem(
                entity_id="place-1",
                name="Test Place",
                location=GeoPoint(latitude=30, longitude=120),
                confidence=Decimal("0.9"),
            ),
        ),
    )


def test_execute_live_call_records_normal_and_expected_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    live_support.reset_records()
    monkeypatch.setenv("AMAP_API_KEY", "live-test-key")
    monkeypatch.delenv("TUNIU_API_KEY", raising=False)

    requests = 0

    def normal_call() -> GeoProviderResult:
        return _result()

    result = live_support.execute_live_call(
        provider="amap",
        operation="geo_search",
        scenario="normal",
        call=normal_call,
        request_count=lambda: requests + 1,
    )

    assert result == _result()

    def empty_call() -> GeoProviderResult:
        raise ToolEmptyResultError(
            provider="amap",
            operation="geo_search",
            safe_message="provider returned no usable results",
        )

    empty_result = live_support.execute_live_call(
        provider="amap",
        operation="geo_search",
        scenario="empty",
        call=empty_call,
        request_count=lambda: 1,
        expected_exception=ToolEmptyResultError,
    )

    assert empty_result is None
    assert len(live_support._records) == 2
    assert live_support._records[1].outcome == "expected_failure"


def test_write_report_requires_all_enabled_provider_scenarios(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    live_support.reset_records()
    monkeypatch.setattr(live_support, "REPORT_PATH", tmp_path / "live-tool.json")
    monkeypatch.delenv("AMAP_API_KEY", raising=False)
    monkeypatch.delenv("TUNIU_API_KEY", raising=False)

    live_support.write_report(exit_status=0)

    report = json.loads((tmp_path / "live-tool.json").read_text(encoding="utf-8"))
    assert report["status"] == "PENDING_MANUAL_ACCEPTANCE"
    assert report["missing_provider_keys"] == ["amap", "tuniu"]
    assert report["redaction"] == {
        "raw_payloads": False,
        "credentials": False,
        "failure_summary": "exception type only",
    }
