"""状态仓储错误契约。"""

from __future__ import annotations

from src.domain.models.value_objects import StableId


class StateConflictError(RuntimeError):
    """状态仓储检测到版本冲突或重复创建时抛出的异常。"""

    def __init__(self, trip_id: StableId, expected_version: int, actual_version: int) -> None:
        self.trip_id = trip_id
        self.expected_version = expected_version
        self.actual_version = actual_version
        super().__init__(
            f"state version conflict for {trip_id}: "
            f"expected {expected_version}, actual {actual_version}"
        )


class StateNotFoundError(LookupError):
    """请求的旅行状态不存在时抛出的异常。"""

    def __init__(self, trip_id: StableId) -> None:
        self.trip_id = trip_id
        super().__init__(f"trip state not found: {trip_id}")

