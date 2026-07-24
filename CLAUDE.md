# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

---

## 环境

- Python: `venv/Scripts/python` (Windows) / `venv/bin/python` (Linux/Mac)
- 包管理: `venv/Scripts/pip`
- Shell: Git Bash（非 cmd/PowerShell），路径用 `/` 分隔

## 常用命令

```bash
# 安装依赖
venv/Scripts/pip install -r requirements.txt

# 运行主流程
venv/Scripts/python main.py

# 运行所有测试（默认跳过 slow）
venv/Scripts/python -m pytest

# 运行全部测试（含真实 API 调用的 e2e）
venv/Scripts/python -m pytest -m slow

# 运行单个测试文件
venv/Scripts/python -m pytest tests/unit/test_planner.py

# 运行单个测试函数
venv/Scripts/python -m pytest tests/unit/test_planner.py -k "test_negation_guard"

# 代码覆盖率
venv/Scripts/python -m pytest --cov=. --cov-report=term-missing

# 仅快速单元测试（跳过集成测试和 slow）
venv/Scripts/python -m pytest -m "not slow and not integration"
```

## 技术栈

| 分类 | 选型 | 用途 |
|:---|:---|:---|
| 语言 | Python 3.11+ | — |
| LLM 网关 | DeepSeek API (OpenAI SDK) | 行程生成、知识查询、语义评审 |
| 状态管理 | Pydantic v2 | WorkflowState, DTO |
| 外部 API | 高德地图 Geocode, 途牛 MCP | 地理编码、酒店/航班/门票 |
| Web 框架 | FastAPI + Uvicorn (远期) | API 服务化 |
| 向量存储 | Chroma (远期) | 用户偏好语义检索 |
| 本地存储 | SQLite + JSONL (远期) | 工作记忆 + 情节画像 |
| 可观测性 | structlog + prometheus_client (第 3 层) | 结构化日志 + Metrics |
| 测试 | pytest + pytest-cov + httpx | 单元/集成/e2e |
| 包管理 | pip + requirements.txt | 零 Docker 依赖 |

## 项目结构

已从扁平结构迁移到 `src/` 包结构（V9.2 架构）。

```
skill/
├── main.py                            # CLI 入口
│
├── src/
│   ├── interfaces/                    # 抽象接口（待实现）
│   │
│   ├── infrastructure/                # 基础设施
│   │   └── deepseek_gateway.py        #   ← llm_client.py（DeepSeek API 封装）
│   │
│   ├── domain/                        # 领域层
│   │   ├── dtos/                      #   阶段契约 DTO（enums/phase1/phase5/retry_context）
│   │   ├── agent_state.py             #   ← state.py（WorkflowState/AgentContext/AgentResult）
│   │   ├── planner.py                 #   ← planner_agent.py（行程生成 Agent）
│   │   ├── knowledge_agent.py         #   ← knowledge_agent.py（知识查询 Agent）
│   │   └── reviewer.py               #   ← reviewer_agent.py（评审 Agent）
│   │
│   ├── application/                   # 应用层
│   │   ├── orchestrator.py            #   ← orchestrator.py（组装层）
│   │   ├── workflow_engine.py         #   ← workflow_engine.py（状态机）
│   │   ├── mappers/                   #   DTO 映射器（待实现）
│   │   ├── guards/                    #   代码守卫（negation_guard）
│   │   └── routers/                   #   路由（待实现）
│   │
│   ├── adapters/                      # 外部适配器（待实现）
│   ├── phase1/                        # Phase 1 意图解析（prompts/pipeline）
│   ├── phase2/ ~ phase8/              # 远期阶段（待实现）
│   ├── api/                           # FastAPI 路由（远期）
│   └── utils/                         # 工具（json_utils）
│
├── evaluation/                        # 评审标准文档
├── tests/
│   ├── unit/                          # 单元测试
│   ├── integration/                   # 集成测试
│   └── e2e/                           # E2E 测试
├── data/                              # 运行时数据
│   ├── profiles/                      # L2 情节画像
│   └── exports/                       # 渲染输出
├── .claude/
│   ├── settings.json
│   ├── hooks/
│   └── rules/                         # ★ 架构与规范文档
├── .env.example
├── requirements.txt
├── pytest.ini
├── VERSION
└── CLAUDE.md
```

---

## 架构概述

### 分层架构

```
API 层 (routes/schemas)     →  不包含业务逻辑
应用层 (orchestrator/router) →  纯编排，不执行业务计算
领域层 (planner/validator)   →  纯 Python/LLM，不依赖具体基础设施
接口层 (interfaces/)         →  所有外部依赖必须通过接口访问
基础设施层 (infrastructure/) →  可插拔的具体实现
适配器层 (adapters/)         →  隔离上游 API 变化
```

### 核心接口契约

所有 Agent 必须遵守：

```python
def run(context: AgentContext) -> AgentResult:
    """Agent 统一入口。
    Args:
        context: 只读上下文（session_id, user_input, upstream_data, retry_context）
    Returns:
        AgentResult: agent 名称 + 产出数据 + 成功标志 + 错误信息
    """
```

**铁律**：
- Agent **互不调用**，全部由 WorkflowEngine 调度
- Agent **不直接写** WorkflowState，Engine 读取 AgentResult.data 后写入
- 数据通过 **DTO** 在阶段间传递，不裸传 dict
- 所有外部依赖通过 **接口抽象层** 调用，不直接依赖具体实现

### 状态机流程（V9.2 升级后）

```
Phase 0: 会话初始化（画像加载）
  ↓
Phase 1: 意图解析（LLM CoT + 🛡️Negation Guard）
  ↓ 门禁: confidence≥0.8 & missing≤2
  ↓
Phase 2: 环境上下文（天气/会展/汇率）
  ↓
Phase 3: 资源候选池（API 拉取 + 空池退避重试）
  ↓
Phase 4: 规划生成（复杂度评分 → Flash/Pro 自适应路由）
  ↓
Phase 5: 两级裁决
  L1 确定性校验器（纯代码，毫秒级）
  L2 语义校验器（LLM 3步：体力/过滤/场景适配）
  L3 用户交互环（补丁/重启/查询 三档路由）
  ↓
Phase 6: 输出交付（行程 + 评分 + Flex_Buffer）
```

### 关键设计决策

- Agent **串行执行**，不并行（依赖明确、可追溯）
- 差异化重试路由（可行性→Knowledge, 体验→Planner Refinement, 完整性→Planner）
- State Store 支持 Checkpoint（保留最近 3 个快照）
- 先手写状态机，后评估是否引入 LangGraph
- 架构升级原则：**增量演进，每步可验证，向后兼容**

---

## 编码规范

> 详细规范见 `.claude/rules/coding-standards.md`

### 必须遵守

- **Python 3.11+**，使用现代语法（`str | None` 而非 `Optional[str]`）
- **强制类型标注**：所有函数签名必须标注参数和返回值类型
- **Pydantic v2** 用于数据模型（DTO、AgentState），`dataclass` 仅用于简单载体（AgentResult）
- **中文注释和 docstring**——当前项目中文为主，关键术语保留英文（AgentContext, WorkflowState）
- `from __future__ import annotations` 在每个文件顶部
- `import` 顺序：标准库 → 第三方 → 项目内，每组空一行

### Docstring 格式

```python
def run(context: AgentContext) -> AgentResult:
    """简短描述（一行）。

    Args:
        context: 参数说明

    Returns:
        AgentResult: 返回值说明

    Raises:
        ValueError: 异常条件
    """
```

### 命名约定

| 类型 | 约定 | 示例 |
|:---|:---|:---|
| 模块文件 | `snake_case` | `planner_agent.py` |
| 类 | `PascalCase` | `WorkflowEngine`, `Phase1Output` |
| 函数/方法 | `snake_case` | `extract_negation_constraints()` |
| 常量 | `UPPER_SNAKE` | `MAX_RETRIES`, `DEFAULT_MODEL` |
| 私有函数 | `_prefix` | `_check_budget()`, `_sanitize_json()` |
| Pydantic Model | `PascalCase` + 描述性后缀 | `PlannerOutput`, `ReviewerInput` |

---

## 测试规范

> 详细规范见 `.claude/rules/testing-rules.md`

### 测试金字塔

```
        ┌──────┐
        │ E2E  │  ← 全流程 + 真实 API (slow)
       ┌┴──────┴┐
       │ 集成测试 │ ← 多模块协作 + Mock API
      ┌┴────────┴┐
      │  单元测试  │ ← 纯逻辑、纯函数、无 IO
      └──────────┘
```

### 必须遵守

- 新功能必须包含测试，修复 bug 必须添加回归测试
- 单元测试覆盖率目标 ≥ 80%
- 使用 `pytest.mark.slow` 标记需要真实 API 的测试
- 外部依赖（LLM、API）必须在测试中 Mock
- 测试函数命名：`test_<被测函数>_<场景>_<期望结果>()`
- 测试目录结构与源码一一对应

### 运行策略

```bash
pytest -m "not slow"              # CI/快速检查（默认）
pytest -m slow                    # 发布前完整验证
pytest --cov=. --cov-report=html  # 覆盖率报告
```

---

## 安全规则

> 详细规范见 `.claude/rules/security-rules.md`

### 必须遵守

1. **API Key 绝不硬编码**：全部走环境变量（`.env`），`.env` 已在 `.gitignore`
2. **`.env.example` 占位符安全**：使用 `sk-xxxxxxxxxxxxxxxx` 或 `xxxxxxxx`，不包含真实凭证
3. **输入校验**：所有用户输入在进入 LLM prompt 前必须经过脱敏（移除疑似注入指令）
4. **Prompt 注入防护**：用户输入作为 `{user_input}` 占位符注入 prompt，禁止直接拼接
5. **日志安全**：禁止打印 API Key、用户个人信息到日志
6. **依赖审计**：定期 `pip list --outdated`，关注安全公告

### 禁止事项（全项目）

| 禁止 | 原因 |
|:---|:---|
| ❌ 在代码中硬编码任何 Key/Token/Password | 泄露风险 |
| ❌ 将 `.env` 或任何含凭证的文件提交 Git | `.gitignore` 已配置 |
| ❌ 直接拼接用户输入到 prompt 指令位置 | Prompt Injection |
| ❌ 在日志/错误消息中打印用户完整行程 | 隐私 |
| ❌ 使用 `eval()` / `exec()` / `pickle` | 代码注入风险 |
| ❌ Agent 直接调用另一个 Agent | 破坏状态机调度，引发级联故障 |
| ❌ Agent 直接写 WorkflowState | 绕过 Engine，状态污染 |
| ❌ 在生产代码中使用 `print()` 而非 logger | 无结构化、不可追踪 |
| ❌ 裸 `except:` 吞掉异常 | 隐藏 bug |
| ❌ LLM 输出直接当作可执行代码执行 | 幻觉/注入风险 |
| ❌ `requirements.txt` 使用 `>=` 不锁定版本 | 构建不可复现 |
| ❌ 提交包含 `__pycache__` / `.pyc` / `.pytest_cache` | `.gitignore` 已配置 |

---

## Git 规范

> 详细规范见 `.claude/rules/git-conventions.md`

### Commit Message 格式

```
[module] type: 简短描述（≤72字符）

正文（可选，每行≤72字符，空一行接标题后）
关联 spec/issue 在正文中注明
```

### Module 标签（V9.2）

| 标签 | 对应范围 |
|:---|:---|
| `core` | 框架内核（state, engine, interfaces） |
| `guard` | 代码守卫（negation_guard 等） |
| `mapper` | DTO 映射器（context_mapper） |
| `agent` | Agent（planner, knowledge, reviewer, semantic_checker） |
| `router` | 路由（model_router, composite_intent_splitter） |
| `infra` | 基础设施（gateway, store, mcp_client） |
| `phaseN` | 阶段 N 实现（phase1~phase8） |
| `api` | FastAPI 接口层 |
| `eval` | 评审/评估相关 |
| `test` | 测试 |
| `docs` | 文档/规格/rules |
| `meta` | 元信息（CLAUDE.md, VERSION, .gitignore） |

### 分支命名

- `feat/<描述>` — 新功能（如 `feat/negation-guard`）
- `fix/<描述>` — Bug 修复
- `refactor/<描述>` — 重构
- `docs/<描述>` — 文档更新

---

## 环境变量

| 变量 | 用途 | 必需 |
|:---|:---|:---:|
| `DEEPSEEK_API_KEY` | DeepSeek LLM API | ✅ |
| `DEEPSEEK_MODEL` | 模型选择（默认 `deepseek-chat`） | ❌ |
| `DEEPSEEK_FLASH_MODEL` | Flash 模型名（第 4 层 双模型路由） | ❌ |
| `DEEPSEEK_PRO_MODEL` | Pro 模型名（第 4 层 双模型路由） | ❌ |
| `AMAP_API_KEY` | 高德地图地理编码 API | ❌ |
| `TUNIU_API_KEY` | 途牛 MCP 酒店/航班/门票 API | ❌ |

---

## Rules 索引

`.claude/rules/` 目录包含详细的规范与设计文档：

| 文件 | 内容 |
|:---|:---|
| `coding-standards.md` | 编码规范（类型标注、Docstring、错误处理、日志） |
| `testing-rules.md` | 测试分层、Mock 策略、覆盖率目标、命名规范 |
| `security-rules.md` | 安全规则（Prompt Injection 防护、API Key 管理、审计） |
| `git-conventions.md` | Git 规范（Commit 格式、分支策略、PR 流程） |
| `tooling-recommendations.md` | ★ 推荐工具链（Plugins + MCP Servers + Skills 安装指南） |
| `upgrade-roadmap.md` | ★ 升级路线图（分模块步骤 + 进度追踪 + 每个模块的验证方式） |
| `architecture-v9.2-adoption.md` | V9.2 目标架构（完整目录结构 + 分层规范 + 不变原则） |
| `data-interfaces.md` | ★ 数据接口规范（枚举、8阶段DTO、ContextMapper、AgentState完整定义） |
| `architecture-validation-25-inputs.md` | 25 条用户输入逻辑推演（架构有效性验证） |
