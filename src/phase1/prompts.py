"""
Phase 1 CoT Prompt 模板 — LLM 意图解析。

当前状态: 模板已定义，暂不实际调用（Step 1.3 中为可选）。
后续接入时通过 orchestrator 调用，产出 Phase1RawOutput。

依赖: src.domain.dtos.phase1_dto.Phase1RawOutput（作为输出 schema 参考）
"""
from __future__ import annotations

# Phase 1 意图解析 CoT prompt（待接入 orchestrator 时使用）
PHASE1_COT_PROMPT: str = """你是一个意图解析器。分析用户输入，提取旅行规划所需的关键信息。

## 推理步骤
1. 识别意图类型：travel（规划行程）/ inquiry（仅查询）/ modify（修改已有方案）/ mixed（混合）
2. 提取目的地和出发地
3. 识别日期范围和天数
4. 提取预算
5. 识别同行人数（默认 1 人）
6. 提取偏好列表（想去什么、喜欢什么、有什么特殊需求）
7. 识别出行目的（商务/度假/亲子/情侣/宗教/未知）
8. 评估信息完整度：列出缺失的关键维度，给出置信度

## 输出 Schema
{
  "intent_type": "travel",
  "destination": "上海",
  "origin": "北京",
  "date_range": "周末",
  "check_in": "2026-07-25",
  "check_out": "2026-07-27",
  "days": 2,
  "budget": 3000,
  "travelers": 1,
  "preferences": ["历史文化", "当地小吃"],
  "trip_purpose": "度假",
  "confidence": 0.9,
  "missing_dimensions": []
}

## 置信度标准
- 0.9-1.0: 信息完整，可直接规划
- 0.8-0.9: 轻微缺失（如未指定出发地），可推断
- 0.6-0.8: 中等缺失（如未指定预算或天数），需要澄清
- <0.6: 严重缺失，必须澄清

## 铁律
- 只输出一行纯 JSON，无 markdown、无解释文字
- 无法确定的字段用 null 或空值，不要编造
- 日期标准化为 YYYY-MM-DD
- 自然语言日期（"周末"、"下周二"）保留在 date_range 字段

## 用户输入
{user_input}"""

# 门禁阈值
GATE_CONFIDENCE_THRESHOLD: float = 0.8
GATE_MAX_MISSING_DIMENSIONS: int = 2
