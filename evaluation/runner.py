from __future__ import annotations

import argparse
import json
import statistics
import sys
import time
import uuid
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path
from typing import Any, cast
from unittest.mock import patch

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.config import Settings  # noqa: E402
from src.engine import loop  # noqa: E402
from src.guard.negation import extract_negation_constraints  # noqa: E402
from src.review.l1 import run_l1_checks  # noqa: E402

DATASET_VERSION = 'baseline-v1'
CASE_FIELDS = {
    'case_id',
    'dataset_version',
    'user_input',
    'tags',
    'fixture_refs',
    'expected_invariants',
    'forbidden_outcomes',
    'scoring_dimensions',
    'baseline_capability',
    'notes',
    'expected_negation_terms',
    'max_revision_rounds',
}
CAPABILITIES = {'EXECUTABLE', 'NOT_SUPPORTED'}


@dataclass(frozen=True, slots=True)
class BaselineCase:
    case_id: str
    dataset_version: str
    user_input: str
    tags: tuple[str, ...]
    fixture_refs: tuple[str, ...]
    expected_invariants: tuple[str, ...]
    forbidden_outcomes: tuple[str, ...]
    scoring_dimensions: tuple[str, ...]
    baseline_capability: str
    notes: str
    expected_negation_terms: tuple[str, ...]
    max_revision_rounds: int


def _require_string(value: object, field: str) -> str:
    if not isinstance(value, str):
        raise ValueError(f'{field} must be a string')
    return value


def _require_string_list(value: object, field: str) -> tuple[str, ...]:
    if not isinstance(value, list) or not value or not all(
        isinstance(item, str) and item for item in value
    ):
        raise ValueError(f'{field} must be a non-empty string list')
    return tuple(value)


def load_cases(path: Path) -> tuple[BaselineCase, ...]:
    cases: list[BaselineCase] = []
    seen: set[str] = set()
    for line_number, line in enumerate(path.read_text(encoding='utf-8').splitlines(), 1):
        if not line.strip():
            continue
        raw = json.loads(line)
        if not isinstance(raw, dict):
            raise ValueError(f'line {line_number}: case must be an object')
        if set(raw) != CASE_FIELDS:
            raise ValueError(f'line {line_number}: case schema mismatch')
        case_id = _require_string(raw['case_id'], 'case_id')
        if case_id in seen:
            raise ValueError(f'duplicate case_id: {case_id}')
        seen.add(case_id)
        version = _require_string(raw['dataset_version'], 'dataset_version')
        if version != DATASET_VERSION:
            raise ValueError(f'{case_id}: unsupported dataset version')
        capability = _require_string(raw['baseline_capability'], 'baseline_capability')
        if capability not in CAPABILITIES:
            raise ValueError(f'{case_id}: unsupported baseline capability')
        rounds = raw['max_revision_rounds']
        if not isinstance(rounds, int) or rounds < 0:
            raise ValueError(f'{case_id}: max_revision_rounds must be non-negative')
        terms = raw['expected_negation_terms']
        if not isinstance(terms, list) or not all(isinstance(item, str) for item in terms):
            raise ValueError(f'{case_id}: expected_negation_terms must be a string list')
        cases.append(
            BaselineCase(
                case_id=case_id,
                dataset_version=version,
                user_input=_require_string(raw['user_input'], 'user_input'),
                tags=_require_string_list(raw['tags'], 'tags'),
                fixture_refs=_require_string_list(raw['fixture_refs'], 'fixture_refs'),
                expected_invariants=_require_string_list(
                    raw['expected_invariants'], 'expected_invariants'
                ),
                forbidden_outcomes=_require_string_list(
                    raw['forbidden_outcomes'], 'forbidden_outcomes'
                ),
                scoring_dimensions=_require_string_list(
                    raw['scoring_dimensions'], 'scoring_dimensions'
                ),
                baseline_capability=capability,
                notes=_require_string(raw['notes'], 'notes'),
                expected_negation_terms=tuple(terms),
                max_revision_rounds=rounds,
            )
        )
    if not 30 <= len(cases) <= 50:
        raise ValueError(f'dataset must contain 30-50 cases, got {len(cases)}')
    return tuple(cases)


def load_fixtures(path: Path) -> dict[str, dict[str, object]]:
    raw = json.loads(path.read_text(encoding='utf-8'))
    if not isinstance(raw, dict) or not raw:
        raise ValueError('fixture file must be a non-empty object')
    if not all(isinstance(key, str) and isinstance(value, dict) for key, value in raw.items()):
        raise ValueError('fixture entries must be objects')
    return raw


@dataclass(frozen=True, slots=True)
class CaseResult:
    case_id: str
    trace_id: str
    status: str
    duration_ms: float
    llm_calls: int
    tool_calls: int
    token_usage: str
    invariant_failures: tuple[str, ...]
    observed_l1_issues: tuple[str, ...]


def _fixture_error(name: str) -> BaseException:
    if name == 'timeout':
        return TimeoutError('offline fixture timeout')
    if name == 'empty_response':
        return ValueError('offline fixture empty response')
    return RuntimeError(f'unsupported fixture error: {name}')


def _run_executable_case(case: BaselineCase, fixture: dict[str, object]) -> CaseResult:
    started = time.perf_counter()
    trace_id = uuid.uuid5(uuid.NAMESPACE_URL, f'{DATASET_VERSION}:{case.case_id}').hex
    responses: list[str] = []
    initial_plan = fixture.get('initial_plan')
    if isinstance(initial_plan, str):
        responses.append(initial_plan)
    revision_plans = fixture.get('revision_plans', [])
    if not isinstance(revision_plans, list) or not all(
        isinstance(item, str) for item in revision_plans
    ):
        raise ValueError(f'{case.case_id}: invalid revision_plans fixture')
    responses.extend(revision_plans)
    reviews = fixture.get('reviews', [])
    if not isinstance(reviews, list) or not all(isinstance(item, dict) for item in reviews):
        raise ValueError(f'{case.case_id}: invalid reviews fixture')
    llm_calls = 0
    review_calls = 0

    def fake_llm(prompt: str, settings: Settings | None = None) -> str:
        nonlocal llm_calls
        llm_calls += 1
        error = fixture.get('error')
        if isinstance(error, str):
            raise _fixture_error(error)
        if not responses:
            raise RuntimeError(f'{case.case_id}: fake response exhausted')
        return responses.pop(0)

    def fake_review(
        user_input: str,
        plan_text: str,
        constraints: list[str],
        *,
        settings: Settings,
    ) -> dict[str, object]:
        nonlocal review_calls
        review_calls += 1
        if not reviews:
            raise RuntimeError(f'{case.case_id}: fake review not configured')
        index = min(review_calls - 1, len(reviews) - 1)
        result = cast(dict[str, object], reviews[index])
        if not isinstance(result.get('pass'), bool):
            raise RuntimeError(f'{case.case_id}: fake review pass flag is invalid')
        return result

    observed_l1: tuple[str, ...] = ()
    failures: list[str] = []
    status = 'SUCCESS'
    constraints = extract_negation_constraints(case.user_input)
    try:
        with patch.object(loop, 'ask_llm', fake_llm), patch.object(
            loop, 'run_l2_review', fake_review
        ):
            result = loop.plan(
                case.user_input,
                max_rounds=case.max_revision_rounds,
                settings=Settings(deepseek_api_key='offline-fake'),
            )
        final_plan = result['plan']
        observed_l1 = tuple(run_l1_checks(final_plan, constraints))
        initial_for_l1 = initial_plan if isinstance(initial_plan, str) else final_plan
        initial_issues = run_l1_checks(initial_for_l1, constraints)
        if 'l1_budget_over' in case.expected_invariants and not any(
            issue.startswith('预算超支') for issue in initial_issues
        ):
            failures.append('expected budget L1 issue was not observed')
    except Exception as exc:
        status = 'FAILED'
        failures.append(f'failure_type={type(exc).__name__}')
        stage = getattr(exc, 'stage', 'unknown')
        failures.append(f'failure_stage={stage}')

    expected_status = next(
        (item.split('=', 1)[1] for item in case.expected_invariants if item.startswith('status=')),
        None,
    )
    if expected_status is not None and status != expected_status:
        failures.append(f'expected status {expected_status}, observed {status}')
    expected_stage = next(
        (
            item.split('=', 1)[1]
            for item in case.expected_invariants
            if item.startswith('failure_stage=')
        ),
        None,
    )
    if expected_stage is not None and not any(
        item == f'failure_stage={expected_stage}' for item in failures
    ):
        failures.append(f'expected failure stage {expected_stage}')
    return CaseResult(
        case_id=case.case_id,
        trace_id=trace_id,
        status=status,
        duration_ms=(time.perf_counter() - started) * 1000,
        llm_calls=llm_calls,
        tool_calls=0,
        token_usage='UNAVAILABLE',
        invariant_failures=tuple(failures),
        observed_l1_issues=observed_l1,
    )


def run_case(case: BaselineCase, fixtures: dict[str, dict[str, object]]) -> CaseResult:
    fixture_key = case.fixture_refs[0]
    if fixture_key not in fixtures:
        raise ValueError(f'{case.case_id}: missing fixture {fixture_key}')
    if case.baseline_capability == 'NOT_SUPPORTED':
        trace_id = uuid.uuid5(uuid.NAMESPACE_URL, f'{DATASET_VERSION}:{case.case_id}').hex
        return CaseResult(
            case_id=case.case_id,
            trace_id=trace_id,
            status='NOT_SUPPORTED',
            duration_ms=0.0,
            llm_calls=0,
            tool_calls=0,
            token_usage='UNAVAILABLE',
            invariant_failures=(),
            observed_l1_issues=(),
        )
    return _run_executable_case(case, fixtures[fixture_key])


def _percentile(values: list[float], fraction: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    index = min(len(ordered) - 1, round((len(ordered) - 1) * fraction))
    return round(ordered[index], 3)


def run_dataset(
    cases: Iterable[BaselineCase],
    fixtures: dict[str, dict[str, object]],
) -> dict[str, object]:
    case_list = tuple(cases)
    results = [run_case(case, fixtures) for case in case_list]
    durations = [result.duration_ms for result in results]
    supported = [result for result in results if result.status != 'NOT_SUPPORTED']
    negation_cases = [
        case for case in case_list if case.expected_negation_terms
    ]
    negation_hits = sum(
        all(
            term in extract_negation_constraints(case.user_input)
            for term in case.expected_negation_terms
        )
        for case in negation_cases
    )
    budget_cases = [
        case for case in case_list if 'l1_budget_over' in case.expected_invariants
    ]
    budget_results = {result.case_id: result for result in results}
    budget_passed = sum(
        not budget_results[case.case_id].invariant_failures for case in budget_cases
    )
    tag_counts: dict[str, int] = {}
    for case in case_list:
        for tag in case.tags:
            tag_counts[tag] = tag_counts.get(tag, 0) + 1
    failure_cases = [
        {
            'case_id': result.case_id,
            'trace_id': result.trace_id,
            'status': result.status,
            'failures': list(result.invariant_failures),
        }
        for result in results
        if result.invariant_failures
    ]
    return {
        'dataset_version': DATASET_VERSION,
        'case_count': len(results),
        'status_counts': {
            status: sum(result.status == status for result in results)
            for status in ('SUCCESS', 'FAILED', 'NOT_SUPPORTED')
        },
        'tag_counts': dict(sorted(tag_counts.items())),
        'metrics': {
            'structured_parse_rate': 0.0,
            'hard_constraint_pass_rate': 'UNAVAILABLE',
            'negation_constraint_recall': round(negation_hits / len(negation_cases), 4),
            'l1_budget_detection_rate': round(budget_passed / len(budget_cases), 4),
            'unsupported_fact_rate': 'UNAVAILABLE',
            'first_pass_success_rate': 'UNAVAILABLE',
            'repair_success_rate': 'UNAVAILABLE',
            'repair_scope_precision': 'UNAVAILABLE',
            'clarification_precision': 'UNAVAILABLE',
            'latency_ms': {
                'average': round(statistics.mean(durations), 3) if durations else None,
                'p50': _percentile(durations, 0.50),
                'p95': _percentile(durations, 0.95),
            },
            'llm_calls': sum(result.llm_calls for result in results),
            'tool_calls': sum(result.tool_calls for result in results),
            'token_usage': 'UNAVAILABLE',
            'api_cost': 'UNAVAILABLE',
        },
        'execution': {
            'offline': True,
            'network_calls': 0,
            'supported_case_count': len(supported),
            'not_supported_count': sum(result.status == 'NOT_SUPPORTED' for result in results),
        },
        'failures': failure_cases,
        'cases': [
            {
                'case_id': result.case_id,
                'trace_id': result.trace_id,
                'status': result.status,
                'duration_ms': round(result.duration_ms, 3),
                'llm_calls': result.llm_calls,
                'tool_calls': result.tool_calls,
                'token_usage': result.token_usage,
                'invariant_failures': list(result.invariant_failures),
                'observed_l1_issues': list(result.observed_l1_issues),
            }
            for result in results
        ],
    }


def render_markdown(report: dict[str, object]) -> str:
    data = cast(dict[str, Any], report)
    version = str(data['dataset_version'])
    case_count = data['case_count']
    execution = data['execution']
    statuses = data['status_counts']
    metrics = data['metrics']
    failures = data['failures']
    success_count = statuses['SUCCESS']
    failed_count = statuses['FAILED']
    unsupported_count = statuses['NOT_SUPPORTED']
    network_calls = execution['network_calls']
    structured_rate = metrics['structured_parse_rate']
    negation_recall = metrics['negation_constraint_recall']
    budget_rate = metrics['l1_budget_detection_rate']
    latency = metrics['latency_ms']
    average_latency = latency['average']
    p50_latency = latency['p50']
    p95_latency = latency['p95']
    llm_calls = metrics['llm_calls']
    tool_calls = metrics['tool_calls']
    token_usage = metrics['token_usage']
    api_cost = metrics['api_cost']
    lines = [
        f'# M0 Baseline Report - {version}',
        '',
        f'- Cases: {case_count}',
        (
            f'- Status: SUCCESS={success_count}, FAILED={failed_count}, '
            f'NOT_SUPPORTED={unsupported_count}'
        ),
        f'- Offline network calls: {network_calls}',
        '',
        '## Metrics',
        '',
        '| Metric | Value |',
        '|---|---:|',
        f'| Structured parse rate | {structured_rate} |',
        f'| Negation constraint recall | {negation_recall} |',
        f'| L1 budget detection rate | {budget_rate} |',
        f'| Average latency (ms) | {average_latency} |',
        f'| P50 latency (ms) | {p50_latency} |',
        f'| P95 latency (ms) | {p95_latency} |',
        f'| LLM calls | {llm_calls} |',
        f'| Tool calls | {tool_calls} |',
        f'| Token usage | {token_usage} |',
        f'| API cost | {api_cost} |',
        '',
        '## Failures and limitations',
        '',
        (
            'Metrics marked `UNAVAILABLE` are not estimated. Cases marked '
            '`NOT_SUPPORTED` remain explicit M0 limitations.'
        ),
    ]
    if failures:
        lines.extend(['', '| Case | Trace | Status | Failures |', '|---|---|---|---|'])
        for failure in failures:
            case_id = failure['case_id']
            trace_id = failure['trace_id']
            status = failure['status']
            failure_text = '; '.join(failure['failures'])
            lines.append(f'| {case_id} | {trace_id} | {status} | {failure_text} |')
    else:
        lines.extend(['', 'No executable invariant failures.'])
    return '\n'.join(lines) + '\n'


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description='Run the versioned offline M0 baseline.')
    parser.add_argument('--dataset', default=DATASET_VERSION)
    parser.add_argument('--offline', action='store_true')
    parser.add_argument(
        '--dataset-path',
        type=Path,
        default=Path('evaluation/datasets/baseline-v1.jsonl'),
    )
    parser.add_argument(
        '--fixture-path',
        type=Path,
        default=Path('evaluation/fixtures/baseline-v1.json'),
    )
    parser.add_argument(
        '--json-output',
        type=Path,
        default=Path('evaluation/reports/baseline-v1.json'),
    )
    parser.add_argument(
        '--markdown-output',
        type=Path,
        default=Path('evaluation/reports/baseline-v1.md'),
    )
    arguments = parser.parse_args(argv)
    if arguments.dataset != DATASET_VERSION:
        parser.error('only baseline-v1 is available in M0')
    if not arguments.offline:
        parser.error('M0 runner requires --offline')
    cases = load_cases(arguments.dataset_path)
    fixtures = load_fixtures(arguments.fixture_path)
    report = run_dataset(cases, fixtures)
    arguments.json_output.parent.mkdir(parents=True, exist_ok=True)
    arguments.json_output.write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + '\n',
        encoding='utf-8',
    )
    arguments.markdown_output.write_text(
        render_markdown(report),
        encoding='utf-8',
    )
    print(f'Wrote {arguments.json_output}')
    print(f'Wrote {arguments.markdown_output}')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
