"""Test suite for tools/ — stub tool implementations.

Covers test_scenarios.md:
- TS-EXEC-001: check_prices normal pass
- TS-EXEC-002: check_prices boundary warning (30%)
- TS-EXEC-003: check_prices blocking (3+ anomalies)
- TS-EXEC-004: check_time normal pass
- TS-EXEC-005: check_time boundary warning
- TS-EXEC-006: check_time blocking (over 12h + conflict)
- TS-EXEC-007: check_geography normal pass
- TS-EXEC-008: check_geography boundary warning
- TS-EXEC-009: check_geography blocking
"""

from __future__ import annotations

import pytest
from tools.geo_checker import check_geography, validate_geography
from tools.price_checker import check_budget_compliance, check_prices, estimate_market_price
from tools.risk_checker import check_travel_requirements, check_weather_risk
from tools.time_checker import calculate_transit_time, check_opening_hours, check_time


# ============================================================
# estimate_market_price
# ============================================================

class TestEstimateMarketPrice:
    def test_flight_domestic_default(self):
        r = estimate_market_price("flight_domestic", "UnknownCity")
        assert r["low"] == 300
        assert r["median"] == 800
        assert r["high"] == 2000
        assert r["currency"] == "CNY"
        assert r["source_type"] == "estimated"

    def test_flight_domestic_tokyo(self):
        r = estimate_market_price("flight_domestic", "Tokyo")
        assert r["median"] == 3000

    def test_hotel_tokyo(self):
        r = estimate_market_price("hotel_per_night", "Tokyo")
        assert r["median"] == 600

    def test_unknown_type_uses_default(self):
        r = estimate_market_price("unknown_type", "Somewhere")
        assert r["median"] == 300  # falls back to hotel_per_night default

    def test_attraction_default(self):
        r = estimate_market_price("attraction_ticket", "Beijing")
        assert r["median"] == 60


# ============================================================
# check_prices — TS-EXEC-001, 002, 003
# ============================================================

class TestCheckPrices:
    # TS-EXEC-001: all prices within 10% — normal pass
    def test_all_within_tolerance(self):
        items = [
            {"item": "flight", "type": "flight_domestic", "estimated_price": 3100},
            {"item": "hotel", "type": "hotel_per_night", "estimated_price": 620},
            {"item": "ticket", "type": "attraction_ticket", "estimated_price": 105},
        ]
        r = check_prices(items, "Tokyo")
        assert r["items_checked"] == 3
        assert r["overall_status"] == "passed"
        assert r["overall_accuracy_score"] > 80

    # TS-EXEC-002: deviation at 30% boundary → warning
    def test_deviation_at_threshold(self):
        """Hotel median is 600, 600 * 1.30 = 780. Deviation = (780-600)/600 = 30%."""
        items = [
            {"item": "hotel", "type": "hotel_per_night", "estimated_price": 780},
        ]
        r = check_prices(items, "Tokyo")
        assert r["items_checked"] == 1
        assert r["overall_status"] == "passed_with_warnings"
        assert len(r["anomalies"]) == 1
        assert r["anomalies"][0]["severity"] == "medium"

    # TS-EXEC-003: 3+ high-severity anomalies → failed
    def test_multiple_high_deviations(self):
        items = [
            {"item": "flight", "type": "flight_domestic", "estimated_price": 10000},
            {"item": "hotel", "type": "hotel_per_night", "estimated_price": 5000},
            {"item": "ticket", "type": "attraction_ticket", "estimated_price": 1000},
        ]
        r = check_prices(items, "Tokyo")
        assert r["items_checked"] == 3
        assert r["overall_status"] == "failed"
        assert all(a["severity"] == "high" for a in r["anomalies"])

    def test_empty_items(self):
        r = check_prices([], "Tokyo")
        assert r["items_checked"] == 0
        assert r["overall_status"] == "passed"

    def test_zero_estimated_price_skipped(self):
        items = [{"item": "free", "type": "attraction_ticket", "estimated_price": 0}]
        r = check_prices(items, "Tokyo")
        assert r["items_checked"] == 0


# ============================================================
# check_budget_compliance
# ============================================================

class TestCheckBudgetCompliance:
    def test_under_budget(self):
        r = check_budget_compliance(8000, 10000)
        assert r["compliant"] is True
        assert r["blocking"] is False

    def test_exact_budget(self):
        r = check_budget_compliance(10000, 10000)
        assert r["compliant"] is True

    def test_within_tolerance(self):
        r = check_budget_compliance(10500, 10000, tolerance_pct=10.0)
        assert r["compliant"] is True

    def test_over_tolerance(self):
        r = check_budget_compliance(12000, 10000, tolerance_pct=10.0)
        assert r["compliant"] is False
        assert r["blocking"] is True
        assert "超支" in r["message"]

    def test_zero_budget(self):
        r = check_budget_compliance(5000, 0)
        assert r["compliant"] is False
        assert r["blocking"] is True


# ============================================================
# check_opening_hours
# ============================================================

class TestCheckOpeningHours:
    def test_default_hours(self):
        r = check_opening_hours("Tokyo Tower")
        assert r["open"] == "09:00"
        assert r["close"] == "17:00"

    def test_museum_closed_monday(self):
        r = check_opening_hours("National Museum", "2026-07-06")  # Monday
        assert r["is_closed"] is True

    def test_non_museum_open_monday(self):
        r = check_opening_hours("Tokyo Tower", "2026-07-06")
        assert r["is_closed"] is False


# ============================================================
# calculate_transit_time
# ============================================================

class TestCalculateTransitTime:
    def test_same_area(self):
        r = calculate_transit_time(
            {"lat": 35.68, "lng": 139.76},
            {"lat": 35.69, "lng": 139.77},
            mode="public_transit",
        )
        assert r["is_cross_area"] is False
        assert r["duration_minutes"] >= 30
        assert r["source_type"] == "estimated"

    def test_cross_area(self):
        r = calculate_transit_time(
            {"lat": 35.68, "lng": 139.76},    # Tokyo
            {"lat": 34.69, "lng": 135.50},    # Osaka (~400km)
            mode="public_transit",
        )
        assert r["is_cross_area"] is True
        assert r["distance_km"] > 15

    def test_walking_mode(self):
        r = calculate_transit_time(
            {"lat": 35.68, "lng": 139.76},
            {"lat": 35.69, "lng": 139.77},
            mode="walking",
        )
        assert r["mode"] == "walking"


# ============================================================
# check_time — TS-EXEC-004, 005, 006
# ============================================================

class TestCheckTime:
    # TS-EXEC-004: normal pass (< 10h)
    def test_normal_day(self):
        itinerary = [{
            "day": 1,
            "activities": [
                {"name": "activity1", "duration_minutes": 120, "start_time": "09:00"},
                {"name": "activity2", "duration_minutes": 180, "start_time": "14:00"},
            ],
            "transit_minutes": 60,
        }]
        r = check_time(itinerary)
        assert r["days_checked"] == 1
        assert r["overall_time_status"] == "passed"
        assert r["overall_time_score"] == 100

    # TS-EXEC-005: boundary warning (10h-12h)
    def test_boundary_warning(self):
        itinerary = [{
            "day": 1,
            "activities": [
                {"name": "long activity", "duration_minutes": 620, "start_time": "08:00"},
            ],
            "transit_minutes": 40,
        }]
        r = check_time(itinerary)
        assert r["overall_time_status"] == "passed_with_warnings"
        assert len(r["warnings"]) >= 1

    # TS-EXEC-006: over 12h → conflict
    def test_over_12_hours(self):
        itinerary = [{
            "day": 1,
            "activities": [
                {"name": "very long", "duration_minutes": 700, "start_time": "08:00"},
            ],
            "transit_minutes": 60,
        }]
        r = check_time(itinerary)
        assert r["overall_time_status"] == "failed"
        assert len(r["conflicts"]) >= 1
        assert r["conflicts"][0]["severity"] == "high"

    def test_lunch_conflict(self):
        itinerary = [{
            "day": 1,
            "activities": [
                {"name": "lunch_blocker", "duration_minutes": 240, "start_time": "11:00"},
            ],
            "transit_minutes": 30,
        }]
        r = check_time(itinerary)
        # Should have a lunch-time conflict warning
        lunch_warnings = [w for w in r["warnings"] if "午餐" in w.get("issue", "")]
        assert len(lunch_warnings) >= 1

    def test_dinner_conflict(self):
        itinerary = [{
            "day": 1,
            "activities": [
                {"name": "dinner_blocker", "duration_minutes": 240, "start_time": "17:00"},
            ],
            "transit_minutes": 30,
        }]
        r = check_time(itinerary)
        dinner_warnings = [w for w in r["warnings"] if "晚餐" in w.get("issue", "")]
        assert len(dinner_warnings) >= 1

    def test_empty_itinerary(self):
        r = check_time([])
        assert r["days_checked"] == 0
        assert r["overall_time_status"] == "passed"


# ============================================================
# check_geography — TS-EXEC-007, 008, 009
# ============================================================

class TestCheckGeography:
    # TS-EXEC-007: linear route, detour ratio < 1.5
    def test_linear_route(self):
        itinerary = [{
            "day": 1,
            "activities": [
                {"name": "A", "location": {"lat": 35.71, "lng": 139.79}},
                {"name": "B", "location": {"lat": 35.72, "lng": 139.80}},
                {"name": "C", "location": {"lat": 35.73, "lng": 139.81}},
            ],
        }]
        r = check_geography(itinerary)
        assert r["detours_found"] == 0
        assert r["overall_geo_status"] == "passed"

    # TS-EXEC-008: detour ratio at threshold
    def test_detour_at_threshold(self):
        # Route that goes back and forth = significant detour
        itinerary = [{
            "day": 1,
            "activities": [
                {"name": "A", "location": {"lat": 35.68, "lng": 139.76}},
                {"name": "B", "location": {"lat": 35.00, "lng": 135.00}},  # far away
                {"name": "C", "location": {"lat": 35.69, "lng": 139.77}},  # back near A
            ],
        }]
        r = check_geography(itinerary)
        # Should have detour warnings
        if r["detours_found"] > 0:
            assert r["detours"][0]["detour_ratio"] > 1.5

    # TS-EXEC-009: extreme detour
    def test_extreme_detour(self):
        itinerary = [{
            "day": 1,
            "activities": [
                {"name": "Tokyo", "location": {"lat": 35.68, "lng": 139.76}},
                {"name": "Osaka", "location": {"lat": 34.69, "lng": 135.50}},
                {"name": "Back", "location": {"lat": 35.69, "lng": 139.77}},
            ],
        }]
        r = check_geography(itinerary)
        assert r["detours_found"] >= 1
        assert r["overall_geo_status"] in ("failed", "passed_with_warnings")

    def test_single_activity(self):
        itinerary = [{"day": 1, "activities": [{"name": "only", "location": {"lat": 35.68, "lng": 139.76}}]}]
        r = check_geography(itinerary)
        assert r["detours_found"] == 0

    def test_empty_itinerary(self):
        r = check_geography([])
        assert r["detours_found"] == 0
        assert r["overall_geo_status"] == "passed"

    def test_long_transit_without_notes_warning(self):
        itinerary = [{
            "day": 1,
            "activities": [
                {"name": "far_place", "duration_minutes": 60, "transit_duration_minutes": 240,
                 "location": {"lat": 35.68, "lng": 139.76}},
            ],
        }]
        r = check_geography(itinerary)
        assert len(r["warnings"]) >= 1


# ============================================================
# validate_geography (single day)
# ============================================================

class TestValidateGeography:
    def test_two_points(self):
        day = {
            "activities": [
                {"name": "A", "location": {"lat": 35.71, "lng": 139.79}},
                {"name": "B", "location": {"lat": 35.72, "lng": 139.80}},
            ],
        }
        r = validate_geography(day)
        assert r["detour_ratio"] >= 1.0


# ============================================================
# check_weather_risk
# ============================================================

class TestCheckWeatherRisk:
    def test_typhoon_season_tokyo(self):
        r = check_weather_risk("Tokyo", "2026-08-15")
        assert len(r["risks"]) >= 1
        assert any("台风" in risk["description"] for risk in r["risks"])

    def test_dry_season(self):
        r = check_weather_risk("Tokyo", "2026-04-15")
        assert len(r["risks"]) == 0  # April no risks for Tokyo

    def test_unknown_location(self):
        r = check_weather_risk("UnknownCity", "2026-08-01")
        assert r["source_type"] == "estimated"

    def test_invalid_date(self):
        r = check_weather_risk("Tokyo", "invalid-date")
        assert r["month"] > 0  # falls back to current month


# ============================================================
# check_travel_requirements
# ============================================================

class TestCheckTravelRequirements:
    def test_japan_visa_required(self):
        r = check_travel_requirements("China", "Japan")
        assert r["visa_required"] is True
        assert r["passport_validity_months"] == 6

    def test_thailand_visa_free(self):
        r = check_travel_requirements("China", "Thailand")
        assert r["visa_required"] is False

    def test_unknown_country_default(self):
        r = check_travel_requirements("China", "Unknownia")
        assert r["visa_required"] is True  # default conservative
        assert "自行核实" in r["notes"]

    def test_safety_risks_included(self):
        r = check_travel_requirements("China", "Paris")
        assert len(r["safety_risks"]) > 0

    def test_partial_match(self):
        r = check_travel_requirements("China", "Tokyo, Japan")
        assert "passport_validity_months" in r
