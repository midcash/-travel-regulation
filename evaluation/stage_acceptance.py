from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
from dataclasses import dataclass
from pathlib import Path

from evaluation.business_travel.fingerprints import (
    dataset_fingerprint,
    policy_fingerprint,
    runtime_fingerprint,
    source_tree_status,
    view_fixture_fingerprint,
)
from evaluation.business_travel.live_runner import (
    LiveRunResult,
    run_live_semantic_from_environment,
)
from evaluation.business_travel.offline_runner import (
    normalized_result_hash,
    run_offline_baseline,
    run_offline_integration,
)
from evaluation.business_travel.policies import load_policy_bundle
from evaluation.business_travel.registry import BusinessTravelCaseRegistry
from evaluation.business_travel.reporting import compare_reports


@dataclass(frozen=True, slots=True)
class StageAcceptanceResult:
    exit_code: int
    checks: dict[str, str]
    live_status: str | None


def _load_dotenv_into_process(root: Path) -> Path | None:
    """在开发期验收入口将 `.env` 白名单配置注入当前进程。"""
    dotenv_path = root / ".env"
    if not dotenv_path.is_file():
        return None
    from evaluation.run_m4_1_acceptance import ACCEPTANCE_ENV_NAMES, parse_dotenv

    values = parse_dotenv(dotenv_path)
    for name, value in values.items():
        if name in ACCEPTANCE_ENV_NAMES and value.strip():
            os.environ[name] = value
    return dotenv_path


def _validate_assets(root: Path) -> None:
    evaluation = root / "evaluation"
    manifest_path = evaluation / "datasets" / "business-travel-m4.1-manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))

    def file_hash(path: Path) -> str:
        return hashlib.sha256(path.read_bytes()).hexdigest()

    formal = evaluation / "datasets" / "business-travel-m4.1-v1.jsonl"
    dev = evaluation / "datasets" / "business-travel-m4.1-dev-v1.jsonl"
    fixture = evaluation / "fixtures" / str(manifest["fixture_file"])
    if file_hash(formal) != manifest["dataset_hash"]:
        raise ValueError("formal dataset hash mismatch")
    if file_hash(dev) != manifest["dev_dataset_hash"]:
        raise ValueError("development dataset hash mismatch")
    if file_hash(fixture) != manifest["fixture_hash"]:
        raise ValueError("fixture hash mismatch")
    for policy_id, filename in manifest["policy_files"].items():
        policy_path = evaluation / "policies" / str(filename)
        if file_hash(policy_path) != manifest["policy_hashes"][policy_id]:
            raise ValueError(f"policy hash mismatch: {policy_id}")
    registry = BusinessTravelCaseRegistry.load(formal)
    dev_registry = BusinessTravelCaseRegistry.load(dev)
    if len(registry.cases) != 12 or len(dev_registry.cases) != 6:
        raise ValueError("M4.1 dataset case count mismatch")
    review = json.loads(
        (evaluation / "datasets" / "business-travel-m4.1-v1-review.json").read_text(
            encoding="utf-8"
        )
    )
    if review.get("unresolved_issue_count") != 0 or review.get("final_decision") != "accepted":
        raise ValueError("M4.1 reviewer gate is not closed")
    fixture_refs = {
        ref for case in (*registry.cases, *dev_registry.cases) for ref in case.fixture_refs
    }
    fixture_payload = json.loads(fixture.read_text(encoding="utf-8"))
    venues = fixture_payload.get("venues", {})
    if not fixture_refs.issubset(venues):
        raise ValueError("dataset references fixture entries that are not configured")
    load_policy_bundle(evaluation / "policies")


def run_stage_acceptance(*, stage: str, mode: str, root: Path) -> StageAcceptanceResult:
    checks: dict[str, str] = {}
    if stage != "M4.1" or mode not in {"offline", "all"}:
        return StageAcceptanceResult(2, {"configuration": "FAIL"}, None)
    try:
        _validate_assets(root)
        checks["dataset_contract"] = "PASS"
        formal_path = root / "evaluation" / "datasets" / "business-travel-m4.1-v1.jsonl"
        component_runs = [run_offline_baseline(formal_path) for _ in range(2)]
        integration_runs = [run_offline_integration(formal_path) for _ in range(2)]
        if normalized_result_hash(component_runs[0]) != normalized_result_hash(component_runs[1]):
            raise ValueError("offline component result hash mismatch")
        if normalized_result_hash(integration_runs[0]) != normalized_result_hash(
            integration_runs[1]
        ):
            raise ValueError("offline integration result hash mismatch")
        all_offline_cases = (*component_runs[0].case_results, *integration_runs[0].case_results)
        if any(
            item.run_status != "COMPLETED" or item.evaluator_error is not None
            for item in all_offline_cases
        ):
            raise ValueError("offline evaluator correctness gate failed")
        checks["offline_determinism"] = "PASS"
        checks["evaluator_correctness"] = "PASS"
        checks["component_baseline"] = "PASS"
        checks["stage_integration_baseline"] = "PASS"
        manifest = json.loads(
            (root / "evaluation" / "datasets" / "business-travel-m4.1-manifest.json").read_text(
                encoding="utf-8"
            )
        )
        policy_hashes = {
            str(key): str(value) for key, value in manifest["policy_hashes"].items()
        }
        fingerprints = {
            "runtime_fingerprint": runtime_fingerprint(
                provider="offline-fixture",
                model="offline-eval",
                base_url="offline://fixture",
                timeout_seconds=0,
                temperature="provider_default",
                retry_count=0,
                seed_status="unsupported",
            ),
            "dataset_fingerprint": dataset_fingerprint(
                str(manifest["dataset_id"]),
                str(manifest["dataset_hash"]),
                str(manifest["oracle_version"]),
            ),
            "policy_fingerprint": policy_fingerprint(**policy_hashes),
            "view_fixture_fingerprint": view_fixture_fingerprint(
                (str(manifest["fixture_hash"]),)
            ),
        }
        m4_before = {
            **fingerprints,
            "component": normalized_result_hash(component_runs[0]),
            "integration": normalized_result_hash(integration_runs[0]),
            "component_case_count": len(component_runs[0].case_results),
            "integration_case_count": len(integration_runs[0].case_results),
            "component_run_status": "COMPLETED",
            "component_component_availability": "NOT_IMPLEMENTED_IN_BASELINE",
            "component_first_failed_stage": "SCOPE",
            "component_evaluator_errors": sum(
                item.evaluator_error is not None for item in component_runs[0].case_results
            ),
            "integration_run_status": "COMPLETED",
            "integration_component_availability": "IMPLEMENTED",
            "integration_first_failed_stage": "INTERPRETER",
            "integration_evaluator_errors": sum(
                item.evaluator_error is not None for item in integration_runs[0].case_results
            ),
        }
        report_dir = root / "evaluation" / "reports" / "M4.1"
        report_dir.mkdir(parents=True, exist_ok=True)
        baseline_path = report_dir / "M4-before.json"
        encoded = json.dumps(m4_before, indent=2, sort_keys=True) + "\n"
        if baseline_path.exists():
            existing = json.loads(baseline_path.read_text(encoding="utf-8"))
            if existing != m4_before:
                raise ValueError("M4-before artifact is immutable and does not match this run")
        else:
            with baseline_path.open("x", encoding="utf-8") as handle:
                handle.write(encoded)
        checks["m4_before"] = "PASS"
        self_diff = compare_reports(m4_before, m4_before)
        if self_diff.status != "COMPARABLE" or self_diff.metric_changes:
            raise ValueError("M4-before self diff is not zero")
        checks["self_diff"] = "PASS"
    except Exception as exc:
        checks["offline"] = f"FAIL:{type(exc).__name__}"
        return StageAcceptanceResult(1, checks, None)
    checks["source_tree_status"] = source_tree_status(root).upper()
    if mode == "offline":
        return StageAcceptanceResult(0, checks, None)
    try:
        live: LiveRunResult = run_live_semantic_from_environment()
    except Exception as exc:
        checks["live"] = f"FAIL:{type(exc).__name__}"
        return StageAcceptanceResult(1, checks, "LIVE_ATTEMPT_RECORDED")
    checks["live"] = live.status
    if live.exit_code != 0 or live.status != "LIVE_BASELINE_SUCCESS":
        return StageAcceptanceResult(1, checks, live.status)
    return StageAcceptanceResult(0, checks, live.status)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Run M4.1 stage acceptance; no arguments runs the full Live gate."
    )
    parser.add_argument("--stage", default="M4.1")
    parser.add_argument("--mode", default="all", choices=("offline", "all"))
    args = parser.parse_args(argv)
    root = Path.cwd()
    dotenv_path = _load_dotenv_into_process(root)
    if dotenv_path is not None:
        sys.stdout.write(f"Loaded local acceptance configuration from {dotenv_path}\n")
        sys.stdout.write("Secret values are not printed; configuration is scoped to this process.\n")
    result = run_stage_acceptance(stage=args.stage, mode=args.mode, root=root)
    sys.stdout.write(
        json.dumps({"checks": result.checks, "live_status": result.live_status}, indent=2) + "\n"
    )
    return result.exit_code


if __name__ == "__main__":
    raise SystemExit(main())
