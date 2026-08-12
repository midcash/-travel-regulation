from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

POLICY_IDS = (
    "timing-policy-cn-domestic-v1",
    "pre-meeting-lodging-policy-v1",
    "meeting-readiness-policy-v1",
    "universal-business-travel-policy-v1",
    "repetition-policy-m4.1-v1",
)


def policy_hash(policy: dict[str, Any]) -> str:
    """计算策略规范化 JSON 的 SHA-256。"""
    payload = json.dumps(policy, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def policy_file_hash(path: Path) -> str:
    """计算 manifest 绑定的策略文件原始 SHA-256。"""
    return hashlib.sha256(path.read_bytes()).hexdigest()


def load_policy_bundle(directory: Path) -> dict[str, dict[str, Any]]:
    """加载、校验并按策略 ID 返回版本化策略。"""
    result: dict[str, dict[str, Any]] = {}
    for policy_id in POLICY_IDS:
        matches = sorted(directory.glob(f"{policy_id}.json"))
        if len(matches) != 1:
            raise ValueError(f"missing policy file: {policy_id}")
        raw = json.loads(matches[0].read_text(encoding="utf-8"))
        if not isinstance(raw, dict):
            raise ValueError(f"policy must be an object: {policy_id}")
        required = {"policy_id", "version", "kind", "rules", "citations"}
        if not required.issubset(raw):
            raise ValueError(f"policy {policy_id} missing required keys")
        if raw["policy_id"] != policy_id or raw["version"] != 1:
            raise ValueError(f"policy identity/version mismatch: {policy_id}")
        if not isinstance(raw["rules"], dict) or not isinstance(raw["citations"], list):
            raise ValueError(f"policy rules/citations have invalid schema: {policy_id}")
        result[policy_id] = raw
    return result
