"""不依赖磁盘 IO 的 InMemory 状态仓储。"""

from __future__ import annotations

from threading import RLock
from uuid import uuid4

from src.domain.models.checkpoint import Checkpoint
from src.domain.models.state import TripState
from src.domain.models.value_objects import TripId
from src.domain.state_repository_errors import StateConflictError, StateNotFoundError


class InMemoryStateRepository:
    """使用实例级存储和锁实现的状态仓储。"""

    def __init__(self, *, max_checkpoints_per_trip: int = 3) -> None:
        if max_checkpoints_per_trip < 1:
            raise ValueError("max_checkpoints_per_trip must be at least 1")
        self._max_checkpoints_per_trip = max_checkpoints_per_trip
        self._states: dict[TripId, TripState] = {}
        self._checkpoints: dict[TripId, list[Checkpoint]] = {}
        self._lock = RLock()

    def create(self, state: TripState) -> TripState:
        """创建状态并拒绝覆盖已有旅行。"""
        with self._lock:
            existing = self._states.get(state.trip_id)
            if existing is not None:
                raise StateConflictError(state.trip_id, 0, existing.version)
            self._states[state.trip_id] = self._copy_state(state)
            return self._copy_state(state)

    def get(self, trip_id: TripId) -> TripState:
        """读取状态的独立副本。"""
        with self._lock:
            state = self._states.get(trip_id)
            if state is None:
                raise StateNotFoundError(trip_id)
            return self._copy_state(state)

    def save(self, state: TripState, expected_version: int) -> TripState:
        """按期望版本原子保存状态，并要求版本严格递增一位。"""
        if expected_version < 1:
            raise ValueError("expected_version must be at least 1")
        if state.version != expected_version + 1:
            raise ValueError("state.version must equal expected_version + 1")

        with self._lock:
            current = self._states.get(state.trip_id)
            if current is None:
                raise StateNotFoundError(state.trip_id)
            if current.version != expected_version:
                raise StateConflictError(state.trip_id, expected_version, current.version)
            self._states[state.trip_id] = self._copy_state(state)
            return self._copy_state(state)

    def checkpoint(self, trip_id: TripId) -> Checkpoint:
        """保存当前状态快照，并按配置淘汰最早的快照。"""
        with self._lock:
            state = self._states.get(trip_id)
            if state is None:
                raise StateNotFoundError(trip_id)
            checkpoint = Checkpoint(
                checkpoint_id=f"checkpoint-{uuid4().hex}",
                trip_id=trip_id,
                state=self._copy_state(state),
            )
            checkpoints = self._checkpoints.setdefault(trip_id, [])
            checkpoints.append(checkpoint)
            del checkpoints[:-self._max_checkpoints_per_trip]
            return self._copy_checkpoint(checkpoint)

    def list_checkpoints(self, trip_id: TripId) -> tuple[Checkpoint, ...]:
        """按创建顺序返回 Checkpoint 的独立副本。"""
        with self._lock:
            if trip_id not in self._states:
                raise StateNotFoundError(trip_id)
            return tuple(self._copy_checkpoint(item) for item in self._checkpoints.get(trip_id, ()))

    @staticmethod
    def _copy_state(state: TripState) -> TripState:
        """深拷贝状态，隔离仓储内部与调用者。"""
        return state.model_copy(deep=True)

    @staticmethod
    def _copy_checkpoint(checkpoint: Checkpoint) -> Checkpoint:
        """深拷贝 Checkpoint，避免快照被调用者旁路修改。"""
        return checkpoint.model_copy(deep=True)

