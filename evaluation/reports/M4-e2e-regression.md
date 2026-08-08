# M4 端到端链路重新验证记录

Date: 2026-08-08
Status: `PASSED`

## 修复范围

- 新增并接入 `GeoResearchAgent`，对 origin 和全部 destinations 逐地点查询，任一失败则整体失败；
- 用确定性 `M4InputResolver` 将冻结 `ConstraintSnapshot` 同步到 M4 `TripRequest`；
- Router 只为显式地点类别创建 `place`，只为显式上下文类型创建 `context`；
- G1 对参考日期之前的日期范围生成 `DATE_RANGE_IN_PAST` blocker；
- Facade 在原始失败已持久化时读取权威状态，不重复记录误导性的状态持久化错误。

## 回归结果

- Geo 成功、空结果、工具错误、超时、Schema 错误、预算耗尽和部分失败：通过；
- Snapshot→TripRequest 的 origin、destinations、date_range、travelers、budget/preferences：通过；
- `geo` 先于 transport/stay/place：通过；
- Future Fake Provider vertical slice：通过，生成候选、排程和预算；
- Past-date CLI/Facade path：以 G1 blocker 结束，未调用外部工具；
- Root failure persistence propagation：通过；
- 全量：`637 passed, 8 deselected`；覆盖率 `93.48%`；Ruff 通过。

## Live 状态

`start-local.ps1 -EnvFile .env -LiveM4` 已使用真实 LLM 和途牛配置完成 4 次 Live Vertical Slice 运行：normal 重复 2 次、constraint 1 次、complex 1 次。报告状态为 `SUCCESS`，Evidence/Candidate 引用、硬约束、硬预算和 fail-fast 策略均通过；未启用 fallback、重试、缓存或部分成功。

M4 端到端链路验收通过，M4 阶段可以闭合；M5 仍未启动。
