---
stage: "M1"
case_id: "M1-ACC-001"
run_id: "manual-e145c3185c4b4fcaa91de51a0674fc7b"
reviewer: "开发者A"
reviewed_at: "2026-08-19"
checked_assertions: ["The valid request is a Pydantic-validated TripRequest.", "The invalid request exposes a Schema validation error rather than being accepted.", "The two outcomes are displayed separately.", "编译验证通过"]
observed_differences: []
mutation_result: "PASS"
independent_review_result: "PASS"
historical_contract_acceptance: "ACCEPTED"
business_transition_baseline: "NOT_APPLICABLE"
decision: "ACCEPTED"
reason: "人工复核接受，未发现差异；变异验证通过；编译验证通过；独立复核通过。"
---

## Human assertions

- The valid request is a Pydantic-validated TripRequest.
- The invalid request exposes a Schema validation error rather than being accepted.
- The two outcomes are displayed separately.

## Mutation target

Remove one required typed field in an isolated variant and confirm validation fails.

## Independent review prompt

Review the typed request and validation error without relying on test names.
