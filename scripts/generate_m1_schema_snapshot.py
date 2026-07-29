"""生成 M1 领域与兼容 Facade 的 JSON Schema 快照。"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import TypeAlias

from pydantic import BaseModel, TypeAdapter

PROJECT_ROOT = Path(__file__).resolve().parents[1]
SNAPSHOT_PATH = PROJECT_ROOT / "data" / "schemas" / "m1-domain-contracts.json"

sys.path.insert(0, str(PROJECT_ROOT))

from src.application.use_cases.plan_trip import PlanTripResult  # noqa: E402
from src.domain.errors import WorkflowErrorPayload  # noqa: E402
from src.domain.models.candidates import (  # noqa: E402
    Candidate,
    ContextCandidate,
    PlaceCandidate,
    StayCandidate,
    TransportCandidate,
)
from src.domain.models.checkpoint import Checkpoint  # noqa: E402
from src.domain.models.constraint import Constraint, ConstraintSnapshot  # noqa: E402
from src.domain.models.evidence import EvidenceItem, EvidenceSnapshot  # noqa: E402
from src.domain.models.itinerary import (  # noqa: E402
    BudgetBreakdown,
    BudgetLine,
    ItineraryDay,
    ItineraryPlan,
    PlanAlternative,
    PlanBuffer,
    PlanItem,
)
from src.domain.models.state import TripState  # noqa: E402
from src.domain.models.trip_request import (  # noqa: E402
    BudgetSpec,
    TravelerProfile,
    TripRequest,
)
from src.domain.models.validation import ValidationIssue  # noqa: E402
from src.domain.models.value_objects import DateRange, GeoPoint, Money  # noqa: E402
from src.legacy.mapper import LegacyPlanResult  # noqa: E402

SchemaSource: TypeAlias = type[BaseModel] | TypeAdapter[object]

MODEL_SCHEMAS: tuple[tuple[str, SchemaSource], ...] = (
    ("Money", Money),
    ("DateRange", DateRange),
    ("GeoPoint", GeoPoint),
    ("BudgetSpec", BudgetSpec),
    ("TravelerProfile", TravelerProfile),
    ("TripRequest", TripRequest),
    ("Constraint", Constraint),
    ("ConstraintSnapshot", ConstraintSnapshot),
    ("EvidenceItem", EvidenceItem),
    ("EvidenceSnapshot", EvidenceSnapshot),
    ("Candidate", TypeAdapter(Candidate)),
    ("TransportCandidate", TransportCandidate),
    ("StayCandidate", StayCandidate),
    ("PlaceCandidate", PlaceCandidate),
    ("ContextCandidate", ContextCandidate),
    ("PlanItem", PlanItem),
    ("ItineraryDay", ItineraryDay),
    ("PlanAlternative", PlanAlternative),
    ("BudgetLine", BudgetLine),
    ("BudgetBreakdown", BudgetBreakdown),
    ("PlanBuffer", PlanBuffer),
    ("ItineraryPlan", ItineraryPlan),
    ("ValidationIssue", ValidationIssue),
    ("WorkflowErrorPayload", WorkflowErrorPayload),
    ("TripState", TripState),
    ("Checkpoint", Checkpoint),
    ("LegacyPlanResult", LegacyPlanResult),
    ("PlanTripResult", PlanTripResult),
)


def build_m1_schema_snapshot() -> dict[str, object]:
    """构建 M1 契约的可审查 JSON Schema 快照。"""
    schemas: dict[str, object] = {}
    for name, source in MODEL_SCHEMAS:
        if isinstance(source, TypeAdapter):
            schemas[name] = source.json_schema()
        else:
            schemas[name] = source.model_json_schema()
    return {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "title": "Travel Planning M1 Contracts",
        "schema_version": "1.0",
        "schemas": schemas,
    }


def write_m1_schema_snapshot(path: Path = SNAPSHOT_PATH) -> None:
    """将当前 Pydantic 契约写入固定格式的 JSON 文件。"""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(build_m1_schema_snapshot(), ensure_ascii=False, indent=2, sort_keys=True)
        + "\n",
        encoding="utf-8",
    )


if __name__ == "__main__":
    write_m1_schema_snapshot()
    print(SNAPSHOT_PATH)
