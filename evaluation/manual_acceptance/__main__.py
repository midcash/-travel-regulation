from __future__ import annotations

import argparse
import json
from pathlib import Path

from evaluation.manual_acceptance.runner import run_manual_acceptance
from evaluation.manual_acceptance.verify import ArtifactVerificationError, verify_artifact


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run local manual acceptance observations.")
    subparsers = parser.add_subparsers(dest="command", required=True)

    run_parser = subparsers.add_parser("run")
    run_parser.add_argument("--stage", required=True)
    run_parser.add_argument("--case")
    run_parser.add_argument("--input")
    run_parser.add_argument("--mode", choices=("offline", "live"), required=True)
    run_parser.add_argument("--show", choices=("summary", "full"), default="summary")
    run_parser.add_argument("--artifact-dir", type=Path, required=True)
    run_parser.add_argument("--exploratory", action="store_true")

    verify_parser = subparsers.add_parser("verify")
    verify_parser.add_argument("--artifact-dir", type=Path, required=True)

    args = parser.parse_args(argv)
    if args.command == "run":
        try:
            result = run_manual_acceptance(
                stage=args.stage,
                case_id=args.case,
                input_text=args.input,
                mode=args.mode,
                artifact_dir=args.artifact_dir,
                root=Path.cwd(),
                exploratory=args.exploratory,
            )
        except Exception as exc:
            parser.error(str(exc))
        print(
            json.dumps(
                {
                    "stage": result.stage,
                    "case_id": result.case_id,
                    "run_id": result.run_id,
                    "runner_status": result.runner_status,
                    "artifact_dir": str(result.artifact_dir),
                },
                ensure_ascii=False,
                indent=2,
            )
        )
        if args.show == "full":
            print((result.artifact_dir / "observation.md").read_text(encoding="utf-8"))
        return 0

    try:
        verification = verify_artifact(args.artifact_dir)
    except ArtifactVerificationError as exc:
        print(json.dumps({"verification": "FAIL", "error": str(exc)}, ensure_ascii=False))
        return 1
    print(
        json.dumps(
            {
                "verification": "PASS",
                "stage": verification.stage,
                "case_id": verification.case_id,
                "run_id": verification.run_id,
                "runner_status": verification.runner_status,
                "machine_assertion": verification.machine_assertion,
                "stage_gate_state": verification.stage_gate_state,
                "gate_open": verification.gate_open,
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
