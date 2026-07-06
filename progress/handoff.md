# Handoff — v1.1.0 API 接入

## 当前状态

- **版本**: `1.1.0-dev`
- **基线**: `v1.0.0` (已封存 — 纯 stub 架构验证版)
- **分支**: `feat/api-integration`
- **目标**: 将 stub 数据替换为真实 LLM/API，使系统从"假数据的真流程"变为"可投产的真系统"

## 开发路线

```
Batch 4 (P0): Planning Agent 接入 LLM     → 行程/餐厅/住宿"活"起来
Batch 5 (P0): Execution Agent 接入真实 API → 价格/地图/时间校验不再用假数据
Batch 6 (P1): 集成验证 + 真实案例          → 3-5 个真实城市端到端跑通
Batch 7+     : 根据真实反馈优化            → 以问题驱动，不预设
```

---

## Batch 4: Planning Agent 接入 LLM（P0 — 最高优先级）

### 目标
替换 `agents/planning_agent.py` 中 6 个方法的 stub 数据为 LLM 调用，让行程生成"活"起来。

### 任务清单

| # | 任务 | 涉及文件 | 描述 |
|---|------|---------|------|
| 4.1 | LLM 客户端封装 | `core/llm_client.py` (NEW) | 统一 LLM 调用接口：发送 prompt → 返回结构化响应；超时 30s，重试 3 次指数退避；支持 Claude API（起步用 Haiku 降成本） |
| 4.2 | 景点搜索接入 LLM | `agents/planning_agent.py` → `search_attractions()` | 替换硬编码"景点A/B/C"为 LLM 按目的地+偏好生成真实景点列表；保留 fallback 到 stub（LLM 不可用时） |
| 4.3 | 餐厅搜索接入 LLM | `agents/planning_agent.py` → `search_restaurants()` | 替换模板餐厅为 LLM 按菜系偏好+预算生成餐厅推荐；返回结构化 Restaurant 列表 |
| 4.4 | 住宿搜索接入 LLM | `agents/planning_agent.py` → `search_accommodations()` | 替换固定酒店为 LLM 按位置+预算范围推荐真实酒店；返回结构化 Accommodation 列表 |
| 4.5 | 行程生成接入 LLM | `agents/planning_agent.py` → `create_itinerary()` | 替换模板行程为 LLM 整合景点+餐厅+住宿+偏好+预算约束，生成完整的 5 天行程 JSON |
| 4.6 | 预算分配接入 LLM | `agents/planning_agent.py` → `allocate_budget()` | 替换固定比例分配为 LLM 按目的地物价水平+偏好动态分配 |
| 4.7 | LLM 错误处理 | `agents/planning_agent.py` | 处理：超时(30s)、限流(429)、格式异常(JSON parse失败)、空响应；每种错误有降级策略 |
| 4.8 | 单元测试 | `tests/test_planning_agent.py` | 新增 LLM 调用的 Mock 测试（不真调 API），覆盖 happy path + 6 种错误模式 + fallback 路径 |

### 约束
- LLM 调用必须通过 `core/llm_client.py` 统一入口（不直接在 Agent 中裸调 API）
- 所有 LLM 响应必须做 schema 校验（返回的 JSON 必须能反序列化为对应 model）
- 对外 API 签名不变（`search_attractions()` 等方法的输入/输出类型保持兼容）

---

## Batch 5: Execution Agent 接入真实 API（P0 — 最高优先级）

### 目标
替换 `tools/` 下 4 个 checker 的 stub 实现为真实 API，让价格/地理/时间校验产生有意义的报告。

### 任务清单

| # | 任务 | 涉及文件 | 描述 |
|---|------|---------|------|
| 5.1 | 价格 API 接入 | `tools/price_checker.py` | 替换硬编码价格字典；对接免费/低成本价格数据源（如 Amadeus Self-Service API、或爬取公开价格数据）；`check_prices()` 返回真实市场价偏差 |
| 5.2 | 地理编码 API 接入 | `tools/geo_checker.py` | 替换 stub 坐标；对接地理编码 API（如 Nominatim 免费、Mapbox 免费层）；`check_geography()` 计算真实距离和绕路比 |
| 5.3 | 交通时间 API 接入 | `tools/time_checker.py` | 替换固定 transit_time = 60min；对接地图 API 获取真实交通时间（驾车/公交/步行）；`calculate_transit_time()` 返回真实耗时 |
| 5.4 | 执行 Agent 适配 | `agents/execution_agent.py` | 适配 3 个 tool 的新返回格式（字段可能有增减）；确保 `validate_feasibility()` 的 blocking_issues 判定逻辑仍正确 |
| 5.5 | API 错误处理 | `tools/price_checker.py`, `geo_checker.py`, `time_checker.py` | 处理：API 超时(15s)、限流、配额耗尽、数据缺失；每个 tool 有降级策略和明确错误码 |
| 5.6 | API 配置管理 | `core/config.py` (NEW) | API key/endpoint/rate_limit 的集中管理；支持环境变量 + 配置文件；不硬编码任何密钥 |
| 5.7 | 单元测试 | `tests/test_execution_agent.py` + tools 测试 | 新增 API Mock 测试；覆盖正常响应 + 超时 + 限流 + 数据缺失 + 降级路径 |

### 约束
- API key 通过环境变量注入，禁止出现在源码或 commit 中
- 每个 tool 必须有明确的降级策略（API 不可用时返回什么、标记什么状态）
- 优先选择免费层级 API（Nominatim/Mapbox free tier/Amadeus Self-Service）

---

## Batch 6: 集成验证 + 真实案例（P1）

### 目标
端到端跑通 3-5 个真实城市案例，验证 LLM + API 链路完整，记录问题到 lessons.md。

### 任务清单

| # | 任务 | 描述 |
|---|------|------|
| 6.1 | 案例 1: 东京 5 天 | 经典案例，验证已有测试基准不受破坏 |
| 6.2 | 案例 2: 巴黎 3 天 | 欧洲城市，验证跨洲数据（时区/货币/语言） |
| 6.3 | 案例 3: 纽约 4 天 | 高物价城市，验证预算约束是否被真实 API 打破 |
| 6.4 | 案例 4: 成都 2 天 | 国内短途，验证中文输入+国内数据 |
| 6.5 | 案例 5: 曼谷 7 天 | 长行程+东南亚，验证极限天数+新兴市场数据 |
| 6.6 | 回归测试 | 552 个现有测试必须全部通过（Mock 层不应受影响） |
| 6.7 | Lessons 汇总 | 将 Batch 4-5 中遇到的问题写入 `progress/lessons.md`；标注 commit hash |

### 验收标准
- 5 个案例全部跑通（Gate 0→1→2→3，最终 status = COMPLETED）
- 0 个回归测试失败
- 真实案例评分 ≥ 70/100（允许低于 stub 时代的 95，因为真实数据更复杂）

---

## Pipeline 执行规则（每个 Batch 复用）

```
主 Agent（你）
  │
  ├─ R1: 启动 Context Agent
  │    输入: 目标模块的 spec/ playbook/ evaluation/ progress/ 文件路径
  │          + progress/lessons.md（检查已知可预防问题）
  │    输出: 结构化上下文摘要（spec要点/现有代码/实现状态/差异标注）
  │    审查: 是否覆盖全部 spec 要求？是否有 blocking 级差异？
  │
  ├─ R2: 启动 Plan Agent
  │    输入: Context Agent 的输出
  │    输出: 实现方案 + 原子任务 DAG + 验收标准（引用 spec + rubric）
  │    审查: spec_coverage_check = 100%？接口定义是否先于实现？
  │
  ├─ R3: 启动 Code Agent
  │    输入: Plan 的任务分配
  │    输出: 代码文件（接口优先 → 核心逻辑 → 边界处理）
  │    审查: 接口签名与 spec 一致？所有外部调用有超时设置？
  │
  ├─ R4: 启动 Test Agent
  │    输入: Code Agent 的代码 + evaluation/test_scenarios.md
  │    输出: 单元测试 + 集成测试，覆盖率 ≥ 70%
  │    审查: 是否覆盖对应 test_scenarios？覆盖率达标？
  │
  ├─ R5: 启动 Evaluation Agent (Mode A)
  │    输入: 代码 + 测试
  │    输出: code_quality_report（按 code_quality_rubric.md 评分）
  │    审查: composite ≥ 80 (PASS) / < 60 (REJECT) / 60-79 (退回修订)
  │    FAIL → 退回 Code/Test Agent，最多 3 轮
  │    PASS → 更新 progress/<module>.md，commit
  │
  └─ R5.5: Lessons（跨轮次知识传递）
        写入 progress/lessons.md（commit 列填 待提交）
        git commit 后由主 Agent 回填实际 commit hash
```

---

## 关键约束

### API 安全
- API key / secret 通过环境变量注入，禁止出现在源码或配置文件中
- `.env` 文件加入 `.gitignore`
- 示例配置 (`config.example.yaml`) 可以提交，但包含占位值

### 降级策略
- 每个外部调用必须有降级路径（API 不可用 → stub fallback 或明确错误标记）
- 降级不得静默进行（必须 log warning 级别以上）
- 降级后的结果必须标记 `degraded: true`，让上游知道数据质量

### 契约优先
- 对外接口签名不变——现有 stub 方法的输入/输出类型保持兼容
- 如需新增字段，只增不减（向后兼容）
- `spec/agent_contract.md` 如有更新，必须同步到所有 playbook

### 质量门
- Gate 0: 必填项完整（目的地/日期/预算/人数）
- Gate 1: blocking_issues == 0
- Gate 2: composite ≥ 80 PASS，< 60 REJECT，≥3维度 < 3 → blocking
- Gate 3: 格式合规 + 完整性 100%

### Commit 格式
```
[module] type: 描述
```
module: core/models/tools/orch/plan/exec/eval/test/meta
type: feat/fix/refactor/test/docs/chore

### 进度回写
- 每完成一个模块 → 更新 `progress/<module>.md`
- 每完成一个 Batch → 更新 `progress/README.md` 阶段状态
- 每轮 R5.5 → 写入 `progress/lessons.md`

---

## 关键文件速查

| 类别 | 文件 | 用途 |
|------|------|------|
| 总览 | `CLAUDE.md` | 项目架构/Pipeline规则/质量门/commit规范 |
| 版本 | `VERSION` | `1.1.0-dev` |
| 路线图 | `ROADMAP.md` | 版本范围定义+交付物清单 |
| 交接 | `progress/handoff.md` | 本文档 — 当前状态+Batch 计划 |
| 经验 | `progress/lessons.md` | 跨轮次问题记录（Context Agent R1 必读） |
| 进度 | `progress/README.md` | 阶段总览+模块索引+变更日志 |
| Spec | `spec/agent_contract.md` | 消息格式/TaskType/ErrorCode/超时重试 SSOT |
| Spec | `spec/system_spec.md` | 系统架构/状态机/数据模型 |
| Spec | `spec/planner_spec.md` | Planning Agent 接口 |
| Spec | `spec/executor_spec.md` | Execution Agent 接口+工具定义 |
| Playbook | `playbooks/planner_playbook.md` | Planning Agent SOP |
| Playbook | `playbooks/executor_playbook.md` | Execution Agent SOP |
| DevAgent | `devagents/code_agent.md` | Code Agent 约束（含§6自检清单） |
| DevAgent | `devagents/test_agent.md` | Test Agent 约束 |
| DevAgent | `devagents/context_agent.md` | Context Agent 约束（含 lessons.md 读取） |
| 评估 | `evaluation/code_quality_rubric.md` | Mode A 代码质量量表（5维度） |
| 评估 | `evaluation/test_scenarios.md` | 41个测试场景（API 接入后需扩充） |
| 代码 | `agents/planning_agent.py` | 134行 — Batch 4 主要改造对象 |
| 代码 | `agents/execution_agent.py` | 234行 — Batch 5 适配对象 |
| 代码 | `tools/price_checker.py` | stub — Batch 5 替换为真实 API |
| 代码 | `tools/geo_checker.py` | stub — Batch 5 替换为真实 API |
| 代码 | `tools/time_checker.py` | stub — Batch 5 替换为真实 API |
| 代码 | `core/llm_client.py` | NEW — Batch 4 统一 LLM 调用接口 |
| 代码 | `core/config.py` | NEW — Batch 5 API 配置管理 |
