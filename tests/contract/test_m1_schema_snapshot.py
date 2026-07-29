"""M1 JSON Schema 快照契约测试。"""

from __future__ import annotations

import json
from pathlib import Path

from scripts.generate_m1_schema_snapshot import build_m1_schema_snapshot

SNAPSHOT_PATH = Path(__file__).parents[2] / "data" / "schemas" / "m1-domain-contracts.json"


def test_m1_schema_snapshot_matches_current_pydantic_contracts() -> None:
    """模型变更必须显式更新快照，避免文档 Schema 静默过期。"""
    snapshot = json.loads(SNAPSHOT_PATH.read_text(encoding="utf-8"))

    assert snapshot == build_m1_schema_snapshot()


def test_m1_schema_snapshot_contains_all_public_contracts() -> None:
    """快照必须覆盖 M1 领域、错误、状态和 Facade 契约。"""
    snapshot = json.loads(SNAPSHOT_PATH.read_text(encoding="utf-8"))
    expected = {
        "Money",
        "DateRange",
        "GeoPoint",
        "BudgetSpec",
        "TravelerProfile",
        "TripRequest",
        "Constraint",
        "ConstraintSnapshot",
        "EvidenceItem",
        "EvidenceSnapshot",
        "Candidate",
        "TransportCandidate",
        "StayCandidate",
        "PlaceCandidate",
        "ContextCandidate",
        "PlanItem",
        "ItineraryDay",
        "PlanAlternative",
        "BudgetLine",
        "BudgetBreakdown",
        "PlanBuffer",
        "ItineraryPlan",
        "ValidationIssue",
        "WorkflowErrorPayload",
        "TripState",
        "Checkpoint",
        "LegacyPlanResult",
        "PlanTripResult",
    }

    assert snapshot["$schema"] == "https://json-schema.org/draft/2020-12/schema"
    assert snapshot["schema_version"] == "1.0"
    assert set(snapshot["schemas"]) == expected
