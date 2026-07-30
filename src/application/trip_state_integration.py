"""M2 第九步：将 RouteDecision 集成到不可变 TripState 状态机。"""

from __future__ import annotations

from typing import Final

from src.domain.models.enums import InteractionMode, WorkflowStatus
from src.domain.models.routing import RouteDecision
from src.domain.models.state import TripState

_ROUTE_TARGET_STATUS: Final[dict[InteractionMode, WorkflowStatus]] = {
    InteractionMode.CLARIFY: WorkflowStatus.CLARIFYING,
    InteractionMode.PLAN: WorkflowStatus.RESEARCHING,
    InteractionMode.COMPARE: WorkflowStatus.RESEARCHING,
    InteractionMode.REPLAN: WorkflowStatus.REPLANNING,
}


class TripStateIntegration:
    """把路由结果转换为受白名单保护的 TripState 新快照。"""

    def apply_route_decision(
        self,
        state: TripState,
        decision: RouteDecision,
    ) -> TripState:
        """应用一个路由决策，不执行外部工具或修改传入状态。

        Args:
            state: 当前不可变旅行状态快照。
            decision: InteractionRouter 生成的类型化路由决策。

        Returns:
            TripState: 状态未需推进时返回原快照，否则返回版本递增的新快照。

        Raises:
            TypeError: 输入不是声明的领域契约。
            InvalidStateTransitionError: 路由目标不在当前状态的白名单中。
        """
        if not isinstance(state, TripState):
            raise TypeError("state must be a TripState")
        if not isinstance(decision, RouteDecision):
            raise TypeError("decision must be a RouteDecision")

        mode = InteractionMode(decision.mode)
        target = _ROUTE_TARGET_STATUS.get(mode)
        if target is None or target is state.status:
            return state
        return state.transition_to(target)

    def apply(self, state: TripState, decision: RouteDecision) -> TripState:
        """应用路由决策的简短别名。"""
        return self.apply_route_decision(state, decision)
