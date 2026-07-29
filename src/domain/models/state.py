"""TripState 及工作流状态转换契约。"""

from __future__ import annotations

from collections.abc import Mapping
from types import MappingProxyType
from typing import Self

from pydantic import BaseModel, ConfigDict, Field, model_validator

from src.domain.errors import InvalidStateTransitionError, WorkflowErrorPayload
from src.domain.models.constraint import ConstraintSnapshot
from src.domain.models.enums import WorkflowStatus
from src.domain.models.evidence import EvidenceSnapshot
from src.domain.models.trip_request import TripRequest
from src.domain.models.value_objects import SessionId, StableId, TripId

ALLOWED_WORKFLOW_TRANSITIONS: Mapping[WorkflowStatus, frozenset[WorkflowStatus]] = (
    MappingProxyType(
        {
            WorkflowStatus.COLLECTING: frozenset(
                {WorkflowStatus.CLARIFYING, WorkflowStatus.RESEARCHING, WorkflowStatus.FAILED}
            ),
            WorkflowStatus.CLARIFYING: frozenset(
                {WorkflowStatus.COLLECTING, WorkflowStatus.RESEARCHING, WorkflowStatus.FAILED}
            ),
            WorkflowStatus.RESEARCHING: frozenset(
                {WorkflowStatus.DRAFTING, WorkflowStatus.FAILED}
            ),
            WorkflowStatus.DRAFTING: frozenset(
                {WorkflowStatus.VALIDATING, WorkflowStatus.FAILED}
            ),
            WorkflowStatus.VALIDATING: frozenset(
                {
                    WorkflowStatus.REPAIRING,
                    WorkflowStatus.NEEDS_CONFIRMATION,
                    WorkflowStatus.FAILED,
                }
            ),
            WorkflowStatus.REPAIRING: frozenset(
                {
                    WorkflowStatus.RESEARCHING,
                    WorkflowStatus.DRAFTING,
                    WorkflowStatus.VALIDATING,
                    WorkflowStatus.FAILED,
                }
            ),
            WorkflowStatus.NEEDS_CONFIRMATION: frozenset(
                {
                    WorkflowStatus.CONFIRMED,
                    WorkflowStatus.STALE,
                    WorkflowStatus.REPLANNING,
                    WorkflowStatus.FAILED,
                }
            ),
            WorkflowStatus.CONFIRMED: frozenset(
                {WorkflowStatus.STALE, WorkflowStatus.REPLANNING, WorkflowStatus.COMPLETED}
            ),
            WorkflowStatus.STALE: frozenset(
                {WorkflowStatus.REPLANNING, WorkflowStatus.FAILED}
            ),
            WorkflowStatus.REPLANNING: frozenset(
                {WorkflowStatus.RESEARCHING, WorkflowStatus.FAILED}
            ),
            WorkflowStatus.COMPLETED: frozenset(),
            WorkflowStatus.FAILED: frozenset(),
        }
    )
)


class TripState(BaseModel):
    """会话与旅行工作流的不可变状态快照。"""

    model_config = ConfigDict(extra="forbid", frozen=True)

    trip_id: TripId
    session_id: SessionId
    version: int = Field(default=1, ge=1)
    status: WorkflowStatus = WorkflowStatus.COLLECTING
    trip_request: TripRequest | None = None
    constraint_snapshot: ConstraintSnapshot | None = None
    evidence_snapshot: EvidenceSnapshot | None = None
    plan_version: int | None = Field(default=None, ge=1)
    pending_action: StableId | None = None
    last_error: WorkflowErrorPayload | None = None

    @model_validator(mode="after")
    def validate_identity_references(self) -> Self:
        """确保状态标识与已挂载的请求和约束快照一致。"""
        if self.trip_request is not None:
            if self.trip_request.trip_id != self.trip_id:
                raise ValueError("trip_request.trip_id must match trip_id")
            if self.trip_request.session_id != self.session_id:
                raise ValueError("trip_request.session_id must match session_id")
        if (
            self.trip_request is not None
            and self.constraint_snapshot is not None
            and self.constraint_snapshot.request_id != self.trip_request.request_id
        ):
            raise ValueError("constraint_snapshot.request_id must match trip_request")
        return self

    def can_transition_to(self, target: WorkflowStatus) -> bool:
        """判断目标状态是否在当前状态的显式白名单中。"""
        return target in ALLOWED_WORKFLOW_TRANSITIONS[self.status]

    def transition_to(self, target: WorkflowStatus) -> TripState:
        """创建递增版本的新状态，不原地修改当前快照。"""
        if not self.can_transition_to(target):
            raise InvalidStateTransitionError(self.status, target)
        return self.model_copy(update={"status": target, "version": self.version + 1})
