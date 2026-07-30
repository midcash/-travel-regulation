from __future__ import annotations

import json

from src.config import load_settings
from src.obs import trace as trace_module
from src.obs.log import configure_logging, get_logger


def test_jsonl_logs_use_stderr_and_leave_stdout_human_readable(
    capsys,
) -> None:
    configure_logging("INFO")
    get_logger("m21-output-test").info("channel_probe", safe_count=1)

    captured = capsys.readouterr()
    assert captured.out == ""
    payload = json.loads(captured.err.strip().splitlines()[-1])
    assert payload["event"] == "channel_probe"
    assert payload["safe_count"] == 1


def test_local_log_level_filters_lower_priority_events(capsys) -> None:
    configure_logging("WARNING")
    logger = get_logger("m21-level-test")
    logger.info("hidden_info")
    logger.warning("visible_warning")

    captured = capsys.readouterr()
    assert "hidden_info" not in captured.err
    assert "visible_warning" in captured.err
    configure_logging("INFO")


def test_console_span_exporter_is_opt_in() -> None:
    assert trace_module.console_span_exporter_enabled() is False
    trace_module.configure_console_span_exporter(False)
    assert trace_module.console_span_exporter_enabled() is False


def test_default_trace_does_not_mix_console_json_into_cli_streams(capsys) -> None:
    trace_module.configure_console_span_exporter(False)
    with trace_module.trace_workflow_request(
        trace_id="route:output-trip:output-request",
        request_id="output-request",
        trip_id="output-trip",
        session_id="output-session",
    ):
        pass

    captured = capsys.readouterr()
    assert captured.out == ""
    assert captured.err == ""


def test_observability_settings_are_loaded_without_changing_strict_defaults() -> None:
    settings = load_settings(
        {
            "STRICT_MODE": "true",
            "RETRY_COUNT": "0",
            "CACHE_READS": "false",
            "FALLBACKS": "false",
            "PARTIAL_SUCCESS": "false",
            "LOG_LEVEL": "warning",
            "CONSOLE_SPAN_EXPORTER": "true",
        }
    )

    assert settings.log_level == "WARNING"
    assert settings.console_span_exporter is True
    assert settings.strict_mode is True
    assert settings.retry_count == 0
