"""Structured legacy L2 review for the compatibility planner."""

from __future__ import annotations

from typing import TypedDict

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    StrictBool,
    StrictStr,
    field_validator,
    model_validator,
)

from src.config import Settings
from src.engine.prompts import build_review_prompt
from src.gateway.deepseek import ask_llm
from src.gateway.json_utils import JsonResponseError, parse_json_object
from src.obs.log import get_logger
from src.ports.llm_gateway import LLMOutputMode

logger = get_logger(__name__)


class L2ReviewError(RuntimeError):
    """Raised when the L2 response violates the structured review contract."""


class _L2ReviewPayload(BaseModel):
    """Validate the only review result shape accepted by the legacy loop."""

    model_config = ConfigDict(extra="forbid", frozen=True, str_strip_whitespace=True)

    passed: StrictBool = Field(alias="pass")
    issues: tuple[StrictStr, ...] = Field(max_length=5)

    @field_validator("issues")
    @classmethod
    def validate_issue_text(cls, value: tuple[StrictStr, ...]) -> tuple[StrictStr, ...]:
        """Reject empty or duplicate review issues."""
        if any(not issue for issue in value):
            raise ValueError("review issues must not be empty")
        if len(value) != len(set(value)):
            raise ValueError("review issues must be unique")
        return value

    @model_validator(mode="after")
    def validate_pass_shape(self) -> _L2ReviewPayload:
        """Require one unambiguous success or failure representation."""
        if self.passed and self.issues:
            raise ValueError("a passing review must not contain issues")
        if not self.passed and not self.issues:
            raise ValueError("a failing review must contain issues")
        return self


L2ReviewResult = TypedDict(
    "L2ReviewResult",
    {"pass": bool, "issues": list[str]},
)


def run_l2_review(
    user_input: str,
    plan_text: str,
    constraints: list[str],
    *,
    settings: Settings,
) -> L2ReviewResult:
    """Run one strict structured L2 review without retries or fallback.

    Args:
        user_input: User request data supplied to the planner.
        plan_text: Candidate itinerary text to review.
        constraints: Explicit exclusions extracted from the user request.
        settings: Validated runtime settings shared by the planner and gateway.

    Returns:
        L2ReviewResult: Explicit pass/fail decision and bounded issue list.

    Raises:
        L2ReviewError: The model response is not the required JSON contract.
        Exception: Upstream LLM failures propagate unchanged.
    """
    prompt = build_review_prompt(user_input, plan_text, constraints)
    response = ask_llm(
        prompt,
        settings=settings,
        output_mode=LLMOutputMode.JSON_OBJECT,
    )
    try:
        payload = _L2ReviewPayload.model_validate(parse_json_object(response))
    except (JsonResponseError, TypeError, ValueError) as exc:
        raise L2ReviewError("L2 review response does not match the JSON contract") from exc

    result: L2ReviewResult = {
        "pass": payload.passed,
        "issues": list(payload.issues),
    }
    if payload.passed:
        logger.info("l2_review_pass")
    else:
        logger.info("l2_review_fail", issue_count=len(payload.issues))
    return result
