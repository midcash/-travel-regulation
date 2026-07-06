"""Test suite for models/ — all data model dataclasses.

Covers model construction, validation, to_dict(), and edge cases.
"""

from __future__ import annotations

import pytest
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
from models.request import (
    Budget,
    DateRange,
    Destination,
    Preferences,
    StructuredRequest,
    Travelers,
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


# ============================================================
# request models
# ============================================================

class TestDestination:
    def test_basic(self):
        d = Destination(city="Tokyo", country="Japan")
        assert d.city == "Tokyo"
        assert d.country == "Japan"
        assert d.region is None

    def test_empty_city_raises(self):
        with pytest.raises(ValueError):
            Destination(city="", country="Japan")


class TestDateRange:
    def test_defaults(self):
        d = DateRange()
        assert d.arrival is None
        assert d.duration_days == 0
        assert d.is_flexible is False

    def test_valid_dates(self):
        d = DateRange(arrival="2026-08-01", departure="2026-08-05", duration_days=5)
        assert d.arrival == "2026-08-01"

    def test_invalid_date_format(self):
        with pytest.raises(ValueError):
            DateRange(arrival="not-a-date")

    def test_negative_duration(self):
        with pytest.raises(ValueError):
            DateRange(duration_days=-1)


class TestBudget:
    def test_basic(self):
        b = Budget(total=10000, currency="CNY")
        assert b.total == 10000
        assert b.currency == "CNY"

    def test_negative_total_raises(self):
        with pytest.raises(ValueError):
            Budget(total=-100)


class TestTravelers:
    def test_defaults(self):
        t = Travelers()
        assert t.adults == 1
        assert t.children == 0

    def test_zero_adults_raises(self):
        with pytest.raises(ValueError):
            Travelers(adults=0)

    def test_total_count(self):
        t = Travelers(adults=2, children=1, infants=1)
        assert t.total_count == 4


class TestPreferences:
    def test_defaults(self):
        p = Preferences()
        assert p.style == []
        assert p.pace == "moderate"

    def test_invalid_pace(self):
        with pytest.raises(ValueError):
            Preferences(pace="extreme")


class TestStructuredRequest:
    def test_full_construction(self):
        req = StructuredRequest(
            destination=Destination(city="Tokyo", country="Japan"),
            dates=DateRange(arrival="2026-08-01", departure="2026-08-05", duration_days=5),
            budget=Budget(total=10000),
            travelers=Travelers(adults=2),
            preferences=Preferences(style=["food", "culture"]),
            raw_text="去东京5天",
        )
        d = req.to_dict()
        assert d["destination"]["city"] == "Tokyo"
        assert d["dates"]["duration_days"] == 5
        assert d["budget"]["total"] == 10000


# ============================================================
# plan models
# ============================================================

class TestTransportation:
    def test_defaults(self):
        t = Transportation()
        assert t.outbound == {}
        assert t.total_cost == 0


class TestAccommodationOption:
    def test_basic(self):
        a = AccommodationOption(
            name="Hotel A", location="Shinjuku", type="hotel",
            cost_per_night=500, total_cost=2500, distance_to_center_km=3.0,
            highlights=["near station"],
        )
        assert a.name == "Hotel A"
        assert a.rating is None


class TestActivity:
    def test_valid_reason(self):
        a = Activity(
            name="Sensoji Temple", type="culture", start_time="09:00",
            duration_minutes=120, location="Asakusa", estimated_cost=0,
            reason="东京最古老的寺庙，感受江户时代的历史氛围",
        )
        assert a.reason.startswith("东京最古老")

    def test_short_reason_raises(self):
        with pytest.raises(ValueError, match="至少需要 10 个字符"):
            Activity(
                name="Test", type="nature", start_time="09:00",
                duration_minutes=60, location="A", estimated_cost=0,
                reason="short",
            )


class TestMeal:
    def test_basic(self):
        m = Meal(type="lunch", restaurant_name="Sushi Dai", location="Tsukiji",
                 cuisine="Japanese", estimated_cost=200)
        assert m.cuisine == "Japanese"
        assert m.dietary_compatible is True


class TestItineraryDay:
    def test_empty_day(self):
        d = ItineraryDay(day=1)
        assert d.day == 1
        assert d.activities == []
        assert d.total_day_cost == 0

    def test_with_activities(self):
        d = ItineraryDay(
            day=1,
            activities=[
                Activity(name="A", type="culture", start_time="09:00",
                         duration_minutes=120, location="X", estimated_cost=50,
                         reason="值得一看的历史文化景点推荐"),
            ],
        )
        assert len(d.activities) == 1


class TestBudgetAllocation:
    def test_defaults(self):
        b = BudgetAllocation()
        assert b.transportation == 0
        assert b.currency == "CNY"


class TestTravelPlanDraft:
    def test_minimal(self):
        d = TravelPlanDraft(destination="Tokyo", duration_days=5, total_budget=10000)
        assert d.revision_version == 0
        assert d.constraints_met == []
        assert d.constraints_unmet == []

    def test_to_dict(self):
        d = TravelPlanDraft(
            destination="Tokyo", duration_days=5, total_budget=10000,
        )
        result = d.to_dict()
        assert result["destination"] == "Tokyo"


class TestFinalTravelPlan:
    def test_full_plan(self):
        p = FinalTravelPlan(
            plan_id="p1",
            summary={"total_budget": 10000},
            transportation={"outbound": {}},
            accommodation=[],
            daily_itinerary=[],
            budget_breakdown={},
            quality_report={},
            metadata={},
        )
        assert p.plan_id == "p1"


# ============================================================
# validation models
# ============================================================

class TestPriceAnomaly:
    def test_basic(self):
        a = PriceAnomaly(
            item="flight", estimated=3000, market_median=1500,
            market_range=[800, 3000], deviation_pct=100.0, severity="high",
        )
        assert a.severity == "high"


class TestPriceCheckResult:
    def test_all_clean(self):
        r = PriceCheckResult(
            items_checked=5, anomalies=[], overall_accuracy_score=95,
            overall_status="passed",
        )
        assert r.overall_status == "passed"


class TestTimeCheckResult:
    def test_with_conflicts(self):
        r = TimeCheckResult(
            days_checked=5, conflicts=[],
            overall_time_status="passed", overall_time_score=100,
        )
        assert r.days_checked == 5


class TestGeographyCheckResult:
    def test_defaults(self):
        r = GeographyCheckResult(
            detours_found=0, detours=[],
            overall_geo_status="passed", overall_geo_score=100,
        )
        assert r.warnings == []


class TestConstraintCheckResult:
    def test_all_passed(self):
        r = ConstraintCheckResult(
            hard_constraints_total=4, hard_constraints_passed=4,
            soft_constraints_total=2, soft_constraints_passed=2,
            blocking_issues=[], warnings=[],
        )
        assert len(r.blocking_issues) == 0


class TestRiskAlert:
    def test_basic(self):
        alert = RiskAlert(
            category="weather", description="台风季",
            severity="high", mitigation="购买保险",
        )
        assert alert.category == "weather"


class TestValidationReport:
    def test_feasible(self):
        r = ValidationReport(
            price_check=PriceCheckResult(
                items_checked=4, anomalies=[], overall_accuracy_score=90,
                overall_status="passed",
            ),
            time_check=TimeCheckResult(
                days_checked=5, conflicts=[],
                overall_time_status="passed", overall_time_score=100,
            ),
            geography_check=GeographyCheckResult(
                detours_found=0, detours=[],
                overall_geo_status="passed", overall_geo_score=100,
            ),
            constraint_check=ConstraintCheckResult(
                hard_constraints_total=4, hard_constraints_passed=4,
                soft_constraints_total=2, soft_constraints_passed=2,
                blocking_issues=[], warnings=[],
            ),
            risk_alerts=[],
            summary=ValidationSummary(
                blocking_count=0, warning_count=0, risk_count=0,
                action_required="none",
            ),
        )
        assert r.overall_status == "feasible"

    def test_infeasible_with_blocking(self):
        r = ValidationReport(
            price_check=PriceCheckResult(items_checked=0, anomalies=[], overall_accuracy_score=0, overall_status="passed"),
            time_check=TimeCheckResult(days_checked=0, conflicts=[], overall_time_status="passed", overall_time_score=0),
            geography_check=GeographyCheckResult(detours_found=0, detours=[], overall_geo_status="passed", overall_geo_score=0),
            constraint_check=ConstraintCheckResult(
                hard_constraints_total=4, hard_constraints_passed=3,
                soft_constraints_total=2, soft_constraints_passed=2,
                blocking_issues=[BlockingConstraint(constraint="budget", expected="10000", actual="12000")],
                warnings=[],
            ),
            risk_alerts=[],
            summary=ValidationSummary(blocking_count=1, warning_count=0, risk_count=0, action_required="revise"),
        )
        assert r.overall_status == "infeasible"


# ============================================================
# quality models
# ============================================================

class TestDimensionScore:
    def test_basic(self):
        s = DimensionScore(dimension="correctness", score=4.5, weight=0.30, issues=[])
        assert s.dimension == "correctness"


class TestCodeQualityReport:
    def test_pass(self):
        r = CodeQualityReport(
            target_agent="planning_agent", code_files=["test.py"],
            dimensions={
                "correctness": DimensionScore(dimension="correctness", score=4.5, weight=0.30, issues=[]),
                "robustness": DimensionScore(dimension="robustness", score=4.0, weight=0.25, issues=[]),
                "readability": DimensionScore(dimension="readability", score=4.5, weight=0.20, issues=[]),
                "performance": DimensionScore(dimension="performance", score=4.0, weight=0.15, issues=[]),
                "security": DimensionScore(dimension="security", score=4.0, weight=0.10, issues=[]),
            },
            total_score=4.25,
        )
        assert r.verdict == "PASS"

    def test_needs_revision(self):
        r = CodeQualityReport(
            target_agent="test", code_files=["x.py"],
            dimensions={},
            total_score=2.5,
        )
        assert r.verdict == "NEEDS_REVISION"


class TestPlanQualityReport:
    def test_pass(self):
        r = PlanQualityReport(
            dimensions={
                "completeness": PlanDimensionScore(dimension="completeness", score=4.5, weight=0.25, issues=[], suggestions=[]),
                "feasibility": PlanDimensionScore(dimension="feasibility", score=4.0, weight=0.25, issues=[], suggestions=[]),
                "constraint_satisfaction": PlanDimensionScore(dimension="constraint_satisfaction", score=4.0, weight=0.25, issues=[], suggestions=[]),
                "experience_quality": PlanDimensionScore(dimension="experience_quality", score=4.5, weight=0.15, issues=[], suggestions=[]),
                "information_accuracy": PlanDimensionScore(dimension="information_accuracy", score=4.0, weight=0.10, issues=[], suggestions=[]),
            },
            composite_score=85,
        )
        assert r.verdict == "PASS"

    def test_revise(self):
        r = PlanQualityReport(
            dimensions={},
            composite_score=72,
        )
        assert r.verdict == "REVISE"

    def test_reject(self):
        r = PlanQualityReport(
            dimensions={},
            composite_score=55,
        )
        assert r.verdict == "REJECT"


class TestContributionReport:
    def test_to_dict(self):
        r = ContributionReport(
            ablation=AblationResults(
                baseline_score=85.0,
                results=[AblationResult(config_name="full", agents_present=["a","b"], score=85.0, llm_calls=10, duration_seconds=30, test_cases_run=5)],
                marginal_contributions={"a": 10.0},
                contribution_rates={"a": 50.0},
                sample_size=5,
            ),
            importance_scores=[ImportanceScore(agent_name="a", score=4.0, rank=1, label="standard", ratings_received={"b": 4})],
            assessments_360=[Assessment360(agent_name="a", self_score=4.0, peer_score=4.0, supervisory_score=4.0, bias=0.0, alignment="aligned")],
            synergy=SynergyReport(synergy_gain=5.0, efficiency_pct=75.0, level="moderate", standalone_scores={"a": 40.0}, full_score=85.0),
        )
        d = r.to_dict()
        assert d["synergy"]["level"] == "moderate"


# ============================================================
# entities models
# ============================================================

class TestAttraction:
    def test_valid_reason(self):
        a = Attraction(
            name="Sensoji", location="Asakusa, Tokyo",
            type="culture", suggested_duration_minutes=120,
            estimated_price=0,
            reason="东京最古老的佛教寺庙，著名的雷门和仲见世通商店街",
        )
        assert len(a.reason) >= 10

    def test_short_reason_raises(self):
        with pytest.raises(ValueError, match="至少需要 10"):
            Attraction(name="X", location="Y", type="nature",
                       suggested_duration_minutes=60, estimated_price=0,
                       reason="short")


class TestRestaurant:
    def test_basic(self):
        r = Restaurant(
            name="Sushi Dai", location="Tsukiji", cuisine="Japanese",
            price_per_person=200,
            dietary_options=["vegetarian"], meal_types=["lunch", "dinner"],
        )
        assert "vegetarian" in r.dietary_options


class TestAccommodationEntity:
    def test_basic(self):
        a = Accommodation(
            name="Hilton Tokyo", location="Shinjuku", type="hotel",
            price_per_night=800, distance_to_center_km=2.0,
            highlights=["pool", "spa"],
        )
        assert a.type == "hotel"


class TestPriceRange:
    def test_basic(self):
        p = PriceRange(
            item_type="hotel_per_night", location="Tokyo",
            low=200, median=500, high=1500,
            source_type="estimated",
        )
        assert p.currency == "CNY"

    def test_cache_requires_data_date(self):
        with pytest.raises(ValueError):
            PriceRange(
                item_type="flight", location="Tokyo",
                low=1000, median=3000, high=6000,
                source_type="cache",
            )


class TestRevisionFeedback:
    def test_basic(self):
        f = RevisionFeedback(
            dimension="completeness", issue="missing day 3 meals",
            suggestion="add dinner recommendation", priority="high",
        )
        assert f.priority == "high"


class TestRevisionDecision:
    def test_approve(self):
        d = RevisionDecision(decision="APPROVE", reason="quality passed", iteration=1)
        assert d.decision == "APPROVE"


class TestDietaryPreferences:
    def test_defaults(self):
        d = DietaryPreferences()
        assert d.restrictions == []
        assert d.spice_tolerance == "medium"


class TestDestinationInfo:
    def test_basic(self):
        i = DestinationInfo(
            destination="Tokyo", country="Japan", currency="JPY",
            language="Japanese", timezone="Asia/Tokyo",
            best_season=["March", "April"],
            visa_required_for_cn=True,
            popular_areas=["Shinjuku", "Shibuya"],
            safety_level="safe",
        )
        assert i.currency == "JPY"


class TestGeoLocation:
    def test_basic(self):
        g = GeoLocation(lat=35.6762, lng=139.6503)
        assert g.lat == 35.6762
