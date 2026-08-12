from __future__ import annotations

import json
from pathlib import Path

import pytest

from evaluation.business_travel.artifacts import ArtifactExistsError, write_artifact
from evaluation.business_travel.fingerprints import (
    configuration_diff,
    dataset_fingerprint,
    normalize_for_fingerprint,
    runtime_fingerprint,
    source_tree_fingerprint,
)


def test_fingerprint_normalization_is_stable_and_redacts_secrets_and_query() -> None:
    left = {
        "api_key": "secret-one",
        "token": "token-one",
        "url": "https://example.test/search?key=secret&city=shanghai",
        "nested": {"password": "pw", "value": 3},
        "deepseek_api_key": "secret-three",
        "access-token": "token-two",
    }
    right = {
        "api_key": "secret-two",
        "token": "token-two",
        "url": "https://example.test/search?key=other&city=beijing",
        "nested": {"password": "pw-two", "value": 3},
        "deepseek_api_key": "secret-three",
        "access-token": "token-two",
    }

    assert normalize_for_fingerprint(left) == normalize_for_fingerprint(right)


def test_runtime_and_dataset_fingerprints_change_for_control_variables() -> None:
    runtime_a = runtime_fingerprint(
        provider="deepseek",
        model="model-a",
        base_url="https://api.example.test/v1",
        timeout_seconds=30,
        temperature="provider_default",
        retry_count=0,
        seed_status="unsupported",
    )
    runtime_b = runtime_fingerprint(
        provider="deepseek",
        model="model-b",
        base_url="https://api.example.test/v1",
        timeout_seconds=30,
        temperature="provider_default",
        retry_count=0,
        seed_status="unsupported",
    )

    assert runtime_a != runtime_b
    assert dataset_fingerprint("dataset", "hash", "oracle-v1") == dataset_fingerprint(
        "dataset", "hash", "oracle-v1"
    )


def test_configuration_diff_is_non_comparable_when_relevant_fingerprint_changes() -> None:
    assert configuration_diff(
        {"runtime_fingerprint": "a", "policy_fingerprint": "same"},
        {"runtime_fingerprint": "b", "policy_fingerprint": "same"},
    ).status == "NON_COMPARABLE_CONFIGURATION"

    assert (
        configuration_diff(
            {"runtime_fingerprint": "a"}, {"runtime_fingerprint": "a"}
        ).status
        == "NON_COMPARABLE_CONFIGURATION"
    )


def test_source_tree_fingerprint_ignores_report_directory(monkeypatch: pytest.MonkeyPatch) -> None:
    commands: list[tuple[str, ...]] = []

    def fake_run(command: list[str], **_: object) -> object:
        commands.append(tuple(command))
        return type("Completed", (), {"stdout": "evaluation/reports/M4.1/runs/x\nsource.py\n"})()

    monkeypatch.setattr("evaluation.business_travel.fingerprints.subprocess.run", fake_run)
    source_tree_fingerprint(Path("."))

    assert commands == [("git", "status", "--porcelain", "--untracked-files=all")]


def test_artifact_is_immutable_and_does_not_write_raw_secret(tmp_path: Path) -> None:
    payload = {"status": "COMPLETED", "api_key": "secret", "prompt": "private prompt"}
    write_artifact(
        tmp_path,
        "baseline",
        payload,
        {"score": 1},
        "# report\nprompt: private prompt\n",
    )

    run_data = json.loads((tmp_path / "baseline" / "run.json").read_text(encoding="utf-8"))
    assert "secret" not in json.dumps(run_data)
    assert "private prompt" not in json.dumps(run_data)
    report_data = (tmp_path / "baseline" / "report.md").read_text(encoding="utf-8")
    assert "private prompt" not in report_data
    assert "[REDACTED]" in report_data
    with pytest.raises(ArtifactExistsError):
        write_artifact(tmp_path, "baseline", payload, {"score": 2}, "# changed\n")
