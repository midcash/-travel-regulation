# Gate Definitions — 质量门定义

---

## 1. 概述

质量门是镶嵌在 Agent 工作流中的自动化质量检查关卡。每个 Gate 有明确的触发时机、输入、通过条件和失败处理策略。

> **当前项目映射**: 当前分支 (`feat/hackathon-rewrite`) 的 Gate 逻辑**内嵌在 orchestrator LLM prompt 中**，而非独立 `GateRunner` 执行。Gate 0 对应 prompt 中的输入解析、Gate 1 对应 KnowledgeAgent 验证、Gate 2 对应 ReviewerAgent 评分（≥70 阈值）、Gate 3 暂未实现。下方 Python 伪代码引用的 `GateRunner`/`StructuredRequest`/`SharedContext` 等组件为后续状态机优化的参考设计。

---

## 2. Gate 0: 输入校验

### 2.1 定义

| 属性 | 值 |
|------|-----|
| Gate ID | 0 |
| 名称 | 输入校验 (Input Validation) |
| 触发时机 | 用户输入被解析为 StructuredRequest 后 |
| 阻断级别 | **阻断** (blocking) |
| 负责执行 | Orchestrator (本地校验) |

### 2.2 检查项

| 检查项 | 规则 | 严重级别 |
|--------|------|---------|
| 目的地 | 非空，可映射到地理实体 | blocking |
| 出发日期 | 非空，在未来，格式 YYYY-MM-DD | blocking |
| 返回日期 | 非空，≥ 出发日期 | blocking |
| 预算 | > 0 | blocking |
| 人数 | ≥ 1（默认 1） | warning |
| 偏好标签 | 有则校验是否在已知标签列表中 | warning |

### 2.3 判定逻辑

```python
def gate_0_check(request: StructuredRequest) -> GateResult:
    issues = []

    if not request.destination:
        issues.append(BlockingIssue("目的地不能为空"))
    if not request.dates.arrival or request.dates.arrival < today:
        issues.append(BlockingIssue("出发日期无效或已过"))
    if not request.dates.departure or request.dates.departure < request.dates.arrival:
        issues.append(BlockingIssue("返回日期无效或早于出发日期"))
    if request.budget.total <= 0:
        issues.append(BlockingIssue("预算必须大于0"))

    if request.travelers.adults < 1:
        issues.append(Warning("人数已自动设为1"))

    return GateResult(
        gate_id=0,
        passed=len([i for i in issues if i.type == "blocking"]) == 0,
        blocking_issues=[i for i in issues if i.type == "blocking"],
        warnings=[i for i in issues if i.type == "warning"]
    )
```

### 2.4 失败处理
- 必填项缺失 → 追问用户（最多2轮）
- 日期无效 → 提示用户重新输入
- 预算 ≤ 0 → 提示用户输入合理预算
- 2 轮追问后仍不完整 → 拒绝请求，返回错误说明

---

## 3. Gate 1: 可行性检查

### 3.1 定义

| 属性 | 值 |
|------|-----|
| Gate ID | 1 |
| 名称 | 可行性检查 (Feasibility Check) |
| 触发时机 | KnowledgeAgent 完成校验后 |
| 阻断级别 | **阻断** (blocking) |
| 负责执行 | GateRunner (读取 ValidationReport) |

### 3.2 检查项

| 检查项 | 规则 | 严重级别 |
|--------|------|---------|
| blocking_issues 数量 | 必须 = 0 | blocking |
| price 异常项数量 | ≤ 3（且无 high severity） | warning |
| time 冲突数量 | ≤ 2 | warning |
| detour 数量 | ≤ 1 | warning |
| 硬约束违反 | 0 | blocking |

### 3.3 判定逻辑

```python
def gate_1_check(validation: ValidationReport) -> GateResult:
    blocking = []
    warnings = []

    if validation.constraint_check.blocking_issues:
        for issue in validation.constraint_check.blocking_issues:
            blocking.append(BlockingIssue(f"硬约束违反: {issue.constraint}"))

    if validation.summary.blocking_count > 0:
        blocking.append(BlockingIssue(f"共 {validation.summary.blocking_count} 个阻断问题"))

    if validation.summary.warning_count > 0:
        warnings.append(Warning(f"共 {validation.summary.warning_count} 个警告"))

    return GateResult(
        gate_id=1,
        passed=len(blocking) == 0,
        blocking_issues=blocking,
        warnings=warnings
    )
```

### 3.4 失败处理
- 硬约束违反 → 退回 PlannerAgent 修订（连同 Execution 的 fix_suggestion）
- 价格异常 → 不阻断，但记录到 warnings（由 Gate 2 综合评判）
- 第一次失败 → 修订后重试
- 连续失败 → 进入 Gate 2 降级流程

---

## 4. Gate 2: 质量评审

### 4.1 定义

| 属性 | 值 |
|------|-----|
| Gate ID | 2 |
| 名称 | 质量评审 (Quality Review) |
| 触发时机 | ReviewerAgent 完成评估后 |
| 阻断级别 | **条件阻断** (conditional blocking) |
| 负责执行 | GateRunner (读取 PlanQualityReport) |

### 4.2 检查项

**综合评分**:

| 检查项 | 规则 | 严重级别 |
|--------|------|---------|
| composite_score | ≥ 80 | blocking (条件) |

**维度级评分** (来自 plan_quality_rubric，1-5 分制):

| 维度 | 缩写 | 警告阈值 | 警告升级规则 |
|------|------|---------|-------------|
| 完整性 (Completeness) | COM | < 3 | 任意维度 < 3 → Warning |
| 可行性 (Feasibility) | FEA | < 3 | ≥ 3 个维度有 Warning → 升级为 blocking |
| 约束满足度 (Constraint Satisfaction) | CON | < 3 | — |
| 体验质量 (Experience Quality) | EXP | < 3 | — |
| 信息准确度 (Information Accuracy) | ACC | < 3 | — |

### 4.3 判定逻辑

```python
def gate_2_check(quality_report: PlanQualityReport, iteration: int) -> GateResult:
    # === Phase 1: 维度级检查 ===
    DIMENSION_THRESHOLD = 3       # 低于 3 分 (1-5 制) 触发警告
    DIM_ESCALATION_COUNT = 3      # ≥ 3 个维度告警时升级为阻断

    dim_scores = {
        "COM": quality_report.dimensions.completeness,
        "FEA": quality_report.dimensions.feasibility,
        "CON": quality_report.dimensions.constraint_satisfaction,
        "EXP": quality_report.dimensions.experience_quality,
        "ACC": quality_report.dimensions.information_accuracy,
    }

    dim_warnings = []
    for name, score in dim_scores.items():
        if score < DIMENSION_THRESHOLD:
            dim_warnings.append(Warning(
                f"维度 [{name}] 得分 {score} < {DIMENSION_THRESHOLD}，存在结构性缺陷"
            ))

    dim_escalated = len(dim_warnings) >= DIM_ESCALATION_COUNT
    if dim_escalated:
        dim_blocking = BlockingIssue(
            f"{len(dim_warnings)} 个维度得分低于 {DIMENSION_THRESHOLD}，方案结构性缺陷严重"
        )

    # === Phase 2: 综合评分判定 ===

    # 综合 ≥ 80 但维度升级: 阻断，需针对性修订
    if quality_report.composite_score >= 80 and dim_escalated:
        return GateResult(
            gate_id=2, passed=False,
            blocking_issues=[dim_blocking],
            warnings=dim_warnings,
            revision_feedback=f"综合分达标但 {len(dim_warnings)} 个维度严重偏低，需针对性修订"
        )

    # 综合 ≥ 80 且无维度升级: 通过 (维度告警附在 warnings 中)
    if quality_report.composite_score >= 80:
        return GateResult(
            gate_id=2, passed=True,
            warnings=dim_warnings if dim_warnings else None
        )

    # 得分 < 60: 无论第几轮，标记为 REJECT
    if quality_report.composite_score < 60:
        return GateResult(
            gate_id=2,
            passed=False,
            rejected=True,
            blocking_issues=[BlockingIssue(
                f"综合得分 {quality_report.composite_score} < 60，严重缺陷，建议重新规划而非修订"
            )],
            warnings=dim_warnings
        )

    if iteration >= 3:
        # 得分 60-79 且达到最大迭代次数: 降级通过
        all_warnings = dim_warnings + [
            Warning(f"已达最大迭代次数({iteration}/3)，降级输出")
        ]
        return GateResult(
            gate_id=2,
            passed=True,  # 强制通过但降级
            degraded=True,
            warnings=all_warnings
        )

    # 得分 60-79 且未达迭代上限: 发送修订反馈
    return GateResult(
        gate_id=2,
        passed=False,
        blocking_issues=[BlockingIssue(
            f"综合得分 {quality_report.composite_score} < 80，需修订"
        )],
        warnings=dim_warnings,
        revision_feedback=quality_report.revision_feedback
    )
```

### 4.4 失败处理
- **维度升级 (≥3 维度 < 3)**: 即使综合分 ≥ 80 也阻断，反馈中标注低分维度，退回 Planning 针对性修订
- **第 1-2 轮不通过**: 将 revision_feedback 发送给 PlannerAgent 修订
- **第 3 轮不通过**: 停止迭代，降级输出（`degraded: true`），标注未满足项
- **得分 < 60**: 无论第几轮，标记为 REJECT，建议重新规划而非修订

---

## 5. Gate 3: 最终校验

### 5.1 定义

| 属性 | 值 |
|------|-----|
| Gate ID | 3 |
| 名称 | 最终校验 (Final Validation) |
| 触发时机 | Orchestrator 整合完成后，最终输出前 |
| 阻断级别 | **阻断** (blocking) |
| 负责执行 | GateRunner |

### 5.2 检查项

| 检查项 | 规则 | 严重级别 |
|--------|------|---------|
| 结构完整性 | 包含 transportation + accommodation + daily_itinerary + budget_breakdown | blocking |
| 每日行程 | 每天 ≥ 2 个活动 | blocking |
| 每餐推荐 | 每天 ≥ 2 餐推荐 | blocking |
| 预算合计 | budget_breakdown 各项之和 ≤ total_budget | blocking |
| 质量报告附件 | quality_report 已附加 | blocking |
| 格式合规 | JSON Schema 校验通过 | blocking |
| 无空值 | 所有必填字段非 null | blocking |
| degraded 标记 | 若降级，必须标注 degraded_reason | blocking |

### 5.3 判定逻辑

```python
def gate_3_check(final_plan: FinalTravelPlan) -> GateResult:
    schema = load_schema("final_travel_plan")
    errors = validate_json(final_plan, schema)

    issues = []
    if errors:
        for e in errors:
            issues.append(BlockingIssue(f"格式错误: {e}"))

    if not final_plan.transportation:
        issues.append(BlockingIssue("缺少交通方案"))
    if not final_plan.accommodation:
        issues.append(BlockingIssue("缺少住宿方案"))
    if not final_plan.daily_itinerary:
        issues.append(BlockingIssue("缺少每日行程"))

    for day in final_plan.daily_itinerary:
        if len(day.activities) < 2:
            issues.append(BlockingIssue(f"第{day.day}天活动不足(至少2个)"))
        meals_count = sum(1 for m in [day.meals.breakfast, day.meals.lunch, day.meals.dinner] if m)
        if meals_count < 2:
            issues.append(BlockingIssue(f"第{day.day}天餐食推荐不足(至少2餐)"))

    total_allocated = sum(final_plan.budget_breakdown.values())
    if total_allocated > final_plan.summary.total_budget:
        issues.append(BlockingIssue(f"预算分配超支: {total_allocated} > {final_plan.summary.total_budget}"))

    if not final_plan.quality_report:
        issues.append(BlockingIssue("缺少质量报告"))

    if final_plan.summary.get("degraded") and not final_plan.summary.get("degraded_reason"):
        issues.append(BlockingIssue("降级输出缺少降级原因"))

    return GateResult(
        gate_id=3,
        passed=len(issues) == 0,
        blocking_issues=issues
    )
```

### 5.4 失败处理
- 格式不合规 → 自动格式化修复
- 内容缺失 → 自动补占位符 + 标注 `auto_filled: true`
- 预算超支 → 必须人工修订（不可自动处理）
- 多次失败 → 记录错误详情到日志，标记为 FAILED

---

## 6. Gate 执行流程总览

```
User Request
    │
    ▼
[Gate 0] ── FAIL → 追问用户 / 拒绝
    │ PASS
    ▼
Orchestrator 分解 → KnowledgeAgent（可行性验证）→ PlannerAgent（生成方案）
    │
    ▼
[Gate 1] ── FAIL → 退回 Planner 修订 (带 fix_suggestions)
    │ PASS
    ▼
ReviewerAgent（质量评审）
    │
    ▼
[Gate 2] ── FAIL (维度升级)  → 退回 Planning 针对性修订
    │      ── FAIL (第1-2轮) → 退回 Planner 修订 (带 revision_feedback)
    │      ── FAIL (第3轮)   → 降级输出
    │ PASS
    ▼
Orchestrator 整合
    │
    ▼
[Gate 3] ── FAIL → 自动修复 (格式/补全) 或 拒绝 (预算超支)
    │ PASS
    ▼
Final Output
```

---

## 7. GateRunner 规格 [FUTURE — 当前分支未实现]

```python
class GateRunner:
    """质量门执行器"""

    def __init__(self, context: SharedContext):
        self.context = context
        self.gate_log: List[GateResult] = []

    async def run_gate_0(self, request: StructuredRequest) -> GateResult: ...
    async def run_gate_1(self, validation: ValidationReport) -> GateResult: ...
    async def run_gate_2(self, quality_report: PlanQualityReport, iteration: int) -> GateResult: ...
    async def run_gate_3(self, final_plan: FinalTravelPlan) -> GateResult: ...

    def get_gate_history(self) -> List[GateResult]:
        """返回所有 Gate 执行历史"""
        return self.gate_log

    def all_passed(self) -> bool:
        """检查是否所有 Gate 都通过"""
        return all(g.passed for g in self.gate_log)
```

---

## 8. 变更日志

| 版本 | 日期 | 变更 |
|------|------|------|
| 1.0.0 | 2026-07-05 | 初始版本，Gate 0-3 完整定义；Gate 2 包含维度级告警检查（5维度 < 3 触发 Warning，≥3 维度告警升级为 blocking） |
