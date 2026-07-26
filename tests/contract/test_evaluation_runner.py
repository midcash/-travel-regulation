from __future__ import annotations

import json
from pathlib import Path

from evaluation.runner import load_cases, load_fixtures, main, render_markdown, run_dataset


def test_baseline_dataset_has_32_schema_validated_cases() -> None:
    cases = load_cases(Path('evaluation/datasets/baseline-v1.jsonl'))

    assert len(cases) == 32
    assert cases[0].dataset_version == 'baseline-v1'
    assert cases[-1].case_id == 'M0-032'


def test_offline_runner_uses_fakes_and_reports_explicit_limits() -> None:
    cases = load_cases(Path('evaluation/datasets/baseline-v1.jsonl'))
    fixtures = load_fixtures(Path('evaluation/fixtures/baseline-v1.json'))

    report = run_dataset(cases, fixtures)

    assert report['execution']['offline'] is True
    assert report['execution']['network_calls'] == 0
    assert report['case_count'] == 32
    assert report['status_counts']['NOT_SUPPORTED'] == 25
    assert report['metrics']['negation_constraint_recall'] == 0.5
    assert report['metrics']['l1_budget_detection_rate'] == 1.0
    assert 'UNAVAILABLE' in render_markdown(report)


def test_runner_writes_machine_and_human_reports() -> None:
    json_output = Path('evaluation/reports/_test-baseline.json')
    markdown_output = Path('evaluation/reports/_test-baseline.md')
    try:
        exit_code = main(
            [
                '--dataset',
                'baseline-v1',
                '--offline',
                '--json-output',
                str(json_output),
                '--markdown-output',
                str(markdown_output),
            ]
        )

        assert exit_code == 0
        report = json.loads(json_output.read_text(encoding='utf-8'))
        assert report['dataset_version'] == 'baseline-v1'
        assert markdown_output.read_text(encoding='utf-8').startswith('# M0 Baseline Report')
    finally:
        json_output.unlink(missing_ok=True)
        markdown_output.unlink(missing_ok=True)
