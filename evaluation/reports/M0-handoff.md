# M0 Handoff

Stage: M0

Scope: 固化 strict、零网络、fail-fast 的当前自由文本流程基线；建立 Characterization/Failure Injection 测试、Fake、网络 Guard、版本化离线评测集和报告。

Contracts: `Settings` 是 M0 配置契约；`PlanningError` 是当前 legacy 流程的显式失败契约；`baseline-v1.jsonl` 是 32 条评测用例契约。M1 领域契约尚未创建。

Migrations: `plan()` 读取注入的 strict 配置；LLM、评审、修订异常和修订耗尽不再返回部分成功；CLI 具备可测试入口并只记录安全错误摘要；旧 `knowledge.py` 不再导入时读取 `.env`，其直接环境变量读取仍属于 M3 迁移项。

Tests: `venv/Scripts/python.exe -m pytest` 通过 55 项；`venv/Scripts/python.exe -m ruff check src evaluation tests` 通过；`venv/Scripts/python.exe -m mypy` 通过；`git diff --check` 通过；覆盖率总计 86%。

Evaluation: `baseline-v1` 共 32 条；离线网络调用 0；5 条 SUCCESS、2 条显式 FAILED、25 条 `NOT_SUPPORTED`；否定约束召回 0.5，预算 L1 检测率 1.0；Token 和 API 成本标记 `UNAVAILABLE`，未估算。

Failures verified: 未配置 Key、LLM 超时、空响应、非法 JSON、评审返回非法结构、预算超支、修订轮次耗尽、工具入口缺 Key/解析失败、默认测试网络访问均有测试或 Fixture 覆盖。

Out of scope: M1 领域模型、状态仓库、Intent/Constraint Interpreter、Interaction Router、Evidence/Candidate、Task Graph、Gate、真实 Adapter、缓存、重试、fallback、部分成功和外部写操作。

Next stage prerequisites: 保持默认测试零网络；以本报告和 `baseline-v1` 作为 M1 回归基线；M1 先定义类型化领域契约、WorkflowError、StateRepository 和兼容 Facade，不能提前实现 M2+ 能力。

Current implementation limitations: 当前主链路仍是自由文本 LLM-A/L1/LLM-B；双重否定未被 Negation Guard 稳定解析；日期、人数、证据时效、工具事实和结构化规划均在评测中明确标记为 `NOT_SUPPORTED`。
