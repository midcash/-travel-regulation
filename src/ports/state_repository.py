"""旅行状态仓储 Port。"""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from src.domain.models.checkpoint import Checkpoint
from src.domain.models.state import TripState
from src.domain.models.value_objects import TripId


@runtime_checkable
class StateRepository(Protocol):
    """为状态存储实现提供的最小接口。"""

    def create(self, state: TripState) -> TripState:
        """创建一个旅行状态。"""

    def get(self, trip_id: TripId) -> TripState:
        """读取指定旅行的当前状态。"""

    def save(self, state: TripState, expected_version: int) -> TripState:
        """在版本匹配时保存新的旅行状态。"""

    def checkpoint(self, trip_id: TripId) -> Checkpoint:
        """保存当前状态的 Checkpoint。"""

    def list_checkpoints(self, trip_id: TripId) -> tuple[Checkpoint, ...]:
        """按创建顺序返回旅行的 Checkpoint。"""

