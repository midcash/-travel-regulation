from __future__ import annotations

import json
from dataclasses import asdict
from pathlib import Path

import pytest

from src.bootstrap import bootstrap_settings
from src.config import Settings
from src.gateway.deepseek import LLMCallRecord, ask_llm
from src.gateway.json_utils import parse_json_object

pytestmark = [pytest.mark.slow, pytest.mark.live_llm]

REPORT_PATH = Path('evaluation/reports/live-llm-smoke.json')
_records: list[LLMCallRecord] = []
_bootstrap_failure: dict[str, str] | None = None


@pytest.fixture(scope='module', autouse=True)
def write_live_report() -> None:
    """在 Live Smoke 结束后写入脱敏的可复现摘要。"""
    yield
    REPORT_PATH.parent.mkdir(parents=True, exist_ok=True)
    report = {
        'status': (
            'SUCCESS'
            if not _bootstrap_failure
            and len(_records) == 2
            and all(record.status == 'success' for record in _records)
            else 'FAILED'
        ),
        'model': _records[0].model if _records else None,
        'calls': [asdict(record) for record in _records],
        'failure': _bootstrap_failure,
        'network_calls': len(_records),
    }
    REPORT_PATH.write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n')


@pytest.fixture(scope='module')
def live_settings() -> Settings:
    global _bootstrap_failure
    try:
        return bootstrap_settings()
    except Exception as exc:
        _bootstrap_failure = {
            'stage': 'bootstrap',
            'failure_type': type(exc).__name__,
        }
        pytest.fail('Live LLM Smoke requires a valid DEEPSEEK_API_KEY')


def _call(prompt: str, settings: Settings) -> str:
    try:
        response = ask_llm(prompt, settings=settings, observer=_records.append)
    except Exception as exc:
        pytest.fail(f'Live LLM call failed: {type(exc).__name__}')
    assert response.strip()
    return response


def test_live_llm_smoke_returns_non_empty_response(live_settings: Settings) -> None:
    response = _call(
        'Reply with one short Chinese sentence confirming that the live smoke test works.',
        live_settings,
    )

    assert response.strip()
    assert len(_records) == 1
    assert _records[0].status == 'success'


def test_live_llm_smoke_returns_parseable_json(live_settings: Settings) -> None:
    response = _call(
        'Return JSON only with exactly this shape: {"ok": true, "value": "smoke"}.',
        live_settings,
    )
    parsed = parse_json_object(response)

    assert parsed['ok'] is True
    assert parsed['value'] == 'smoke'
    assert len(_records) == 2
    assert all(record.input_tokens >= 0 and record.output_tokens >= 0 for record in _records)
