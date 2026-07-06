"""User request data models for the Travel Planning Multi-Agent system.

Defines the structured representation of a user's travel request, covering
destination, dates, budget, traveler composition, and preferences. These
dataclasses are the contract between user input parsing (Orchestrator) and
downstream Agent processing (Planning, Execution, Evaluation).

Sources:
    - spec/system_spec.md §5 (SharedContext fields)
    - spec/orchestrator_spec.md §2.1 (parse_user_request output schema)
    - spec/agent_contract.md §3.3 (payload schemas)
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_DATE_PATTERN = re.compile(r"^\d{4}-\d{2}-\d{2}$")
"""Regex for YYYY-MM-DD date format validation."""

_VALID_PACES = frozenset({"relaxed", "moderate", "intensive"})
"""Accepted values for the ``pace`` field of Preferences."""


# ===================================================================
# Destination
# ===================================================================

@dataclass
class Destination:
    """A travel destination location.

    Attributes:
        city: City name (e.g. "Tokyo", "Paris").
        country: Country name (e.g. "Japan", "France").
        region: Optional sub-national region (e.g. "Kanto", "Ile-de-France").
        coordinates: Optional geographic coordinates with ``lat`` and ``lng``
            keys, e.g. ``{"lat": 35.6762, "lng": 139.6503}``.
    """

    city: str
    country: str
    region: Optional[str] = None
    coordinates: Optional[Dict[str, float]] = None

    def __post_init__(self) -> None:
        if not self.city or not isinstance(self.city, str):
            raise ValueError(f"city must be a non-empty string, got: {self.city!r}")
        if not self.country or not isinstance(self.country, str):
            raise ValueError(
                f"country must be a non-empty string, got: {self.country!r}"
            )
        if self.coordinates is not None:
            self._validate_coordinates()

    def _validate_coordinates(self) -> None:
        """Validate that coordinates contains valid lat/lng values."""
        if not isinstance(self.coordinates, dict):
            raise TypeError(
                f"coordinates must be a dict, got: {type(self.coordinates).__name__}"
            )
        missing = {"lat", "lng"} - set(self.coordinates.keys())
        if missing:
            raise ValueError(
                f"coordinates must contain 'lat' and 'lng', missing: {missing}"
            )
        lat = self.coordinates["lat"]
        lng = self.coordinates["lng"]
        if not isinstance(lat, (int, float)):
            raise TypeError(f"coordinates.lat must be a number, got: {type(lat).__name__}")
        if not isinstance(lng, (int, float)):
            raise TypeError(f"coordinates.lng must be a number, got: {type(lng).__name__}")
        if not (-90.0 <= lat <= 90.0):
            raise ValueError(f"coordinates.lat must be in [-90, 90], got: {lat}")
        if not (-180.0 <= lng <= 180.0):
            raise ValueError(f"coordinates.lng must be in [-180, 180], got: {lng}")

    def to_dict(self) -> Dict[str, Any]:
        """Return a JSON-serializable dictionary representation."""
        return {
            "city": self.city,
            "country": self.country,
            "region": self.region,
            "coordinates": self.coordinates,
        }


# ===================================================================
# DateRange
# ===================================================================

@dataclass
class DateRange:
    """A date range for a trip.

    At least one of ``arrival``, ``departure``, or ``duration_days`` should
    be provided after user clarification.

    Attributes:
        arrival: Arrival/start date in ``YYYY-MM-DD`` format (optional).
        departure: Departure/end date in ``YYYY-MM-DD`` format (optional).
        duration_days: Duration of the trip in days. Defaults to 0 when unknown.
        is_flexible: Whether the user has indicated flexible dates.
    """

    arrival: Optional[str] = None
    departure: Optional[str] = None
    duration_days: int = 0
    is_flexible: bool = False

    def __post_init__(self) -> None:
        if self.arrival is not None:
            self._validate_date(self.arrival, "arrival")
        if self.departure is not None:
            self._validate_date(self.departure, "departure")
        if not isinstance(self.duration_days, int) or self.duration_days < 0:
            raise ValueError(
                f"duration_days must be a non-negative int, got: {self.duration_days!r}"
            )
        if (
            self.arrival is not None
            and self.departure is not None
            and self.duration_days > 0
        ):
            # Light sanity check: duration_days should be consistent with
            # arrival/departure when both are present, but we do not enforce
            # an exact match here because the user may have given approximate
            # values that the Orchestrator resolves later.
            pass

    @staticmethod
    def _validate_date(value: str, field_name: str) -> None:
        """Validate that *value* is a well-formed YYYY-MM-DD string."""
        if not isinstance(value, str):
            raise TypeError(
                f"{field_name} must be a string (YYYY-MM-DD), "
                f"got: {type(value).__name__}"
            )
        if not _DATE_PATTERN.match(value):
            raise ValueError(
                f"{field_name} must be in YYYY-MM-DD format, got: {value!r}"
            )

    def to_dict(self) -> Dict[str, Any]:
        """Return a JSON-serializable dictionary representation."""
        return {
            "arrival": self.arrival,
            "departure": self.departure,
            "duration_days": self.duration_days,
            "is_flexible": self.is_flexible,
        }


# ===================================================================
# Budget
# ===================================================================

@dataclass
class Budget:
    """Financial budget for a trip.

    Attributes:
        total: Total budget amount in the given currency. Must be > 0.
        currency: ISO 4217 currency code. Defaults to ``"CNY"``.
        per_day: Optional per-day budget breakdown, typically derived from
            total and duration during validation.
    """

    total: float
    currency: str = "CNY"
    per_day: Optional[float] = None

    def __post_init__(self) -> None:
        if not isinstance(self.total, (int, float)):
            raise TypeError(
                f"total must be a number, got: {type(self.total).__name__}"
            )
        if self.total <= 0:
            raise ValueError(
                f"total budget must be > 0, got: {self.total}"
            )
        if not self.currency or not isinstance(self.currency, str):
            raise ValueError(
                f"currency must be a non-empty string, got: {self.currency!r}"
            )
        if self.per_day is not None:
            if not isinstance(self.per_day, (int, float)):
                raise TypeError(
                    f"per_day must be a number or None, "
                    f"got: {type(self.per_day).__name__}"
                )
            if self.per_day <= 0:
                raise ValueError(
                    f"per_day budget must be > 0 when provided, got: {self.per_day}"
                )

    def to_dict(self) -> Dict[str, Any]:
        """Return a JSON-serializable dictionary representation."""
        return {
            "total": self.total,
            "currency": self.currency,
            "per_day": self.per_day,
        }


# ===================================================================
# Travelers
# ===================================================================

@dataclass
class Travelers:
    """Composition of travelers in the group.

    Attributes:
        adults: Number of adults (>= 1). Defaults to 1.
        children: Number of children (>= 0). Defaults to 0.
        infants: Number of infants (>= 0). Defaults to 0.
    """

    adults: int = 1
    children: int = 0
    infants: int = 0

    def __post_init__(self) -> None:
        if not isinstance(self.adults, int) or self.adults < 1:
            raise ValueError(
                f"adults must be an int >= 1, got: {self.adults!r}"
            )
        if not isinstance(self.children, int) or self.children < 0:
            raise ValueError(
                f"children must be a non-negative int, got: {self.children!r}"
            )
        if not isinstance(self.infants, int) or self.infants < 0:
            raise ValueError(
                f"infants must be a non-negative int, got: {self.infants!r}"
            )

    @property
    def total_count(self) -> int:
        """Return the total number of travelers."""
        return self.adults + self.children + self.infants

    def to_dict(self) -> Dict[str, Any]:
        """Return a JSON-serializable dictionary representation."""
        return {
            "adults": self.adults,
            "children": self.children,
            "infants": self.infants,
        }


# ===================================================================
# Preferences
# ===================================================================

@dataclass
class Preferences:
    """User preferences and constraints for the trip.

    Attributes:
        style: Travel-style tags such as ``"food"``, ``"culture"``,
            ``"adventure"``, ``"shopping"``, ``"nature"``.
        pace: Desired travel pace: ``"relaxed"``, ``"moderate"``, or
            ``"intensive"``.
        dietary: Dietary restrictions (e.g. ``"vegetarian"``,
            ``"halal"``, ``"gluten-free"``).
        accessibility: Accessibility requirements (e.g. ``"wheelchair"``,
            ``"hearing-impaired"``).
        excluded: Places, activities, or accommodation types to exclude
            (e.g. ``["museums"]``, ``["hostels"]``).
        notes: Free-text notes or special requests from the user.
    """

    style: List[str] = field(default_factory=list)
    pace: str = "moderate"
    dietary: List[str] = field(default_factory=list)
    accessibility: List[str] = field(default_factory=list)
    excluded: List[str] = field(default_factory=list)
    notes: Optional[str] = None

    def __post_init__(self) -> None:
        self._validate_list_field(self.style, "style")
        self._validate_list_field(self.dietary, "dietary")
        self._validate_list_field(self.accessibility, "accessibility")
        self._validate_list_field(self.excluded, "excluded")
        if self.pace not in _VALID_PACES:
            raise ValueError(
                f"pace must be one of {sorted(_VALID_PACES)}, got: {self.pace!r}"
            )

    @staticmethod
    def _validate_list_field(value: object, field_name: str) -> None:
        """Ensure the field is a list of non-empty strings."""
        if not isinstance(value, list):
            raise TypeError(
                f"{field_name} must be a list, got: {type(value).__name__}"
            )
        for i, item in enumerate(value):
            if not isinstance(item, str) or not item:
                raise ValueError(
                    f"{field_name}[{i}] must be a non-empty string, got: {item!r}"
                )

    def to_dict(self) -> Dict[str, Any]:
        """Return a JSON-serializable dictionary representation."""
        return {
            "style": self.style,
            "pace": self.pace,
            "dietary": self.dietary,
            "accessibility": self.accessibility,
            "excluded": self.excluded,
            "notes": self.notes,
        }


# ===================================================================
# StructuredRequest
# ===================================================================

@dataclass
class StructuredRequest:
    """Fully parsed and structured representation of a user's travel request.

    This is the primary input contract for the Orchestrator after parsing
    and validating the user's natural-language request (Gate 0). All
    downstream Agents consume this structure.

    Attributes:
        destination: Parsed destination location.
        dates: Requested date range (may be partial before user clarification).
        budget: Budget constraints.
        travelers: Traveler composition.
        preferences: Travel-style preferences and constraints.
        raw_text: The original user input string, preserved for reference.
        request_id: Unique identifier for this request, assigned by the
            Orchestrator (UUID v4 string).
    """

    destination: Destination
    dates: DateRange
    budget: Budget
    travelers: Travelers = field(default_factory=Travelers)
    preferences: Preferences = field(default_factory=Preferences)
    raw_text: Optional[str] = None
    request_id: Optional[str] = None

    def __post_init__(self) -> None:
        if not isinstance(self.destination, Destination):
            raise TypeError(
                "destination must be a Destination instance, "
                f"got: {type(self.destination).__name__}"
            )
        if not isinstance(self.dates, DateRange):
            raise TypeError(
                f"dates must be a DateRange instance, "
                f"got: {type(self.dates).__name__}"
            )
        if not isinstance(self.budget, Budget):
            raise TypeError(
                f"budget must be a Budget instance, "
                f"got: {type(self.budget).__name__}"
            )
        if not isinstance(self.travelers, Travelers):
            raise TypeError(
                f"travelers must be a Travelers instance, "
                f"got: {type(self.travelers).__name__}"
            )
        if not isinstance(self.preferences, Preferences):
            raise TypeError(
                f"preferences must be a Preferences instance, "
                f"got: {type(self.preferences).__name__}"
            )

    def to_dict(self) -> Dict[str, Any]:
        """Return a JSON-serializable dictionary representation."""
        return {
            "destination": self.destination.to_dict(),
            "dates": self.dates.to_dict(),
            "budget": self.budget.to_dict(),
            "travelers": self.travelers.to_dict(),
            "preferences": self.preferences.to_dict(),
            "raw_text": self.raw_text,
            "request_id": self.request_id,
        }
