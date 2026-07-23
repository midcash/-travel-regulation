"""
DTO 核心枚举 — 全阶段共用类型定义。

依赖: 无（仅依赖 Python stdlib enum）
被引用: retry_context, phase1_dto, phase5_dto, 以及后续所有 DTO
"""
from __future__ import annotations

from enum import Enum


class Verdict(str, Enum):
    """评审裁决（Phase 5 输出）。"""
    EXCELLENT = "EXCELLENT"   # ≥90
    PASS = "PASS"             # 80-89
    REVISE = "REVISE"         # 60-79
    REJECT = "REJECT"         # <60


class TripPurpose(str, Enum):
    """出行目的（驱动场景适配）。"""
    BUSINESS = "商务"
    VACATION = "度假"
    FAMILY = "亲子"
    COUPLE = "情侣"
    RELIGIOUS = "宗教/灵修"
    UNKNOWN = "未知"


class Severity(str, Enum):
    """问题严重度（L1 确定性校验 + L2 语义校验）。"""
    BLOCKING = "blocking"     # 阻断：必须修正
    WARNING = "warning"       # 警告：建议修正
    SUGGESTION = "suggestion" # 建议：可选优化


class TrafficLight(str, Enum):
    """裁决牌色（Phase 5 输出，合并 L1 + L2 结果）。"""
    GREEN = "green"           # 通过，直接交付
    YELLOW = "yellow"         # 有风险但可交付，附警告
    RED = "red"               # 阻断，需重试或澄清


class IntentType(str, Enum):
    """用户意图类型（Phase 1 解析输出）。"""
    TRAVEL = "travel"
    INQUIRY = "inquiry"       # 仅查询（天气/餐厅）
    MODIFY = "modify"         # 修改已有方案
    MIXED = "mixed"           # 混合意图


class PaceMode(str, Enum):
    """行程节奏（Phase 1 推断 + Phase 4 输出）。"""
    RELAXED = "relaxed"       # ≤3 活动/天
    NORMAL = "normal"         # 4-5 活动/天
    INTENSE = "intense"       # >5 活动/天


class ErrorCode(str, Enum):
    """标准化错误码（Phase 3 资源拉取失败时）。"""
    E001_BUDGET_TOO_LOW = "E001"        # 预算不足以覆盖基础资源
    E002_THEME_NO_MATCH = "E002"        # 主题偏好无匹配资源
    E003_SOLD_OUT = "E003"              # 全部售罄
    E004_API_TIMEOUT = "E004"           # 外部 API 超时
    E005_NEGATION_VIOLATION = "E005"    # 否定约束违规
    E006_EMPTY_PLAN = "E006"            # LLM 未生成有效行程
    E007_VALIDATION_FAILED = "E007"     # 确定性校验失败
