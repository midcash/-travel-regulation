"""M2.1 第一步：冻结 M2 行为与观测字段的离线基线。"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, date, datetime
from decimal import Decimal

import pytest

from src.application.interaction_facade import TripInteractionFacade, TripInteractionResult
from src.application.use_cases.plan_trip import PlanTripResult
from src.config import Settings
from src.domain.errors import WorkflowError, WorkflowErrorPayload
from src.domain.models.enums import (
    ConstraintHardness,
    ErrorCategory,
    InteractionMode,
    WorkflowStatus,
)
from src.domain.models.interpretation import ConstraintCandidate, InterpretationResult
from src.domain.models.state import TripState
from src.domain.models.trip_request import TravelerProfile, TripRequest
from src.domain.models.value_objects import DateRange
from src.engine import loop
from src.infrastructure.persistence.in_memory import InMemoryStateRepository
from src.ports.llm_gateway import LLMOutputMode
from tests.support.clock_fakes import FakeClock
from tests.support.fakes import FakeLLM
from tests.support.llm_fakes import FakeLLMGateway


@dataclass(frozen=True, slots=True)
class BaselineCase:
    """一个固定的 M2 离线行为样本。"""

    case_id: str
    raw_input: str
    interpretation_response: str
    expected_state: WorkflowStatus
    expected_mode: InteractionMode | None = None
    expected_reason_codes: tuple[str, ...] = ()
    expected_blocker_codes: tuple[str, ...] = ()
    expected_snapshot_version: int | None = None
    expected_constraint_count: int | None = None
    expected_question_count: int | None = None
    expected_error_stage: str | None = None
    expected_error_category: ErrorCategory | None = None
    expected_error_code: str | None = None
    expected_planner_calls: int = 0


@dataclass(frozen=True, slots=True)
class ObservationRecord:
    """只供等价性断言使用的安全测试观察摘要。"""

    output_chars: int


class ObservingFakeLLMGateway(FakeLLMGateway):
    """测试专用观察包装器，不是生产运行时埋点。"""

    def __init__(
        self,
        responses: list[str | BaseException],
        *,
        observation_enabled: bool,
    ) -> None:
        super().__init__(responses)
        self._observation_enabled = observation_enabled
        self.records: list[ObservationRecord] = []

    def complete(
        self,
        prompt: str,
        *,
        settings: Settings,
        output_mode: LLMOutputMode = LLMOutputMode.TEXT,
    ) -> str:
        """转发 Fake 调用，并仅在测试内收集安全长度摘要。"""
        response = super().complete(
            prompt,
            settings=settings,
            output_mode=output_mode,
        )
        if self._observation_enabled:
            self.records.append(ObservationRecord(output_chars=len(response)))
        return response


class RecordingPlanner:
    """记录 legacy Planner 调用而不引入实际网络依赖。"""

    def __init__(self) -> None:
        self.calls: list[TripRequest] = []

    def execute(self, request: TripRequest) -> PlanTripResult:
        """返回确定性的兼容规划结果。"""
        self.calls.append(request)
        return PlanTripResult(
            request_id=request.request_id,
            trip_id=request.trip_id,
            session_id=request.session_id,
            plan="legacy plan",
            rounds=1,
            issues_found=(),
        )


@dataclass(frozen=True, slots=True)
class BaselineExecution:
    """一次基线执行的业务可见结果。"""

    result: TripInteractionResult | None
    error_payload: WorkflowErrorPayload | None
    persisted_state: TripState
    gateway: ObservingFakeLLMGateway
    planner_call_count: int


def _request(case_id: str) -> TripRequest:
    """构造不含 PII 的固定旅行请求。"""
    return TripRequest(
        request_id=f"{case_id}-request",
        trip_id=f"{case_id}-trip",
        session_id=f"{case_id}-session",
        origin="上海",
        destinations=("杭州",),
        date_range=DateRange(start=date(2026, 8, 1), end=date(2026, 8, 3)),
        travelers=TravelerProfile(adults=2),
    )


def _candidate(category: str, value: object) -> ConstraintCandidate:
    """构造固定解释候选，供 Fake Gateway 返回。"""
    return ConstraintCandidate(
        category=category,
        value=value,
        hardness=ConstraintHardness.HARD,
        scope="trip",
        confidence=Decimal("0.95"),
    )


def _interpretation_response(*candidates: ConstraintCandidate) -> str:
    """生成符合当前 M2 Schema 的固定解释响应。"""
    return InterpretationResult(
        mode_hint=InteractionMode.PLAN,
        extracted_entities=(),
        constraint_candidates=candidates,
        explicit_questions=(),
        references_to_current_plan=(),
        field_confidence={},
        overall_confidence=Decimal("0.95"),
        safety_flags=(),
    ).model_dump_json()


_READY_CANDIDATES = (
    _candidate("origin", "上海"),
    _candidate("destination", "杭州"),
    _candidate("date_range", "2026年8月1日至2026年8月3日"),
    _candidate("travelers", 2),
)

_CONSTRAINT_FAILURE_CANDIDATES = (
    _candidate("origin", "上海"),
    _candidate("destination", "杭州"),
    _candidate("date_range", "unsupported-date"),
    _candidate("travelers", 2),
)

_BASELINE_CASES = (
    BaselineCase(
        case_id="m21-plan-success",
        raw_input="请安排上海到杭州的三日行程。",
        interpretation_response=_interpretation_response(*_READY_CANDIDATES),
        expected_state=WorkflowStatus.RESEARCHING,
        expected_mode=InteractionMode.PLAN,
        expected_reason_codes=("PLAN_REQUEST",),
        expected_snapshot_version=1,
        expected_constraint_count=4,
        expected_planner_calls=1,
    ),
    BaselineCase(
        case_id="m21-clarify",
        raw_input="我想安排一次旅行。",
        interpretation_response=_interpretation_response(),
        expected_state=WorkflowStatus.CLARIFYING,
        expected_mode=InteractionMode.CLARIFY,
        expected_reason_codes=("CLARIFICATION_REQUIRED",),
        expected_blocker_codes=(
            "MISSING_ORIGIN",
            "MISSING_DESTINATION",
            "DATE_OR_DURATION_UNDETERMINED",
            "TRAVELER_COUNT_UNDETERMINED",
        ),
        expected_snapshot_version=1,
        expected_constraint_count=0,
        expected_question_count=3,
    ),
    BaselineCase(
        case_id="m21-interpreter-failure",
        raw_input="请安排上海到杭州的三日行程。",
        interpretation_response="not-json",
        expected_state=WorkflowStatus.FAILED,
        expected_error_stage="request_interpreter",
        expected_error_category=ErrorCategory.VALIDATION,
        expected_error_code="INTERPRETATION_INVALID",
    ),
    BaselineCase(
        case_id="m21-constraint-failure",
        raw_input="请安排上海到杭州的三日行程。",
        interpretation_response=_interpretation_response(*_CONSTRAINT_FAILURE_CANDIDATES),
        expected_state=WorkflowStatus.FAILED,
        expected_error_stage="constraint_service",
        expected_error_category=ErrorCategory.VALIDATION,
        expected_error_code="INTERPRETATION_INVALID",
    ),
)


def _execute_case(
    case: BaselineCase,
    *,
    observation_enabled: bool,
) -> BaselineExecution:
    """在固定时钟、Fake Gateway 与独立状态仓库中执行一个基线样本。"""
    request = _request(case.case_id)
    gateway = ObservingFakeLLMGateway(
        [case.interpretation_response],
        observation_enabled=observation_enabled,
    )
    planner = RecordingPlanner()
    repository = InMemoryStateRepository()
    facade = TripInteractionFacade(
        Settings(),
        planner=planner,
        gateway=gateway,
        state_repository=repository,
        clock=FakeClock(datetime(2026, 7, 30, 12, tzinfo=UTC)),
    )

    try:
        result = facade.execute(request, case.raw_input)
    except WorkflowError as error:
        return BaselineExecution(
            result=None,
            error_payload=error.public_payload(),
            persisted_state=repository.get(request.trip_id),
            gateway=gateway,
            planner_call_count=len(planner.calls),
        )

    return BaselineExecution(
        result=result,
        error_payload=None,
        persisted_state=repository.get(request.trip_id),
        gateway=gateway,
        planner_call_count=len(planner.calls),
    )


@pytest.mark.integration
@pytest.mark.parametrize("case", _BASELINE_CASES, ids=lambda item: item.case_id)
def test_m2_behavior_samples_remain_fixed(case: BaselineCase) -> None:
    """冻结 M2 成功、澄清与两类失败的类型化外部行为。"""
    execution = _execute_case(case, observation_enabled=False)

    assert execution.persisted_state.status is case.expected_state
    assert execution.persisted_state.version == 2
    if case.expected_error_stage is None:
        assert execution.persisted_state.last_error is None
    else:
        assert execution.persisted_state.last_error is not None
        assert execution.persisted_state.last_error.stage == case.expected_error_stage
        assert execution.persisted_state.last_error.code == case.expected_error_code
    assert len(execution.gateway.calls) == 1
    assert execution.planner_call_count == case.expected_planner_calls

    if case.expected_error_stage is not None:
        assert execution.result is None
        assert execution.error_payload is not None
        assert execution.error_payload.stage == case.expected_error_stage
        assert execution.error_payload.category is case.expected_error_category
        assert execution.error_payload.code == case.expected_error_code
        return

    assert execution.error_payload is None
    assert execution.result is not None
    assert execution.result.route_decision.mode == case.expected_mode.value
    assert tuple(
        code.value for code in execution.result.route_decision.reason_codes
    ) == case.expected_reason_codes
    assert execution.result.constraint_snapshot.version == case.expected_snapshot_version
    assert len(execution.result.constraint_snapshot.constraints) == case.expected_constraint_count
    assert tuple(
        blocker.code.value for blocker in execution.result.readiness.blockers
    ) == case.expected_blocker_codes

    if case.expected_question_count is not None:
        assert execution.result.clarification is not None
        assert len(execution.result.clarification.questions) == case.expected_question_count
    else:
        assert execution.result.clarification is None


@pytest.mark.integration
@pytest.mark.parametrize("case", _BASELINE_CASES, ids=lambda item: item.case_id)
def test_test_only_observation_toggle_preserves_m2_business_behavior(
    case: BaselineCase,
) -> None:
    """冻结后续埋点接入时必须保持的业务等价性。"""
    disabled = _execute_case(case, observation_enabled=False)
    enabled = _execute_case(case, observation_enabled=True)

    assert enabled.result == disabled.result
    assert enabled.error_payload == disabled.error_payload
    assert enabled.persisted_state == disabled.persisted_state
    assert enabled.planner_call_count == disabled.planner_call_count
    assert enabled.gateway.calls == disabled.gateway.calls
    assert disabled.gateway.records == []
    assert len(enabled.gateway.records) == 1


@pytest.mark.integration
def test_legacy_l2_revision_sample_remains_fixed(monkeypatch: pytest.MonkeyPatch) -> None:
    """冻结 legacy L2 触发一次修订后的轮次、调用数和问题来源。"""
    planner_llm = FakeLLM(
        [
            "预算 2000 元，总费用 1200 元。",
            "预算 2000 元，总费用 1100 元，并保留休息安排。",
        ]
    )
    review_results = [
        {"pass": False, "issues": ["缺少休息安排"]},
        {"pass": True, "issues": []},
    ]
    review_call_count = 0

    def fake_l2_review(
        user_input: str,
        plan_text: str,
        constraints: list[str],
        *,
        settings: Settings,
    ) -> dict[str, object]:
        """返回固定 L2 结果，不记录自由文本到测试产物。"""
        nonlocal review_call_count
        assert user_input
        assert plan_text
        assert isinstance(constraints, list)
        assert settings.strict_mode is True
        review_call_count += 1
        return review_results.pop(0)

    monkeypatch.setattr(loop, "ask_llm", planner_llm)
    monkeypatch.setattr(loop, "run_l2_review", fake_l2_review)

    result = loop.plan(
        "安排一次预算 2000 元的城市旅行。",
        settings=Settings(deepseek_api_key="fake-key"),
    )

    assert result["rounds"] == 2
    assert result["issues_found"] == ["缺少休息安排"]
    assert len(planner_llm.calls) == 2
    assert review_call_count == 2
