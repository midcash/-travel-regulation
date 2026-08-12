from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from evaluation.business_travel.policies import (
    POLICY_IDS,
    load_policy_bundle,
    policy_hash,
)

ROOT = Path("evaluation")


def test_all_frozen_policies_load_and_hash_deterministically() -> None:
    bundle = load_policy_bundle(ROOT / "policies")

    assert set(bundle) == set(POLICY_IDS)
    for policy_id, policy in bundle.items():
        assert policy["policy_id"] == policy_id
        assert policy_hash(policy) == policy_hash(json.loads(json.dumps(policy, sort_keys=True)))


def test_policy_loader_rejects_unknown_policy_schema(tmp_path: Path) -> None:
    source = ROOT / "policies"
    for path in source.glob("*.json"):
        (tmp_path / path.name).write_bytes(path.read_bytes())
    (tmp_path / "timing-policy-cn-domestic-v1.json").write_text(
        '{"policy_id":"timing-policy-cn-domestic-v1","version":1}\n', encoding="utf-8"
    )

    with pytest.raises(ValueError, match="required keys"):
        load_policy_bundle(tmp_path)


def test_manifest_hashes_match_policy_files() -> None:
    manifest = json.loads(
        (ROOT / "datasets" / "business-travel-m4.1-manifest.json").read_text(encoding="utf-8")
    )
    for policy_id, expected_hash in manifest["policy_hashes"].items():
        path = ROOT / "policies" / manifest["policy_files"][policy_id]
        actual = hashlib.sha256(path.read_bytes()).hexdigest()
        assert actual == expected_hash
