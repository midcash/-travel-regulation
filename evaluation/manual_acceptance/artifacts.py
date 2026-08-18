from __future__ import annotations

import json
from pathlib import Path
from typing import Any


class ArtifactExistsError(FileExistsError):
    """Manual acceptance artifacts are immutable once created."""


class UnsafeArtifactError(ValueError):
    """An artifact contains a forbidden secret or raw sensitive payload."""


_JSON_FILES = ("actual", "expected", "machine-checks", "runtime")
_SENSITIVE_KEY_MARKERS = (
    "api_key",
    "access_token",
    "authorization",
    "cookie",
    "password",
    "secret",
    "system_prompt",
    "full_prompt",
    "supplier_payload",
    "supplier_raw_response",
)
_SENSITIVE_TEXT_MARKERS = (
    "authorization:",
    "bearer ",
    "api_key=",
    "apikey=",
    "-----begin private key-----",
)


def write_artifacts(root: Path, payload: dict[str, Any]) -> None:
    """Write one immutable six-file manual-acceptance artifact."""
    if root.exists() and any(root.iterdir()):
        raise ArtifactExistsError(str(root))
    _assert_safe(payload, path="artifact")
    root.mkdir(parents=True, exist_ok=True)
    for name in _JSON_FILES:
        _write_new(
            root / f"{name}.json",
            json.dumps(payload[name.replace("-", "_")], ensure_ascii=False, indent=2) + "\n",
        )
    _write_new(root / "observation.md", str(payload["observation"]))
    _write_new(root / "human-review.md", str(payload["human_review"]))


def _write_new(path: Path, content: str) -> None:
    try:
        with path.open("x", encoding="utf-8") as handle:
            handle.write(content)
    except FileExistsError as exc:
        raise ArtifactExistsError(str(path)) from exc


def _assert_safe(value: Any, *, path: str) -> None:
    if isinstance(value, dict):
        for key, child in value.items():
            key_text = str(key).casefold().replace("-", "_")
            if any(marker in key_text for marker in _SENSITIVE_KEY_MARKERS):
                raise UnsafeArtifactError(f"forbidden artifact field: {path}.{key}")
            _assert_safe(child, path=f"{path}.{key}")
        return
    if isinstance(value, list | tuple):
        for index, child in enumerate(value):
            _assert_safe(child, path=f"{path}[{index}]")
        return
    if isinstance(value, str):
        lowered = value.casefold()
        if any(marker in lowered for marker in _SENSITIVE_TEXT_MARKERS):
            raise UnsafeArtifactError(f"forbidden artifact text: {path}")
