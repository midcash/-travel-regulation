"""Evidence Registry 存储 Port。"""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from src.domain.models.evidence import EvidenceItem, EvidenceRegistration
from src.domain.models.value_objects import StableId


@runtime_checkable
class EvidenceRepository(Protocol):
    """为标准化证据提供确定性注册和检索接口。"""

    def register(self, registration: EvidenceRegistration) -> EvidenceItem:
        """分配稳定 ID 并持久化一条标准化事实。"""

    def find(
        self,
        *,
        entity_id: StableId | None = None,
        fact_type: str | None = None,
        query_fingerprint: StableId | None = None,
    ) -> tuple[EvidenceItem, ...]:
        """返回同时满足所有已提供筛选条件的已注册证据。"""
