# AGENTS.md

本文件规定 Codex 在本仓库中的开发方式。项目业务边界、技术选型、目标架构与全局验收的唯一设计依据是 `.codex/rules/架构.md`；历史 V9.2、Phase 0～8 等文档只能作为背景材料，不得覆盖项目总 Spec。

执行架构升级时还必须阅读 `.codex/rules/roadmap/00-总路线图.md`、当前阶段 Spec 和对应 Plan；M0～M6（包含插入阶段 M4.1、M4.2、M4.3）是求职项目核心完成线，M7 是进阶差异化能力，M8～M9 是岗位定向扩展。前一阶段未验收，不得启动后一阶段或提前实现未来阶段能力。

---

## 环境

- Python：`venv/Scripts/python`（Windows）/ `venv/bin/python`（Linux/Mac）
- 包管理：`venv/Scripts/pip`
- Shell：优先 Git Bash，路径使用 `/`
- Python 版本：3.11+

## 常用命令

```bash
# 安装依赖
venv/Scripts/pip install -r requirements.txt

# 运行主流程
venv/Scripts/python main.py

# 运行默认测试（跳过 slow）
venv/Scripts/python -m pytest

# 仅快速单元测试
venv/Scripts/python -m pytest -m "not slow and not integration"

# 运行单个测试文件
venv/Scripts/python -m pytest tests/unit/test_negation_guard.py

# 运行全部测试（包含真实 API 的 slow 测试）
venv/Scripts/python -m pytest -m slow

# 覆盖率
venv/Scripts/python -m pytest --cov=. --cov-report=term-missing
```

---

## 技术栈

| 分类 | 选型 | 用途 |
|:---|:---|:---|
| 语言 | Python 3.11+ | 领域逻辑、Agent 与工具编排 |
| LLM 网关 | DeepSeek API（OpenAI SDK） | 约束理解、方案生成、语义 Critic |
| 数据模型 | Pydantic v2 | 请求、约束、证据、候选、方案、验证问题 |
| 外部 API | 高德地图、途牛 MCP | 地理、酒店、航班/铁路、市内交通 |
| 政策知识 | PolicyKnowledgePort + 本地 PDF Adapter | 公司政策检索与页码级引用；完整 RAG 后续评测决定 |
| API 服务 | FastAPI + Uvicorn（后期） | 对外服务化 |
| 状态存储 | SQLite / JSONL（演进目标） | 会话、计划版本、Checkpoint、反馈 |
| 可观测性 | structlog + OpenTelemetry + prometheus_client | 日志、Trace、Metrics |
| 测试 | pytest + pytest-cov + httpx | 单元、集成、E2E |
| 包管理 | pip + 锁定版本的 requirements.txt | 可复现构建 |

---

## 当前代码基线

当前仓库已完成 M0～M4 通用内核的历史验收，但尚未完成 M4.1 商务差旅评测基线、M4.2 差旅语义与能力路由、M4.3 差旅最小纵向切片。以下仅列职责入口，不代表所有文件：

```text
skill/
├── main.py
├── src/
│   ├── domain/                      # Pydantic 合同与确定性领域服务
│   ├── application/                 # Router、Orchestrator、Task Graph、Use Case
│   ├── agents/                      # Interpreter、Research、Composer
│   ├── ports/                       # LLM、Tool、Evidence、State 等抽象接口
│   ├── infrastructure/              # 高德/途牛、Evidence 与 State 实现
│   ├── gateway/                     # DeepSeek LLM Gateway 与 JSON 边界
│   ├── obs/                         # 日志、Trace、Metrics
│   ├── engine/                      # 历史双 LLM 兼容内核
│   └── legacy/                      # 旧接口兼容 Mapper
├── tests/
│   ├── unit/
│   ├── integration/
│   └── e2e/
├── evaluation/
├── data/
├── .codex/rules/架构.md             # 项目总 Spec 与目标架构唯一依据
└── AGENTS.md
```

不要将尚不存在的目录或能力描述为“已实现”。每次架构升级都要区分历史已验收内核、当前业务差距、目标状态和本次增量。

---

## 项目总 Spec 与目标架构概述

企业商务差旅规划是**交互式约束满足 + 多目标优化 + 动态重规划**，不是风险二分类，也不是一次性自由文本生成。求职版以 `meeting_arrival_ready` 为边界：覆盖通用公司政策、去程、候选级且最多一晚的会前住宿、市内交通和首场会议到达时限；会议结束时间、会议期间住宿和返程默认不规划并显式披露，景点/活动不进入主链路。

主链路：

```text
Request Gateway
  → Session & Trip State
  → Intent & Constraint Interpreter
  → Interaction Router
      ├─ ANSWER：有依据的简单问答
      ├─ CLARIFY：最少必要追问
      ├─ PLAN：新建规划
      ├─ REFINE：局部修改
      ├─ COMPARE：同指标候选比较
      ├─ REPLAN：事件影响分析与重规划
      ├─ ACTION：预订/付款/取消确认边界
      └─ UNSUPPORTED：边界说明或人工接管
  → Orchestrator / Dynamic Task Graph
  → Research Agents + Tool Adapters
  → Evidence Registry
  → Candidate Pool
  → Hybrid Planner / Optimizer
  → Deterministic Validators
  → Independent Critic
  → Targeted Repair（有界）
  → Delivery / FAILED
```

### 三个平面

- **控制平面**：Gateway、Router、Orchestrator、状态机、预算、质量门；
- **数据平面**：Tool Adapter、Evidence Registry、Candidate Pool、版本化知识；
- **智能平面**：约束解释、Research Agent、方案生成、Critic 和交付表达。

控制平面决定是否继续和下一步动作。Agent 不得绕过控制平面修改状态或执行外部写操作。

### 核心设计决策

1. 先冻结 `ConstraintSnapshot`，再检索和规划；
2. 硬约束失败不能被综合评分抵消；
3. 动态事实必须携带来源、`observed_at`、`valid_until` 和置信度；
4. Research Agent 按当前任务动态选择，不要求每次全部运行；
5. 独立任务可以并行，存在依赖的规划与验证必须有序执行；
6. 生成使用 LLM，算术、时空可行性、Schema、权限和幂等使用确定性代码；
7. 修复基于结构化 `ValidationIssue`，优先局部补证和局部修改；
8. 计划与交易分离；预订、付款、取消、改签必须重新验证并获得用户最终确认；
9. 所有循环都有调用数、轮次、时长和成本上限；
10. 开发期严格 fail-fast，不实现或启用降级机制。

---

## 核心领域契约

优先稳定以下 Pydantic 模型：

- `TripRequest`：出发地、目的地、日期、人数、预算、偏好和工作模式；
- `Constraint` / `ConstraintSnapshot`：hard、soft、assumption、unknown 及其来源和优先级；
- `EvidenceItem` / `EvidenceSnapshot`：事实、来源、时间、TTL、状态和原始引用；
- `Candidate`：可参与规划的标准化去程交通、住宿和市内交通；公司政策作为版本化 Evidence/Rule，不作为旅游地点候选；
- `ItineraryPlan`：版本化日程、预算、备选、假设、警告和证据引用；
- `ValidationIssue`：Gate、严重级别、影响范围、证据、修复策略；
- `AgentContext` / `AgentResult`：Agent 的统一输入输出；
- `WorkflowError`：失败阶段、错误类型、上游引用和 `trace_id`。

跨模块不得裸传任意 `dict`，不得使用自由文本作为系统判断的唯一输入。自由文本用于用户展示，判断基于类型化字段。

### Agent 契约

```python
def run(context: AgentContext) -> AgentResult:
    """执行单个、边界清晰的 Agent 任务。"""
```

所有 Agent 必须遵守：

- Agent 不直接调用其他 Agent，由 Orchestrator 调度 Task Graph；
- Agent 不直接写全局 Trip State，只返回 `AgentResult`；
- 实时事实引用 `evidence_id`，不得把模型记忆当作事实；
- 失败明确分类为 `retryable`、`needs_user`、`unsupported` 或 `fatal`；
- 不把完整供应商响应塞入模型上下文；
- 不记录凭证、完整行程或不必要的 PII。

### Agent 与确定性服务边界

适合 Agent：意图与约束理解、跨来源研究判断、方案骨架生成、体验 Critic。

适合确定性服务：日期/时区、路程矩阵、预算、币种、营业区间、换乘缓冲、Schema、去重、TTL、权限、幂等和审计。

---

## 质量门

| Gate | 检查内容 | 失败行为 |
|:---|:---|:---|
| G0 安全与输入 | 权限、注入、PII、Schema、危险动作 | 显式失败或安全边界说明 |
| G1 规划就绪 | 关键字段、歧义、约束冲突 | 进入澄清，不继续规划 |
| G2 证据就绪 | 覆盖率、来源、TTL、冲突、关键缺失 | 补证失败后进入 `FAILED` |
| G3 确定性可行 | 日期、时区、路程、营业时间、预算、硬约束 | 结构化局部修复，仍失败则 `FAILED` |
| G4 语义与体验 | 节奏、偏好、特殊人群、解释 | Critic 返回结构化问题 |
| G5 交付完整 | Schema、证据、假设、警告、备选、版本 | 结构化错误；禁止自动补全 |
| G6 动作前验证 | 最新价格、库存、条款、身份与最终确认 | 不执行外部写操作 |

Critic 必须引用 `constraint_id`、`plan_item_id` 或 `evidence_id`，不能在无证据时断言实时事实，也不能直接重写方案。

---

## 开发期 Fail-fast 铁律

在 M1～M6 核心链路稳定前，**禁止实现或启用降级机制**：

- 禁止备用供应商自动接管；
- 禁止缓存回退；
- 禁止用估算或合成数据替代查询失败；
- 禁止占位符自动补全；
- 禁止返回部分方案并标记为正常成功；
- 禁止 Gate 强制通过；
- 禁止达到循环上限后视为成功；
- 禁止 Critic 或验证器异常时跳过；
- 禁止 Mock 提供未显式配置的默认成功响应。

工具失败、超时、解析失败、证据缺失/过期/冲突、验证异常和预算耗尽必须使任务或工作流进入 `FAILED`。失败至少包含：

- `trace_id`；
- 失败阶段；
- 错误类型；
- 受影响任务/证据；
- 可重试性；
- 原始异常的安全摘要。

单元测试和集成测试默认：

```text
strict_mode = true
retry_count = 0
cache_reads = false
fallbacks = false
partial_success = false
```

只有某个机制自身的专项测试可以显式改变对应配置。

生产重试、备用供应商、缓存等韧性能力属于后期 M7，必须由默认关闭的 Feature Flag 隔离，并单独进行正常路径、故障注入和回归测试。不得引入自动估算替代、无标识部分成功或强制通过。

---

## 编码规范

- 所有 Python 文件顶部使用 `from __future__ import annotations`；
- 所有函数签名必须完整标注参数和返回类型；
- 使用 Python 3.11+ 现代类型语法，如 `str | None`；
- DTO、状态和领域模型使用 Pydantic v2；简单只读载体可使用 `dataclass`；
- 中文注释和 docstring，关键术语保留英文；
- import 顺序：标准库、第三方、项目内，每组空一行；
- 生产代码使用 logger，禁止 `print()`；
- 禁止裸 `except:`；异常必须转换、记录或继续抛出；
- 不允许在领域层直接依赖具体供应商 SDK；
- 外部依赖必须通过接口和 Adapter；
- 结构化结果必须通过 Schema 校验后才能进入下游。

Docstring：

```python
def run(context: AgentContext) -> AgentResult:
    """简短描述。

    Args:
        context: 参数说明。

    Returns:
        AgentResult: 返回值说明。

    Raises:
        WorkflowError: 失败条件。
    """
```

命名：

| 类型 | 约定 | 示例 |
|:---|:---|:---|
| 模块 | `snake_case` | `evidence_registry.py` |
| 类 | `PascalCase` | `ConstraintSnapshot` |
| 函数 | `snake_case` | `validate_evidence()` |
| 常量 | `UPPER_SNAKE` | `MAX_TOOL_CALLS` |
| 私有函数 | `_prefix` | `_normalize_price()` |
| Pydantic Model | 描述性 `PascalCase` | `ValidationIssue` |

---

## 测试规范

- 新功能必须包含测试，Bug 修复必须添加回归测试；
- 单元测试覆盖率目标 ≥ 80%；
- 外部 LLM/API 在单元和普通集成测试中必须 Mock；
- 真实 API 测试标记 `pytest.mark.slow`；
- 测试目录与源码职责对应；
- 测试函数命名：`test_<被测行为>_<场景>_<期望结果>()`。

每个新组件至少测试：

1. 正常成功；
2. 输入 Schema 失败；
3. 上游工具失败；
4. 超时；
5. 空结果；
6. 响应解析失败；
7. 证据过期或冲突；
8. 硬约束失败；
9. 调用预算耗尽；
10. 不会触发缓存、估算、部分成功或强制通过。

测试断言必须验证精确错误类型和失败阶段，不能只断言“返回了内容”或“没有抛异常”。

---

## 安全规则

1. API Key、Token、Password 只来自环境变量或密钥系统；
2. `.env` 不得提交，`.env.example` 只使用安全占位符；
3. 用户输入以数据字段注入 Prompt，不拼接到系统指令；
4. 工具名和参数使用 allowlist 与 Schema 校验；
5. 外部 API/网页文本视为不可信输入，防止间接 Prompt Injection；
6. 日志禁止记录完整行程、证件、联系方式和凭证；
7. 预订、付款、取消、改签使用最小权限、幂等、审计和用户最终确认；
8. 禁止 `eval()`、`exec()`、`pickle` 和执行 LLM 生成代码；
9. `requirements.txt` 必须锁定版本，禁止使用无上限的 `>=`；
10. 禁止提交 `__pycache__`、`.pyc`、`.pytest_cache` 和凭证文件。

---

## Git 规范

Commit Message：

```text
[module] type: 简短描述（≤72字符）
```

模块标签：

| 标签 | 范围 |
|:---|:---|
| `core` | 状态、契约、Orchestrator、Task Graph |
| `router` | Intent、Constraint、Interaction Router |
| `evidence` | Evidence Registry、来源与 TTL |
| `candidate` | 候选标准化、去重和剪枝 |
| `agent` | Research Agent、Composer、Critic |
| `planner` | 排程、多目标优化和局部修复 |
| `validator` | G0～G6 与确定性验证 |
| `tool` | Tool 接口和供应商 Adapter |
| `action` | 预订/付款/取消确认边界 |
| `obs` | 日志、Trace、Metrics |
| `api` | FastAPI 接口层 |
| `eval` | 评估与回归集 |
| `test` | 测试 |
| `docs` | 文档和规则 |
| `meta` | AGENTS.md、VERSION、.gitignore |

分支：

- `feat/<描述>`
- `fix/<描述>`
- `refactor/<描述>`
- `docs/<描述>`

---

## 环境变量

| 变量 | 用途 | 必需 |
|:---|:---|:---:|
| `DEEPSEEK_API_KEY` | DeepSeek LLM API | 是 |
| `DEEPSEEK_MODEL` | Live 运行使用的模型 ID；禁止隐式默认或回退 | Live 必需，离线测试否 |
| `AMAP_API_KEY` | 高德地图 API | 按功能 |
| `TUNIU_API_KEY` | 途牛 MCP API | 按功能 |
| `STRICT_MODE` | 开发/测试强制 fail-fast，默认应为 `true` | 开发测试必需 |

不得通过环境变量在普通测试中静默开启 fallback、cache 或 partial success。

---

## 文档优先级

发生冲突时按以下顺序处理：

1. 当前用户明确要求；
2. `.codex/rules/架构.md`；
3. 本 `AGENTS.md`；
4. `evaluation/` 下的评估资料；
5. 历史架构、路线图和实验文档。

如果实现与目标架构不同，必须在变更说明中明确标注“当前实现限制”，不得修改文档来掩盖实现偏差。

---

## 文件写入与工作区边界

- 允许使用 shell 写入开发指南明确要求修改的目标文件，以避免 `apply_patch` 连续失败。
- 每次准备使用 shell 写文件前，必须先在 Codex 终端通知用户，说明将要写入的目标文件；只有得到用户明确同意后，才可执行 shell 写入命令。
- shell 写文件的授权仅限用户明确同意的目标文件，不得借此写入其他文件。
- 工作区只能是当前项目根目录 `F:\Commercial project\skill`；不得切换或操作其他工作区。
- 只有写文件部分修改为shell，其余操作照旧
