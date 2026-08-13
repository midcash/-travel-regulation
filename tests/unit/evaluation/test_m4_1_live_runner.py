from __future__ import annotations

import json
from pathlib import Path

import pytest

from evaluation.business_travel.live_runner import (
    EvaluationConfigurationError,
    LiveRunResult,
    load_live_eval_settings,
    run_live_semantic,
    run_live_semantic_from_environment,
)
from src.config import Settings
from src.ports.llm_gateway import LLMResponseError
from tests.support.llm_fakes import FakeLLMGateway


def _valid_interpretation() -> str:
    return (
        '{"mode_hint":"plan","extracted_entities":[],"constraint_candidates":['
        '{"category":"origin","value":"Shanghai","hardness":"hard","scope":"trip",'
        '"confidence":0.95},{"category":"destination","value":"Hangzhou",'
        '"hardness":"hard","scope":"trip","confidence":0.95},{"category":"date_range",'
        '"value":"2026-08-20","hardness":"hard","scope":"trip","confidence":0.95},'
        '{"category":"travelers","value":1,"hardness":"hard","scope":"trip",'
        '"confidence":0.95}],"explicit_questions":[],"references_to_current_plan":[],'
        '"field_confidence":{},"overall_confidence":0.95,"safety_flags":[]}'
    )


def test_live_settings_require_explicit_model_without_fallback() -> None:
    with pytest.raises(EvaluationConfigurationError, match="DEEPSEEK_MODEL is required"):
        load_live_eval_settings({"DEEPSEEK_API_KEY": "key", "STRICT_MODE": "true"})

    settings = load_live_eval_settings(
        {
            "DEEPSEEK_API_KEY": "key",
            "DEEPSEEK_MODEL": "deepseek-v4-flash",
            "STRICT_MODE": "true",
        }
    )
    assert settings.deepseek_model == "deepseek-v4-flash"
    assert settings.deepseek_max_tokens == 4096
    assert settings.retry_count == 0


def test_live_runner_missing_key_records_attempt_and_fails(tmp_path: Path) -> None:
    result = run_live_semantic(
        settings=Settings(deepseek_api_key=None, deepseek_model="deepseek-v4-flash"),
        output_dir=tmp_path,
    )

    assert isinstance(result, LiveRunResult)
    assert result.status == "LIVE_ATTEMPT_RECORDED"
    assert result.exit_code != 0
    assert result.run_status == "EXTERNAL_FAILURE"
    assert (tmp_path / "run.json").exists()


def test_live_runner_does_not_invent_success_when_gateway_fails(tmp_path: Path) -> None:
    result = run_live_semantic(
        settings=Settings(deepseek_api_key="key", deepseek_model="deepseek-v4-flash"),
        output_dir=tmp_path,
        gateway_factory=lambda _: (_ for _ in ()).throw(TimeoutError("timeout")),
    )

    assert result.status == "LIVE_ATTEMPT_RECORDED"
    assert result.exit_code != 0
    assert result.run_status == "EXTERNAL_FAILURE"
    payload = json.loads((tmp_path / "run.json").read_text(encoding="utf-8"))
    assert payload["workflow_error"]["code"] == "UNCLASSIFIED_FAILURE"
    assert payload["workflow_error"]["stage"] == "live_runner"
    assert payload["workflow_error"]["cause_type"] == "TimeoutError"
    assert payload["workflow_error"]["cause_summary"] == "LLM request timed out"


def test_live_runner_preserves_safe_provider_connection_chain(tmp_path: Path) -> None:
    try:
        raise OSError("TLS handshake failed")
    except OSError as cause:
        failure = ConnectionError("provider connection closed")
        failure.__cause__ = cause

    result = run_live_semantic(
        settings=Settings(deepseek_api_key="key", deepseek_model="deepseek-v4-flash"),
        output_dir=tmp_path,
        gateway_factory=lambda _: (_ for _ in ()).throw(failure),
    )

    assert result.status == "LIVE_ATTEMPT_RECORDED"
    payload = json.loads((tmp_path / "run.json").read_text(encoding="utf-8"))
    assert payload["workflow_error"]["cause_summary"] == (
        "ConnectionError: provider connection closed; "
        "cause=OSError: TLS handshake failed"
    )


def test_live_runner_records_workflow_error_root_cause(tmp_path: Path) -> None:
    failure = LLMResponseError(
        "LLM output was truncated",
        cause_code="LLM_OUTPUT_TRUNCATED",
        finish_reason="length",
        model="deepseek-v4-flash",
        max_tokens=4096,
        input_tokens=800,
        output_tokens=4096,
    )
    result = run_live_semantic(
        settings=Settings(deepseek_api_key="key", deepseek_model="deepseek-v4-flash"),
        output_dir=tmp_path,
        gateway_factory=lambda _: FakeLLMGateway([failure]),
    )

    assert result.status == "LIVE_ATTEMPT_RECORDED"
    assert result.exit_code != 0
    payload = json.loads((tmp_path / "run.json").read_text(encoding="utf-8"))
    assert payload["case_id"] == "BT-M41-001"
    assert payload["semantic_runs"] == 0
    assert payload["workflow_error"] == {
        "category": "llm",
        "cause_code": "LLM_OUTPUT_TRUNCATED",
        "cause_summary": "LLM output was truncated",
        "cause_type": "LLMResponseError",
        "code": "INTERPRETATION_INVALID",
        "finish_reason": "length",
        "input_tokens": 800,
        "max_tokens": 4096,
        "message": "request interpretation failed",
        "model": "deepseek-v4-flash",
        "output_tokens": 4096,
        "retryable": False,
        "stage": "request_interpreter",
        "trace_id": "semantic:live-BT-M41-001:live-BT-M41-001",
    }
    encoded = json.dumps(payload, ensure_ascii=False).casefold()
    assert "prompt" not in encoded
    assert "api_key" not in encoded


def test_live_runner_executes_only_read_only_semantic_chain(tmp_path: Path) -> None:
    result = run_live_semantic(
        settings=Settings(deepseek_api_key="key", deepseek_model="deepseek-v4-flash"),
        output_dir=tmp_path,
        gateway_factory=lambda _: FakeLLMGateway([_valid_interpretation()] * 20),
    )

    assert result.status == "LIVE_BASELINE_SUCCESS"
    assert result.semantic_runs == 20
    assert result.downstream_calls == 0
    assert '"case_results"' in (tmp_path / "run.json").read_text(encoding="utf-8")


def test_missing_environment_configuration_records_attempt(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)
    monkeypatch.delenv("DEEPSEEK_MODEL", raising=False)
    monkeypatch.chdir(tmp_path)

    result = run_live_semantic_from_environment()

    assert result.status == "LIVE_ATTEMPT_RECORDED"
    assert result.exit_code == 1
    assert (tmp_path / "evaluation/reports/M4.1/runs/live-attempt/run.json").exists()
