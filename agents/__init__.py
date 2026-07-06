"""agents 包 — 业务 Agent 层。

包含:
- Orchestrator: 主控编排器
- PlanningAgent: 行程规划
- ExecutionAgent: 可行性验证
- EvaluationAgent: 三合一质量评估 (Mode A/B/C)
"""

from agents.orchestrator import Orchestrator
from agents.planning_agent import PlanningAgent
from agents.execution_agent import ExecutionAgent
from agents.evaluation_agent import EvaluationAgent

__version__ = "1.0.0-dev"

__all__ = [
    "Orchestrator",
    "PlanningAgent",
    "ExecutionAgent",
    "EvaluationAgent",
]
