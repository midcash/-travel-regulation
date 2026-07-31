"""M3 Candidate Normalizer 与 Candidate Pool 的确定性实现。"""

from __future__ import annotations

import hashlib
import json
from collections import defaultdict
from datetime import UTC, date, datetime
from typing import Final

from src.domain.models.candidates import (
    Candidate,
    CandidatePoolResult,
    CandidatePrice,
    CandidateProvenance,
    CandidateRejection,
    CandidateRejectReason,
    ContextCandidate,
    PlaceCandidate,
    StayCandidate,
    TransportCandidate,
)
from src.domain.models.constraint import Constraint, ConstraintSnapshot
from src.domain.models.enums import CandidateRejectCode, EvidenceStatus
from src.domain.models.evidence import EvidenceItem, EvidenceSnapshot
from src.domain.models.value_objects import DateRange, Money

_SUPPORTED_HARD_CONSTRAINT_CATEGORIES: Final[frozenset[str]] = frozenset(
    {
        "budget",
        "budget_max",
        "price_limit",
        "max_total_price",
        "currency",
        "budget_currency",
        "candidate_kind",
        "transport_mode",
        "mode",
        "origin",
        "destination",
        "date",
        "date_range",
        "hotel_area",
        "stay_area",
        "place_category",
        "category",
        "context_type",
        "exclude_tag",
        "exclusion",
    }
)


class CandidateNormalizer:
    """将已类型化的候选规范化为可去重的稳定表示。"""

    def normalize(self, candidate: Candidate) -> Candidate:
        """归一化候选字段、目标时区和稳定候选 ID。

        Args:
            candidate: 已经过 Pydantic Schema 校验的候选草稿。

        Returns:
            Candidate: 字段顺序和时间统一后的候选。

        Raises:
            TypeError: 输入不是受支持的 Candidate 变体时抛出。
        """
        if not isinstance(
            candidate,
            TransportCandidate | StayCandidate | PlaceCandidate | ContextCandidate,
        ):
            raise TypeError("candidate must be a supported Candidate variant")

        normalized = candidate.model_copy(
            update={
                "timezone": "UTC",
                "evidence_refs": tuple(sorted(candidate.evidence_refs)),
                "provenance": _normalized_provenance(candidate.provenance),
                "tags": tuple(sorted({tag.casefold() for tag in candidate.tags})),
                "price": _normalized_price(candidate.price),
                "rating": (
                    candidate.rating.model_copy(
                        update={"evidence_refs": tuple(sorted(candidate.rating.evidence_refs))}
                    )
                    if candidate.rating is not None
                    else None
                ),
            }
        )
        normalized = _normalize_candidate_times(normalized)
        candidate_id = _candidate_id(normalized)
        return normalized.model_copy(update={"candidate_id": candidate_id})


class CandidatePool:
    """按证据状态去重并执行候选级硬约束剪枝，不执行体验排序。"""

    def __init__(self, normalizer: CandidateNormalizer | None = None) -> None:
        """注入候选标准化器，默认使用 M3 的确定性实现。"""
        if normalizer is not None and not isinstance(normalizer, CandidateNormalizer):
            raise TypeError("normalizer must be a CandidateNormalizer instance")
        self._normalizer = normalizer or CandidateNormalizer()

    def build(
        self,
        candidates: tuple[Candidate, ...],
        *,
        evidence_snapshot: EvidenceSnapshot,
        constraint_snapshot: ConstraintSnapshot,
    ) -> CandidatePoolResult:
        """生成候选池，并保留所有淘汰与待后续处理的硬约束原因。

        Args:
            candidates: Research Agent 或 Adapter 已构造的候选草稿。
            evidence_snapshot: 当前 Evidence Registry 快照。
            constraint_snapshot: 当前轮冻结的约束快照。

        Returns:
            CandidatePoolResult: 入选候选、拒绝原因和未在候选级处理的硬约束。

        Raises:
            TypeError: 输入不是规定的不可变领域契约时抛出。
        """
        if not isinstance(candidates, tuple):
            raise TypeError("candidates must be a tuple")
        if not isinstance(evidence_snapshot, EvidenceSnapshot):
            raise TypeError("evidence_snapshot must be an EvidenceSnapshot instance")
        if not isinstance(constraint_snapshot, ConstraintSnapshot):
            raise TypeError("constraint_snapshot must be a ConstraintSnapshot instance")

        normalized = tuple(self._normalizer.normalize(candidate) for candidate in candidates)
        merged = _merge_candidates(normalized)
        evidence_by_id = {
            evidence.evidence_id: evidence for evidence in evidence_snapshot.evidence_items
        }
        accepted: list[Candidate] = []
        rejected: list[CandidateRejection] = []

        for candidate in merged:
            reasons = [
                *_evidence_reasons(candidate, evidence_by_id),
                *(
                    reason
                    for constraint in constraint_snapshot.hard_constraints
                    for reason in _hard_constraint_reasons(candidate, constraint)
                ),
            ]
            if reasons:
                rejected.append(CandidateRejection(candidate=candidate, reasons=tuple(reasons)))
            else:
                accepted.append(candidate)

        return CandidatePoolResult(
            evidence_snapshot_id=evidence_snapshot.snapshot_id,
            constraint_snapshot_version=constraint_snapshot.version,
            candidates=tuple(sorted(accepted, key=lambda candidate: candidate.candidate_id)),
            rejected=tuple(
                sorted(rejected, key=lambda item: item.candidate.candidate_id)
            ),
            deferred_hard_constraint_refs=tuple(
                constraint.id
                for constraint in constraint_snapshot.hard_constraints
                if constraint.category.casefold() not in _SUPPORTED_HARD_CONSTRAINT_CATEGORIES
            ),
        )


def _normalized_provenance(
    provenance: tuple[CandidateProvenance, ...],
) -> tuple[CandidateProvenance, ...]:
    """按来源键排序，保证相同来源集合得到一致输出。"""
    return tuple(
        sorted(
            provenance,
            key=lambda item: (item.provider.casefold(), item.entity_id, item.source_ref),
        )
    )


def _normalized_price(price: CandidatePrice | None) -> CandidatePrice | None:
    """规范化价格包含项和价格证据的顺序。"""
    if price is None:
        return None
    return price.model_copy(
        update={
            "inclusions": tuple(sorted({value.casefold() for value in price.inclusions})),
            "evidence_refs": tuple(sorted(price.evidence_refs)),
        }
    )


def _normalize_candidate_times(candidate: Candidate) -> Candidate:
    """将候选内的已验证时刻统一转换为 UTC。"""
    if isinstance(candidate, TransportCandidate):
        return candidate.model_copy(
            update={
                "departure_at": _to_utc(candidate.departure_at),
                "arrival_at": _to_utc(candidate.arrival_at),
            }
        )
    if isinstance(candidate, StayCandidate):
        return candidate.model_copy(
            update={
                "check_in": _to_utc(candidate.check_in),
                "check_out": _to_utc(candidate.check_out),
            }
        )
    return candidate


def _to_utc(value: datetime | None) -> datetime | None:
    """保留空值，否则把已校验时刻转换为 UTC。"""
    return value.astimezone(UTC) if value is not None else None


def _candidate_id(candidate: Candidate) -> str:
    """从候选语义字段派生稳定 ID，不把证据或供应商来源作为实体身份。"""
    payload = candidate.model_dump(mode="json")
    payload.pop("candidate_id")
    payload.pop("evidence_refs")
    payload.pop("provenance")
    if payload["price"] is not None:
        payload["price"].pop("evidence_refs")
    if payload["rating"] is not None:
        payload["rating"].pop("evidence_refs")
    canonical = json.dumps(
        _casefold_strings(payload), ensure_ascii=True, separators=(",", ":"), sort_keys=True
    )
    digest = hashlib.sha256(canonical.encode("utf-8")).hexdigest()
    return f"candidate:{candidate.kind}:{digest}"


def _casefold_strings(value: object) -> object:
    """对身份计算中的文本执行大小写无关的确定性规范化。"""
    if isinstance(value, str):
        return value.casefold()
    if isinstance(value, list):
        return [_casefold_strings(item) for item in value]
    if isinstance(value, dict):
        return {key: _casefold_strings(item) for key, item in value.items()}
    return value


def _merge_candidates(candidates: tuple[Candidate, ...]) -> tuple[Candidate, ...]:
    """合并语义相同候选的证据与供应商来源，保留单一标准候选。"""
    grouped: dict[str, list[Candidate]] = defaultdict(list)
    for candidate in candidates:
        grouped[candidate.candidate_id].append(candidate)

    return tuple(
        _merge_candidate_group(group)
        for _, group in sorted(grouped.items(), key=lambda item: item[0])
    )


def _merge_candidate_group(candidates: list[Candidate]) -> Candidate:
    """合并已拥有相同稳定 ID 的候选集合。"""
    base = candidates[0]
    evidence_refs = tuple(
        sorted(
            {
                evidence_ref
                for candidate in candidates
                for evidence_ref in candidate.evidence_refs
            }
        )
    )
    provenance_by_key = {
        (item.provider, item.entity_id, item.source_ref): item
        for candidate in candidates
        for item in candidate.provenance
    }
    price = base.price
    if price is not None:
        price = price.model_copy(
            update={
                "evidence_refs": tuple(
                    sorted(
                        {
                            evidence_ref
                            for candidate in candidates
                            if candidate.price is not None
                            for evidence_ref in candidate.price.evidence_refs
                        }
                    )
                )
            }
        )
    rating = base.rating
    if rating is not None:
        rating = rating.model_copy(
            update={
                "evidence_refs": tuple(
                    sorted(
                        {
                            evidence_ref
                            for candidate in candidates
                            if candidate.rating is not None
                            for evidence_ref in candidate.rating.evidence_refs
                        }
                    )
                )
            }
        )
    return base.model_copy(
        update={
            "evidence_refs": evidence_refs,
            "provenance": _normalized_provenance(tuple(provenance_by_key.values())),
            "price": price,
            "rating": rating,
        }
    )


def _evidence_reasons(
    candidate: Candidate,
    evidence_by_id: dict[str, EvidenceItem],
) -> tuple[CandidateRejectReason, ...]:
    """要求候选的每个证据引用均存在于当前快照且状态为 VERIFIED。"""
    reasons: list[CandidateRejectReason] = []
    for evidence_ref in candidate.evidence_refs:
        evidence = evidence_by_id.get(evidence_ref)
        if evidence is None:
            reasons.append(
                CandidateRejectReason(
                    code=CandidateRejectCode.EVIDENCE_MISSING,
                    message="candidate evidence is absent from the current snapshot",
                    evidence_ref=evidence_ref,
                )
            )
            continue
        if evidence.status is not EvidenceStatus.VERIFIED:
            reasons.append(
                CandidateRejectReason(
                    code=CandidateRejectCode.EVIDENCE_NOT_VERIFIED,
                    message="candidate evidence is not verified in the current snapshot",
                    evidence_ref=evidence_ref,
                )
            )
    return tuple(reasons)


def _hard_constraint_reasons(
    candidate: Candidate,
    constraint: Constraint,
) -> tuple[CandidateRejectReason, ...]:
    """评估候选级可判定的硬约束，并把失败转换为结构化原因。"""
    category = constraint.category.casefold()
    if category in {"budget", "budget_max", "price_limit", "max_total_price"}:
        return _price_limit_reasons(candidate, constraint)
    if category in {"currency", "budget_currency"}:
        return _currency_reasons(candidate, constraint)
    if category == "candidate_kind":
        return _text_match_reasons(candidate.kind, constraint, "candidate kind")
    if category in {"transport_mode", "mode"} and isinstance(candidate, TransportCandidate):
        return _text_match_reasons(candidate.mode, constraint, "transport mode")
    if category == "origin" and isinstance(candidate, TransportCandidate):
        return _text_match_reasons(candidate.origin, constraint, "transport origin")
    if category == "destination" and isinstance(candidate, TransportCandidate):
        return _text_match_reasons(candidate.destination, constraint, "transport destination")
    if category in {"hotel_area", "stay_area"} and isinstance(candidate, StayCandidate):
        return _text_match_reasons(candidate.area, constraint, "stay area")
    if category in {"place_category", "category"} and isinstance(candidate, PlaceCandidate):
        return _text_match_reasons(candidate.category, constraint, "place category")
    if category == "context_type" and isinstance(candidate, ContextCandidate):
        return _text_match_reasons(candidate.context_type, constraint, "context type")
    if category in {"exclude_tag", "exclusion"}:
        return _excluded_tag_reasons(candidate, constraint)
    if category in {"date", "date_range"}:
        return _date_range_reasons(candidate, constraint)
    return ()


def _price_limit_reasons(
    candidate: Candidate,
    constraint: Constraint,
) -> tuple[CandidateRejectReason, ...]:
    """按总价和币种执行候选级预算上限剪枝。"""
    if candidate.price is None:
        return (_missing_constraint_data(constraint, "candidate total price is required"),)
    if not isinstance(constraint.normalized_value, Money):
        return (_missing_constraint_data(constraint, "hard price limit must use Money"),)
    if candidate.price.total.currency != constraint.normalized_value.currency:
        return (_violation(constraint, "candidate price currency does not match hard limit"),)
    if candidate.price.total.amount > constraint.normalized_value.amount:
        return (_violation(constraint, "candidate total price exceeds hard limit"),)
    return ()


def _currency_reasons(
    candidate: Candidate,
    constraint: Constraint,
) -> tuple[CandidateRejectReason, ...]:
    """要求可定价候选使用指定的硬约束币种。"""
    if candidate.price is None:
        return (_missing_constraint_data(constraint, "candidate total price is required"),)
    values = _constraint_strings(constraint)
    if len(values) != 1:
        return (_missing_constraint_data(constraint, "hard currency must contain one code"),)
    if candidate.price.total.currency.casefold() != values[0]:
        return (_violation(constraint, "candidate price currency violates hard currency"),)
    return ()


def _text_match_reasons(
    actual: str,
    constraint: Constraint,
    label: str,
) -> tuple[CandidateRejectReason, ...]:
    """把文本或文本集合硬约束匹配到候选字段。"""
    values = _constraint_strings(constraint)
    if not values:
        return (_missing_constraint_data(constraint, f"hard {label} must contain text"),)
    if actual.casefold() not in values:
        return (_violation(constraint, f"candidate {label} violates hard constraint"),)
    return ()


def _excluded_tag_reasons(
    candidate: Candidate,
    constraint: Constraint,
) -> tuple[CandidateRejectReason, ...]:
    """拒绝带有显式排除标签的候选。"""
    excluded = set(_constraint_strings(constraint))
    if not excluded:
        return (_missing_constraint_data(constraint, "hard exclusion must contain text"),)
    if set(candidate.tags).intersection(excluded):
        return (_violation(constraint, "candidate contains an excluded tag"),)
    return ()


def _date_range_reasons(
    candidate: Candidate,
    constraint: Constraint,
) -> tuple[CandidateRejectReason, ...]:
    """检查交通和住宿候选的可验证时间窗口是否落在硬日期范围内。"""
    date_range = _constraint_date_range(constraint)
    if date_range is None:
        return (
            _missing_constraint_data(
                constraint, "hard date constraint must use date or DateRange"
            ),
        )
    if isinstance(candidate, TransportCandidate):
        if candidate.departure_at is None or candidate.arrival_at is None:
            return (_missing_constraint_data(constraint, "transport schedule is required"),)
        values = (candidate.departure_at.date(), candidate.arrival_at.date())
    elif isinstance(candidate, StayCandidate):
        if candidate.check_in is None or candidate.check_out is None:
            return (_missing_constraint_data(constraint, "stay window is required"),)
        values = (candidate.check_in.date(), candidate.check_out.date())
    else:
        return ()
    if any(value < date_range.start or value > date_range.end for value in values):
        return (_violation(constraint, "candidate time window violates hard date range"),)
    return ()


def _constraint_strings(constraint: Constraint) -> tuple[str, ...]:
    """提取可用于候选字段匹配的标准化文本集合。"""
    value = constraint.normalized_value
    if isinstance(value, str):
        return (value.casefold(),)
    if isinstance(value, tuple) and all(isinstance(item, str) for item in value):
        return tuple(item.casefold() for item in value)
    return ()


def _constraint_date_range(constraint: Constraint) -> DateRange | None:
    """把单日或日期范围硬约束统一为 DateRange。"""
    value = constraint.normalized_value
    if isinstance(value, DateRange):
        return value
    if isinstance(value, date):
        return DateRange(start=value, end=value)
    return None


def _violation(constraint: Constraint, message: str) -> CandidateRejectReason:
    """构造已判定违反硬约束的拒绝原因。"""
    return CandidateRejectReason(
        code=CandidateRejectCode.HARD_CONSTRAINT_VIOLATION,
        message=message,
        constraint_ref=constraint.id,
    )


def _missing_constraint_data(constraint: Constraint, message: str) -> CandidateRejectReason:
    """构造因候选或约束数据不足而无法通过硬约束的拒绝原因。"""
    return CandidateRejectReason(
        code=CandidateRejectCode.HARD_CONSTRAINT_DATA_MISSING,
        message=message,
        constraint_ref=constraint.id,
    )
