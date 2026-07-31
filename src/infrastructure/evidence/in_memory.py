"""Evidence Registry 的内存实现。"""

from __future__ import annotations

import hashlib
import json
from threading import RLock

from src.domain.models.evidence import EvidenceItem, EvidenceRegistration
from src.domain.models.value_objects import EvidenceId, StableId


class InMemoryEvidenceRepository:
    """按确定性注册标识存储不可变证据。

    本仓储刻意不判断 TTL、过期状态、冲突或生成快照；这些策略留待 M3
    的下一实现步骤引入。
    """

    def __init__(self) -> None:
        self._items: dict[EvidenceId, EvidenceItem] = {}
        self._lock = RLock()

    def register(self, registration: EvidenceRegistration) -> EvidenceItem:
        """幂等注册证据，且不覆盖其他来源的记录。"""
        if not isinstance(registration, EvidenceRegistration):
            raise TypeError("registration must be an EvidenceRegistration instance")

        evidence = registration.to_item(_evidence_id(registration))
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
