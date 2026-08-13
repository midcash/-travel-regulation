from __future__ import annotations

import json
import os
from collections.abc import Callable, Mapping
from dataclasses import dataclass, replace
from datetime import timedelta
from pathlib import Path

from evaluation.business_travel.contracts import (
    ComponentAvailability,
    FailureCategory,
    RunStatus,
)
from evaluation.business_travel.fingerprints import (
    dataset_fingerprint,
    policy_fingerprint,
    runtime_fingerprint,
    view_fixture_fingerprint,
)
from evaluation.business_travel.registry import BusinessTravelCaseRegistry
from evaluation.business_travel.scoring import score_case
from evaluation.business_travel.semantic_use_case import (
    SemanticEvaluationResult,
    SemanticEvaluationUseCase,
)
from src.config import ConfigurationError, Settings, load_settings
from src.domain.errors import WorkflowError
from src.domain.models.trip_request import TravelerProfile, TripRequest
from src.domain.models.value_objects import DateRange
from src.ports.llm_gateway import LLMGateway, LLMResponseError


class EvaluationConfigurationError(ConfigurationError):
    """Live 评测配置不完整或不合法。"""


def load_live_eval_settings(environ: Mapping[str, str]) -> Settings:
    """加载显式 Live 配置，不允许隐式模型回退。"""
    model = environ.get("DEEPSEEK_MODEL", "").strip()
    if not model:
        raise EvaluationConfigurationError("DEEPSEEK_MODEL is required")
    try:
        settings = load_settings(environ)
    except ConfigurationError as exc:
        raise EvaluationConfigurationError(str(exc)) from exc
    if not settings.deepseek_api_key:
        raise EvaluationConfigurationError("DEEPSEEK_API_KEY is required")
    return replace(
        settings,
        retry_count=0,
        cache_reads=False,
        fallbacks=False,
        partial_success=False,
        deepseek_model=model,
        deepseek_max_tokens=4096,
    )


@dataclass(frozen=True, slots=True)
class LiveRunResult:
    status: str
    run_status: str
    exit_code: int
    output_dir: Path
    error_type: str | None = None
    semantic_runs: int = 0
    downstream_calls: int = 0


def _workflow_error_summary(exc: BaseException, *, case_id: str | None = None) -> dict[str, object]:
    """Build a safe, structured failure summary without raw prompts or responses."""
    if isinstance(exc, WorkflowError):
        payload = exc.public_payload()
        cause = exc.cause
        summary: dict[str, object] = {
            "trace_id": str(payload.trace_id),
            "stage": payload.stage,
            "category": payload.category.value,
            "code": payload.code,
            "cause_code": payload.cause_code,
            "message": payload.safe_message,
            "retryable": payload.retryable,
            "cause_type": type(cause).__name__ if cause is not None else None,
            "cause_summary": _safe_cause_summary(cause),
            "finish_reason": getattr(cause, "finish_reason", None),
            "model": getattr(cause, "model", None),
            "max_tokens": getattr(cause, "max_tokens", None),
            "input_tokens": getattr(cause, "input_tokens", 0),
            "output_tokens": getattr(cause, "output_tokens", 0),
        }
    else:
        summary = {
            "trace_id": f"live:{case_id}" if case_id else "live:unknown",
            "stage": "live_runner",
            "category": "internal",
            "code": "UNCLASSIFIED_FAILURE",
            "cause_code": "UNCLASSIFIED_FAILURE",
            "message": "live semantic evaluation failed",
            "retryable": False,
            "cause_type": type(exc).__name__,
            "cause_summary": _safe_cause_summary(exc),
            "finish_reason": None,
            "model": None,
            "max_tokens": None,
            "input_tokens": 0,
            "output_tokens": 0,
        }
    return summary


def _safe_cause_summary(cause: BaseException | None) -> str | None:
    """Return a bounded summary without copying arbitrary provider payloads."""
    if cause is None:
        return None
    if isinstance(cause, LLMResponseError):
        return str(cause)[:256]
    if isinstance(cause, TimeoutError):
        return "LLM request timed out"
    if isinstance(cause, ConfigurationError):
        return str(cause)[:256]
    return type(cause).__name__


def _semantic_summary(result: SemanticEvaluationResult) -> dict[str, object]:
    """提取可用于 Oracle 对照的语义字段，不保存 Prompt 或供应商响应。"""
    return {
        "mode": result.route_decision.mode,
        "required_capabilities": list(result.route_decision.required_capabilities),
        "missing_blocker_fields": [blocker.field for blocker in result.readiness.blockers],
        "terminal_status": {
            "clarify": "clarifying",
            "unsupported": "unsupported_scope",
        }.get(result.route_decision.mode, "planned"),
        "trajectory": list(result.trajectory),
    }


def _live_identity(settings: Settings) -> dict[str, str]:
    """计算 Live Artifact 使用的四类配置指纹。"""
    evaluation_root = Path("evaluation")
    manifest = json.loads(
        (evaluation_root / "datasets" / "business-travel-m4.1-manifest.json").read_text(
            encoding="utf-8"
        )
    )
    policy_hashes = {
        str(key): str(value) for key, value in manifest["policy_hashes"].items()
    }
    return {
        "runtime_fingerprint": runtime_fingerprint(
            provider="deepseek",
            model=settings.deepseek_model,
            base_url="https://api.deepseek.com",
            timeout_seconds=settings.llm_timeout_seconds,
            temperature=(
                0
                if settings.deepseek_model.casefold().startswith("deepseek-v4")
                else "provider_default"
            ),
            retry_count=settings.retry_count,
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


def _write_attempt(output_dir: Path, payload: dict[str, object]) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    (output_dir / "run.json").write_text(
        json.dumps(payload, ensure_ascii=False, sort_keys=True, indent=2) + "\n",
        encoding="utf-8",
    )


def run_live_semantic(
    *,
    settings: Settings,
    output_dir: Path,
    gateway_factory: Callable[[Settings], object] | None = None,
) -> LiveRunResult:
    """执行受控 Live 语义评测；任何外部失败都保留 attempt。"""
    base_payload: dict[str, object] = {
        "status": "LIVE_ATTEMPT_RECORDED",
        "run_status": "EXTERNAL_FAILURE",
        "provider": "deepseek",
        "model": settings.deepseek_model,
        "max_tokens": 4096,
        "retry_count": 0,
        "temperature": "provider_default",
        "seed_status": "unsupported",
    }
    try:
        if not settings.deepseek_api_key:
            raise EvaluationConfigurationError("DEEPSEEK_API_KEY is required")
        if not settings.deepseek_model.strip():
            raise EvaluationConfigurationError("DEEPSEEK_MODEL is required")
        if gateway_factory is None:
            from src.gateway.deepseek_adapter import DeepSeekLLMGateway

            def default_gateway_factory(_: Settings) -> object:
                return DeepSeekLLMGateway()

            gateway_factory = default_gateway_factory
        gateway = gateway_factory(settings)
        if not isinstance(gateway, LLMGateway):
            raise TypeError("gateway_factory must return an LLMGateway")
        registry = BusinessTravelCaseRegistry.load(
            Path("evaluation/datasets/business-travel-m4.1-v1.jsonl")
        )
        blocking = registry.select(tags=frozenset({"blocking_live_stability"}))
        observation = registry.select(tags=frozenset({"blocking_live_stability"}))
        observation_ids = {case.case_id for case in blocking}
        observation = tuple(
            case for case in registry.cases if case.case_id not in observation_ids
        )[:8]
        live_cases = tuple(case for case in blocking for _ in range(3)) + observation
        if len(live_cases) > 20:
            raise EvaluationConfigurationError("live interpreter call budget exceeded")
        semantic = SemanticEvaluationUseCase(settings, gateway=gateway)
        identity = _live_identity(settings)
        semantic_runs = 0
        case_results: list[dict[str, object]] = []
        current_case_id: str | None = None
        for case in live_cases:
            current_case_id = case.case_id
            request = TripRequest(
                request_id=f"live-{case.case_id}",
                trip_id=f"live-{case.case_id}",
                session_id=f"live-session-{case.case_id}",
                origin="Shanghai",
                destinations=("Hangzhou",),
                date_range=DateRange(
                    start=case.fixed_now.date(),
                    end=case.fixed_now.date() + timedelta(days=1),
                ),
                travelers=TravelerProfile(adults=1),
            )
            semantic_result = semantic.execute(
                request,
                case.input_text,
                reference_date=case.fixed_now.date(),
            )
            semantic_summary = _semantic_summary(semantic_result)
            score = score_case(
                {
                    "predicted": {
                        "mode": semantic_summary["mode"],
                        "clarification_fields": semantic_summary["missing_blocker_fields"],
                        "capabilities": semantic_summary["required_capabilities"],
                        "scope": (),
                        "lodging": "not_required",
                        "terminal_status": semantic_summary["terminal_status"],
                        "trajectory": semantic_summary["trajectory"],
                        "recommendation_evidence_types": (),
                        "forbidden_outputs": (),
                    },
                    "component_availability": ComponentAvailability.IMPLEMENTED.value,
                    "run_status": RunStatus.COMPLETED.value,
                    "failure_category": FailureCategory.BUSINESS.value,
                },
                case,
            )
            case_results.append(
                {
                    "case_id": case.case_id,
                    "view": (
                        "live_blocking"
                        if "blocking_live_stability" in case.tags
                        else "live_observation"
                    ),
                    "semantic": semantic_summary,
                    "business_assertion": score.business_assertion.value,
                    "first_failed_stage": (
                        score.first_failed_stage.value
                        if score.first_failed_stage is not None
                        else None
                    ),
                    "failure_category": (
                        score.failure_category.value if score.failure_category is not None else None
                    ),
                    "metric_values": {
                        key: (None if value is None else str(value))
                        for key, value in score.metric_values.items()
                    },
                }
            )
            semantic_runs += 1
        base_payload.update({"status": "LIVE_BASELINE_SUCCESS", "run_status": "COMPLETED"})
        base_payload["semantic_runs"] = semantic_runs
        base_payload["downstream_calls"] = 0
        base_payload["case_results"] = case_results
        base_payload.update(identity)
        _write_attempt(output_dir, base_payload)
        return LiveRunResult(
            "LIVE_BASELINE_SUCCESS", "COMPLETED", 0, output_dir, semantic_runs=semantic_runs
        )
    except Exception as exc:
        base_payload.update(
            {
                "error_type": type(exc).__name__,
                "workflow_error": _workflow_error_summary(
                    exc,
                    case_id=locals().get("current_case_id"),
                ),
                "case_id": locals().get("current_case_id"),
                "semantic_runs": locals().get("semantic_runs", 0),
            }
        )
        _write_attempt(output_dir, base_payload)
        return LiveRunResult(
            "LIVE_ATTEMPT_RECORDED",
            "EXTERNAL_FAILURE",
            1,
            output_dir,
            type(exc).__name__,
            semantic_runs=locals().get("semantic_runs", 0),
            downstream_calls=0,
        )


def run_live_semantic_from_environment() -> LiveRunResult:
    output_dir = Path("evaluation/reports/M4.1/runs/live-attempt")
    try:
        settings = load_live_eval_settings(os.environ)
    except EvaluationConfigurationError as exc:
        _write_attempt(
            output_dir,
            {
                "status": "LIVE_ATTEMPT_RECORDED",
                "run_status": "EXTERNAL_FAILURE",
                "provider": "deepseek",
                "model": os.environ.get("DEEPSEEK_MODEL", "").strip() or "<unset>",
                "max_tokens": 4096,
                "retry_count": 0,
                "temperature": "provider_default",
                "seed_status": "unsupported",
                "error_type": type(exc).__name__,
                "workflow_error": _workflow_error_summary(exc),
            },
        )
        return LiveRunResult(
            "LIVE_ATTEMPT_RECORDED",
            "EXTERNAL_FAILURE",
            1,
            output_dir,
            type(exc).__name__,
        )
    return run_live_semantic(
        settings=settings,
        output_dir=output_dir,
    )
