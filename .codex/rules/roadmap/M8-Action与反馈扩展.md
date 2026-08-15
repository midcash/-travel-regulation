# M8：Confirmation、Action Boundary 与反馈治理（岗位定向扩展）

## 1. 阶段定位

M8 只在目标岗位需要 Agent Commerce、交易编排或长期用户闭环时启动。它不属于求职项目完成线。

本阶段建立差旅高影响动作安全边界和离线反馈治理；默认只实现 FakeActionAdapter 与人工 handoff。动作对象限定为已选 Plan 中的去程交通、该方案需要的一晚会前酒店和批准的市内交通；会议期间住宿与返程不因进入 Action 阶段而自动扩张，真实预订/付款必须另立安全评审和供应商规格。

## 2. 前置条件

- M7 生命周期、版本、持久化和并发控制验收通过；
- 计划与“已执行交易”的语义已在 API/UI 明确分离；
- 身份、权限、审计和敏感数据保存范围有 ADR；
- 目标岗位或演示用例能说明 M8 的实际收益。

## 3. 允许修改范围

- ConfirmationRequest/Service；
- G6 Action 前验证；
- ActionRepository、FeedbackRepository；
- FakeActionAdapter、人工 handoff；
- Feedback Pipeline 和离线导出；
- presentation 的 confirm/request-action/feedback；
- 安全、幂等、隐私、E2E 测试。

## 4. 禁止事项

- 未确认的预订、付款、取消或改签；
- 从普通聊天中的“好”推断 Action 授权；
- 默认接入真实支付；
- 旧 plan/evidence/confirmation 执行动作；
- retry/cache/fallback 掩盖动作失败；
- 一次点击永久写入画像；
- 在线自更新 Prompt、Router、Gate 或权重；
- 将实时报价写成长期知识。
- 为 `return_scope=not_planned` 的返程生成或执行 Action；
- 把公司政策“需要审批”误写成“已获批准”。

## 5. Confirmation 契约

```text
ConfirmationRequest
  confirmation_id
  trip_id
  plan_id
  plan_version
  scope
  action_item_ids
  policy_compliance_snapshot_ref
  evidence_snapshot_refs
  summary_hash
  risks
  expires_at
  idempotency_key
```

规则：

- 确认绑定精确 version、hash 和 scope；
- plan/evidence 变化使旧确认失效；
- “确认计划”与“确认付款”是不同 scope；
- confirmation scope 必须是 BusinessTripScope 的子集；
- 未规划返程、会议后的住宿和景点永远不能由确认文本隐式加入；
- 涨价、不可退款和显著风险必须再次确认；
- 确认有过期时间；
- 审计只保存必要信息。

## 6. G6 Action Boundary

G6 检查：

- 身份和权限；
- plan version/hash；
- confirmation scope/expiry；
- 最新价格、库存、取消条款和政策；
- 已选方案中的会前酒店与 action item 覆盖关系；
- 风险确认；
- 幂等键；
- Action Adapter allowlist。

任一事实变化：

1. 不执行；
2. 生成结构化差异；
3. 创建新 ConfirmationRequest；
4. 等待再次确认。

FakeActionAdapter 也必须实现幂等和审计回执，证明重复请求最多执行一次。

## 7. Action Repository 与回执

ActionRequest/Receipt 必须记录 action_id、scope、idempotency key、plan/confirmation version、status、provider ref、created/updated time 和安全错误。Repository 使用唯一约束保障幂等，禁止只靠进程内锁。

真实 Action Adapter 的进入条件：

- 供应商沙箱和条款明确；
- 写操作幂等语义已验证；
- 密钥、权限、退款/补偿边界已评审；
- 独立 Feature Flag，默认关闭；
- 完整审计、回滚和人工处理手册；
- 不与 M9 的自动重试同时首发。

## 8. Feedback Pipeline

FeedbackEvent 支持：

- explicit rating；
- accept/delete/replace；
- user edit distance；
- replan outcome；
- post-trip feedback；
- human correction。

处理规则：

- 原始反馈脱敏并绑定 trip/plan version；
- 区分明确偏好和推测信号；
- 写入 FeedbackRepository；
- 用户可查看、纠正和删除；
- 导出离线 evaluation dataset；
- 不直接修改在线 Profile、Prompt、Router、Gate 或权重；
- 策略变化必须离线评测、版本化发布和可回滚。

## 9. 实现顺序

1. Confirmation/Action/Feedback 契约；
2. Repository Port 和迁移；
3. ConfirmationService；
4. G6；
5. FakeActionAdapter + 幂等；
6. 人工 handoff；
7. FeedbackRepository/Pipeline；
8. 离线 Eval 导出；
9. API/CLI/Demo；
10. 安全 Review；
11. 如确有需求，另开真实 Adapter 子规格。

## 10. 测试矩阵

- Confirmation：正确/旧/过期 version、hash 变化、scope 错误；
- G6：价格/库存/条款/政策变化、已选方案会前酒店不匹配、未规划返程、越权、未确认；
- Action：重复请求、并发幂等、供应商失败、回执恢复；
- Feedback：脱敏、绑定、更正、删除、绝不在线改策略；
- E2E：确认→变化→重新确认→FakeAction；反馈→离线导出。

Confirmation、G6、幂等覆盖率 ≥ 95%。

### 10.1 Live Boundary Gate

M8 必须继承并由用户手动重跑上游 Live Smoke/Online Eval；若启用真实 LLM 或工具查询，验证最新价格、库存、条款或政策的响应可解析、Evidence 可追溯且变化会使旧确认失效。真实 LLM/工具失败阻断门禁，不得改用 Fake、缓存或旧事实。真实预订、付款、取消、改签不纳入默认 Live Gate；没有独立安全评审、供应商沙箱和真实 Adapter 子规格时，FakeAction 通过不得解释为真实交易通过。

Codex 只准备 Boundary 用例、命令、离线故障注入和脱敏报告格式，不自动执行真实 API 或真实交易。用户应通过 `start-local.ps1` 或本阶段明确的等价启动方式加载真实配置；未提供人工执行结果时，Live Boundary Gate 状态为 `PENDING_MANUAL_ACCEPTANCE`，不得标记 M8 完成。真实预订、付款、取消、改签仍须遵守独立的安全评审、供应商沙箱和最终确认边界。



## 11. 阶段验收门

- [ ] 计划生成与 Action 语义完全分离；
- [ ] 旧确认不能执行新计划；
- [ ] G6 变化必定重新确认；
- [ ] FakeAction 重复请求最多执行一次；
- [ ] Action scope 不得超出 BusinessTripScope，返程未规划时不能生成返程动作；
- [ ] 政策例外只产生审批 handoff，不伪造批准状态；
- [ ] 反馈不直接改变在线策略；
- [ ] 用户手动执行的 Live Boundary Gate（适用时）通过，且不以 FakeAction 结果替代真实 LLM/工具验证；
- [ ] 真实 Action 默认关闭或未实现；
- [ ] 无 retry/cache/fallback；
- [ ] 安全和隐私 Review 通过。

## 12. 交付清单

- ConfirmationService、G6；
- Action/Feedback Repositories；
- FakeActionAdapter、handoff、Receipt；
- Feedback Pipeline 与离线导出；
- 幂等、安全、隐私、E2E 测试；
- M8 ADR：确认作用域、Action 安全边界和反馈治理。
