from __future__ import annotations

from datetime import date

from evaluation.business_travel.semantic_use_case import SemanticEvaluationUseCase
from src.config import Settings
from src.domain.models.trip_request import TravelerProfile, TripRequest
from src.domain.models.value_objects import DateRange
from tests.support.llm_fakes import FakeLLMGateway


def _request() -> TripRequest:
    return TripRequest(
        request_id="eval-request",
        trip_id="eval-trip",
        session_id="eval-session",
        origin="Shanghai",
        destinations=("Hangzhou",),
        date_range=DateRange(start=date(2026, 8, 20), end=date(2026, 8, 20)),
        travelers=TravelerProfile(adults=1),
    )


def _plan_interpretation() -> str:
    return (
        '{"mode_hint":"plan","extracted_entities":[],"constraint_candidates":['
        '{"category":"origin","value":"Shanghai","hardness":"hard","scope":"trip",'
        '"confidence":0.95},{"category":"destination","value":"Hangzhou",'
        '"hardness":"hard","scope":"trip","confidence":0.95},{"category":"date_range",'
        '"value":"2026-08-20","hardness":"hard","scope":"trip","confidence":0.95},'
        '{"category":"travelers","value":1,"hardness":"hard","scope":"trip",'
        '"confidence":0.95}],"explicit_questions":[],"references_to_current_plan":[],'
        '"field_confidence":{},"overall_confidence":0.95,"safety_flags":[]}'
    )


class ForbiddenDownstream:
    def __init__(self) -> None:
        self.calls = 0

    def __getattr__(self, name: str):
        def forbidden(*args: object, **kwargs: object) -> None:
            self.calls += 1
            raise AssertionError(f"downstream call: {name}")

        return forbidden


def test_semantic_use_case_stops_after_router_for_plan() -> None:
    forbidden_downstream = ForbiddenDownstream()
    use_case = SemanticEvaluationUseCase(
        Settings(deepseek_api_key="offline-eval"),
        gateway=FakeLLMGateway([_plan_interpretation()]),
    )

    result = use_case.execute(
        _request(),
        "请规划从上海到杭州的会议去程",
        reference_date=date(2026, 8, 12),
    )

    assert result.route_decision.mode == "plan"
    assert result.g0.passed is True
    assert tuple(result.trajectory) == (
        "g0",
        "interpreter",
        "constraint_service",
        "readiness_evaluator",
        "router",
    )
    assert forbidden_downstream.calls == 0
