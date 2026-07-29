from __future__ import annotations

import pytest
from pydantic import ValidationError

from src.legacy.mapper import LegacyPlanMapper, LegacyPlanResult, map_legacy_plan_result


def test_legacy_mapper_converts_valid_result_to_frozen_typed_dto() -> None:
    result = map_legacy_plan_result(
        {"plan": "深圳科技园一日行程", "rounds": 2, "issues_found": ["预算已复核"]}
    )

    assert isinstance(result, LegacyPlanResult)
    assert result.plan == "深圳科技园一日行程"
    assert result.rounds == 2
    assert result.issues_found == ("预算已复核",)
    assert result.model_validate_json(result.model_dump_json()) == result

    with pytest.raises(ValidationError):
        result.rounds = 3


def test_legacy_mapper_accepts_empty_issue_list_without_raw_dict_leaking() -> None:
    result = LegacyPlanMapper.map({"plan": "可交付方案", "rounds": 1, "issues_found": []})

    assert result.issues_found == ()
    assert isinstance(result.issues_found, tuple)


@pytest.mark.parametrize(
    "raw_result",
    [
        {"rounds": 1, "issues_found": []},
        {"plan": "方案", "issues_found": []},
        {"plan": "方案", "rounds": 1},
    ],
)
def test_legacy_mapper_rejects_missing_required_fields(
    raw_result: dict[str, object],
) -> None:
    with pytest.raises(ValidationError):
        LegacyPlanMapper.map(raw_result)


@pytest.mark.parametrize(
    "raw_result",
    [
        {"plan": "", "rounds": 1, "issues_found": []},
        {"plan": "方案", "rounds": 0, "issues_found": []},
        {"plan": "方案", "rounds": True, "issues_found": []},
        {"plan": "方案", "rounds": 1, "issues_found": ["正常", 2]},
        {"plan": "方案", "rounds": 1, "issues_found": [], "raw": {"secret": "value"}},
    ],
)
def test_legacy_mapper_rejects_invalid_or_unknown_legacy_result(
    raw_result: dict[str, object],
) -> None:
    with pytest.raises(ValidationError):
        map_legacy_plan_result(raw_result)


def test_legacy_mapper_rejects_non_mapping_input() -> None:
    with pytest.raises(TypeError, match="must be a mapping"):
        LegacyPlanMapper.map(["方案", 1, []])  # type: ignore[arg-type]
