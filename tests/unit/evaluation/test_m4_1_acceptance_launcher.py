from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

from evaluation.run_m4_1_acceptance import (
    ACCEPTANCE_COMMAND,
    build_child_environment,
    main,
    parse_dotenv,
)


def test_parse_dotenv_supports_comments_exports_and_quotes(tmp_path: Path) -> None:
    env_file = tmp_path / ".env"
    env_file.write_text(
        "# comment\n"
        "export DEEPSEEK_MODEL='deepseek-v4-flash'\n"
        'STRICT_MODE="true"\n'
        "IGNORED_VALUE=preserved\n",
        encoding="utf-8",
    )

    assert parse_dotenv(env_file) == {
        "DEEPSEEK_MODEL": "deepseek-v4-flash",
        "STRICT_MODE": "true",
        "IGNORED_VALUE": "preserved",
    }


def test_parse_dotenv_rejects_invalid_assignment(tmp_path: Path) -> None:
    env_file = tmp_path / ".env"
    env_file.write_text("not an assignment\n", encoding="utf-8")

    with pytest.raises(ValueError, match="line 1"):
        parse_dotenv(env_file)


def test_build_child_environment_allows_only_acceptance_settings(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("INHERITED_VALUE", "kept")
    child = build_child_environment(
        {"DEEPSEEK_API_KEY": "from-dotenv", "DEEPSEEK_MODEL": "deepseek-v4-flash"}
    )

    assert child["DEEPSEEK_API_KEY"] == "from-dotenv"
    assert child["DEEPSEEK_MODEL"] == "deepseek-v4-flash"
    assert child["INHERITED_VALUE"] == "kept"


def test_main_injects_dotenv_without_printing_secret(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    secret = "sk-test-secret-do-not-print"
    env_file = tmp_path / ".env"
    env_file.write_text(
        f"DEEPSEEK_API_KEY={secret}\nDEEPSEEK_MODEL=deepseek-v4-flash\nSTRICT_MODE=true\n",
        encoding="utf-8",
    )
    calls: list[tuple[list[str], dict[str, str], Path]] = []

    def fake_run(
        command: list[str],
        *,
        cwd: Path,
        env: dict[str, str],
        check: bool,
    ) -> subprocess.CompletedProcess[str]:
        calls.append((command, env, cwd))
        assert check is False
        return subprocess.CompletedProcess(command, 0)

    monkeypatch.setattr("evaluation.run_m4_1_acceptance.subprocess.run", fake_run)
    monkeypatch.setattr(sys, "executable", "python-test")

    assert main(["--env-file", str(env_file)]) == 0
    output = capsys.readouterr().out
    assert secret not in output
    assert calls == [
        (
            ["python-test", *ACCEPTANCE_COMMAND],
            {
                **build_child_environment({
                    "DEEPSEEK_API_KEY": secret,
                    "DEEPSEEK_MODEL": "deepseek-v4-flash",
                    "STRICT_MODE": "true",
                })
            },
            Path(__file__).resolve().parents[3],
        )
    ]
