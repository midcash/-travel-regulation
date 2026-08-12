from __future__ import annotations

import hashlib
import json
import subprocess
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit, urlunsplit

_SECRET_KEYS = {
    "api_key",
    "apikey",
    "authorization",
    "password",
    "prompt",
    "secret",
    "token",
}


def _is_secret_key(key: str) -> bool:
    normalized = key.casefold().replace("-", "_")
    return normalized in _SECRET_KEYS or any(
        normalized.endswith(f"_{suffix}") for suffix in ("api_key", "token", "secret", "password")
    )


def normalize_for_fingerprint(value: Any, *, key: str = "") -> Any:
    """移除凭证并规范化 URL 查询参数。"""
    if _is_secret_key(key):
        return "<redacted>"
    if isinstance(value, dict):
        return {
            str(item_key): normalize_for_fingerprint(item_value, key=str(item_key))
            for item_key, item_value in sorted(value.items(), key=lambda item: str(item[0]))
        }
    if isinstance(value, list | tuple):
        return [normalize_for_fingerprint(item) for item in value]
    if isinstance(value, str) and "://" in value:
        parsed = urlsplit(value)
        if parsed.query:
            return urlunsplit((parsed.scheme, parsed.netloc, parsed.path, "<redacted-query>", ""))
    return value


def _hash(value: Any) -> str:
    normalized = normalize_for_fingerprint(value)
    payload = json.dumps(normalized, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def runtime_fingerprint(
    *,
    provider: str,
    model: str,
    base_url: str,
    timeout_seconds: float,
    temperature: float | str,
    retry_count: int,
    seed_status: str,
) -> str:
    return _hash(
        {
            "provider": provider,
            "model": model,
            "base_url": base_url,
            "timeout_seconds": timeout_seconds,
            "temperature": temperature,
            "retry_count": retry_count,
            "seed_status": seed_status,
        }
    )


def dataset_fingerprint(dataset_id: str, dataset_hash: str, oracle_version: str) -> str:
    return _hash(
        {"dataset_id": dataset_id, "dataset_hash": dataset_hash, "oracle_version": oracle_version}
    )


def policy_fingerprint(**policy_hashes: str) -> str:
    return _hash(policy_hashes)


def view_fixture_fingerprint(fixture_hashes: tuple[str, ...]) -> str:
    return _hash(sorted(fixture_hashes))


class ConfigurationDiff:
    def __init__(self, status: str) -> None:
        self.status = status


def configuration_diff(
    baseline: dict[str, str], current: dict[str, str]
) -> ConfigurationDiff:
    relevant = (
        "runtime_fingerprint",
        "dataset_fingerprint",
        "view_fixture_fingerprint",
        "policy_fingerprint",
    )
    if any(key not in baseline or key not in current for key in relevant):
        return ConfigurationDiff("NON_COMPARABLE_CONFIGURATION")
    if any(baseline[key] != current[key] for key in relevant):
        return ConfigurationDiff("NON_COMPARABLE_CONFIGURATION")
    return ConfigurationDiff("COMPARABLE")


def source_tree_fingerprint(root: Path) -> str:
    completed = subprocess.run(
        ["git", "status", "--porcelain", "--untracked-files=all"],
        cwd=root,
        check=True,
        capture_output=True,
        text=True,
    )
    relevant = [
        line
        for line in completed.stdout.splitlines()
        if line and not line[3:].replace("\\", "/").startswith("evaluation/reports/")
    ]
    return _hash(relevant)


def source_tree_status(root: Path) -> str:
    completed = subprocess.run(
        ["git", "status", "--porcelain", "--untracked-files=all"],
        cwd=root,
        check=True,
        capture_output=True,
        text=True,
    )
    relevant = [
        line
        for line in completed.stdout.splitlines()
        if line and not line[3:].replace("\\", "/").startswith("evaluation/reports/")
    ]
    return "dirty" if relevant else "clean"
