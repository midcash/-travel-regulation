"""M2 ConstraintService：把解释候选冻结为可验证的约束快照。"""

from __future__ import annotations

import json
import math
import re
import unicodedata
from collections.abc import Collection
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from decimal import Decimal, InvalidOperation
from hashlib import sha256
from typing import Final, NoReturn

from pydantic import BaseModel, ConfigDict, ValidationError

from src.domain.errors import WorkflowError
from src.domain.models.constraint import (
    Constraint,
    ConstraintSnapshot,
    ConstraintSource,
    ConstraintValue,
)
from src.domain.models.enums import ConstraintHardness, ErrorCategory
from src.domain.models.interpretation import ConstraintCandidate, InterpretationResult
from src.domain.models.value_objects import DateRange, Money, RequestId, TraceId
from src.guard.negation import extract_negation_constraints

_DATE_CATEGORIES: Final[frozenset[str]] = frozenset({"date", "date_range"})
_MONEY_CATEGORIES: Final[frozenset[str]] = frozenset(
    {"budget", "budget_max", "budget_min", "budget_target", "price_limit"}
)
_CURRENCY_CATEGORIES: Final[frozenset[str]] = frozenset({"currency", "budget_currency"})
_TRAVELER_CATEGORIES: Final[frozenset[str]] = frozenset(
    {"traveler", "travelers", "people", "person_count", "traveler_count"}
)
_PLACE_CATEGORIES: Final[frozenset[str]] = frozenset(
    {
        "origin",
        "departure",
        "departure_city",
        "destination",
        "destinations",
        "arrival",
        "arrival_city",
        "place",
        "location",
        "hotel_area",
    }
)
_MULTI_VALUE_CATEGORIES: Final[frozenset[str]] = frozenset(
    {
        "destination",
        "preference",
        "preferences",
        "exclusion",
        "exclusions",
        "preferred_activity",
        "avoid_activity",
        "negation_recall",
    }
)
_CATEGORY_ALIASES: Final[dict[str, str]] = {
    "depart_from": "origin",
    "departure_city": "origin",
    "from": "origin",
    "arrive_at": "destination",
    "arrival_city": "destination",
    "to": "destination",
    "destinations": "destination",
    "travel_dates": "date_range",
    "travel_date": "date_range",
    "dates": "date_range",
    "people": "travelers",
    "person_count": "travelers",
    "traveler_count": "travelers",
}
_CURRENCY_ALIASES: Final[dict[str, str]] = {
    "人民币": "CNY",
    "元": "CNY",
    "块": "CNY",
    "rmb": "CNY",
    "renminbi": "CNY",
    "yuan": "CNY",
    "美元": "USD",
    "美金": "USD",
    "dollar": "USD",
    "dollars": "USD",
    "欧元": "EUR",
    "euro": "EUR",
    "euros": "EUR",
    "日元": "JPY",
    "円": "JPY",
    "yen": "JPY",
    "英镑": "GBP",
    "pound": "GBP",
    "pounds": "GBP",
}
_CHINESE_DIGITS: Final[dict[str, int]] = {
    "零": 0,
    "一": 1,
    "二": 2,
    "两": 2,
    "三": 3,
    "四": 4,
    "五": 5,
    "六": 6,
    "七": 7,
    "八": 8,
    "九": 9,
    "十": 10,
}
_WEEKDAY_NAMES: Final[dict[str, int]] = {
    "一": 0,
    "二": 1,
    "三": 2,
    "四": 3,
    "五": 4,
    "六": 5,
    "日": 6,
    "天": 6,
}
_SOURCE_RANK: Final[dict[ConstraintSource, int]] = {
    ConstraintSource.USER: 4,
    ConstraintSource.ASSUMPTION: 2,
    ConstraintSource.PROFILE: 1,
    ConstraintSource.SYSTEM: 0,
}
_HARDNESS_RANK: Final[dict[ConstraintHardness, int]] = {
    ConstraintHardness.HARD: 4,
    ConstraintHardness.SOFT: 3,
    ConstraintHardness.ASSUMPTION: 2,
    ConstraintHardness.UNKNOWN: 1,
}
_ISO_DATE = re.compile(r"^(\d{4})[-/.](\d{1,2})[-/.](\d{1,2})$")
_CN_DATE = re.compile(r"^(?:(?P<year>\d{4})年)?(?P<month>\d{1,2})月(?P<day>\d{1,2})日?$")
_CN_RANGE = re.compile(
    r"^(?:(?P<year1>\d{4})年)?(?P<month1>\d{1,2})月(?P<day1>\d{1,2})日?"
    r"\s*(?:至|到|~|～|—)\s*"
    r"(?:(?P<year2>\d{4})年)?(?P<month2>\d{1,2})月(?P<day2>\d{1,2})日?$"
)
_AMOUNT = re.compile(r"(?<![\d.])\d+(?:[,.]\d+)?(?![\d.])")
_MONTHS: Final[dict[str, int]] = {
    name: number
    for number, names in enumerate(
        (
            ("jan", "january"),
            ("feb", "february"),
            ("mar", "march"),
            ("apr", "april"),
            ("may",),
            ("jun", "june"),
            ("jul", "july"),
            ("aug", "august"),
            ("sep", "sept", "september"),
            ("oct", "october"),
            ("nov", "november"),
            ("dec", "december"),
        ),
        start=1,
    )
    for name in names
}
_EN_DATE = re.compile(
    r"^(?:(?P<year>\d{4})[-\s/]*)?(?P<month>[A-Za-z]+)\s+(?P<day>\d{1,2})"
    r"(?:st|nd|rd|th)?$",
    re.IGNORECASE,
)
_EN_RANGE = re.compile(
    r"^(?P<month1>[A-Za-z]+)\s+(?P<day1>\d{1,2})(?:st|nd|rd|th)?"
    r"\s*(?:to|through|-)\s*(?P<month2>[A-Za-z]+)?\s*"
    r"(?P<day2>\d{1,2})(?:st|nd|rd|th)?(?:,?\s*(?P<year>\d{4}))?$",
    re.IGNORECASE,
)


class ConstraintObservation(BaseModel):
    """带有来源和确认状态的约束候选。"""

    model_config = ConfigDict(extra="forbid", frozen=True)

    candidate: ConstraintCandidate
    source: ConstraintSource = ConstraintSource.USER
    user_confirmed: bool = False


@dataclass(frozen=True)
class _NormalizedConstraint:
    """服务内部的归一化中间结果。"""

    category: str
    normalized_value: ConstraintValue
    hardness: ConstraintHardness
    scope: str
    source: ConstraintSource
    confidence: Decimal
    user_confirmed: bool
    is_current: bool
    conflict_group: str | None = None


class ConstraintService:
    """将语义候选确定性归一化并生成新的不可变 ConstraintSnapshot。"""

    def build_snapshot(
        self,
        interpretation: InterpretationResult,
        *,
        request_id: RequestId,
        trace_id: TraceId,
        created_at: datetime,
        previous_snapshot: ConstraintSnapshot | None = None,
        context_observations: Collection[ConstraintObservation] = (),
        negation_text: str | None = None,
        reference_date: date | None = None,
        default_currency: str = "CNY",
    ) -> ConstraintSnapshot:
        """把解释结果归一化、合并并生成一个新版本快照。

        当前方法不查询外部事实；相对日期必须使用调用方提供的参考日期。
        """
        self._validate_context(
            request_id=request_id,
            trace_id=trace_id,
            created_at=created_at,
            previous_snapshot=previous_snapshot,
            default_currency=default_currency,
        )
        normalized = [
            self._normalize_observation(
                ConstraintObservation(candidate=candidate),
                trace_id=trace_id,
                reference_date=reference_date,
                default_currency=default_currency,
                is_current=True,
            )
            for candidate in interpretation.constraint_candidates
        ]
        normalized.extend(
            self._normalize_observation(
                observation,
                trace_id=trace_id,
                reference_date=reference_date,
                default_currency=default_currency,
                is_current=True,
            )
            for observation in context_observations
        )
        if previous_snapshot is not None:
            normalized.extend(
                _NormalizedConstraint(
                    category=item.category,
                    normalized_value=item.normalized_value,
                    hardness=item.hardness,
                    scope=item.scope,
                    source=item.source,
                    confidence=item.confidence,
                    user_confirmed=item.user_confirmed,
                    is_current=False,
                )
                for item in previous_snapshot.constraints
            )
        if negation_text is not None:
            normalized.extend(self._negation_recall(negation_text, normalized))

        constraints = self._merge(normalized, trace_id=trace_id)
        try:
            if previous_snapshot is None:
                return ConstraintSnapshot(
                    version=1,
                    created_at=created_at,
                    request_id=request_id,
                    constraints=constraints,
                )
            return previous_snapshot.new_version(constraints=constraints, created_at=created_at)
        except (ValidationError, ValueError) as exc:
            self._fail(
                trace_id,
                "INTERPRETATION_INVALID",
                "constraints violate snapshot contract",
                exc,
            )

    @staticmethod
    def _validate_context(
        *,
        request_id: RequestId,
        trace_id: TraceId,
        created_at: datetime,
        previous_snapshot: ConstraintSnapshot | None,
        default_currency: str,
    ) -> None:
        if previous_snapshot is not None and previous_snapshot.request_id != request_id:
            ConstraintService._fail(
                trace_id,
                "INTERPRETATION_INVALID",
                "previous constraint snapshot belongs to another request",
            )
        if created_at.tzinfo is None or created_at.utcoffset() is None:
            ConstraintService._fail(
                trace_id,
                "INTERPRETATION_INVALID",
                "constraint snapshot timestamp must include a timezone",
            )
        if _currency_code(default_currency) is None:
            ConstraintService._fail(
                trace_id,
                "INTERPRETATION_INVALID",
                "default currency must be a three-letter ISO code",
            )

    @staticmethod
    def _normalize_observation(
        observation: ConstraintObservation,
        *,
        trace_id: TraceId,
        reference_date: date | None,
        default_currency: str,
        is_current: bool,
    ) -> _NormalizedConstraint:
        candidate = observation.candidate
        category = _category(candidate.category)
        scope = _text(candidate.scope)
        if not scope:
            ConstraintService._fail(trace_id, "INTERPRETATION_INVALID", "constraint scope is empty")
        try:
            normalized = _value(
                category,
                candidate.value,
                reference_date=reference_date,
                default_currency=default_currency,
            )
        except (TypeError, ValueError, InvalidOperation) as exc:
            ConstraintService._fail(
                trace_id,
                "INTERPRETATION_INVALID",
                f"constraint value cannot be normalized for category {category}",
                exc,
            )
        return _NormalizedConstraint(
            category=category,
            normalized_value=normalized,
            hardness=candidate.hardness,
            scope=scope,
            source=observation.source,
            confidence=candidate.confidence,
            user_confirmed=observation.user_confirmed,
            is_current=is_current,
        )

    @staticmethod
    def _merge(
        values: list[_NormalizedConstraint],
        *,
        trace_id: TraceId,
    ) -> tuple[Constraint, ...]:
        dedup: dict[tuple[str, str, str], _NormalizedConstraint] = {}
        for value in values:
            key = (value.category, value.scope, _value_key(value.normalized_value))
            old = dedup.get(key)
            if old is None:
                dedup[key] = value
            elif _winner_key(value) > _winner_key(old):
                dedup[key] = _merge_duplicate(value, old)
            else:
                dedup[key] = _merge_duplicate(old, value)

        groups: dict[tuple[str, str], list[_NormalizedConstraint]] = {}
        for value in dedup.values():
            groups.setdefault((value.category, value.scope), []).append(value)

        merged: list[_NormalizedConstraint] = []
        for (category, scope), group in groups.items():
            if category in _MULTI_VALUE_CATEGORIES:
                merged.append(_merge_multi(group))
                continue
            source_rank = max(_source_rank(value) for value in group)
            selected = [value for value in group if _source_rank(value) == source_rank]
            current = [value for value in selected if value.is_current]
            if current:
                selected = current
            if len(selected) > 1:
                conflict = _conflict_group(category, scope)
                selected = [_add_conflict(value, conflict) for value in selected]
            merged.extend(selected)

        result: list[Constraint] = []
        for value in sorted(
            merged,
            key=lambda item: (
                -_source_rank(item),
                -_HARDNESS_RANK[item.hardness],
                item.category,
                item.scope,
                _value_key(item.normalized_value),
            ),
        ):
            try:
                result.append(
                    Constraint(
                        id=_constraint_id(value),
                        category=value.category,
                        normalized_value=value.normalized_value,
                        hardness=value.hardness,
                        priority=_priority(value),
                        scope=value.scope,
                        source=value.source,
                        confidence=value.confidence,
                        user_confirmed=value.user_confirmed,
                        conflict_group=value.conflict_group,
                    )
                )
            except (ValidationError, ValueError) as exc:
                ConstraintService._fail(
                    trace_id,
                    "INTERPRETATION_INVALID",
                    "normalized constraint violates the domain contract",
                    exc,
                )
        return tuple(result)

    @staticmethod
    def _negation_recall(
        text: str,
        existing: list[_NormalizedConstraint],
    ) -> tuple[_NormalizedConstraint, ...]:
        recalls = extract_negation_constraints(text)
        if not recalls:
            return ()
        searchable = tuple(
            str(value.normalized_value).casefold()
            for value in existing
            if value.category != "negation_recall"
        )
        return tuple(
            _NormalizedConstraint(
                category="negation_recall",
                normalized_value=recall,
                hardness=ConstraintHardness.UNKNOWN,
                scope="trip",
                source=ConstraintSource.USER,
                confidence=Decimal("0.5"),
                user_confirmed=False,
                is_current=True,
            )
            for recall in recalls
            if recall.casefold() not in searchable
        )

    @staticmethod
    def _fail(
        trace_id: TraceId,
        code: str,
        message: str,
        cause: BaseException | None = None,
    ) -> NoReturn:
        raise WorkflowError(
            trace_id=trace_id,
            stage="constraint_service",
            category=ErrorCategory.VALIDATION,
            code=code,
            safe_message=message,
            retryable=False,
            cause=cause,
        )


def _category(category: str) -> str:
    normalized = unicodedata.normalize("NFKC", category).strip().casefold()
    normalized = re.sub(r"[\s-]+", "_", normalized)
    return _CATEGORY_ALIASES.get(normalized, normalized)


def _text(value: str) -> str:
    return " ".join(unicodedata.normalize("NFKC", value).split())


def _value(
    category: str,
    value: object,
    *,
    reference_date: date | None,
    default_currency: str,
) -> ConstraintValue:
    if category in _DATE_CATEGORIES:
        parsed = _date_value(value, reference_date=reference_date)
        if category == "date_range" and isinstance(parsed, date):
            return DateRange(start=parsed, end=parsed)
        return parsed
    if category in _MONEY_CATEGORIES:
        return _money(value, default_currency=default_currency)
    if category in _CURRENCY_CATEGORIES:
        if not isinstance(value, str) or _currency_code(value) is None:
            raise ValueError("unsupported currency")
        return _currency_code(value)  # type: ignore[return-value]
    if category in _TRAVELER_CATEGORIES:
        return _traveler_count(value)
    if category in _PLACE_CATEGORIES:
        return _place(value)
    if isinstance(value, tuple):
        items = tuple(dict.fromkeys(_text(item) for item in value))
        if not items or any(not item for item in items):
            raise ValueError("empty text collection")
        return items
    if isinstance(value, str):
        normalized = _text(value)
        if not normalized:
            raise ValueError("empty text")
        return normalized
    if isinstance(value, float):
        if not math.isfinite(value):
            raise ValueError("numeric value must be finite")
        return Decimal(str(value))
    if isinstance(value, bool | int | Decimal | date | Money | DateRange):
        return value
    raise TypeError("unsupported constraint value")


def _date_value(value: object, *, reference_date: date | None) -> date | DateRange:
    if isinstance(value, date):
        return value
    if not isinstance(value, str):
        raise TypeError("date value must be text")
    text = _text(value).strip("，,。.")
    match = _ISO_DATE.fullmatch(text)
    if match:
        return _make_date(*match.groups())
    match = re.fullmatch(
        r"(\d{4}[-/.]\d{1,2}[-/.]\d{1,2})\s*(?:至|到|/|~|～|—|to)\s*"
        r"(\d{4}[-/.]\d{1,2}[-/.]\d{1,2})",
        text,
        re.IGNORECASE,
    )
    if match:
        start = _date_value(match.group(1), reference_date=reference_date)
        end = _date_value(match.group(2), reference_date=reference_date)
        if not isinstance(start, date) or not isinstance(end, date):
            raise TypeError("ISO date range endpoints must be dates")
        return DateRange(start=start, end=end)
    match = _CN_RANGE.fullmatch(text)
    if match:
        year1 = _year(match.group("year1"), reference_date)
        year2 = _year(match.group("year2"), reference_date, fallback=year1)
        start = _make_date(year1, match.group("month1"), match.group("day1"))
        end = _make_date(year2, match.group("month2"), match.group("day2"))
        if match.group("year2") is None and end < start:
            end = end.replace(year=end.year + 1)
        return DateRange(start=start, end=end)
    match = _CN_DATE.fullmatch(text)
    if match:
        return _make_date(
            _year(match.group("year"), reference_date),
            match.group("month"),
            match.group("day"),
        )
    match = _EN_RANGE.fullmatch(text)
    if match:
        month1 = _MONTHS.get(match.group("month1").casefold())
        month2_name = match.group("month2") or match.group("month1")
        month2 = _MONTHS.get(month2_name.casefold())
        if month1 is None or month2 is None:
            raise ValueError("unsupported English month")
        year = _year(match.group("year"), reference_date)
        start = _make_date(year, month1, match.group("day1"))
        end = _make_date(year, month2, match.group("day2"))
        if match.group("year") is None and end < start:
            end = end.replace(year=end.year + 1)
        return DateRange(start=start, end=end)
    match = _EN_DATE.fullmatch(text)
    if match:
        month = _MONTHS.get(match.group("month").casefold())
        if month is None:
            raise ValueError("unsupported English month")
        return _make_date(_year(match.group("year"), reference_date), month, match.group("day"))
    if reference_date is not None:
        offsets = {"今天": 0, "明天": 1, "后天": 2, "today": 0, "tomorrow": 1}
        if text.casefold() in offsets:
            return reference_date + timedelta(days=offsets[text.casefold()])
        if text in {"本周末", "周末"} or text.casefold() == "weekend":
            start = reference_date + timedelta(days=5 - reference_date.weekday())
            return DateRange(start=start, end=start + timedelta(days=1))
        if text == "下周末" or text.casefold() == "next weekend":
            start = reference_date + timedelta(days=12 - reference_date.weekday())
            return DateRange(start=start, end=start + timedelta(days=1))
        weekday = re.fullmatch(r"下周([一二三四五六日天])", text)
        if weekday:
            monday = reference_date + timedelta(days=7 - reference_date.weekday())
            return monday + timedelta(days=_WEEKDAY_NAMES[weekday.group(1)])
    raise ValueError("unsupported date expression")


def _make_date(year: str | int, month: str | int, day: str | int) -> date:
    return date(int(year), int(month), int(day))


def _year(
    value: str | None,
    reference_date: date | None,
    *,
    fallback: int | None = None,
) -> int:
    if value is not None:
        return int(value)
    if fallback is not None:
        return fallback
    if reference_date is None:
        raise ValueError("year is required without reference date")
    return reference_date.year


def _money(value: object, *, default_currency: str) -> Money:
    currency = _currency_code(default_currency)
    if currency is None:
        raise ValueError("invalid default currency")
    if isinstance(value, bool):
        raise TypeError("money amount must be numeric")
    if isinstance(value, int | Decimal):
        amount = Decimal(value)
    elif isinstance(value, float):
        if not math.isfinite(value):
            raise ValueError("money amount must be finite")
        amount = Decimal(str(value))
    elif isinstance(value, str):
        text = _text(value).casefold()
        match = _AMOUNT.search(text.replace(",", ""))
        if match is None:
            raise ValueError("money amount is missing")
        amount = Decimal(match.group().replace(",", ""))
        currency = _currency_code(_find_currency(text) or currency) or currency
    else:
        raise TypeError("money value must be numeric or text")
    if amount <= 0:
        raise ValueError("money amount must be positive")
    return Money(amount=amount, currency=currency)


def _find_currency(text: str) -> str | None:
    for alias, currency in sorted(_CURRENCY_ALIASES.items(), key=lambda item: -len(item[0])):
        if alias in text:
            return currency
    if "¥" in text or "￥" in text:
        return "CNY"
    if "$" in text:
        return "USD"
    if "€" in text:
        return "EUR"
    match = re.search(r"\b([a-z]{3})\b", text)
    return _currency_code(match.group(1)) if match else None


def _currency_code(value: str) -> str | None:
    normalized = _text(value).casefold()
    if normalized in _CURRENCY_ALIASES:
        return _CURRENCY_ALIASES[normalized]
    return normalized.upper() if re.fullmatch(r"[a-z]{3}", normalized) else None


def _traveler_count(value: object) -> int:
    if type(value) is int:
        count = value
    elif isinstance(value, str):
        text = _text(value).casefold()
        if text in _CHINESE_DIGITS:
            count = _CHINESE_DIGITS[text]
        else:
            numbers = [int(item) for item in re.findall(r"\d+", text)]
            count = (
                sum(numbers)
                if numbers
                else sum(_CHINESE_DIGITS[item] for item in text if item in _CHINESE_DIGITS)
            )
    else:
        raise TypeError("traveler count must be integer or text")
    if count < 1:
        raise ValueError("traveler count must be positive")
    return count


def _place(value: object) -> ConstraintValue:
    if isinstance(value, tuple):
        places = tuple(dict.fromkeys(_text(item) for item in value))
        if not places or any(not place for place in places):
            raise ValueError("empty place collection")
        return places
    if not isinstance(value, str):
        raise TypeError("place must be text")
    place = _text(value)
    if not place:
        raise ValueError("empty place")
    return place


def _value_key(value: ConstraintValue) -> str:
    if isinstance(value, BaseModel):
        return json.dumps(value.model_dump(mode="json"), ensure_ascii=False, sort_keys=True)
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, Decimal):
        return str(value)
    return json.dumps(value, ensure_ascii=False, sort_keys=True, default=str)


def _source_rank(value: _NormalizedConstraint) -> int:
    return _SOURCE_RANK[value.source] - (
        1 if value.source == ConstraintSource.USER and value.user_confirmed else 0
    )


def _winner_key(value: _NormalizedConstraint) -> tuple[int, int, int, int, str]:
    return (
        int(value.is_current),
        _source_rank(value),
        _HARDNESS_RANK[value.hardness],
        int(value.confidence * 100),
        _value_key(value.normalized_value),
    )


def _merge_duplicate(
    left: _NormalizedConstraint,
    right: _NormalizedConstraint,
) -> _NormalizedConstraint:
    winner = left if _winner_key(left) >= _winner_key(right) else right
    return _NormalizedConstraint(
        category=winner.category,
        normalized_value=winner.normalized_value,
        hardness=winner.hardness,
        scope=winner.scope,
        source=winner.source,
        confidence=max(left.confidence, right.confidence),
        user_confirmed=winner.user_confirmed,
        is_current=winner.is_current,
        conflict_group=winner.conflict_group,
    )


def _merge_multi(group: list[_NormalizedConstraint]) -> _NormalizedConstraint:
    winner = max(group, key=_winner_key)
    items: list[str] = []
    for value in group:
        normalized = value.normalized_value
        if isinstance(normalized, tuple):
            items.extend(normalized)
        elif isinstance(normalized, str):
            items.append(normalized)
    unique = tuple(dict.fromkeys(items))
    normalized_value: ConstraintValue = unique[0] if len(unique) == 1 else unique
    return _NormalizedConstraint(
        category=winner.category,
        normalized_value=normalized_value,
        hardness=winner.hardness,
        scope=winner.scope,
        source=winner.source,
        confidence=max(value.confidence for value in group),
        user_confirmed=winner.user_confirmed,
        is_current=winner.is_current,
    )


def _add_conflict(value: _NormalizedConstraint, conflict: str) -> _NormalizedConstraint:
    return _NormalizedConstraint(
        category=value.category,
        normalized_value=value.normalized_value,
        hardness=value.hardness,
        scope=value.scope,
        source=value.source,
        confidence=value.confidence,
        user_confirmed=value.user_confirmed,
        is_current=value.is_current,
        conflict_group=conflict,
    )


def _conflict_group(category: str, scope: str) -> str:
    digest = sha256(f"{category}|{scope}".encode()).hexdigest()[:16]
    return f"conflict-{digest}"


def _constraint_id(value: _NormalizedConstraint) -> str:
    content = "|".join(
        (
            value.category,
            value.scope,
            _value_key(value.normalized_value),
            value.source.value,
            value.hardness.value,
            str(value.user_confirmed),
        )
    )
    return f"constraint-{sha256(content.encode()).hexdigest()[:24]}"


def _priority(value: _NormalizedConstraint) -> int:
    return _source_rank(value) * 100 + _HARDNESS_RANK[value.hardness]
