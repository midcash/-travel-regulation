# 设计决策文档

> 本文档讲解在旅游规划 Agent 的业务背景下，为何这样设计意图识别和可观测性两个模块。
> 面向读者：接手此项目的开发者，需理解"为什么这么设计"而不仅是"怎么实现"。

---

## 一、意图识别 (Phase 1)：双保险架构

### 1.1 旅游规划的业务特殊性

旅游规划不同于通用 chatbot，它对意图解析有**极高精度要求**：

| 业务场景 | 解析错误的后果 | 严重度 |
|:---|:---|:---|
| "不想去人多的地方" 被理解为 "想去人多的地方" | 行程推荐了网红景点 → 用户直接放弃产品 | 🔴 严重 |
| "出差顺便玩半天" 被理解为 "3天纯玩" | 3天行程塞满出差日 → 计划完全不可用 | 🔴 严重 |
| "预算 500 元周末游三亚" | 系统照常生成行程 → 用户发现钱不够才报错 | 🟡 体验差 |
| "想去暖和的地方发呆" | 无法推断目的地 → 随机推荐可能用户完全不喜欢 | 🟡 浪费 API 调用 |

**核心矛盾**：LLM 擅长语义理解但**对否定词不稳定**（"不要X" 常被当作 "要X"），且**无法区分框架时间和可用时间**（"出差3天其中半天空闲"）。

### 1.2 为什么不用纯 LLM 方案

纯 LLM 方案（直接把用户输入扔给 Planner）有三个致命缺陷：

**缺陷 1：否定词不稳定**

LLM 的注意力机制对否定词（"不要""不想""避免"）天然不敏感。研究表明，在中文旅游场景中，LLM 将否定约束误解为正向偏好的概率约 15-20%。例如：

```
输入: "不要网红店，避免太辣的食物"
纯 LLM: 可能推荐 "网红火锅店"（因为它学会了"网红=热门"的正向关联）
```

**缺陷 2：混合意图无法区分时间框架**

```
输入: "下周二到周四去深圳出差，其中周三下午和晚上有空闲"
纯 LLM: 可能将 3 天全部用于规划旅游活动
实际需求: 只有周三下午+晚上可自由支配，其余时间是工作
```

这是一个**三层信息模型**问题：
- **框架层**：下周二到周四在深圳（整体时间范围）
- **约束层**：出差（时间的80%被锁定）
- **目的层**：科技和创意园区（可用时间内的偏好）

纯 LLM 没有机制分离这三层信息。

**缺陷 3：门禁缺失**

纯 LLM 对模糊输入（"出去玩"）不会主动拒绝或追问，而是强行生成一个泛化行程。用户收到一个"看起来还行"但完全不匹配需求的计划，在后续环节才发现问题 — 浪费了 Planner + Knowledge + Reviewer 的全部 Token。

### 1.3 双保险架构的设计逻辑

```
用户输入
  │
  ├─→ 保险 1: Negation Guard (代码正则, 0ms)
  │     └─→ [negation_constraints]  ← 100% 确定性, 永不漏检
  │
  └─→ 保险 2: CoT LLM (语义解析, ~3-10s)
        └─→ Phase1RawOutput          ← 处理歧义 + 混合意图 + 偏好提取
        │
        └─→ 合并 + 门禁 → Phase1Output
```

**为什么正则先行？**

否定词是**高价值、低复杂度**的信息。16 个中文否定句式（不要/不想/避免/拒绝/讨厌/别/不能/请勿/千万别/切勿/不含/禁止/谢绝/无需/不用/不愿）覆盖了 95%+ 的否定表达，正则提取在 0ms 内完成，且**永远不会漏检**。

正则提取后，否定约束以 `❌ 硬性排除` 指令块注入 Planner prompt。这不是 "建议考虑"，而是 "绝对不得出现" — 规避了 LLM 把否定词当偏好的问题。

**为什么 CoT LLM 后行？**

CoT（Chain-of-Thought）让 LLM 分步骤推理：
1. 先判断 intent_type（travel / inquiry / modify / mixed）
2. 再提取 destination / date_range / budget
3. 最后识别 free_time_slots（混合意图中用户实际可支配时间段）

这个顺序很重要 — **先分类再提取**。如果跳过分类直接提取，混合意图（mixed）会被当作纯旅游（travel）处理，free_time_slots 字段就是空的。

**为什么需要门禁？**

```python
# 门禁条件
needs_clarification = confidence < 0.8 or len(missing_dimensions) > 2
```

| 输入 | confidence | missing | 门禁结果 |
|:---|:---:|:---:|:---|
| "周末北京去上海两天预算3000" | 0.92 | 0 | ✅ 通过 |
| "去泰国曼谷五天不吃生食" | 0.83 | 1 | ✅ 通过 |
| "深圳出发周末找个安静地方" | 0.72 | 1 | 🗣️ 澄清 |
| "出去玩" | 0.35 | 4 | 🗣️ 澄清 |

门禁的**核心价值**不是阻止执行，而是**防止信息不足时浪费下游 Token**。一次 Planner + Knowledge + Reviewer 的完整调用消耗 5-8k Token，如果 Phase 1 就已经知道信息不足，直接进入澄清闭环比盲目规划后再推翻划算得多。

### 1.4 为什么 Phase1Output 是 Pydantic Model 而非 dict

```python
class Phase1Output(BaseModel):
    intent_type: IntentType = IntentType.TRAVEL
    destination: str | None = None
    days: int = 0
    budget: float = 0
    negation_constraints: list[str] = []
    free_time_slots: list[str] = []
    confidence: float = Field(ge=0, le=1)
    ...
```

三个理由：

1. **类型安全**：`budget: float` 不会在某处被误传为 `"三千元"`。Pydantic 在 LLM 输出进入系统的第一时间校验，非法数据在边界就被拦截。

2. **字段级文档**：`Field(description="...")` 是活文档。6 个月后有人修改 CoT prompt 导致 `days` 字段语义变化，Pydantic 的 JSON Schema 导出可以直接对比新旧差异。

3. **门禁逻辑内聚**：`needs_clarification` 作为 `@property` 挂在 `Phase1Output` 上，而不是散落在 orchestrator 里。修改门禁条件只需改一处。

### 1.5 free_time_slots 的业务价值

这是 Phase 1.1 最关键的字段。它解决了旅游规划中一个高频场景：**出差顺游**。

```
输入: "下周二到周四去深圳出差，其中周三下午和晚上有空闲，预算2000"
      ↓
Phase 1 CoT:
  intent_type = "mixed"
  days = 3 (框架时间)
  free_time_slots = ["周三下午", "周三晚上"]  ← 实际可用时间
      ↓
Planner: 只规划周三下午+晚上的活动，周二和周四标注为"出差工作"
Reviewer: 不因 day2/day3 活动少而报 insufficient_activities
```

没有 free_time_slots 时，Planner 看到 `days=3` 会为全部 3 天生成行程；Reviewer 看到 day2/day3 只有 0-1 个活动会报 `insufficient_activities`。一个字段解决了两个模块的误判。

---

## 二、可观测性 (Layer 2)：三层架构

### 2.1 为什么可观测性优先于评估模块

按照原始路线图，第 2 层是评估模块（Validator + SemanticChecker + 绿黄红牌）。调整为可观测性优先，理由是：

| 对比维度 | 先做评估 | 先做可观测性 |
|:---|:---|:---|
| **调试效率** | print() 打点，跨 Phase 关联靠肉眼 | trace_id 串联，jq 一键过滤 |
| **Token 成本可见** | 不知道每次调用花多少 | 模型/Agent/Phase 三级 Token 统计 |
| **瓶颈定位** | "感觉 planner 很慢" | `agent.planner duration_ms=15885` |
| **评估模块开发** | 自己验证自己 | 日志和指标支撑验证 |

一句话总结：**你无法评估你观察不到的东西**。评估模块本身需要日志和指标来验证 — 先建观测基础设施，后建评估逻辑。

### 2.2 为什么是 structlog + OTel + prometheus 三件套

这是 2026 年 LLM Agent 可观测性的行业标准组合：

```
┌──────────────────────────────────────────────┐
│  Metrics (prometheus_client)                  │
│  "有多少请求？多快？花多少钱？"                 │
│  聚合维度：agent × status, model × type       │
├──────────────────────────────────────────────┤
│  Tracing (OpenTelemetry)                      │
│  "这次请求经过哪些步骤？每步多久？"              │
│  层级：session → phase → agent → llm          │
├──────────────────────────────────────────────┤
│  Logging (structlog)                          │
│  "在某个具体时刻发生了什么？"                   │
│  每个事件携带 trace_id，可定位到 Span           │
└──────────────────────────────────────────────┘
```

**为什么不是 print()？**

`print()` 输出是给人看的非结构化文本，structlog 输出是给**工具分析**的 JSON。在旅游规划场景中：

- 一次请求触发 4-6 次 LLM 调用，每次有独立的 Token 消耗和延迟
- 重试时同一 Phase 可能执行 2-3 次
- 需要在日志中区分 "第一次 planner" 和 "重试 planner"

`print()` 无法高效回答这些问题，structlog 的 `trace_id` + `span_id` 可以。

**为什么 structlog 而非标准 logging？**

structlog 的优势在于**处理器链**：

```python
structlog.configure(processors=[
    add_log_level,           # 自动注入 level
    _add_otel_context,       # 自动注入 trace_id/span_id（从 OTel context 读取）
    TimeStamper(fmt="iso"),  # 自动注入时间戳
    JSONRenderer(ensure_ascii=False),  # JSON 序列化
])
```

每个处理器的输入和输出都是 dict，可以自由组合。`_add_otel_context` 是关键 — 它自动从 OTel 的当前 Span 读取 trace_id/span_id 注入每条日志。无需在每个 logger.info() 调用处手动传 trace_id。

**为什么 OpenTelemetry 而非自定义 tracing？**

两个核心收益：

1. **Span 自动嵌套**：Python 的 `contextvars` 在底层传播 Span 上下文。`ask_llm()` 被 `agent.planner` 调用时，无需传任何参数，`gen_ai.chat` 自动成为 `agent.planner` 的子 Span。

2. **零成本迁移到可视化平台**：当前 `ConsoleSpanExporter(out=sys.stderr)` 仅用于开发调试。远期只需改一行：
   ```python
   # 开发 → 生产
   ConsoleSpanExporter(out=sys.stderr)
   → OTLPSpanExporter(endpoint="http://phoenix:4317")
   ```
   所有 `trace_phase()` / `trace_agent()` / `trace_llm_call()` 调用点完全不动。

### 2.3 Span 层级设计：为什么是 session → phase → agent → llm

这个层级直接映射 V9.2 架构的阶段模型：

```
session          ← 一次用户请求的完整生命周期 (orchestrator.run)
├── phase_1      ← 意图解析 (run_phase1)
│   └── gen_ai.chat  ← CoT LLM 调用
├── phase_4      ← 规划生成 (WorkflowEngine Steps 1-3)
│   ├── agent.planner
│   │   └── gen_ai.chat  ← 每次 LLM 调用带 Token + 耗时
│   ├── agent.knowledge
│   └── agent.planner (refinement)
│       └── gen_ai.chat
└── phase_5      ← 评审 (WorkflowEngine Step 4)
    └── agent.reviewer
        └── gen_ai.chat
```

**业务价值**：在旅游规划中，不同 Phase 的耗时对用户体验影响不同：
- Phase 1 慢（10s）：用户还在输入，可接受
- Phase 4 慢（60s）：用户等待行程生成，需要优化
- Phase 5 慢（30s）：评审慢通常是语义检查太复杂，需要精简 prompt

没有 Span 层级时，只能看到 "总耗时 120s"。有 Span 后，立刻知道瓶颈在 Phase 4 的 knowledge agent（50s），可以针对性地加缓存或用 Flash 模型。

**为什么 Span 输出到 stderr 而非 stdout？**

stdout 是 structlog 业务日志的通道，stderr 是 OTel Span 结构的通道。分离后：

```bash
# 看业务事件
venv/Scripts/python main.py 2>/dev/null | jq -c 'select(.event == "llm_call_finished")'

# 看 Span 结构
venv/Scripts/python main.py 2>&1 1>/dev/null | jq -c '{name, duration_s}'
```

两者通过 `trace_id` 关联。同一个 `trace_id` 在 stdout 中出现在每条日志的 `trace_id` 字段，在 stderr 中出现在每个 Span 的 `context.trace_id` 字段。

### 2.4 Metrics 设计：为什么选这些指标

```python
AGENT_CALLS_TOTAL       # agent × status
AGENT_DURATION_SECONDS  # agent 直方图
LLM_CALLS_TOTAL         # model × status
LLM_TOKENS_TOTAL        # model × type(input/output)  ← 核心成本指标
LLM_DURATION_SECONDS    # model 直方图
PHASE_DURATION_SECONDS  # phase 直方图
RETRY_COUNT_TOTAL       # agent × reason
```

**为什么不只是计数器？**

旅游规划 Agent 的成本结构特殊：Token 消耗占运营成本的 90%+。`LLM_TOKENS_TOTAL` 按 model 和 input/output 分维，可以直接回答：

- "Flash 模型真的比 Pro 便宜吗？" → 看 `LLM_TOKENS_TOTAL{model=~"flash|pro"}` 
- "为什么这周成本翻了 3 倍？" → 看 `LLM_TOKENS_TOTAL` 的周环比
- "重试消耗了多少额外 Token？" → 看 `RETRY_COUNT_TOTAL` 关联的 LLM 调用次数

**为什么用 Histogram 而非 Summary？**

Histogram 的 bucket 在客户端定义，可以在服务端做任意分位数聚合（P50/P90/P99）。Summary 的分位数在客户端计算，跨实例无法聚合。对于旅游规划场景，我们需要知道"90% 的用户在多少秒内拿到行程" — 这需要 Histogram。

**为什么不暴露 /metrics 端点？**

当前是 CLI 单进程，`prometheus_client` 值在内存累积。等 FastAPI 阶段只需一行接入：

```python
from prometheus_client import make_asgi_app
app.mount("/metrics", make_asgi_app())
```

所有指标定义代码（`AGENT_CALLS_TOTAL` 等）完全不动。

### 2.5 Hermes Lineage 压缩：为什么现在只是骨架

Lineage 压缩解决的是**长对话 Token 窗口膨胀**问题。触发场景：

| 场景 | 压缩目标 | 当前状态 |
|:---|:---|:---|
| 30天新疆自驾行程 | Phase 3 资源池（丢弃非选中 hotel/flight） | 尚未实现 Phase 3 |
| 3 次以上重试 | 前几次的 reviewer 反馈详情 | MAX_RETRIES=1，罕见 |
| 多轮用户交互 | 早期反馈轮次 | 无前端交互环 |

当前没有触发场景，所以 `compress()` 只是接口和基础逻辑。但接口已定义好（`compress(phase_output, target_ratio) -> dict`），后续在 `workflow_engine._checkpoint()` 或 retry_feedback 构建时接入只需一行。

---

## 三、模块间的协同关系

```
Phase 1 (意图识别)
  │
  │  negation_constraints + intent_summary
  ▼
Phase 4 (规划生成)  ←── 日志: agent_started/finished, Span: agent.planner
  │                     指标: AGENT_CALLS_TOTAL, AGENT_DURATION_SECONDS
  │
  │  refined_plan
  ▼
Phase 5 (评审)      ←── 日志: review_complete, Span: agent.reviewer
  │                     指标: RETRY_COUNT_TOTAL
  │
  ▼
Phase 6 (交付)      ←── 日志: final_plan, quality_scores, budget_summary
```

可观测性层横切所有 Phase，提供：
- **Phase 1**：`negation_guard_hit` / `phase1_cot_parsed` / `phase1_needs_clarification` 事件
- **Phase 4**：`agent_started/finished` 事件 + `agent.*` Span + Agent 指标
- **Phase 5**：`review_complete` / `retry_exhausted` / `workflow_pass_finish` 事件 + 重试指标
- **全局**：`orchestrator_started/finished` + `session` Span + `llm_call_*` 事件 + Token 指标

---

## 四、设计原则总结

| 原则 | 意图识别中的体现 | 可观测性中的体现 |
|:---|:---|:---|
| **确定性优先** | Negation Guard 用正则，不用 LLM | Metrics 用 Counter/Histogram，确定性的数值 |
| **LLM 做 LLM 擅长的事** | CoT 解析意图和偏好，不依赖它处理否定词 | — |
| **失败早暴露** | Phase 1 门禁：信息不足时直接进入澄清，不往下跑 | ConsoleExporter 输出所有 Span，错误 Span 有 `exception` 事件 |
| **增量演进** | 先 Guard 后 CoT，逐步叠加 | 先 ConsoleExporter 后 OTLP，远期切换平台不改变代码 |
| **每层可独立验证** | `run_phase1()` 独立函数，pipeline 内聚 | 4 个 util 文件互相独立，可按需 import |
