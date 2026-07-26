# M0 Baseline Report - baseline-v1

- Cases: 32
- Status: SUCCESS=5, FAILED=2, NOT_SUPPORTED=25
- Offline network calls: 0

## Metrics

| Metric | Value |
|---|---:|
| Structured parse rate | 0.0 |
| Negation constraint recall | 0.5 |
| L1 budget detection rate | 1.0 |
| Average latency (ms) | 0.184 |
| P50 latency (ms) | 0.0 |
| P95 latency (ms) | 0.774 |
| LLM calls | 8 |
| Tool calls | 0 |
| Token usage | UNAVAILABLE |
| API cost | UNAVAILABLE |

## Failures and limitations

Metrics marked `UNAVAILABLE` are not estimated. Cases marked `NOT_SUPPORTED` remain explicit M0 limitations.

| Case | Trace | Status | Failures |
|---|---|---|---|
| M0-021 | f9bc4e7647e259c88986c9a094af8588 | FAILED | failure_type=PlanningError; failure_stage=generation |
| M0-022 | 99b94c28c6075cd1a09079f288daf85b | FAILED | failure_type=PlanningError; failure_stage=generation |
