# M6：求职交付层——API、Demo、可观测展示与项目包装

> 文档状态：Frozen v1.0，可在 M5 验收后编写阶段 Plan  
> 本阶段性质：求职完成线，只包装已验证能力  

## 1. 阶段定位

M6 是核心项目完成线。目标是把 M0～M5（包含 M4.1、M4.2、M4.3）已验证的企业商务差旅能力交付成第三方可运行、可观察、可评测的求职作品，不增加新的规划业务能力。

完成 M6 后项目状态标记为 `JOB_READY`。M7～M9 未完成不影响该结论。

## 2. 前置条件

- M0～M5（包含 M4.1、M4.2、M4.3）验收全部通过；
- 新主链路无 legacy L1/L2 依赖；
- 离线 Eval 可重复执行并有 baseline/current 报告；
- CLI 输入输出契约稳定；
- Tool/Agent/Gate Trace、错误类型、成本和延迟可采集；
- strict 模式 E2E 稳定。

## 3. 技术栈与边界

- API：FastAPI + Uvicorn；
- API 测试：httpx `ASGITransport`，默认不启动真实端口；
- Demo：静态 HTML/CSS/原生 JavaScript，调用同一 API；
- Schema：Pydantic v2，presentation DTO 与 domain DTO 显式映射；
- 可观测：structlog、OpenTelemetry、prometheus_client；
- CI：GitHub Actions 或仓库已有 CI；
- 文档：Markdown、Mermaid、可提交的 JSON/Markdown 评测报告。

禁止在 M6 引入 React/Vue、Node 构建链、LangGraph、向量库、Action、SQLite、缓存或重试，除非另有已批准 ADR。

## 4. 允许修改范围

- `src/presentation/api.py`、`schemas.py`、`demo/`；
- composition root 与启动命令；
- `src/infrastructure/observability/`；
- API/E2E/安全测试；
- `evaluation/reports/`；
- README、架构图、演示用例、部署/运行说明；
- CI 配置、`.env.example` 和最小容器化文件（可选）。

应用层和领域层只允许修复暴露出来的缺陷，不允许在本阶段新增业务分支。若 M6 发现核心能力缺失，返回责任阶段修复并重新验收 M5。

## 5. API 契约

首版只提供必要只读/规划接口：

```text
POST /api/v1/trips/plan
POST /api/v1/trips/clarify
GET  /api/v1/runs/{run_id}
GET  /api/v1/runs/{run_id}/trace
GET  /api/v1/evaluation/summary
GET  /health/live
GET  /health/ready
GET  /metrics
```

规则：

- route 只做请求校验、认证占位边界、Use Case 调用和响应映射；
- `run_id`、`trace_id` 在边界产生并回传；
- API 错误使用稳定 code、stage、retryable、safe_message；
- 不向客户端返回 Prompt、堆栈、Key、完整供应商 payload；
- HTTP 状态码与领域错误映射有契约测试；
- 同步执行超过产品阈值时返回明确失败；M6 不私自加入异步队列；
- `/trace` 返回脱敏后的展示视图，不暴露内部完整思维过程。

## 6. Demo 页面

页面必须让面试官在 3 分钟内理解核心能力，至少展示：

1. 差旅请求、会议要求、政策版本和预置黄金场景；
2. 解析后的 hard/soft/unknown 约束与 BusinessTripScope；
3. policy、geo、intercity、stay、local transport Task Graph 节点、依赖和状态；
4. 政策 PDF、航班/城际交通、酒店和市内路线的 Evidence 来源/时效；
5. 去程、每晚酒店、市内交通、会议节点、预算、假设和备选；
6. G0～G5 结果；
7. Critic issue 和 Targeted Repair 前后差异；
8. 延迟、调用数、Token 和成本摘要；
9. 显式失败的责任阶段和安全错误信息。

禁止展示隐藏 Chain-of-Thought。只展示结构化决策摘要、输入输出契约、证据和验证结果。

Demo 默认使用固定 Fixture 和明确的 `DEMO_DATA_MODE=fixture`。该模式是独立测试/演示环境，不得在生产配置中作为工具失败后的 fallback。

## 7. 黄金演示场景

只准备四类高信息密度场景：

| 场景 | 必须证明 |
|:---|:---|
| 缺少会议时间或唯一会场 | 精准澄清 blocker，不提前生成；系统政策缺失不向用户追问 |
| 标准单人次日早会 | 政策→去程航班→前一晚酒店→市内交通→会议全链路 |
| 无需住宿的同日会议 | ScopeResolver 不多查酒店，仍覆盖最后一段市内交通 |
| 酒店超政策或到达缓冲不足 | G2/G3 阻断并进行一次有界局部修复，hard constraint 不被总分抵消 |
| 政策 PDF/工具失败/非法 Schema | strict 模式显式失败且 trace 可定位 |

成功场景中的 Critic 必须能发现一个“方案可行但过早出发或缓冲解释不足”的语义问题，并展示局部修复前后差异。每个场景绑定固定 `case_id` 和 Eval 结果，所有正常方案都必须显示 `return_scope`。

## 8. 可观测性

Trace 层级至少为：

```text
Workflow
  ├── Interpret
  ├── Route
  ├── TaskGraph
  │   ├── Agent
  │   └── Tool
  ├── Plan
  ├── Gate
  ├── Critic
  └── Repair
```

Span 记录安全字段：component、operation、status、duration、model/provider、token count、evidence count、issue count、plan version。禁止记录完整 Prompt、完整用户行程、PII 和凭证。

指标至少包括：

- workflow success/failure by stage；
- P50/P95 latency；
- LLM/Tool 调用和错误；
- evidence coverage；
- Gate blocking；
- repair attempt/success；
- token/cost；
- 当前配置和 rubric version 标签。

## 9. README 与求职材料

README 必须按以下顺序：

1. 一句话问题定义和项目价值；
2. 可运行截图/GIF；
3. 3 分钟 Quick Start；
4. 架构图和一次请求时序；
5. 关键设计：Evidence、Task Graph、Gate/Critic/Repair；
6. Eval 方法、数据集和 baseline/current 指标表；
7. 失败处理、strict 模式和安全边界；
8. 项目结构与测试命令；
9. 技术取舍和未实现扩展；
10. 面试演示脚本。

不得把未来架构写成已实现。每项能力使用 `Implemented / Planned / Extension` 明确标记。

## 10. CI 与复现

CI 至少执行：

1. 依赖安装；
2. `ruff`；
3. 类型检查；
4. unit/contract/integration；
5. offline E2E；
6. offline Eval smoke；
7. `git diff --check` 或等价检查；
8. 凭证/生成物基础扫描。

`.env.example` 只含占位符。无 API Key 时必须能运行 fixture demo、测试和离线评测；真实模式缺 Key 启动失败。

容器化为可选切片：只有本地启动和 CI 已稳定后才添加单进程 Dockerfile，不引入数据库和编排平台。

## 11. 实现顺序

1. presentation request/response/error Schema；
2. FastAPI composition root 与 health；
3. `/plan` 垂直切片；
4. run/trace/eval 只读接口；
5. API 契约和安全测试；
6. 四个差旅黄金 Demo Fixture；
7. 静态 Demo 页面；
8. Trace/Metrics 展示；
9. CI；
10. README、架构图、指标报告和演示脚本；
11. 从全新环境执行复现验收；
12. 独立 Review。

## 12. 测试矩阵

- API：合法、缺字段、超长输入、非法枚举、内部异常、超时、错误映射；
- 安全：Prompt 注入标志、PII 脱敏、CORS/Host 配置、Key/堆栈不泄露；
- Demo：四个差旅黄金场景、浏览器基本交互、返程范围和失败状态可见；
- Trace：层级、状态、版本、脱敏、失败定位；
- CI：无 Key、零网络、重复运行一致；
- 文档：命令可执行、链接有效、Implemented 标记与代码一致。

### 12.1 Live E2E Gate

M6 必须在离线测试之外由用户手动执行真实 API 验证：复用 M4.3 的一条真实成功案例，再增加一条受控失败案例验证 API 错误映射；每条运行一次。检查 Schema、硬约束、Evidence、Gate/Repair、Trace 脱敏、延迟、Token 和成本。固定预算、超时和 `retry_count=0`；真实失败阻断 M6，不得切换 Fixture/Fake 生成通过报告。Fixture Demo 只证明展示链路可复现，不证明真实 API 可用。

Codex 只负责准备启动命令、黄金案例、离线测试和脱敏报告格式；用户应通过 `start-local.ps1` 或本阶段明确的等价启动方式加载真实配置。未提供人工执行结果时，Live E2E Gate 状态为 `PENDING_MANUAL_ACCEPTANCE`，不得标记 M6 完成。



## 13. 阶段验收门

- [ ] API 只做 presentation 适配；
- [ ] 四个差旅黄金场景可离线演示；
- [ ] 政策引用、去程、候选级单晚酒店、市内交通、会议缓冲和 `return_scope` 可见；
- [ ] Task/Tool/Evidence/Gate/Repair 可观察；
- [ ] 不展示 Chain-of-Thought 或敏感信息；
- [ ] baseline/current 报告可复现；
- [ ] CI 在无真实 Key 环境通过；
- [ ] 全新环境按 README 可在 10 分钟内启动；
- [ ] strict 失败在 Demo 中清晰呈现；
- [ ] 用户手动执行的 Live E2E Gate 通过，且没有 Fake-only 验收；
- [ ] README 不把 Planned 写成 Implemented；
- [ ] 未引入 Action、SQLite、retry/cache/fallback；
- [ ] 项目标记为 `JOB_READY`。

## 14. 交付清单

- FastAPI、Schemas、错误映射和 API 测试；
- 静态 Demo 与黄金场景；
- Trace/Metrics 展示；
- CI；
- README、架构图、评测报告、演示脚本；
- M6 ADR：展示边界、Fixture Demo 与真实运行模式隔离。

## 15. 版本记录

| 版本 | 日期 | 变更 |
|:---|:---|:---|
| Frozen v1.0 | 2026-08-12 | 按快速求职目标冻结 FastAPI、静态 Demo、Trace/Metrics、CI 和 README；演示压缩为 4 个高信息场景，Live API 门压缩为 1 个成功与 1 个受控失败案例。 |
