"""旅行状态 Checkpoint 契约。"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict

from src.domain.models.state import TripState
from src.domain.models.value_objects import CheckpointId, TripId


class Checkpoint(BaseModel):
    """可恢复的不可变旅行状态快照。"""

    model_config = ConfigDict(extra="forbid", frozen=True)

    checkpoint_id: CheckpointId
    trip_id: TripId
    state: TripState

