"""Execution and validation data models for the Travel Planning Multi-Agent system.

Defines the structured result types produced by the Execution Agent when
validating the feasibility of a travel plan draft. Includes price checks,
time feasibility, geographic route validation, hard/soft constraint checks,
risk identification, and the top-level ValidationReport.

Spec reference: spec/executor_spec.md (sections 2.1-2.6, 4)
Playbook reference: playbooks/executor_playbook.md (section 5)
"""

from __future__ import annotations

from dataclasses import dataclass, field, fields
from typing import Any, Dict, List, Optional


# ============================================================
# Serialization helper
# ============================================================


def _to_dict(value: Any) -> Any:
    """Recursively convert a value to a plain dict for serialization."""
    if hasattr(value, "to_dict"):
        return value.to_dict()
    if isinstance(value, list):
        return [_to_dict(item) for item in value]
    if isinstance(value, dict):
        return {k: _to_dict(v) for k, v in value.items()}
    return value


class SerializableMixin:
    """Mixin that provides a ``to_dict()`` method for dataclass instances.

    Recursively converts nested dataclass objects, lists, and dicts.
    """

    def to_dict(self) -> Dict[str, Any]:
        """Convert this dataclass instance to a plain ``Dict[str, Any]``.

        Returns:
            A dictionary representation suitable for JSON serialisation.
        """
        result: Dict[str, Any] = {}
        for f in fields(self):
            result[f.name] = _to_dict(getattr(self, f.name))
        return result


# ============================================================
# Price Check (spec §2.2)
# ============================================================


@dataclass
class PriceAnomaly(SerializableMixin):
    """A single price anomaly detected during market-price comparison.

    Attributes:
        item: Name of the priced item (e.g. "Flight PEK-SHA").
        estimated: The estimated price in the travel-plan draft.
        market_median: Median market price for the same item.
        market_range: Typical market price range as ``[low, high]``.
        deviation_pct: Absolute deviation percentage:
            ``|estimated - market_median| / market_median * 100``.
        severity: One of ``"high"`` (deviation > 30 %),
            ``"medium"`` (10-30 %), or ``"low"`` (<= 10 %).
        suggestion: Optional human-readable suggestion for resolving the
            anomaly.
    """

    item: str
    estimated: float
    market_median: float
    market_range: List[float]
    deviation_pct: float
    severity: str
    suggestion: Optional[str] = None


@dataclass
class PriceCheckResult(SerializableMixin):
    """Aggregated result of the price-validation step.

    Attributes:
        items_checked: Total number of items whose price was verified.
        anomalies: List of anomalies found (may be empty).
        overall_accuracy_score: Composite accuracy score (0-100) based on
            severity and count of anomalies.
        overall_status: One of ``"passed"``, ``"passed_with_warnings"``,
            or ``"failed"``.  Failure is triggered when 3+ high-severity
            anomalies are present.
        notes: Optional free-text notes (e.g. data-source caveats).
    """

    items_checked: int
    anomalies: List[PriceAnomaly]
    overall_accuracy_score: float
    overall_status: str
    notes: Optional[str] = None


# ============================================================
# Time Check (spec §2.3)
# ============================================================


@dataclass
class TimeConflict(SerializableMixin):
    """A single time-related conflict or concern within a day's itinerary.

    Attributes:
        day: The day number on which the conflict occurs (1-based).
        issue: Human-readable description of the conflict.
        severity: One of ``"high"`` (total time > 12 h or opening-hours
            clash) or ``"medium"`` / ``"low"``.
        suggestion: Optional suggestion for resolving the conflict.
        affected_activities: List of activity names affected by this
            conflict.
    """

    day: int
    issue: str
    severity: str
    suggestion: Optional[str] = None
    affected_activities: List[str] = field(default_factory=list)


@dataclass
class TimeCheckResult(SerializableMixin):
    """Aggregated result of the time-feasibility validation step.

    Attributes:
        days_checked: Number of days that were inspected.
        conflicts: List of time conflicts identified (may be empty).
        overall_time_status: One of ``"passed"``,
            ``"passed_with_warnings"``, or ``"failed"``.
        overall_time_score: Composite time-feasibility score (0-100).
        warnings: Additional non-blocking time-related warnings as a list
            of plain dicts.
    """

    days_checked: int
    conflicts: List[TimeConflict]
    overall_time_status: str
    overall_time_score: float
    warnings: List[Dict[str, Any]] = field(default_factory=list)


# ============================================================
# Geography Check (spec §2.4)
# ============================================================


@dataclass
class GeographyDetour(SerializableMixin):
    """A single geographic inefficiency (detour) found in the itinerary.

    Attributes:
        day: The day number on which the detour occurs (1-based).
        description: Human-readable description of the detour.
        detour_ratio: Ratio of actual route length to optimal route length.
            Values > 1.5 indicate a significant detour.
        wasted_time_minutes: Estimated wasted time in minutes caused by
            the sub-optimal routing.
        optimized_route: Optional suggested replacement route description.
    """

    day: int
    description: str
    detour_ratio: float
    wasted_time_minutes: int
    optimized_route: Optional[str] = None


@dataclass
class GeographyCheckResult(SerializableMixin):
    """Aggregated result of the geographic-route validation step.

    Attributes:
        detours_found: Total number of detours identified.
        detours: List of detour details (may be empty).
        overall_geo_status: One of ``"passed"``,
            ``"passed_with_warnings"``, or ``"failed"``.
        overall_geo_score: Composite geographic-logic score (0-100).
        warnings: Additional non-blocking geography-related warnings as a
            list of plain dicts.
    """

    detours_found: int
    detours: List[GeographyDetour]
    overall_geo_status: str
    overall_geo_score: float
    warnings: List[Dict[str, Any]] = field(default_factory=list)


# ============================================================
# Constraint Check (spec §2.5)
# ============================================================


@dataclass
class BlockingConstraint(SerializableMixin):
    """A hard-constraint violation that makes the plan infeasible.

    Attributes:
        constraint: Name of the violated constraint
            (e.g. ``"budget_ceiling"``).
        expected: The expected / allowed value.
        actual: The actual value found in the draft.
        fix_suggestion: Optional suggestion for how to resolve the
            violation.  Per spec §4.1, this MUST be present for every
            blocking issue.
    """

    constraint: str
    expected: str
    actual: str
    fix_suggestion: Optional[str] = None


@dataclass
class ConstraintWarning(SerializableMixin):
    """A soft-constraint concern that does not block feasibility.

    Attributes:
        constraint: Name of the soft constraint
            (e.g. ``"dietary_preference"``).
        issue: Human-readable description of the concern.
        suggestion: Optional suggestion for addressing the issue.
    """

    constraint: str
    issue: str
    suggestion: Optional[str] = None


@dataclass
class ConstraintCheckResult(SerializableMixin):
    """Aggregated result of the hard/soft constraint validation step.

    Attributes:
        hard_constraints_total: Total number of hard constraints evaluated.
        hard_constraints_passed: Number of hard constraints that passed.
        soft_constraints_total: Total number of soft constraints evaluated.
        soft_constraints_passed: Number of soft constraints that passed.
        blocking_issues: List of hard-constraint violations (may be empty).
            If non-empty the plan is considered infeasible.
        warnings: List of soft-constraint concerns (may be empty).
    """

    hard_constraints_total: int
    hard_constraints_passed: int
    soft_constraints_total: int
    soft_constraints_passed: int
    blocking_issues: List[BlockingConstraint]
    warnings: List[ConstraintWarning]


# ============================================================
# Risk Alert (spec §2.6)
# ============================================================


@dataclass
class RiskAlert(SerializableMixin):
    """A single risk identified for the travel plan.

    Attributes:
        category: Risk dimension -- one of ``"weather"``, ``"safety"``,
            ``"health"``, or ``"documents"``.
        description: Human-readable description of the risk.
        severity: One of ``"high"``, ``"medium"``, or ``"low"``.
        mitigation: Optional suggestion for mitigating the risk.
    """

    category: str
    description: str
    severity: str
    mitigation: Optional[str] = None


# ============================================================
# Validation Summary
# ============================================================


@dataclass
class ValidationSummary(SerializableMixin):
    """High-level summary counters and recommended action.

    Attributes:
        blocking_count: Total number of blocking issues across all checks.
        warning_count: Total number of non-blocking warnings.
        risk_count: Total number of risk alerts identified.
        action_required: Recommended action -- one of ``"none"``,
            ``"revise"``, or ``"manual_review"``.
    """

    blocking_count: int
    warning_count: int
    risk_count: int
    action_required: str


# ============================================================
# ValidationReport (spec §2.1, §4.1; Gate 1)
# ============================================================


@dataclass
class ValidationReport(SerializableMixin):
    """Top-level report produced by the Execution Agent's feasibility
    validation.

    Aggregates results from all five validation steps (price, time,
    geography, constraints, risks) and derives an ``overall_status``
    according to the rules in ``spec/executor_spec.md §4.1``:

    - ``constraint_check.blocking_issues`` non-empty → ``"infeasible"``.
    - ``summary.warning_count > 0`` → ``"feasible_with_warnings"``.
    - Otherwise → ``"feasible"``.

    Gate 1 (``gate_definitions.md §3``) reads this report to decide
    whether to block the pipeline or allow it to proceed.

    Attributes:
        price_check: Results from the price-validation step.
        time_check: Results from the time-feasibility step.
        geography_check: Results from the geographic-route step.
        constraint_check: Results from the hard/soft constraint step.
        risk_alerts: List of identified risks.
        summary: High-level summary counters and action recommendation.
        validation_id: Optional UUID for this validation report.
        draft_id: Optional UUID of the travel-plan draft that was
            validated.
        overall_status: Auto-derived feasibility status
            (``"feasible"`` | ``"feasible_with_warnings"`` |
            ``"infeasible"``).  Computed in ``__post_init__``.
    """

    price_check: PriceCheckResult
    time_check: TimeCheckResult
    geography_check: GeographyCheckResult
    constraint_check: ConstraintCheckResult
    risk_alerts: List[RiskAlert]
    summary: ValidationSummary
    validation_id: Optional[str] = None
    draft_id: Optional[str] = None
    overall_status: str = field(init=False)

    def __post_init__(self) -> None:
        """Derive ``overall_status`` from constraint and warning data.

        Logic (per spec §4.1):
        1. If ``constraint_check`` contains any ``blocking_issues``, the
           plan is ``"infeasible"``.
        2. Otherwise, if the summary reports any warnings, the plan is
           ``"feasible_with_warnings"``.
        3. Otherwise the plan is ``"feasible"``.
        """
        if self.constraint_check.blocking_issues:
            self.overall_status = "infeasible"
        elif self.summary.warning_count > 0:
            self.overall_status = "feasible_with_warnings"
        else:
            self.overall_status = "feasible"
