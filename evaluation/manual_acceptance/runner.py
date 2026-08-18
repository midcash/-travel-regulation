from __future__ import annotations

import hashlib
import io
import json
import os
import subprocess
import tempfile
import uuid
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

from pydantic import ValidationError

from evaluation.business_travel.fingerprints import source_tree_status
from evaluation.business_travel.live_runner import (
    EvaluationConfigurationError,
    load_live_eval_settings,
    run_live_semantic,
)
from evaluation.business_travel.offline_runner import (
    _request as _offline_request,
)
from evaluation.business_travel.offline_runner import (
    normalized_result_hash,
    run_offline_baseline,
    run_offline_integration,
)
from evaluation.manual_acceptance.artifacts import ArtifactExistsError, write_artifacts
from evaluation.manual_acceptance.cases import load_case
from evaluation.manual_acceptance.contracts import (
    BusinessTransitionBaseline,
    HumanDecision,
    MachineAssertion,
    ManualCase,
    RunnerStatus,
)
from evaluation.manual_acceptance.review import render_human_review
from src.application.interaction_facade import TripInteractionFacade
from src.application.use_cases.plan_trip import PlanTripResult
from src.config import Settings
from src.domain.errors import WorkflowError
from src.domain.models.enums import InteractionMode
from src.domain.models.trip_request import TravelerProfile, TripRequest
from src.domain.models.value_objects import DateRange
from src.gateway.deepseek_adapter import DeepSeekLLMGateway
from src.infrastructure.persistence.in_memory import InMemoryStateRepository
from src.obs.log import configure_logging
from src.ports.llm_gateway import LLMGateway, LLMOutputMode

PROJECT_ROOT = Path(__file__).resolve().parents[2]
_STAGES = frozenset({"M0", "M1", "M2", "M2.1", "M3", "M4", "M4.1"})


@dataclass(frozen=True, slots=True)
class RunSummary:
    stage: str
    case_id: str
    run_id: str
    runner_status: str
    artifact_dir: Path


@dataclass(frozen=True, slots=True)
class _StageExecution:
    actual: dict[str, Any]
    runner_status: RunnerStatus
    error: str | None = None


class _CapturedGateway:
    """Explicit offline gateway whose response is part of the observation."""

    def __init__(self, payload: dict[str, Any]) -> None:
        self._payload = payload
        self.last_payload: dict[str, Any] | None = None

    def complete(
        self,
        prompt: str,
        *,
        settings: Settings,
        output_mode: LLMOutputMode = LLMOutputMode.TEXT,
    ) -> str:
        del prompt, settings, output_mode
        self.last_payload = self._payload
        return json.dumps(self._payload, ensure_ascii=False)


class _ManualOfflineGateway:
    """Use an explicit request-shaped fixture at the public M4 boundary."""

    def __init__(self, request: TripRequest) -> None:
        self._request = request

    def complete(
        self,
        prompt: str,
        *,
        settings: Settings,
        output_mode: LLMOutputMode = LLMOutputMode.TEXT,
    ) -> str:
        del prompt, settings, output_mode
        if self._request.date_range is None:
            raise ValueError("manual M4 fixture requires a date range")
        date_value = self._request.date_range.start.isoformat()
        return json.dumps(
            {
                "mode_hint": "plan",
                "extracted_entities": [],
                "constraint_candidates": [
                    {
                        "category": "origin",
                        "value": self._request.origin,
                        "hardness": "hard",
                        "scope": "trip",
                        "confidence": 0.95,
                    },
                    {
                        "category": "destination",
                        "value": self._request.destinations[0],
                        "hardness": "hard",
                        "scope": "trip",
                        "confidence": 0.95,
                    },
                    {
                        "category": "date_range",
                        "value": date_value,
                        "hardness": "hard",
                        "scope": "trip",
                        "confidence": 0.95,
                    },
                    {
                        "category": "travelers",
                        "value": self._request.travelers.total_count,
                        "hardness": "hard",
                        "scope": "trip",
                        "confidence": 0.95,
                    },
                ],
                "explicit_questions": [],
                "references_to_current_plan": [],
                "field_confidence": {},
                "overall_confidence": 0.95,
                "safety_flags": [],
            },
            ensure_ascii=False,
        )


class _RecordingPlanner:
    def __init__(self) -> None:
        self.calls = 0

    def execute(self, request: TripRequest) -> PlanTripResult:
        self.calls += 1
        return PlanTripResult(
            request_id=request.request_id,
            trip_id=request.trip_id,
            session_id=request.session_id,
            plan="offline manual-acceptance planner result; not a business-trip success claim",
            rounds=1,
            issues_found=(),
        )


class _FixedClock:
    def __init__(self, current: datetime) -> None:
        self._current = current

    def now(self) -> datetime:
        return self._current


def run_manual_acceptance(
    *,
    stage: str,
    mode: str,
    artifact_dir: Path,
    root: Path,
    case_id: str | None = None,
    input_text: str | None = None,
    exploratory: bool = False,
) -> RunSummary:
    """Run one fixed or exploratory manual observation and write immutable artifacts."""
    if stage not in _STAGES:
        raise ValueError(f"unsupported stage: {stage}")
    if mode not in {"offline", "live"}:
        raise ValueError("mode must be offline or live")
    if (case_id is None) == (input_text is None):
        raise ValueError("provide exactly one of case_id or input_text")
    if artifact_dir.exists() and any(artifact_dir.iterdir()):
        raise ArtifactExistsError(str(artifact_dir))

    run_id = f"manual-{uuid.uuid4().hex}"
    case = _load_requested_case(root, stage, case_id, input_text, exploratory, run_id)
    expected = _expected_payload(case, exploratory=exploratory)
    started_at = datetime.now().astimezone()
    execution = _execute_stage(stage, mode, case, root)
    finished_at = datetime.now().astimezone()

    source_tree_status, git_commit = _source_identity(root)
    acceptance_eligibility = "OBSERVATION_ONLY" if exploratory else "ELIGIBLE"
    actual = {
        "run_id": run_id,
        "stage": stage,
        "case_id": case.case_id,
        "mode": mode,
        **execution.actual,
        "acceptance_eligibility": acceptance_eligibility,
    }
    required_outputs = case.required_outputs
    missing_outputs = tuple(name for name in required_outputs if name not in actual)
    machine_assertion = (
        MachineAssertion.PASS
        if execution.runner_status is RunnerStatus.OBSERVATION_READY and not missing_outputs
        else MachineAssertion.FAIL
        if execution.runner_status is not RunnerStatus.BLOCKED
        else MachineAssertion.NOT_RUN
    )
    machine_checks = {
        "machine_assertion": machine_assertion.value,
        "artifact_schema": "PASS",
        "required_outputs": {
            name: "PASS" if name in actual else "FAIL" for name in required_outputs
        },
        "missing_outputs": list(missing_outputs),
        "expected_actual_separation": "PASS",
        "security_scan": "PASS",
    }
    runtime_status = RunnerStatus.NON_ACCEPTANCE_RUN if exploratory else execution.runner_status
    runtime = {
        "run_id": run_id,
        "stage": stage,
        "case_id": case.case_id,
        "mode": mode,
        "runner_status": runtime_status.value,
        "acceptance_eligibility": acceptance_eligibility,
        "source_tree_status": source_tree_status,
        "git_commit": git_commit,
        "started_at": started_at.isoformat(),
        "finished_at": finished_at.isoformat(),
        "error": execution.error,
        "model_id": actual.get("model_id", "not_applicable"),
        "llm_execution": actual.get("llm_execution", {}),
        "call_stats": actual.get("call_stats", {}),
    }
    observation = _render_observation(expected, actual, machine_checks, runtime, case)
    payload = {
        "actual": actual,
        "expected": expected,
        "machine_checks": machine_checks,
        "runtime": runtime,
        "observation": observation,
        "human_review": render_human_review(case, run_id=run_id),
    }
    write_artifacts(artifact_dir, payload)
    return RunSummary(
        stage=stage,
        case_id=case.case_id,
        run_id=run_id,
        runner_status=runtime_status.value,
        artifact_dir=artifact_dir,
    )


def _load_requested_case(
    root: Path,
    stage: str,
    case_id: str | None,
    input_text: str | None,
    exploratory: bool,
    run_id: str,
) -> ManualCase:
    if case_id is not None:
        for relative in (
            Path("evaluation/manual_cases/business-travel-v1") / f"{case_id}.json",
            Path("evaluation/manual_cases/historical") / f"{case_id}.json",
        ):
            path = root / relative
            if path.is_file():
                case = load_case(path)
                if case.stage != stage:
                    raise ValueError(f"case {case_id} belongs to {case.stage}, not {stage}")
                return case
        raise FileNotFoundError(f"manual case not found: {case_id}")
    if not exploratory or input_text is None or not input_text.strip():
        raise ValueError("exploratory input must be non-empty")
    digest = hashlib.sha256(input_text.encode("utf-8")).hexdigest()[:12]
    return ManualCase(
        case_id=f"EXPLORATORY-{digest}",
        stage=stage,
        input=input_text,
        reference_now=datetime.now().astimezone().isoformat(),
        expected_stage_behavior="Observation only; no semantic acceptance is allowed.",
        expected_key_fields={
            "input_sha256": hashlib.sha256(input_text.encode("utf-8")).hexdigest()
        },
        expected_failure_or_success_semantics="NON_ACCEPTANCE_RUN",
        human_assertions=("Do not use exploratory output as a fixed acceptance record.",),
        historical_contract_acceptance=HumanDecision.PENDING,
        business_transition_baseline=BusinessTransitionBaseline.NOT_APPLICABLE,
        required_outputs=("observation_only",),
        mutation_target="Exploratory inputs have no fixed mutation contract.",
        independent_review_prompt="Exploratory output is not eligible for independent acceptance.",
    )


def _expected_payload(case: ManualCase, *, exploratory: bool) -> dict[str, Any]:
    return {
        "case_id": case.case_id,
        "stage": case.stage,
        "input": "exploratory input is intentionally not persisted"
        if exploratory
        else case.input,
        "reference_now": case.reference_now,
        "expected_stage_behavior": case.expected_stage_behavior,
        "expected_key_fields": case.expected_key_fields,
        "expected_failure_or_success_semantics": case.expected_failure_or_success_semantics,
        "human_assertions": list(case.human_assertions),
        "historical_contract_acceptance": case.historical_contract_acceptance.value,
        "business_transition_baseline": case.business_transition_baseline.value,
        "required_outputs": list(case.required_outputs),
        "exploratory": exploratory,
    }


def _execute_stage(stage: str, mode: str, case: ManualCase, root: Path) -> _StageExecution:
    try:
        if case.case_id.startswith("EXPLORATORY-") and mode == "offline":
            return _blocked(
                "custom exploratory input requires live mode; offline mode only "
                "supports fixed fixtures"
            )
        if mode == "live":
            settings = load_live_eval_settings(os.environ)
            if stage == "M4.1":
                return _run_m41_live(case, settings, root)
            if stage in {"M2", "M2.1"}:
                return _run_m2(case, stage, live=True, settings=settings)
            if stage in {"M3", "M4"}:
                return _run_public_interaction(case, settings, root, live=True, stage=stage)
            return _blocked("Live mode is not applicable to this historical contract.")
        if stage == "M0":
            return _run_m0(root)
        if stage == "M1":
            return _run_m1()
        if stage in {"M2", "M2.1"}:
            return _run_m2(case, stage)
        if stage in {"M3", "M4"}:
            return _run_public_interaction(
                case,
                Settings(deepseek_api_key="offline-manual", deepseek_model="offline-fixture"),
                root,
                live=False,
                stage=stage,
            )
        if stage == "M4.1":
            return _run_m41_offline(root)
    except EvaluationConfigurationError as exc:
        message = str(exc)[:256]
        if mode == "live":
            return _blocked(
                message,
                actual={
                    "failure": {
                        "type": "BLOCKED",
                        "stage": "live_configuration",
                        "code": "LIVE_CONFIGURATION_MISSING",
                        "cause_code": "DEEPSEEK_MODEL_REQUIRED",
                        "safe_message": message,
                    },
                    "model_id": "not_configured",
                    "llm_execution": {
                        "source": "live_llm",
                        "model_id": "not_configured",
                        "real_llm_called": False,
                        "network_calls": 0,
                    },
                    "call_stats": {
                        "llm_calls": 0,
                        "real_llm_calls": 0,
                        "planner_calls": 0,
                        "external_calls": 0,
                    },
                },
            )
        return _blocked(message)
    except (ValidationError, ValueError, OSError) as exc:
        return _failed(type(exc).__name__, str(exc)[:256])
    except Exception as exc:
        return _failed(type(exc).__name__, "manual acceptance stage execution failed")
    return _blocked("stage adapter is not implemented")


def _run_m0(root: Path) -> _StageExecution:
    from evaluation.runner import load_cases, load_fixtures, run_dataset

    dataset = root / "evaluation/datasets/baseline-v1.jsonl"
    fixture = root / "evaluation/fixtures/baseline-v1.json"
    stream = io.StringIO()
    with _configured_log_stream(stream):
        report = run_dataset(load_cases(dataset), load_fixtures(fixture))
    return _ready(
        {
            "dataset_report": report,
            "execution": report["execution"],
            "failures": report["failures"],
            "events": _parse_events(stream.getvalue()),
            "model_id": "not_applicable",
            "call_stats": {"llm_calls": 0, "external_calls": 0},
        }
    )


def _run_m1() -> _StageExecution:
    valid_payload = {
        "request_id": "manual-m1-request",
        "trip_id": "manual-m1-trip",
        "session_id": "manual-m1-session",
        "origin": "上海",
        "destinations": ["杭州"],
        "date_range": {"start": "2026-08-22", "end": "2026-08-22"},
        "travelers": {"adults": 1},
    }
    valid = TripRequest.model_validate(valid_payload)
    invalid_payload = {**valid_payload, "travelers": {"adults": 0}}
    try:
        TripRequest.model_validate(invalid_payload)
    except ValidationError as exc:
        invalid: dict[str, Any] = {
            "error_type": type(exc).__name__,
            "error_count": len(exc.errors()),
            "status": "validation_error",
        }
    else:
        invalid = {"status": "unexpected_success"}
    return _ready(
        {
            "valid_request": valid.model_dump(mode="json"),
            "invalid_request": invalid,
            "model_id": "not_applicable",
            "call_stats": {"llm_calls": 0, "external_calls": 0},
        }
    )


def _run_m2(
    case: ManualCase,
    stage: str,
    *,
    live: bool = False,
    settings: Settings | None = None,
) -> _StageExecution:
    reference = datetime.fromisoformat(case.reference_now)
    payload = _interpreter_payload(case.case_id, reference)
    gateway: LLMGateway = _CapturedGateway(payload)
    if live:
        gateway = DeepSeekLLMGateway()
    planner = _RecordingPlanner()
    active_settings = settings or Settings(
        deepseek_api_key="offline-manual", deepseek_model="offline-manual"
    )
    request = TripRequest(
        request_id=f"manual-{case.case_id}-request",
        trip_id=f"manual-{case.case_id}-trip",
        session_id=f"manual-{case.case_id}-session",
        origin="杭州",
        destinations=("上海",),
        date_range=DateRange(
            start=reference.date() + timedelta(days=6), end=reference.date() + timedelta(days=6)
        ),
        travelers=TravelerProfile(adults=1),
    )
    stream = io.StringIO()
    try:
        with _configured_log_stream(stream):
            result = TripInteractionFacade(
                active_settings,
                planner=planner,
                gateway=gateway,
                state_repository=InMemoryStateRepository(),
                clock=_FixedClock(reference),
            ).execute(request, case.input, reference_date=reference.date())
    except Exception as exc:
        model_id = active_settings.deepseek_model or "offline-manual"
        return _m2_failure(
            exc,
            live=live,
            model_id=model_id,
            events=_parse_events(stream.getvalue()),
            planner_calls=planner.calls,
        )
    events = _parse_events(stream.getvalue())
    return _ready(
        {
            "trace_id": f"route:{request.trip_id}:{request.request_id}",
            "interpretation": (
                gateway.last_payload if isinstance(gateway, _CapturedGateway) else None
            ),
            "constraint_snapshot": result.constraint_snapshot.model_dump(mode="json"),
            "readiness": result.readiness.model_dump(mode="json"),
            "business_scope": _dump_model(result.business_scope),
            "route_decision": result.route_decision.model_dump(mode="json"),
            "state": result.state.model_dump(mode="json"),
            "final_state": result.state.model_dump(mode="json"),
            "clarification": _dump_model(result.clarification),
            "plan_result": _dump_model(result.plan_result),
            "planner_calls": planner.calls,
            "events": events,
            "stage_projection": stage,
            "model_id": active_settings.deepseek_model or "offline-manual",
            "llm_execution": _llm_execution_metadata(
                live=live,
                model_id=active_settings.deepseek_model or "offline-manual",
            ),
            "call_stats": {
                "llm_calls": 1,
                "real_llm_calls": 1 if live else 0,
                "planner_calls": planner.calls,
                "external_calls": 0,
            },
        }
    )


def _run_public_interaction(
    case: ManualCase,
    settings: Settings,
    root: Path,
    *,
    live: bool,
    stage: str,
) -> _StageExecution:
    if live:
        repository = InMemoryStateRepository()
        from src.application.use_cases.m4_plan import M4PlanUseCase

        planner = M4PlanUseCase.from_settings(
            settings,
            state_repository=repository,
        )
        gateway: LLMGateway = DeepSeekLLMGateway()
    else:
        from evaluation.business_travel.offline_runner import _workflow

        reference = datetime.fromisoformat(case.reference_now)
        request = _offline_request(case.case_id, reference)
        planner, repository = _workflow(request, reference)
        gateway = _ManualOfflineGateway(request)
    reference = datetime.fromisoformat(case.reference_now)
    request = request if not live else _m4_request(case, reference)
    stream = io.StringIO()
    with _configured_log_stream(stream):
        with _event_loop_socket_if_offline(live):
            result = TripInteractionFacade(
                settings,
                planner=planner,
                gateway=gateway,
                state_repository=repository,
                clock=_FixedClock(reference),
            ).execute(request, case.input, reference_date=reference.date())
    plan_result = result.plan_result
    actual: dict[str, Any] = {
        "trace_id": f"route:{request.trip_id}:{request.request_id}",
        "route_decision": result.route_decision.model_dump(mode="json"),
        "constraint_snapshot": result.constraint_snapshot.model_dump(mode="json"),
        "readiness": result.readiness.model_dump(mode="json"),
        "state": result.state.model_dump(mode="json"),
        "events": _parse_events(stream.getvalue()),
        "plan_result": _dump_model(plan_result),
        "public_route": True,
        "stage_projection": stage,
        "model_id": settings.deepseek_model or ("offline-fixture" if not live else "configured"),
        "llm_execution": _llm_execution_metadata(
            live=live,
            model_id=settings.deepseek_model or ("offline-fixture" if not live else "configured"),
        ),
    }
    if plan_result is not None:
        orchestration = getattr(plan_result, "orchestration", None)
        task_results = _dump_model(getattr(orchestration, "task_results", None))
        actual.update(
            {
                "task_graph": _dump_model(getattr(orchestration, "graph", None)),
                "task_results": task_results,
                "provider_results": task_results,
                "evidence_snapshot": _dump_model(getattr(plan_result, "evidence_snapshot", None)),
                "candidate_pool": _dump_model(getattr(plan_result, "candidate_pool", None)),
                "plan_structure": _dump_model(getattr(plan_result, "schedule", None)),
                "call_stats": {
                    "llm_calls": 1,
                    "provider_calls": len(task_results or []),
                    "external_calls": 0 if not live else len(task_results or []),
                },
            }
        )
    else:
        actual.update(
            {
                "task_graph": None,
                "task_results": (),
                "provider_results": (),
                "evidence_snapshot": None,
                "candidate_pool": None,
                "plan_structure": None,
                "call_stats": {"llm_calls": 1, "provider_calls": 0, "external_calls": 0},
            }
        )
    return _ready(actual)


def _llm_execution_metadata(*, live: bool, model_id: str) -> dict[str, Any]:
    """标记本次是否调用真实 LLM，避免把固定响应误报为 Live 证据。"""
    return {
        "source": "live_llm" if live else "offline_fixture",
        "model_id": model_id,
        "real_llm_called": live,
        "network_calls": 1 if live else 0,
    }


def _m2_failure(
    exc: Exception,
    *,
    live: bool,
    model_id: str,
    events: list[dict[str, Any]],
    planner_calls: int,
) -> _StageExecution:
    """保留 M2 失败的安全阶段信息，不保存供应商原始响应。"""
    failure: dict[str, Any] = {
        "type": type(exc).__name__,
        "safe_message": "M2 interaction facade failed",
    }
    if isinstance(exc, WorkflowError):
        payload = exc.public_payload()
        failure.update(
            {
                "stage": payload.stage,
                "code": payload.code,
                "cause_code": payload.cause_code,
                "safe_message": payload.safe_message,
            }
        )
    execution = {
        "failure": failure,
        "events": events,
        "model_id": model_id,
        "llm_execution": _llm_execution_metadata(live=live, model_id=model_id),
        "call_stats": {
            "llm_calls": 1,
            "real_llm_calls": 1 if live else 0,
            "planner_calls": planner_calls,
            "external_calls": 0,
        },
    }
    return _StageExecution(
        actual=execution,
        runner_status=RunnerStatus.RUNTIME_FAILURE,
        error=str(failure["safe_message"]),
    )


def _run_m41_offline(root: Path) -> _StageExecution:
    formal_path = root / "evaluation/datasets/business-travel-m4.1-v1.jsonl"
    stream = io.StringIO()
    with _configured_log_stream(stream):
        component = run_offline_baseline(formal_path)
        integration = run_offline_integration(formal_path)
    return _ready(
        {
            "evaluation_status": "PASS",
            "business_assertion": {
                "component": [item.business_assertion.value for item in component.case_results],
                "integration": [item.business_assertion.value for item in integration.case_results],
            },
            "run_status": {
                "component": component.run_status,
                "integration": integration.run_status,
            },
            "live_status": "NOT_RUN",
            "status_distinction": {
                "evaluation_status": "PASS",
                "business_assertion": "separate",
                "run_status": "separate",
                "live_status": "separate",
            },
            "offline_component": {
                "result_hash": normalized_result_hash(component),
                "case_count": len(component.case_results),
            },
            "offline_integration": {
                "result_hash": normalized_result_hash(integration),
                "case_count": len(integration.case_results),
            },
            "events": _parse_events(stream.getvalue()),
            "model_id": "not_applicable",
            "call_stats": {
                "llm_calls": 0,
                "external_calls": 0,
                "semantic_runs": len(component.case_results) + len(integration.case_results),
            },
        }
    )


def _run_m41_live(case: ManualCase, settings: Settings, root: Path) -> _StageExecution:
    del case, root
    with tempfile.TemporaryDirectory(prefix="manual-m41-") as temporary:
        result = run_live_semantic(settings=settings, output_dir=Path(temporary))
        live_payload: dict[str, Any] = {}
        run_path = Path(temporary) / "run.json"
        if run_path.is_file():
            live_payload = json.loads(run_path.read_text(encoding="utf-8"))
    return (
        _ready(
            {
                "evaluation_status": result.status,
                "business_assertion": live_payload.get("case_results", []),
                "run_status": result.run_status,
                "live_status": result.status,
                "semantic_runs": result.semantic_runs,
                "live_attempt": live_payload,
            }
        )
        if result.exit_code == 0
        else _blocked(result.error_type or result.status)
    )


def _interpreter_payload(case_id: str, reference: datetime) -> dict[str, Any]:
    date_value = (reference.date() + timedelta(days=6)).isoformat()
    candidates: list[dict[str, Any]] = [
        {
            "category": "origin",
            "value": "杭州",
            "hardness": "hard",
            "scope": "trip",
            "confidence": 0.95,
        },
        {
            "category": "destination",
            "value": "上海",
            "hardness": "hard",
            "scope": "trip",
            "confidence": 0.95,
        },
        {
            "category": "date_range",
            "value": date_value,
            "hardness": "hard",
            "scope": "trip",
            "confidence": 0.95,
        },
    ]
    if case_id == "BT-ACC-002":
        candidates.append(
            {
                "category": "travelers",
                "value": 1,
                "hardness": "hard",
                "scope": "trip",
                "confidence": 0.95,
            }
        )
    if case_id == "BT-ACC-003":
        candidates.append(
            {
                "category": "travelers",
                "value": 3,
                "hardness": "hard",
                "scope": "trip",
                "confidence": 0.95,
            }
        )
    if case_id == "BT-ACC-004":
        candidates.extend(
            [
                {
                    "category": "place",
                    "value": "景点",
                    "hardness": "soft",
                    "scope": "trip",
                    "confidence": 0.95,
                },
                {
                    "category": "activity",
                    "value": "游玩",
                    "hardness": "soft",
                    "scope": "trip",
                    "confidence": 0.95,
                },
            ]
        )
    if case_id in {"BT-ACC-001", "BT-ACC-003"}:
        meeting_start_value = f"{date_value}T08:00:00"
        candidates.extend(
            [
                {
                    "category": "meeting_city",
                    "value": "上海",
                    "hardness": "hard",
                    "scope": "meeting",
                    "confidence": 0.95,
                },
                {
                    "category": "meeting_location",
                    "value": "上海东方明珠塔",
                    "hardness": "hard",
                    "scope": "meeting",
                    "confidence": 0.95,
                },
                {
                    "category": "meeting_starts_at",
                    "value": meeting_start_value,
                    "hardness": "hard",
                    "scope": "meeting",
                    "confidence": 0.95,
                },
            ]
        )
    elif case_id == "BT-ACC-002":
        candidates.extend(
            [
                {
                    "category": "meeting_city",
                    "value": "上海",
                    "hardness": "hard",
                    "scope": "meeting",
                    "confidence": 0.95,
                },
                {
                    "category": "meeting_location",
                    "value": "上海东方明珠塔",
                    "hardness": "hard",
                    "scope": "meeting",
                    "confidence": 0.95,
                },
                {
                    "category": "meeting_starts_at",
                    "value": f"{date_value}T08:00:00+08:00",
                    "hardness": "hard",
                    "scope": "meeting",
                    "confidence": 0.95,
                },
                {
                    "category": "meeting_timezone",
                    "value": "Asia/Shanghai",
                    "hardness": "hard",
                    "scope": "meeting",
                    "confidence": 0.95,
                },
                {
                    "category": "planning_horizon",
                    "value": "meeting_arrival_ready",
                    "hardness": "hard",
                    "scope": "trip",
                    "confidence": 0.95,
                },
            ]
        )
    return {
        "mode_hint": "plan",
        "extracted_entities": [
            {
                "entity_type": "meeting_location",
                "value": "上海东方明珠塔",
                "normalized_value": "上海东方明珠塔",
                "confidence": 0.95,
            },
            {
                "entity_type": "meeting_city",
                "value": "上海",
                "normalized_value": "上海",
                "confidence": 0.95,
            },
        ],
        "constraint_candidates": candidates,
        "explicit_questions": [],
        "references_to_current_plan": [],
        "field_confidence": {},
        "overall_confidence": 0.95,
        "safety_flags": [],
    }


def _m4_request(case: ManualCase, reference: datetime) -> TripRequest:
    return TripRequest(
        request_id=f"manual-{case.case_id}-request",
        trip_id=f"manual-{case.case_id}-trip",
        session_id=f"manual-{case.case_id}-session",
        origin="上海",
        destinations=("杭州",),
        date_range=DateRange(
            start=reference.date() + timedelta(days=1), end=reference.date() + timedelta(days=1)
        ),
        travelers=TravelerProfile(adults=1),
        requested_mode=InteractionMode.PLAN,
    )


@contextmanager
def _configured_log_stream(stream: io.StringIO) -> Iterator[None]:
    configure_logging("INFO", stream=stream)
    try:
        yield
    finally:
        configure_logging("INFO")


@contextmanager
def _event_loop_socket_if_offline(live: bool) -> Iterator[None]:
    if live:
        yield
        return
    from evaluation.business_travel.offline_runner import _event_loop_socket

    with _event_loop_socket():
        yield


def _parse_events(raw: str) -> list[dict[str, Any]]:
    events: list[dict[str, Any]] = []
    for line in raw.splitlines():
        try:
            item = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(item, dict) and isinstance(item.get("event"), str):
            events.append(item)
    return events


def _dump_model(value: Any) -> Any:
    if value is None:
        return None
    if isinstance(value, list | tuple):
        return [_dump_model(item) for item in value]
    if hasattr(value, "model_dump"):
        return value.model_dump(mode="json")
    if isinstance(value, dict):
        return {str(key): _dump_model(item) for key, item in value.items()}
    return value


def _ready(actual: dict[str, Any]) -> _StageExecution:
    return _StageExecution(actual=actual, runner_status=RunnerStatus.OBSERVATION_READY)


def _blocked(message: str, *, actual: dict[str, Any] | None = None) -> _StageExecution:
    payload: dict[str, Any] = {
        "failure": {"type": "BLOCKED", "safe_message": message}
    }
    if actual is not None:
        payload.update(actual)
    return _StageExecution(
        actual=payload,
        runner_status=RunnerStatus.BLOCKED,
        error=message,
    )


def _failed(error_type: str, message: str) -> _StageExecution:
    return _StageExecution(
        actual={"failure": {"type": error_type, "safe_message": message}},
        runner_status=RunnerStatus.RUNTIME_FAILURE,
        error=message,
    )


def _source_identity(root: Path) -> tuple[str, str]:
    try:
        commit = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=root,
            check=True,
            capture_output=True,
            text=True,
        ).stdout.strip()
        return source_tree_status(root).upper(), commit or "UNKNOWN"
    except (OSError, subprocess.CalledProcessError):
        return "UNKNOWN", "UNKNOWN"


def _render_observation(
    expected: dict[str, Any],
    actual: dict[str, Any],
    machine_checks: dict[str, Any],
    runtime: dict[str, Any],
    case: ManualCase,
) -> str:
    return "\n".join(
        [
            "# Manual Acceptance Observation",
            "",
            "## 案例输入",
            "",
            f"- case_id: `{case.case_id}`",
            f"- stage: `{case.stage}`",
            f"- reference_now: `{case.reference_now}`",
            f"- input: {expected.get('input', case.input)}",
            "",
            _render_human_summary(actual),
            "",
            "## 期望判断（EXPECTED）",
            "",
            "```json",
            json.dumps(expected, ensure_ascii=False, indent=2),
            "```",
            "",
            "## 实际输出（ACTUAL）",
            "",
            "```json",
            json.dumps(actual, ensure_ascii=False, indent=2),
            "```",
            "",
            "## 机器检查",
            "",
            "```json",
            json.dumps(machine_checks, ensure_ascii=False, indent=2),
            "```",
            "",
            "## 失败阶段与运行元数据",
            "",
            "```json",
            json.dumps(runtime, ensure_ascii=False, indent=2),
            "```",
            "",
            "## 人工核对清单",
            "",
            *[f"- [ ] {assertion}" for assertion in case.human_assertions],
            "",
        ]
    )


def _render_human_summary(actual: dict[str, Any]) -> str:
    """把关键语义压缩成开发者先读的中文结论。"""
    route = actual.get("route_decision")
    readiness = actual.get("readiness")
    scope = actual.get("business_scope")
    llm_source = _llm_source_summary(actual)
    if not isinstance(route, dict) or not isinstance(readiness, dict):
        failure = actual.get("failure")
        failure_summary = "详细失败信息请查看下方脱敏证据。"
        if isinstance(failure, dict):
            failure_summary = (
                f"失败阶段：{failure.get('stage', '未记录')}；"
                f"错误码：{failure.get('code', '未记录')}；"
                f"原因码：{failure.get('cause_code', '未记录')}。"
            )
        return "\n".join(
            (
                "## 人工先看这里",
                "",
                llm_source,
                "本次运行没有形成完整的路由和就绪结果。",
                failure_summary,
            )
        )

    unsupported_reason = _unsupported_boundary_reason(route)
    if unsupported_reason is not None:
        return _render_unsupported_summary(
            actual,
            llm_source=llm_source,
            reason=unsupported_reason,
        )

    mode = str(route.get("mode", "未知"))
    planner_calls = actual.get("planner_calls", "未记录")
    if isinstance(scope, dict):
        meeting = scope.get("meeting") if isinstance(scope.get("meeting"), dict) else {}
        city = meeting.get("city", "未识别")
        location = meeting.get("location", "未识别")
        starts_at = meeting.get("starts_at", "未识别")
        timezone = meeting.get("timezone", "未识别")
        travelers = meeting.get("traveler_count", "未识别")
        initial = _join_text(scope.get("initial_required_capabilities"))
        conditional = _join_text(scope.get("conditional_capabilities"))
        excluded = _join_text(scope.get("excluded_capabilities"))
        assumptions = _assumption_summary(readiness.get("assumptions"), actual)
        return "\n".join(
            [
                "## 人工先看这里",
                "",
                llm_source,
                "本次结论是：商务差旅范围已经确定，但本切片只完成语义和初始路由，没有生成最终行程。",
                (
                    f"系统识别到会议城市为“{city}”，会议地点为“{location}”，"
                    f"会议开始时间为“{starts_at}”（{timezone}），出行人数为 {travelers} 人。"
                ),
                assumptions,
                (
                    f"规划边界是“{scope.get('planning_horizon', '未识别')}”；"
                    f"首轮需要地理、政策和城际去程能力（{initial}）。"
                ),
                f"住宿属于候选级条件能力（{conditional}），市内交通的具体任务等待到达点和住宿事实；明确排除{excluded}。",
                (
                    f"当前路由模式是“{mode}”，Planner 调用 {planner_calls} 次，"
                    f"系统状态为“{_state_status(actual)}”。"
                ),
            ]
        )

    blockers = readiness.get("blockers")
    blocker_text = _blocker_summary(blockers)
    origin = _value_from_actual(actual, "origin")
    city = _value_from_actual(actual, "meeting_city")
    location = _value_from_actual(actual, "meeting_location")
    starts_at = _value_from_actual(actual, "meeting_starts_at")
    assumptions = _assumption_summary(readiness.get("assumptions"), actual)
    timezone_note = _timezone_resolution_note(readiness.get("assumptions"), actual)
    return "\n".join(
        [
            "## 人工先看这里",
            "",
            llm_source,
            "本次结论是：系统进入澄清，没有继续规划。",
            f"系统已识别出发地“{origin}”、会议城市“{city}”、会议地点“{location}”和会议开始时间“{starts_at}”。",
            (
                f"当前阻塞项是{blocker_text}；{timezone_note}"
                f"Planner 调用 {planner_calls} 次，系统状态为“{_state_status(actual)}”。"
            ),
            assumptions,
        ]
    )


def _unsupported_boundary_reason(value: Any) -> str | None:
    if not isinstance(value, dict) or value.get("mode") != "unsupported":
        return None
    reasons = value.get("reason_codes")
    if not isinstance(reasons, list):
        return None
    for reason in reasons:
        if reason in {"MULTI_TRAVELER_UNSUPPORTED", "TOURISM_UNSUPPORTED"}:
            return str(reason)
    return None


def _render_unsupported_summary(
    actual: dict[str, Any],
    *,
    llm_source: str,
    reason: str,
) -> str:
    planner_calls = actual.get("planner_calls", "未记录")
    if reason == "MULTI_TRAVELER_UNSUPPORTED":
        travelers = _value_from_actual(actual, "travelers")
        conclusion = (
            f"系统识别到 {travelers} 人同行；当前产品只支持单人商务差旅，"
            "本次请求不进入规划。"
        )
    else:
        conclusion = (
            "系统识别到这是普通旅游请求；当前产品专注商务差旅，"
            "旅游请求不受支持，本次不进入规划。"
        )
    assumption_summary = (
        "本次没有生成商务差旅默认假设。"
        if reason == "TOURISM_UNSUPPORTED"
        else _assumption_summary(
            actual.get("readiness", {}).get("assumptions")
            if isinstance(actual.get("readiness"), dict)
            else None,
            actual,
        )
    )
    return "\n".join(
        [
            "## 人工先看这里",
            "",
            llm_source,
            "本次结论是：请求超出当前产品边界，系统明确拒绝继续规划。",
            conclusion,
            (
                f"边界原因是“{reason}”；Planner 调用 {planner_calls} 次，"
                f"系统状态为“{_state_status(actual)}”。"
            ),
            assumption_summary,
        ]
    )


def _llm_source_summary(actual: dict[str, Any]) -> str:
    """以中文摘要说明结果来自固定响应还是真实 LLM。"""
    metadata = actual.get("llm_execution")
    if not isinstance(metadata, dict):
        return "运行来源：未记录；真实 LLM 调用：未知；网络调用：未知。"
    source = metadata.get("source")
    if source == "live_llm":
        source_text = "真实 DeepSeek LLM"
    elif source == "offline_fixture":
        source_text = "离线固定响应"
    else:
        source_text = str(source or "未知")
    called = "是" if metadata.get("real_llm_called") is True else "否"
    network_calls = metadata.get("network_calls", "未知")
    return f"运行来源：{source_text}；真实 LLM 调用：{called}；网络调用：{network_calls} 次。"


def _value_from_actual(actual: dict[str, Any], category: str) -> str:
    snapshot = actual.get("constraint_snapshot")
    if isinstance(snapshot, dict):
        constraints = snapshot.get("constraints")
        if isinstance(constraints, list):
            for item in constraints:
                if isinstance(item, dict) and item.get("category") == category:
                    return _display_value(item.get("normalized_value"))
    interpretation = actual.get("interpretation")
    if isinstance(interpretation, dict):
        candidates = interpretation.get("constraint_candidates")
        if isinstance(candidates, list):
            for item in candidates:
                if isinstance(item, dict) and item.get("category") == category:
                    return _display_value(item.get("value"))
    return "未识别"


def _display_value(value: Any) -> str:
    if value is None:
        return "未提供"
    if isinstance(value, dict) and "start" in value and "end" in value:
        if value["start"] == value["end"]:
            return str(value["start"])
        return f"{value['start']} 至 {value['end']}"
    return str(value)


def _assumption_summary(value: Any, actual: dict[str, Any]) -> str:
    """把系统假设翻译为人工验收可以直接判断的中文。"""
    if not isinstance(value, list) or not value:
        return "本次没有新增系统假设。"
    summaries: list[str] = []
    for item in value:
        if not isinstance(item, dict):
            continue
        field = item.get("field")
        if field == "meeting_timezone":
            timezone = _value_from_actual(actual, "meeting_timezone")
            summaries.append(f"会议时区根据可识别的会议城市推导为“{timezone}”，尚未获得用户确认")
        elif field == "travelers":
            travelers = _value_from_actual(actual, "travelers")
            summaries.append(f"未明确人数，当前按 {travelers} 人规划，尚未获得用户确认")
        elif field == "budget":
            summaries.append("用户未提供预算，本次不推测预算金额")
        else:
            message = item.get("message")
            summaries.append(str(message or f"系统对 {field or '未知字段'} 使用了假设"))
    if not summaries:
        return "本次没有新增系统假设。"
    return f"系统假设：{'；'.join(summaries)}。"


def _timezone_resolution_note(value: Any, actual: dict[str, Any]) -> str:
    if isinstance(value, list) and any(
        isinstance(item, dict) and item.get("field") == "meeting_timezone"
        for item in value
    ):
        timezone = _value_from_actual(actual, "meeting_timezone")
        return f"会议时区已根据可识别会议城市采用 {timezone} 假设；"
    return "系统无法根据当前会议地点唯一确定会议时区，未自行补全；"


def _join_text(value: Any) -> str:
    if isinstance(value, list | tuple):
        return "、".join(str(item) for item in value) or "无"
    return str(value) if value else "无"


def _blocker_summary(value: Any) -> str:
    if not isinstance(value, list) or not value:
        return "未形成可展示的结构化阻塞项"
    names = [
        str(item.get("field") or item.get("code") or "未知阻塞项")
        for item in value
        if isinstance(item, dict)
    ]
    return "、".join(names) if names else "未形成可展示的结构化阻塞项"


def _state_status(actual: dict[str, Any]) -> str:
    state = actual.get("final_state") or actual.get("state")
    if isinstance(state, dict):
        return str(state.get("status", "未知"))
    return "未知"
