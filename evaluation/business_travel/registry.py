from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from pydantic import ValidationError

from evaluation.business_travel.contracts import AgentEvalCase, EvalView


class DatasetContractError(ValueError):
    """冻结评测数据不满足机器合同。"""


class BusinessTravelCaseRegistry:
    """提供分区、视图和标签筛选的只读案例注册表。"""

    def __init__(self, cases: tuple[AgentEvalCase, ...]) -> None:
        self._cases = cases

    @classmethod
    def from_cases(cls, cases: tuple[AgentEvalCase, ...]) -> BusinessTravelCaseRegistry:
        if not cases:
            raise DatasetContractError("dataset must contain at least one case")
        seen_ids: set[str] = set()
        seen_inputs: dict[str, str] = {}
        for case in cases:
            if case.case_id in seen_ids:
                raise DatasetContractError(f"duplicate case_id: {case.case_id}")
            seen_ids.add(case.case_id)
            prior_case_id = seen_inputs.get(case.input_text)
            if prior_case_id is not None:
                raise DatasetContractError(
                    f"duplicate input_text: {case.input_text!r} ({prior_case_id}, {case.case_id})"
                )
            seen_inputs[case.input_text] = case.case_id
            if (
                "blocking_live_stability" in case.tags
                and EvalView.LIVE_BLOCKING not in case.applicable_views
            ):
                raise DatasetContractError(
                    f"blocking_live_stability requires live_blocking view: {case.case_id}"
                )
        return cls(tuple(cases))

    @classmethod
    def load(cls, path: Path) -> BusinessTravelCaseRegistry:
        cases: list[AgentEvalCase] = []
        for line_number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            if not line.strip():
                continue
            raw: Any = json.loads(line)
            case_id = raw.get("case_id", "<missing>") if isinstance(raw, dict) else "<invalid>"
            try:
                cases.append(AgentEvalCase.model_validate(raw))
            except (ValidationError, TypeError, ValueError) as exc:
                raise DatasetContractError(f"{path}:{line_number}:{case_id}: {exc}") from exc
        try:
            return cls.from_cases(tuple(cases))
        except DatasetContractError as exc:
            raise DatasetContractError(f"{path}: {exc}") from exc

    def cases_for(self, view: EvalView) -> tuple[AgentEvalCase, ...]:
        return tuple(case for case in self._cases if view in case.applicable_views)

    def select(
        self,
        *,
        case_ids: frozenset[str] = frozenset(),
        tags: frozenset[str] = frozenset(),
    ) -> tuple[AgentEvalCase, ...]:
        return tuple(
            case
            for case in self._cases
            if (not case_ids or case.case_id in case_ids)
            and (not tags or tags.issubset(set(case.tags)))
        )

    @property
    def cases(self) -> tuple[AgentEvalCase, ...]:
        return self._cases
