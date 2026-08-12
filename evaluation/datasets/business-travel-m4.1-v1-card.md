# business-travel-m4.1-v1 Dataset Card

## Scope

国内单人商务差旅，规划边界为 `meeting_arrival_ready`：从出发地到首场会议的 `required_arrival_at`。正式集包含 12 条 Golden Case；开发集 `business-travel-m4.1-dev-v1` 包含 6 条不同输入文本的变体。

## Frozen policies

- `timing-policy-cn-domestic-v1`
- `pre-meeting-lodging-policy-v1`
- `meeting-readiness-policy-v1`
- `universal-business-travel-policy-v1`
- `repetition-policy-m4.1-v1`

## Behavior coverage

正式集覆盖当日到达、会前一晚住宿、候选级混合住宿、跨午夜、会议地点/时间澄清、政策限制、酒店价格口径、住宿失败隔离、不可达路线、政策冲突/过期、返程范围披露、供应商异常、原 M4 交通候选回归和景点禁止输出。

## Live stability subset

Blocking cases：`BT-M41-001`、`BT-M41-003`、`BT-M41-005`、`BT-M41-012`，每案例三次；观察案例最多八条，每案例一次。Live Semantic 只运行 G0、Interpreter、Constraint、Readiness、Router，不启动 Planner、Task Graph、Composer 或工具。

## Privacy and limitations

案例文本为脱敏合成输入，不包含真实公司、员工、联系方式、证件或真实行程。数据不证明现实世界绝对准时，也不覆盖国际、多人数、返程交易、景点规划、预订付款或个性化员工政策。
