"""
State Store — 全局工作流状态管理。
仅 Workflow Engine 可写，Agent 通过 AgentContext 只读上游数据。
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from pydantic import BaseModel


# ============================================================
# WorkflowState — 全局状态容器（Pydantic，仅 Engine 可写）
# ============================================================

class WorkflowState(BaseModel):
    """全局工作流状态。Agent 不可直接写，由 Workflow Engine 统一写。"""

    session_id: str = ""
    user_input: str = ""
    analyzed_req: dict = {}
    plan: dict | None = None
    knowledge_data: dict | None = None
    refined_plan: dict | None = None
    review_result: dict | None = None
    retry_count: int = 0
    retry_history: list[dict] = []
    checkpoints: list[dict] = []  # 状态快照（model_dump），保留最近 3 个
    negation_constraints: list[str] = []  # 🛡️ Phase 1 Negation Guard 提取的硬约束


# ============================================================
# AgentContext — 传给 Agent 的上下文（只暴露必要数据）
# ============================================================

@dataclass
class AgentContext:
    """传给 Agent 的上下文。只包含该 Agent 需要的数据，不含完整 state。"""

    session_id: str
    user_input: str
    upstream_data: dict     # 上一个 Agent 的输出
    retry_context: dict | None = None  # reviewer 的反馈（重试时）
    negation_constraints: list[str] | None = None  # 🛡️ Phase 1 Negation Guard

    def __post_init__(self):
        if self.negation_constraints is None:
            self.negation_constraints = []


# ============================================================
# AgentResult — Agent 返回结果
# ============================================================

@dataclass
class AgentResult:
    """Agent 返回结果。Engine 据此裁决下一步并写入 State Store。"""

    agent: str
    data: dict              # Agent 产出的结构化数据
    success: bool = True
    error: str | None = None
