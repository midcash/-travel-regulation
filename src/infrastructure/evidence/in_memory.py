"""Evidence Registry 的内存实现。"""

from __future__ import annotations

import hashlib
import json
from decimal import Decimal
from threading import RLock

from src.domain.models.enums import EvidenceStatus
from src.domain.models.evidence import (
    EvidenceItem,
    EvidenceRegistration,
    EvidenceSnapshot,
    EvidenceSnapshotQuery,
    EvidenceTtlPolicy,
)
from src.domain.models.value_objects import EvidenceId, StableId
from src.obs.metric import record_evidence_snapshot
from src.ports.clock import Clock


class InMemoryEvidenceRepository:
    """按确定性标识保存证据，并构建带 TTL 的当前快照。"""

    def __init__(self, *, clock: Clock, ttl_policy: EvidenceTtlPolicy) -> None:
        """注入时间来源和显式 TTL 策略，避免隐式实时判断。"""
        if not isinstance(clock, Clock):
            raise TypeError("clock must implement Clock")
        if not isinstance(ttl_policy, EvidenceTtlPolicy):
            raise TypeError("ttl_policy must be an EvidenceTtlPolicy instance")

        self._clock = clock
        self._ttl_policy = ttl_policy
        self._items: dict[EvidenceId, EvidenceItem] = {}
        self._lock = RLock()

    def register(self, registration: EvidenceRegistration) -> EvidenceItem:
        """幂等注册证据，且不覆盖其他来源的记录。"""
        if not isinstance(registration, EvidenceRegistration):
            raise TypeError("registration must be an EvidenceRegistration instance")

        effective_registration = registration.model_copy(
            update={
                "valid_until": self._ttl_policy.valid_until_for(
                    category=registration.ttl_category,
                    observed_at=registration.observed_at,
                    provider_valid_until=registration.valid_until,
                )
            }
        )
        evidence = effective_registration.to_item(_evidence_id(registration))
        with self._lock:
            existing = self._items.get(evidence.evidence_id)
            if existing is None:
                self._items[evidence.evidence_id] = self._copy_evidence(evidence)
                existing = evidence
            return self._copy_evidence(existing)

    def find(
        self,
        *,
        entity_id: StableId | None = None,
        fact_type: str | None = None,
        query_fingerprint: StableId | None = None,
    ) -> tuple[EvidenceItem, ...]:
        """按注册顺序返回匹配项，不执行策略过滤。"""
        with self._lock:
            return tuple(
                self._copy_evidence(evidence)
                for evidence in self._items.values()
                if (entity_id is None or evidence.entity_id == entity_id)
                and (fact_type is None or evidence.fact_type == fact_type)
                and (
                    query_fingerprint is None
                    or evidence.query_fingerprint == query_fingerprint
                )
            )

    def snapshot(self, query: EvidenceSnapshotQuery) -> EvidenceSnapshot:
        """基于同一 Clock 时刻计算证据新鲜度、冲突和完整性。"""
        if not isinstance(query, EvidenceSnapshotQuery):
            raise TypeError("query must be an EvidenceSnapshotQuery instance")

        now = self._clock.now()
        if now.tzinfo is None:
            raise ValueError("clock must return timezone-aware datetime")

        with self._lock:
            selected = tuple(
                self._copy_evidence(evidence)
                for evidence in self._items.values()
                if (query.entity_id is None or evidence.entity_id == query.entity_id)
                and (query.fact_type is None or evidence.fact_type == query.fact_type)
                and (
                    query.query_fingerprint is None
                    or evidence.query_fingerprint == query.query_fingerprint
                )
            )

        stale_ids = {
        evidence.evidence_id
        for evidence in selected
        if evidence.status is EvidenceStatus.STALE
        or evidence.valid_until is None
        or evidence.valid_until <= now
        }
        conflict_ids = _conflicting_evidence_ids(selected, stale_ids)
        snapshot_items = tuple(
            evidence.model_copy(
                update={
                    "status": _snapshot_status(
                        evidence=evidence,
                        stale_ids=stale_ids,
                        conflict_ids=conflict_ids,
                    )
                }
            )
            for evidence in selected
        )
        missing_fact_types = _missing_fact_types(snapshot_items, query.required_fact_types)
        coverage = _coverage(snapshot_items, query.required_fact_types)
        freshness = _freshness(snapshot_items)
        conflict_refs = tuple(
            evidence.evidence_id
            for evidence in snapshot_items
            if evidence.evidence_id in conflict_ids
        )
        snapshot = EvidenceSnapshot(
            snapshot_id=_snapshot_id(
                created_at=now,
                query=query,
                evidence_items=snapshot_items,
                coverage=coverage,
                freshness=freshness,
                conflict_refs=conflict_refs,
                missing_fact_types=missing_fact_types,
            ),
            created_at=now,
            evidence_items=snapshot_items,
            coverage=coverage,
            freshness=freshness,
            conflict_refs=conflict_refs,
            missing_fact_types=missing_fact_types,
        )
        record_evidence_snapshot(
            statuses=tuple(item.status.value for item in snapshot.evidence_items),
            coverage=float(snapshot.coverage),
            freshness=float(snapshot.freshness),
            conflict_count=len(snapshot.conflict_refs),
            missing_count=len(snapshot.missing_fact_types),
        )
        return snapshot

    @staticmethod
    def _copy_evidence(evidence: EvidenceItem) -> EvidenceItem:
        """隔离调用方与仓储内部保存的值。"""
        return evidence.model_copy(deep=True)


def _evidence_id(registration: EvidenceRegistration) -> EvidenceId:
    """从完整的规范化注册内容派生可复现 ID。"""
    canonical = json.dumps(
        registration.model_dump(mode="json"),
        ensure_ascii=True,
        separators=(",", ":"),
        sort_keys=True,
    )
    digest = hashlib.sha256(canonical.encode("utf-8")).hexdigest()
    return f"evidence:{digest}"


def _conflicting_evidence_ids(
    evidence_items: tuple[EvidenceItem, ...],
    stale_ids: set[EvidenceId],
) -> set[EvidenceId]:
    """找出当前有效范围内、同一事实但值不一致的来源。"""
    groups: dict[tuple[str, str, str], list[EvidenceItem]] = {}
    conflict_ids = {
        evidence.evidence_id
        for evidence in evidence_items
        if evidence.status is EvidenceStatus.CONFLICTING
        and evidence.evidence_id not in stale_ids
    }
    for evidence in evidence_items:
        if evidence.evidence_id in stale_ids or evidence.status is EvidenceStatus.UNAVAILABLE:
            continue
        key = (evidence.entity_id, evidence.fact_type, evidence.query_fingerprint)
        groups.setdefault(key, []).append(evidence)

    for group in groups.values():
        if len({_canonical_value(evidence) for evidence in group}) > 1:
            conflict_ids.update(evidence.evidence_id for evidence in group)
    return conflict_ids


def _canonical_value(evidence: EvidenceItem) -> str:
    """将类型化事实值规范化为可比较的确定性表示。"""
    return json.dumps(
        evidence.value.model_dump(mode="json")
        if hasattr(evidence.value, "model_dump")
        else evidence.value,
        ensure_ascii=True,
        separators=(",", ":"),
        sort_keys=True,
        default=str,
    )


def _snapshot_status(
    *,
    evidence: EvidenceItem,
    stale_ids: set[EvidenceId],
    conflict_ids: set[EvidenceId],
) -> EvidenceStatus:
    """以过期优先级覆盖注册状态，并保留当前冲突语义。"""
    if evidence.evidence_id in stale_ids:
        return EvidenceStatus.STALE
    if evidence.status is EvidenceStatus.UNAVAILABLE:
        return EvidenceStatus.UNAVAILABLE
    if evidence.evidence_id in conflict_ids:
        return EvidenceStatus.CONFLICTING
    return EvidenceStatus.VERIFIED


def _missing_fact_types(
    evidence_items: tuple[EvidenceItem, ...],
    required_fact_types: tuple[str, ...],
) -> tuple[str, ...]:
    """返回没有任何当前 VERIFIED 证据支撑的要求事实。"""
    verified_fact_types = {
        evidence.fact_type
        for evidence in evidence_items
        if evidence.status is EvidenceStatus.VERIFIED
    }
    return tuple(
        fact_type for fact_type in required_fact_types if fact_type not in verified_fact_types
    )


def _coverage(
    evidence_items: tuple[EvidenceItem, ...],
    required_fact_types: tuple[str, ...],
) -> Decimal:
    """计算要求事实的可用覆盖率，未指定要求时退化为证据可用率。"""
    verified = sum(
        evidence.status is EvidenceStatus.VERIFIED for evidence in evidence_items
    )
    if required_fact_types:
        missing = _missing_fact_types(evidence_items, required_fact_types)
        return Decimal(len(required_fact_types) - len(missing)) / Decimal(
            len(required_fact_types)
        )
    if not evidence_items:
        return Decimal("0")
    return Decimal(verified) / Decimal(len(evidence_items))


def _freshness(evidence_items: tuple[EvidenceItem, ...]) -> Decimal:
    """计算未过期证据在当前快照中的占比。"""
    if not evidence_items:
        return Decimal("0")
    fresh = sum(evidence.status is not EvidenceStatus.STALE for evidence in evidence_items)
    return Decimal(fresh) / Decimal(len(evidence_items))


def _snapshot_id(
    *,
    created_at: object,
    query: EvidenceSnapshotQuery,
    evidence_items: tuple[EvidenceItem, ...],
    coverage: Decimal,
    freshness: Decimal,
    conflict_refs: tuple[EvidenceId, ...],
    missing_fact_types: tuple[str, ...],
) -> StableId:
    """从快照内容派生可复现标识，便于后续版本化和审计。"""
    canonical = json.dumps(
        {
            "created_at": created_at,
            "query": query.model_dump(mode="json"),
            "evidence_items": [item.model_dump(mode="json") for item in evidence_items],
            "coverage": coverage,
            "freshness": freshness,
            "conflict_refs": conflict_refs,
            "missing_fact_types": missing_fact_types,
        },
        ensure_ascii=True,
        separators=(",", ":"),
        sort_keys=True,
        default=str,
    )
    digest = hashlib.sha256(canonical.encode("utf-8")).hexdigest()
    return f"evidence-snapshot:{digest}"
