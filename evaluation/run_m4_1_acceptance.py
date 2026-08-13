"""开发期 M4.1 Live 验收启动器。

该模块只负责读取仓库根目录 `.env` 并将白名单配置注入验收子进程。
业务代码和 `load_settings()` 仍然只读取显式进程环境，避免生产运行隐式依赖本地文件。
"""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
from pathlib import Path

ACCEPTANCE_COMMAND: tuple[str, ...] = (
    "-m",
    "evaluation.stage_acceptance",
    "--stage",
    "M4.1",
    "--mode",
    "all",
)

ACCEPTANCE_ENV_NAMES = frozenset(
    {
        "DEEPSEEK_API_KEY",
        "DEEPSEEK_MODEL",
        "DEEPSEEK_MAX_TOKENS",
        "STRICT_MODE",
        "RETRY_COUNT",
        "CACHE_READS",
        "FALLBACKS",
        "PARTIAL_SUCCESS",
        "WORKFLOW_USE_CASE",
        "LLM_TIMEOUT_SECONDS",
        "EXTERNAL_API_TIMEOUT_SECONDS",
        "MAX_REVISION_ROUNDS",
        "LOG_LEVEL",
        "CONSOLE_SPAN_EXPORTER",
    }
)

PROJECT_ROOT = Path(__file__).resolve().parents[1]


def _unquote(value: str) -> str:
    stripped = value.strip()
    if len(stripped) >= 2 and stripped[0] == stripped[-1] and stripped[0] in {'"', "'"}:
        return stripped[1:-1]
    return stripped


def parse_dotenv(path: Path) -> dict[str, str]:
    """解析验收所需的简单 `.env` KEY=VALUE 文件，不输出任何值。"""
    if not path.is_file():
        raise FileNotFoundError(f"dotenv file not found: {path}")

    values: dict[str, str] = {}
    for line_number, raw_line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("export "):
            line = line[7:].lstrip()
        separator = line.find("=")
        if separator <= 0:
            raise ValueError(f"dotenv line {line_number} is not a KEY=VALUE assignment")
        name = line[:separator].strip()
        if not name.isidentifier() or not name.isupper():
            raise ValueError(f"dotenv line {line_number} has an invalid variable name")
        values[name] = _unquote(line[separator + 1 :])
    return values


def build_child_environment(dotenv_values: dict[str, str]) -> dict[str, str]:
    """构造继承当前环境、覆盖验收白名单变量的子进程环境。"""
    child_environment = dict(os.environ)
    for name, value in dotenv_values.items():
        if name in ACCEPTANCE_ENV_NAMES and value.strip():
            child_environment[name] = value
    return child_environment


def main(argv: list[str] | None = None) -> int:
    """从 `.env` 启动正式 M4.1 全量验收并原样返回子进程退出码。"""
    parser = argparse.ArgumentParser(description="Run M4.1 acceptance with local .env")
    parser.add_argument("--env-file", type=Path, default=PROJECT_ROOT / ".env")
    args = parser.parse_args(argv)

    dotenv_values = parse_dotenv(args.env_file.resolve())
    child_environment = build_child_environment(dotenv_values)
    missing = [
        name
        for name in ("DEEPSEEK_API_KEY", "DEEPSEEK_MODEL")
        if not child_environment.get(name, "").strip()
    ]
    if missing:
        raise ValueError(f"missing required dotenv variables: {', '.join(missing)}")

    print(f"Loaded local acceptance configuration from {args.env_file.resolve()}")
    print("Secret values are not printed; configuration is scoped to the child process.")
    completed = subprocess.run(
        [sys.executable, *ACCEPTANCE_COMMAND],
        cwd=PROJECT_ROOT,
        env=child_environment,
        check=False,
    )
    return completed.returncode


if __name__ == "__main__":
    raise SystemExit(main())
