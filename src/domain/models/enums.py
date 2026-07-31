"""M1 阶段的领域枚举。"""

from __future__ import annotations

from enum import Enum


class InteractionMode(str, Enum):
    """用户请求在交互控制平面中的工作模式。"""

    ANSWER = "answer"
    CLARIFY = "clarify"
    PLAN = "plan"
    REFINE = "refine"
    COMPARE = "compare"
    REPLAN = "replan"
    ACTION = "action"
    UNSUPPORTED = "unsupported"


class ConstraintHardness(str, Enum):
    """约束对可行性的影响等级。"""

    HARD = "hard"
    SOFT = "soft"
    ASSUMPTION = "assumption"
    UNKNOWN = "unknown"


class EvidenceStatus(str, Enum):
    """证据在当前快照中的可信状态。"""

    VERIFIED = "verified"
    CONFLICTING = "conflicting"
    STALE = "stale"
    UNAVAILABLE = "unavailable"


class EvidenceTtlCategory(str, Enum):
    """决定证据有效期上限的业务类别。"""

    STATIC_GEOGRAPHY = "static_geography"
    BUSINESS_HOURS_POLICY = "business_hours_policy"
    WEATHER_FORECAST = "weather_forecast"
    TRANSPORT_SCHEDULE = "transport_schedule"
    QUOTE_INVENTORY = "quote_inventory"
    EXCHANGE_RATE = "exchange_rate"


class CandidateRejectCode(str, Enum):
    """Candidate Pool 剪枝时使用的机器可读拒绝原因。"""

    EVIDENCE_MISSING = "evidence_missing"
    EVIDENCE_NOT_VERIFIED = "evidence_not_verified"
    HARD_CONSTRAINT_VIOLATION = "hard_constraint_violation"
    HARD_CONSTRAINT_DATA_MISSING = "hard_constraint_data_missing"


class WorkflowStatus(str, Enum):
    """旅行规划工作流允许使用的状态。"""

    COLLECTING = "collecting"
    CLARIFYING = "clarifying"
    RESEARCHING = "researching"
    DRAFTING = "drafting"
    VALIDATING = "validating"
    REPAIRING = "repairing"
    NEEDS_CONFIRMATION = "needs_confirmation"
    CONFIRMED = "confirmed"
    STALE = "stale"
    REPLANNING = "replanning"
    COMPLETED = "completed"
    FAILED = "failed"


class IssueSeverity(str, Enum):
    """验证问题的严重级别。"""

    INFO = "info"
    WARNING = "warning"
    BLOCKING = "blocking"


class ErrorCategory(str, Enum):
    """工作流失败的安全分类。"""

    VALIDATION = "validation"
    CONFIGURATION = "configuration"
    LLM = "llm"
    TOOL = "tool"
    EVIDENCE = "evidence"
    BUDGET = "budget"
    TIMEOUT = "timeout"
    STATE_CONFLICT = "state_conflict"
    SECURITY = "security"
    INTERNAL = "internal"
