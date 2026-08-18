---
stage: "M4.1"
case_id: "M4.1-ACC-001"
run_id: "manual-7063bfa6b8194a368fa133a10a1b61c1"
reviewer: "开发者A"
reviewed_at: "2026-08-19"
checked_assertions: ["The formal M4.1 dataset and Oracle remain unchanged.", "Evaluator errors are distinct from business assertion failures.", "A completed evaluator run with business failures remains visible as such.", "编译验证通过"]
observed_differences: []
mutation_result: "PASS"
independent_review_result: "PASS"
historical_contract_acceptance: "ACCEPTED"
business_transition_baseline: "BASELINE_FAIL"
decision: "ACCEPTED"
reason: "人工复核接受，未发现差异；变异验证通过；编译验证通过；独立复核通过。"
---

## Human assertions

- The formal M4.1 dataset and Oracle remain unchanged.
- Evaluator errors are distinct from business assertion failures.
- A completed evaluator run with business failures remains visible as such.

## Mutation target

Change first_failed_stage or business assertion in an isolated result variant.

## Independent review prompt

Review the status distinction and failure attribution against the existing M4.1 contract.
