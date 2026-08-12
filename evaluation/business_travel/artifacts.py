from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

from evaluation.business_travel.fingerprints import normalize_for_fingerprint


class ArtifactExistsError(FileExistsError):
    """正式评测 Artifact 不允许覆盖。"""


def _sanitize(value: Any) -> Any:
    return normalize_for_fingerprint(value)


def _write_new(path: Path, content: str) -> None:
    try:
        with path.open("x", encoding="utf-8") as handle:
            handle.write(content)
    except FileExistsError as exc:
        raise ArtifactExistsError(str(path)) from exc


def _sanitize_report(report: str) -> str:
    """移除报告中可能误传入的凭证、Prompt 或供应商原始行。"""
    sensitive_markers = (
        "api_key",
        "access_token",
        "authorization",
        "password",
        "prompt",
        "supplier_payload",
    )
    safe_lines = []
    for line in report.splitlines():
        lowered = line.casefold().replace("-", "_")
        if any(marker in lowered for marker in sensitive_markers):
            safe_lines.append("[REDACTED]")
        else:
            safe_lines.append(line)
    return "\n".join(safe_lines) + ("\n" if report.endswith("\n") else "")


def write_artifact(
    root: Path,
    run_label: str,
    run: dict[str, Any],
    scorecard: dict[str, Any],
    report: str,
) -> Path:
    directory = root / run_label
    if directory.exists():
        raise ArtifactExistsError(str(directory))
    directory.mkdir(parents=True, exist_ok=False)
    run_json = json.dumps(_sanitize(run), ensure_ascii=False, sort_keys=True, indent=2) + "\n"
    _write_new(directory / "run.json", run_json)
    _write_new(
        directory / "scorecard.json",
        json.dumps(_sanitize(scorecard), ensure_ascii=False, sort_keys=True, indent=2) + "\n",
    )
    safe_report = _sanitize_report(report)
    _write_new(directory / "report.md", safe_report)
    scorecard_json = (
        json.dumps(_sanitize(scorecard), ensure_ascii=False, sort_keys=True, indent=2) + "\n"
    )
    manifest = {
        "run_label": run_label,
        "run_sha256": hashlib.sha256(run_json.encode("utf-8")).hexdigest(),
        "scorecard_sha256": hashlib.sha256(scorecard_json.encode("utf-8")).hexdigest(),
        "report_sha256": hashlib.sha256(safe_report.encode("utf-8")).hexdigest(),
    }
    _write_new(directory / "manifest.json", json.dumps(manifest, indent=2) + "\n")
    return directory
