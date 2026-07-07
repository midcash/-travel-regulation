"""修订反馈数据模型。

定义 Reasoning 管线中 StructuredFeedback 子系统所需的数据类型：
- RevisionFeedback：发给 LLM 的结构化修订指令。

注意：此模块的 RevisionFeedback 与 models/entities.py 中的
RevisionFeedback 是不同的类型，服务于不同的管道：
- entities.RevisionFeedback → Evaluation Agent 的通用反馈（维度级）
- feedback.RevisionFeedback → Reasoning 管线的精确修订指令（问题定位级）

v1.2.0 Step 0 — 数据模型先行定义。
来源: progress/handoff.md §12 Phase 0 Step 0
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Dict

if TYPE_CHECKING:
    from models.check import SelfCheckIssue


@dataclass
class RevisionFeedback:
    """发给 LLM 的结构化修订指令。

    替代当前裸 dict 方式传递修订反馈。
    包含精确的问题定位、期望修正值和可执行的修订建议。

    与 entities.RevisionFeedback 的区别：
    - entities.RevisionFeedback: 维度级反馈 (dimension + issue + suggestion)
    - feedback.RevisionFeedback: 问题定位级反馈 (issue: SelfCheckIssue + source)
    """

    issue: SelfCheckIssue
    """具体的违规记录（含类型、定位、实际值、期望值）。"""

    suggestion: str = ""
    """可执行的修订建议（如 '替换为同区域预算内的居酒屋，如 xxx'）。"""

    priority: str = "blocking"
    """优先级：'blocking' | 'warning'。"""

    source: str = "self_check"
    """反馈来源：'self_check' | 'execution_agent' | 'evaluation_agent'。"""

    def to_dict(self) -> Dict[str, Any]:
        """将实例序列化为字典。"""
        return {
            "issue": self.issue.to_dict(),
            "suggestion": self.suggestion,
            "priority": self.priority,
            "source": self.source,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "RevisionFeedback":
        """从字典反序列化。

        注意：issue 字段需要从 dict 重建为 SelfCheckIssue 实例。
        调用方需确保 data['issue'] 可被 SelfCheckIssue 构造函数接受。
        """
        from models.check import IssueType, SelfCheckIssue

        issue_data = data.get("issue", {})
        issue = SelfCheckIssue(
            type=IssueType(issue_data.get("type", "budget_overspend")),
            location=issue_data.get("location", ""),
            actual_value=issue_data.get("actual_value"),
            expected=issue_data.get("expected", ""),
            severity=issue_data.get("severity", "blocking"),
        )
        return cls(
            issue=issue,
            suggestion=data.get("suggestion", ""),
            priority=data.get("priority", "blocking"),
            source=data.get("source", "self_check"),
        )

    def format_for_prompt(self) -> str:
        """将修订反馈转为 LLM 可精确执行的提示文本。

        输出格式示例：
        [BLOCKING] day_2.dinner: 当前=8000, 期望=≤1500.
        建议: 替换为同区域 2500 日元以内的居酒屋，如「鳥貴族」。
        """
        severity_tag = "BLOCKING" if self.priority == "blocking" else "WARNING"
        lines = [
            f"[{severity_tag}] {self.issue.location}: "
            f"当前={self.issue.actual_value}, 期望={self.issue.expected}.",
        ]
        if self.suggestion:
            lines.append(f"建议: {self.suggestion}")
        return "\n".join(lines)
