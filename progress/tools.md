# tools/ — 进度跟踪

**所属阶段**: Phase 0: 基础设施

---

## 文档-代码同步状态

| spec 文件 | spec commit | 对应代码 | 同步状态 | 备注 |
|-----------|-------------|---------|---------|------|
| `spec/executor_spec.md` §2.2 | HEAD | `tools/price_checker.py` | 已完成 | check_prices() / check_budget_compliance() / estimate_market_price() |
| `spec/executor_spec.md` §2.3 | HEAD | `tools/time_checker.py` | 已完成 | check_time() / check_opening_hours() / calculate_transit_time() |
| `spec/executor_spec.md` §2.4 | HEAD | `tools/geo_checker.py` | 已完成 | check_geography() / validate_geography() (Haversine + 贪心) |
| `spec/executor_spec.md` §2.6 | HEAD | `tools/risk_checker.py` | 已完成 | check_weather_risk() / check_travel_requirements() |

> **spec commit**: 上次确认同步时 spec 文件的 commit hash。检查漂移: `git diff <spec_commit>..HEAD -- <spec_file>`

---

## 任务历史

| 日期 | 任务 | 状态 | 备注 |
|------|------|------|------|
| 2026-07-06 | 实现 tools/price_checker.py | 已完成 | stub 实现，内置参考价格表，check_prices/check_budget_compliance/estimate_market_price |
| 2026-07-06 | 实现 tools/time_checker.py | 已完成 | stub 实现，Haversine距离+午餐/晚餐冲突检测 |
| 2026-07-06 | 实现 tools/geo_checker.py | 已完成 | stub 实现，贪心最优路径+绕路比计算 |
| 2026-07-06 | 实现 tools/risk_checker.py | 已完成 | stub 实现，内置天气/签证/安全风险数据库 |
| 2026-07-06 | 实现 tools/__init__.py | 已完成 | 10个公共函数统一导出 |
| 2026-07-06 | 编写 tests/test_tools.py | 已完成 | 45 tests，覆盖TS-EXEC-001~009全部价格/时间/地理场景 |
| 2026-07-06 | Batch 5: API 接入改造 | 已完成 | price: AmadeusPriceClient + 降级; geo: NominatimClient + geocode_async + 降级; time: MapboxDirectionsClient + 降级; 全部保留 stub fallback + degraded 标记 |
