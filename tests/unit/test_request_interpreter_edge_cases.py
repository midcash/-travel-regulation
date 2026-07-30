from __future__ import annotations

import pytest

from src.agents.request_interpreter import RequestInterpreter
from src.config import ConfigurationError, Settings
from src.domain.errors import WorkflowError
from src.domain.models.interpretation import SafetyFlag
from src.guard.g0 import G0SecurityContext, G0ValidationResult
from tests.support.llm_fakes import FakeLLMGateway


def _context() -> G0SecurityContext:
    return G0SecurityContext(
        principal_ref="principal:interpreter-edge",
        authenticated=True,
        authorized=True,
    )


def test_interpreter_rejects_invalid_summary_type_and_length() -> None:
    interpreter = RequestInterpreter(FakeLLMGateway(["{}"]), Settings())

    with pytest.raises(WorkflowError):
        interpreter.interpret(
            "规划杭州旅行",
            context=_context(),
            trace_id="trace:summary-type",
            conversation_summary=object(),  # type: ignore[arg-type]
        )
    with pytest.raises(WorkflowError):
        interpreter.interpret(
            "规划杭州旅行",
            context=_context(),
            trace_id="trace:summary-length",
            conversation_summary="x" * 4097,
        )


def test_interpreter_rejects_invalid_modes_and_unexpected_redaction() -> None:
    interpreter = RequestInterpreter(FakeLLMGateway(["{}"]), Settings())

    with pytest.raises(WorkflowError):
        interpreter.interpret(
            "规划杭州旅行",
            context=_context(),
            trace_id="trace:mode-type",
            allowed_modes=("plan",),  # type: ignore[arg-type]
        )
    with pytest.raises(WorkflowError):
        interpreter.interpret(
            "规划杭州旅行",
            context=_context(),
            trace_id="trace:redaction-unexpected",
            redacted_input="已脱敏",
        )


def test_interpreter_maps_configuration_error_and_non_text_response() -> None:
    configured_error = RequestInterpreter(
        FakeLLMGateway([ConfigurationError("bad config")]),
        Settings(),
    )
    with pytest.raises(WorkflowError) as configured:
        configured_error.interpret(
            "规划杭州旅行",
            context=_context(),
            trace_id="trace:configuration-error",
        )
    assert configured.value.payload.category.value == "configuration"

    class NonTextGateway:
        def complete(self, prompt: str, *, settings: Settings) -> str:
            return 42  # type: ignore[return-value]

    non_text = RequestInterpreter(NonTextGateway(), Settings())
    with pytest.raises(WorkflowError) as response:
        non_text.interpret(
            "规划杭州旅行",
            context=_context(),
            trace_id="trace:non-text-response",
        )
    assert response.value.payload.code == "INTERPRETATION_INVALID"


def test_interpreter_rejects_redacted_input_when_g0_result_is_not_safe() -> None:
    class PiiG0:
        def validate(
            self,
            raw_input: object,
            *,
            context: G0SecurityContext | None,
        ) -> G0ValidationResult:
            return G0ValidationResult(
                passed=True,
                input_length=4,
                pii_detected=True,
                safety_flags=(SafetyFlag.PII,),
            )

    interpreter = RequestInterpreter(
        FakeLLMGateway(["{}"]),
        Settings(),
        g0_validator=PiiG0(),  # type: ignore[arg-type]
    )
    with pytest.raises(WorkflowError):
        interpreter.interpret(
            "手机号",
            context=_context(),
            trace_id="trace:redacted-missing",
        )
