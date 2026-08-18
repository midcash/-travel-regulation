---
stage: "M3"
case_id: "M3-ACC-001"
run_id: "manual-f5f9efaec01b4138a46555d0099c19f2"
reviewer: "开发者A"
reviewed_at: "2026-08-19"
checked_assertions: ["Every accepted candidate references an Evidence item.", "Evidence exposes source, observed_at and validity information.", "Failure and empty-result paths remain distinguishable.", "编译验证通过"]
observed_differences: []
mutation_result: "PASS"
independent_review_result: "PASS"
historical_contract_acceptance: "ACCEPTED"
business_transition_baseline: "BASELINE_FAIL"
decision: "ACCEPTED"
reason: "人工复核接受，未发现差异；变异验证通过；编译验证通过；独立复核通过。"
---

## Human assertions

- Every accepted candidate references an Evidence item.
- Evidence exposes source, observed_at and validity information.
- Failure and empty-result paths remain distinguishable.

## Mutation target

Remove an Evidence reference or convert an empty result into a candidate in an isolated variant.

## Independent review prompt

Review candidate-to-evidence references and failure semantics independently.
