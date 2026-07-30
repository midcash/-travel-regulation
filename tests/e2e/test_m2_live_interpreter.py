from __future__ import annotations

import json
from pathlib import Path

import pytest

from evaluation.m2_live_interpreter import run_m2_live_gate

pytestmark = [pytest.mark.slow, pytest.mark.live_llm]

REPORT_PATH = Path("evaluation/reports/M2-live-interpreter.json")


def test_m2_live_interpreter_gate_passes() -> None:
    report = run_m2_live_gate()
    REPORT_PATH.parent.mkdir(parents=True, exist_ok=True)
    REPORT_PATH.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n")

    assert report["status"] == "SUCCESS", report["failures"]
    assert report["execution"]["run_count"] == 18
    assert report["execution"]["network_calls"] == 14
    assert report["budget"]["retry_count"] == 0
    assert report["metrics"]["schema_pass_rate"] == 1.0
