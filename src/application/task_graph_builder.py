"""M4 第二步：依据路由与约束快照构建受控 Task Graph。"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Final

from src.application.task_graph import TaskGraph, TaskSpec
from src.domain.models.constraint import ConstraintSnapshot
from src.domain.models.enums import InteractionMode
from src.domain.models.routing import RouteDecision
from src.domain.models.value_objects import StableId

MAX_TASKS: Final[int] = 16
_GRAPH_MODES: Final[frozenset[InteractionMode]] = frozenset(
    {
        InteractionMode.PLAN,
        InteractionMode.COMPARE,
        InteractionMode.REFINE,
        InteractionMode.REPLAN,
    }
)
_NON_GRAPH_MODES: Final[frozenset[InteractionMode]] = frozenset(
    {
        InteractionMode.ANSWER,
        InteractionMode.CLARIFY,
        InteractionMode.ACTION,
        InteractionMode.UNSUPPORTED,
    }
)
_RESEARCH_CAPABILITIES: Final[frozenset[str]] = frozenset(
    {"geo", "transport", "place", "stay", "context"}
)
_PLAN_EDIT_CAPABILITIES: Final[frozenset[str]] = frozenset({"plan_refinement", "plan_replanning"})


class TaskGraphBuildError(ValueError):
    """Task Graph 输入不满足 Builder 白名单或前置条件。"""


@dataclass(frozen=True)
class _TaskTemplate:
    """一个受控任务模板，不接受模型或用户直接注入任务定义。"""

    task_type: str
    expected_output_type: str
    timeout: float
    tool_call_budget: int
    model_call_budget: int


_TEMPLATES: Final[dict[str, _TaskTemplate]] = {
    "geo": _TaskTemplate("geo_research", "EvidenceDraft", 60.0, 4, 0),
    "transport": _TaskTemplate("transport_research", "CandidateDraft", 90.0, 6, 0),
    "place": _TaskTemplate("place_research", "CandidateDraft", 90.0, 6, 0),
    "stay": _TaskTemplate("stay_research", "CandidateDraft", 90.0, 6, 0),
    "context": _TaskTemplate("context_research", "EvidenceDraft", 60.0, 4, 1),
    "plan_refinement": _TaskTemplate("plan_refinement", "PlanDelta", 60.0, 0, 1),
    "plan_replanning": _TaskTemplate("plan_replanning", "PlanDelta", 60.0, 0, 1),
}


class TaskGraphValidator:
    """校验 Builder 输出与路由、快照之间的应用层契约。"""

    def validate(
        self,
        graph: TaskGraph,
        route_decision: RouteDecision,
        constraint_snapshot: ConstraintSnapshot,
        *,
        trip_id: StableId,
    ) -> TaskGraph:
        """校验任务图绑定的身份、版本、能力与依赖。"""
        if graph.trip_id != trip_id:
            raise TaskGraphBuildError("task graph trip_id does not match builder input")
        if graph.constraint_snapshot_id != _snapshot_id(constraint_snapshot):
            raise TaskGraphBuildError("task graph is bound to a different constraint snapshot")
        if graph.graph_version != constraint_snapshot.version:
            raise TaskGraphBuildError("task graph version must match constraint snapshot version")

        mode = _mode(route_decision)
        if mode not in _GRAPH_MODES:
            raise TaskGraphBuildError("non-planning route must not produce a task graph")
        allowed = _allowed_capabilities(mode)
        unknown = set(route_decision.required_capabilities).difference(allowed)
        if unknown:
            raise TaskGraphBuildError("route requires unsupported task capability")
        if len(graph.tasks) > MAX_TASKS:
            raise TaskGraphBuildError("task graph exceeds maximum task count")
        task_capabilities = {task.capability for task in graph.tasks}
        if task_capabilities != set(route_decision.required_capabilities):
            raise TaskGraphBuildError("task graph capabilities do not match route decision")
        return graph


class TaskGraphBuilder:
    """将 RouteDecision 的能力白名单确定性地映射为 Task Graph。"""

    def __init__(self, *, validator: TaskGraphValidator | None = None) -> None:
        self._validator = validator or TaskGraphValidator()

    def build(
        self,
        route_decision: RouteDecision,
        constraint_snapshot: ConstraintSnapshot,
        *,
        trip_id: StableId,
    ) -> TaskGraph | None:
        """构建规划任务图；ANSWER 等非规划路由返回 None。"""
        if not isinstance(route_decision, RouteDecision):
            raise TypeError("route_decision must be a RouteDecision")
        if not isinstance(constraint_snapshot, ConstraintSnapshot):
            raise TypeError("constraint_snapshot must be a ConstraintSnapshot")

        mode = _mode(route_decision)
        if mode in _NON_GRAPH_MODES:
            if route_decision.required_capabilities:
                raise TaskGraphBuildError("non-planning route must not require capabilities")
            return None
        if mode not in _GRAPH_MODES:
            raise TaskGraphBuildError("unsupported route mode")

        capabilities = tuple(route_decision.required_capabilities)
        if len(capabilities) != len(set(capabilities)):
            raise TaskGraphBuildError("route capabilities must be unique")
        allowed = _allowed_capabilities(mode)
        unknown = set(capabilities).difference(allowed)
        if unknown:
            raise TaskGraphBuildError("route requires unsupported task capability")

        tasks = _build_tasks(capabilities, route_decision.current_plan_ref)
        if len(tasks) > MAX_TASKS:
            raise TaskGraphBuildError("task graph exceeds maximum task count")
        graph = TaskGraph(
            graph_id=f"graph-{trip_id}-{constraint_snapshot.version}-{mode.value}",
            trip_id=trip_id,
            constraint_snapshot_id=_snapshot_id(constraint_snapshot),
            tasks=tasks,
            graph_version=constraint_snapshot.version,
        )
        return self._validator.validate(
            graph,
            route_decision,
            constraint_snapshot,
            trip_id=trip_id,
        )


def _mode(route_decision: RouteDecision) -> InteractionMode:
    try:
        return InteractionMode(route_decision.mode)
    except ValueError as exc:
        raise TaskGraphBuildError("route decision contains an unsupported mode") from exc


def _allowed_capabilities(mode: InteractionMode) -> frozenset[str]:
    if mode is InteractionMode.REFINE:
        return frozenset({"plan_refinement"})
    if mode is InteractionMode.REPLAN:
        return frozenset({"plan_replanning"})
    return _RESEARCH_CAPABILITIES


def _snapshot_id(snapshot: ConstraintSnapshot) -> str:
    return f"snapshot-{snapshot.request_id}-{snapshot.version}"


def _build_tasks(
    capabilities: tuple[str, ...],
    current_plan_ref: StableId | None,
) -> tuple[TaskSpec, ...]:
    if any(capability in _PLAN_EDIT_CAPABILITIES for capability in capabilities):
        if current_plan_ref is None:
            raise TaskGraphBuildError("plan edit task requires current_plan_ref")
        capability = capabilities[0]
        template = _TEMPLATES[capability]
        return (
            TaskSpec(
                task_id=f"task-{capability}",
                task_type=template.task_type,
                capability=capability,
                input_refs=(current_plan_ref,),
                expected_output_type=template.expected_output_type,
                timeout=template.timeout,
                tool_call_budget=template.tool_call_budget,
                model_call_budget=template.model_call_budget,
            ),
        )

    tasks: list[TaskSpec] = []
    if "geo" in capabilities:
        tasks.append(_task_for("geo"))
    for capability in capabilities:
        if capability == "geo":
            continue
        dependencies = ("task-geo",) if capability in {"transport", "place", "stay"} else ()
        tasks.append(_task_for(capability, dependencies=dependencies))
    return tuple(tasks)


def _task_for(capability: str, *, dependencies: tuple[StableId, ...] = ()) -> TaskSpec:
    template = _TEMPLATES[capability]
    return TaskSpec(
        task_id=f"task-{capability}",
        task_type=template.task_type,
        capability=capability,
        dependencies=dependencies,
        expected_output_type=template.expected_output_type,
        timeout=template.timeout,
        tool_call_budget=template.tool_call_budget,
        model_call_budget=template.model_call_budget,
    )
