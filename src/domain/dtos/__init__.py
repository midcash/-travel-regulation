"""
DTO 数据契约包 — 全部 8 个阶段的数据接口。

导出顺序: enums → retry_context → phase1 → phase5
"""
from src.domain.dtos.enums import (
    Verdict,
    TripPurpose,
    Severity,
    TrafficLight,
    IntentType,
    PaceMode,
    ErrorCode,
)
from src.domain.dtos.retry_context import (
    RetryContext,
    WeakDimension,
    BlockingViolation,
    RetryIssue,
)
from src.domain.dtos.phase1_dto import (
    Phase1RawOutput,
    Phase1Output,
    build_intent_summary,
)
from src.domain.dtos.phase5_dto import (
    Phase5Input,
    Phase5Output,
    HardChecksResult,
    Violation,
    FatigueAssessment,
    SemanticFilterResult,
    ScenarioAdaptation,
    QualityScore,
    QualityScores,
    Issue,
)

__all__ = [
    # enums
    "Verdict", "TripPurpose", "Severity", "TrafficLight",
    "IntentType", "PaceMode", "ErrorCode",
    # retry_context
    "RetryContext", "WeakDimension", "BlockingViolation", "RetryIssue",
    # phase1
    "Phase1RawOutput", "Phase1Output", "build_intent_summary",
    # phase5
    "Phase5Input", "Phase5Output",
    "HardChecksResult", "Violation",
    "FatigueAssessment", "SemanticFilterResult", "ScenarioAdaptation",
    "QualityScore", "QualityScores", "Issue",
]
