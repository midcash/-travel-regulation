from __future__ import annotations

from decimal import Decimal

import pytest
from pydantic import ValidationError

from src.application.use_cases.plan_trip import (
    PlanTripResult,
    PlanTripUseCase,
    render_legacy_request,
)
from src.config import Settings
from src.domain.errors import WorkflowError
from src.domain.models.trip_request import BudgetSemantics, BudgetSpec, TravelerProfile, TripRequest
from src.domain.models.value_objects import DateRange, Money


def _request() -> TripRequest:
    return TripRequest(
        request_id="request-1",
        trip_id="trip-1",
        session_id="session-1",
        origin="上海",
        destinations=("深圳", "珠海"),
        date_range=DateRange(start="2026-08-01", end="2026-08-03"),
        travelers=TravelerProfile(adults=2),
        budget=BudgetSpec(
            semantics=BudgetSemantics.MAXIMUM,
            maximum=Money(amount=Decimal("3000"), currency="CNY"),
        ),
        preferences=("科技",),
        explicit_exclusions=("不安排夜间航班",),
    )


def test_facade_calls_legacy_and_returns_typed_result() -> None:
    calls: list[tuple[str, Settings]] = []

    def fake_planner(user_input: str, *, settings: Settings) -> dict[str, object]:
        calls.append((user_input, settings))
        return {"plan": "兼容方案", "rounds": 1, "issues_found": ["提示"]}

    settings = Settings(deepseek_api_key="test-key")
    result = PlanTripUseCase(settings, planner=fake_planner).execute(_request())

    assert isinstance(result, PlanTripResult)
    assert result.plan == "兼容方案"
    assert result.issues_found == ("提示",)
    assert result.trip_id == "trip-1"
    assert calls == [(render_legacy_request(_request()), settings)]


def test_render_legacy_request_preserves_structured_request_facts() -> None:
    rendered = render_legacy_request(_request())

    assert "出发地：上海" in rendered
    assert "目的地：深圳、珠海" in rendered
    assert "日期：2026-08-01至2026-08-03" in rendered
    assert "预算上限：3000CNY" in rendered
    assert "排除：不安排夜间航班" in rendered


def test_facade_wraps_legacy_failure_without_leaking_cause() -> None:
    def fail(_: str, *, settings: Settings) -> dict[str, object]:
        raise RuntimeError("secret-key=must-not-leak")

    with pytest.raises(WorkflowError) as raised:
        PlanTripUseCase(Settings(deepseek_api_key="test-key"), planner=fail).execute(_request())

    error = raised.value
    assert error.category.value == "validation"
    assert error.public_payload().safe_message == "legacy planner returned an invalid result"
    assert "secret-key" not in str(error.public_payload())
    assert error.cause is not None


def test_facade_wraps_planning_error_with_stage_and_retryability() -> None:
    from src.engine.loop import PlanningError

    def fail(_: str, *, settings: Settings) -> dict[str, object]:
        raise PlanningError("review", "审查失败", retryable=True)

    with pytest.raises(WorkflowError) as raised:
        PlanTripUseCase(Settings(deepseek_api_key="test-key"), planner=fail).execute(_request())

    error = raised.value
    assert error.stage == "review"
    assert error.category.value == "llm"
    assert error.retryable is True


def test_facade_rejects_invalid_legacy_result() -> None:
    def invalid(_: str, *, settings: Settings) -> dict[str, object]:
        return {"plan": "方案", "rounds": 1, "issues_found": [], "unexpected": True}

    with pytest.raises(WorkflowError) as raised:
        PlanTripUseCase(Settings(deepseek_api_key="test-key"), planner=invalid).execute(_request())

    assert raised.value.stage == "mapping"
    assert isinstance(raised.value.cause, ValidationError)


def test_render_legacy_request_supports_duration_and_budget_shapes() -> None:
    duration_request = _request().model_copy(
        update={
            "date_range": None,
            "duration_days": 2,
            "budget": BudgetSpec(
                semantics=BudgetSemantics.RANGE,
                minimum=Money(amount=Decimal("1000"), currency="CNY"),
                maximum=Money(amount=Decimal("2000"), currency="CNY"),
            ),
        }
    )
    duration_rendered = render_legacy_request(duration_request)

    assert "\u5929\u6570\uff1a2\u5929" in duration_rendered
    assert "\u9884\u7b97\u8303\u56f4\uff1a1000-2000CNY" in duration_rendered

    target_request = _request().model_copy(
        update={
            "budget": BudgetSpec(
                semantics=BudgetSemantics.TARGET,
                target=Money(amount=Decimal("1800"), currency="CNY"),
            )
        }
    )

    assert "\u76ee\u6807\u9884\u7b97\uff1a1800CNY" in render_legacy_request(target_request)
