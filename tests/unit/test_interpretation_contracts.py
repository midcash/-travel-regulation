from __future__ import annotations

from decimal import Decimal

import pytest
from pydantic import ValidationError

from src.domain.models.enums import ConstraintHardness, InteractionMode
from src.domain.models.interpretation import (
    ConstraintCandidate,
    ExtractedEntity,
    InterpretationResult,
)


def _valid_result() -> InterpretationResult:
    return InterpretationResult(
        mode_hint=InteractionMode.PLAN,
        extracted_entities=(
            ExtractedEntity(
                entity_type="destination",
                value="杭州",
                normalized_value="杭州",
                confidence=Decimal("0.95"),
            ),
        ),
        constraint_candidates=(
            ConstraintCandidate(
                category="date",
                value="2026-08-01/2026-08-03",
                hardness=ConstraintHardness.HARD,
                scope="trip",
                confidence=Decimal("0.9"),
            ),
        ),
        explicit_questions=(),
        references_to_current_plan=(),
        field_confidence={"destinations": Decimal("0.95")},
        overall_confidence=Decimal("0.9"),
        safety_flags=(),
    )


def test_interpretation_result_accepts_typed_complete_result() -> None:
    result = _valid_result()

    assert result.mode_hint is InteractionMode.PLAN
    assert result.extracted_entities[0].entity_type == "destination"
    assert result.constraint_candidates[0].hardness is ConstraintHardness.HARD
    assert result.model_dump(mode="json")["overall_confidence"] == "0.9"


def test_interpretation_result_rejects_missing_top_level_field() -> None:
    payload = _valid_result().model_dump()
    del payload["explicit_questions"]

    with pytest.raises(ValidationError):
        InterpretationResult.model_validate(payload)


def test_interpretation_result_rejects_unknown_top_level_and_nested_fields() -> None:
    payload = _valid_result().model_dump()
    payload["unexpected"] = True

    with pytest.raises(ValidationError):
        InterpretationResult.model_validate(payload)

    nested_payload = _valid_result().model_dump()
    nested_payload["extracted_entities"][0]["unexpected"] = True

    with pytest.raises(ValidationError):
        InterpretationResult.model_validate(nested_payload)


@pytest.mark.parametrize(
    "field,value",
    [
        ("mode_hint", "not-a-mode"),
        ("overall_confidence", Decimal("1.01")),
        ("overall_confidence", Decimal("-0.01")),
        ("safety_flags", ("not-a-safety-flag",)),
    ],
)
def test_interpretation_result_rejects_invalid_enum_or_confidence(
    field: str,
    value: object,
) -> None:
    payload = _valid_result().model_dump()
    payload[field] = value

    with pytest.raises(ValidationError):
        InterpretationResult.model_validate(payload)


def test_interpretation_result_rejects_duplicate_references_and_empty_confidence_key() -> None:
    duplicate_payload = _valid_result().model_dump()
    duplicate_payload["references_to_current_plan"] = ("day-2", "day-2")

    with pytest.raises(ValidationError, match="must be unique"):
        InterpretationResult.model_validate(duplicate_payload)

    empty_key_payload = _valid_result().model_dump()
    empty_key_payload["field_confidence"] = {"": Decimal("0.5")}

    with pytest.raises(ValidationError, match="keys must not be empty"):
        InterpretationResult.model_validate(empty_key_payload)


def test_interpretation_result_is_immutable_and_round_trips_json() -> None:
    result = _valid_result()

    with pytest.raises(ValidationError):
        result.overall_confidence = Decimal("0.5")

    assert InterpretationResult.model_validate_json(result.model_dump_json()) == result
