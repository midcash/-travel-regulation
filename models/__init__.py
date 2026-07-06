"""
Models package for TravelPlan Orchestrator.

Defines the core data types, validation results, quality reports,
and entities used throughout the multi-agent travel planning system.
"""

from __future__ import annotations

from models.request import (
    Budget,
    DateRange,
    Destination,
    Preferences,
    StructuredRequest,
    Travelers,
)
from models.plan import (
    AccommodationOption,
    Activity,
    BudgetAllocation,
    FinalTravelPlan,
    ItineraryDay,
    Meal,
    Transportation,
    TravelPlanDraft,
)
from models.validation import (
    BlockingConstraint,
    ConstraintCheckResult,
    ConstraintWarning,
    GeographyCheckResult,
    GeographyDetour,
    PriceAnomaly,
    PriceCheckResult,
    RiskAlert,
    TimeCheckResult,
    TimeConflict,
    ValidationReport,
    ValidationSummary,
)
from models.quality import (
    AblationResult,
    AblationResults,
    Assessment360,
    CodeQualityReport,
    ContributionReport,
    DimensionScore,
    ImportanceScore,
    PlanDimensionScore,
    PlanQualityReport,
    SynergyReport,
)
from models.entities import (
    Accommodation,
    Attraction,
    DestinationInfo,
    DietaryPreferences,
    GeoLocation,
    PriceRange,
    Restaurant,
    RevisionDecision,
    RevisionFeedback,
)

__version__ = "1.0.0-dev"

__all__ = [
    # request
    "Destination",
    "DateRange",
    "Budget",
    "Travelers",
    "Preferences",
    "StructuredRequest",
    # plan
    "Transportation",
    "AccommodationOption",
    "Activity",
    "Meal",
    "ItineraryDay",
    "BudgetAllocation",
    "TravelPlanDraft",
    "FinalTravelPlan",
    # validation
    "PriceAnomaly",
    "PriceCheckResult",
    "TimeConflict",
    "TimeCheckResult",
    "GeographyDetour",
    "GeographyCheckResult",
    "BlockingConstraint",
    "ConstraintWarning",
    "ConstraintCheckResult",
    "RiskAlert",
    "ValidationSummary",
    "ValidationReport",
    # quality
    "DimensionScore",
    "CodeQualityReport",
    "PlanDimensionScore",
    "PlanQualityReport",
    "AblationResult",
    "AblationResults",
    "ImportanceScore",
    "Assessment360",
    "SynergyReport",
    "ContributionReport",
    # entities
    "GeoLocation",
    "Attraction",
    "Restaurant",
    "Accommodation",
    "DestinationInfo",
    "PriceRange",
    "DietaryPreferences",
    "RevisionFeedback",
    "RevisionDecision",
]
