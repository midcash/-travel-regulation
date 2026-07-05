# Handoff — 试点编码启动

## 当前状态

**项目版本**: `1.0.0-dev`（未发布）
**分支**: `main`
**阶段**: 约束修补完成，准备试点编码

## 已完成工作

### 第一批修补（progress/ 碎片化 + ROADMAP + .gitmessage）
- `progress/` 拆分为 8 个模块碎片 + 1 个 README 索引
- `ROADMAP.md` 定义 v1.0.0 范围
- `.gitmessage` 定义 commit 格式 `[module] type: 描述`

### 约束推演（4 链并行 walkthrough）
- Chain A: code_agent §6 ↔ code_quality_rubric
- Chain B: spec ↔ test_scenarios
- Chain C: gate_definitions ↔ evaluator playbook
- Chain D: agent_contract ↔ playbooks

### 必须修复项（5项）
1. Gate 2 伪代码增加 <60 → REJECT 分支
2. CLAUDE.md Quality Gate 表对齐 gate_definitions 二进制逻辑
3. Code Agent §6 增加性能自检（算法复杂度/重复计算/缓存）
4. Code Agent §6 增加测试覆盖率自检（≥ 70%）
5. agent_contract 增加 response.result 和 control.abort 消息类型

### 阻塞级修复项（6项，通过并行子 agent 完成）
1. `spec/orchestrator_spec.md` — 路由表新增 `task.revise_itinerary`
2. 4 个 playbooks + code_agent.md — retry/timeout/backoff 策略统一引用 agent_contract.md
3. `spec/agent_contract.md` — 新增 §3.2 TaskType 枚举（11个值）
4. `evaluation/gate_definitions.md` — Gate 2 新增维度级告警检查（5维度 < 3 → Warning，≥3 → blocking）
5. `evaluation/test_scenarios.md` — 新增 TS-EXEC-001~009（执行 Agent 核心检查函数）
6. `evaluation/test_scenarios.md` — 新增 TS-ORCH-001~009（编排器错误恢复）

### 版本号统一
- 全项目 15 个 changelog 条目统一为 `1.0.0`，与 `VERSION` 对齐

## 未修复项（在试点编码中按需处理）

**重要级（~15项）**:
- TaskType 枚举在各 playbook 中的引用
- 评分粒度不统一（6 vs 3 vs 2 级）
- evaluator response types 独立定义
- playbooks 未引用 error_codes
- 13 个基础设施接口无 test scenarios
- Code Agent §6 安全覆盖过窄
- Code Agent §6 自评项不映射 rubric 维度
- 等等

**优化级（~24项）**:
- LOO 协议细节
- Mode A 不在 test_scenarios 中
- 等等

## 下一步：试点编码

**目标**: 实现 `core/message.py` + `core/context.py`，跑通完整 Dev Agent Pipeline

**Pipeline**: Context Agent → Plan Agent → Code Agent → Test Agent → Evaluation Agent (Mode A)

**流程**:
1. 启动 Context Agent（扫描 spec/、playbooks/、evaluation/、progress/，输出上下文摘要）
2. 启动 Plan Agent（设计 message.py + context.py 实现方案，分解原子任务）
3. 启动 Code Agent（按 Plan 编写代码）
4. 启动 Test Agent（编写测试，覆盖率 ≥ 70%）
5. 启动 Evaluation Agent (Mode A)（按 code_quality_rubric 评分）
6. 若未通过质量门 → 退回 Code/Test Agent，最多 3 轮

## 关键文件索引

| 文件 | 用途 |
|------|------|
| `CLAUDE.md` | 项目总览、架构、Pipeline 规则 |
| `VERSION` | 版本号 `1.0.0-dev` |
| `spec/agent_contract.md` | Agent 通信契约（消息格式/TaskType/错误处理/超时重试） |
| `spec/system_spec.md` | 系统架构规格 |
| `spec/orchestrator_spec.md` | Orchestrator 接口规格 |
| `devagents/context_agent.md` | Context Agent 约束 |
| `devagents/plan_agent.md` | Plan Agent 约束 |
| `devagents/code_agent.md` | Code Agent 约束（含 §6 质量自检清单） |
| `devagents/test_agent.md` | Test Agent 约束 |
| `evaluation/code_quality_rubric.md` | Mode A 代码质量评分量表 |
| `evaluation/gate_definitions.md` | 质量门定义（Gate 0-3，含维度告警） |
| `evaluation/test_scenarios.md` | 41个测试场景 |
| `playbooks/evaluator_playbook.md` | Evaluation Agent 操作手册 |
| `progress/` | 各模块进度碎片 |
