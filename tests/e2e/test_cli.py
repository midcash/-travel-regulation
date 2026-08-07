from __future__ import annotations

import pytest

import main
from src.application.use_cases.plan_trip import PlanTripResult
from src.config import Settings
from src.domain.models.trip_request import TripRequest


@pytest.fixture(autouse=True)
def fake_bootstrap_settings(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        main,
        'bootstrap_settings',
        lambda: Settings(
            deepseek_api_key='fake-key',
            workflow_use_case='legacy',
        ),
    )


def _result(request: TripRequest) -> PlanTripResult:
    return PlanTripResult(
        request_id=request.request_id,
        trip_id=request.trip_id,
        session_id=request.session_id,
        plan='fake plan',
        rounds=1,
        issues_found=(),
    )


def test_cli_without_arguments_uses_facade_with_default_input(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    seen: list[TripRequest] = []

    class FakeUseCase:
        def __init__(self, settings: Settings) -> None:
            assert settings.deepseek_api_key == 'fake-key'

        def execute(self, request: TripRequest) -> PlanTripResult:
            seen.append(request)
            return _result(request)

    monkeypatch.setattr(main, 'PlanTripUseCase', FakeUseCase)
    monkeypatch.setattr(main, '_print_result', lambda result: None)

    assert main.main([]) == 0
    assert len(seen) == 1
    assert '深圳' in seen[0].preferences[0]


def test_cli_with_arguments_joins_user_input_into_structured_request(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    seen: list[TripRequest] = []

    class FakeUseCase:
        def __init__(self, settings: Settings) -> None:
            pass

        def execute(self, request: TripRequest) -> PlanTripResult:
            seen.append(request)
            return _result(request)

    monkeypatch.setattr(main, 'PlanTripUseCase', FakeUseCase)
    monkeypatch.setattr(main, '_print_result', lambda result: None)

    assert main.main(['去', '广州', '两天']) == 0
    assert len(seen) == 1
    assert seen[0].preferences == ('去 广州 两天',)
    assert seen[0].duration_days == 1


def test_cli_prints_ascii_success_marker_for_windows_console(
    capsys: pytest.CaptureFixture[str],
) -> None:
    request = main._build_cli_request('上海到杭州')

    main._print_result(_result(request))

    captured = capsys.readouterr()
    assert '[PASS] 方案通过评审' in captured.out
    assert '✅' not in captured.out


def test_cli_internal_exception_returns_failure_without_traceback(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    class FailingUseCase:
        def __init__(self, settings: Settings) -> None:
            pass

        def execute(self, request: TripRequest) -> PlanTripResult:
            raise RuntimeError('secret-key must not be logged')

    monkeypatch.setattr(main, 'PlanTripUseCase', FailingUseCase)

    assert main.main(['去深圳']) == 1
    captured = capsys.readouterr()
    assert 'workflow_failed' in captured.err
    assert '{' not in captured.out
    assert '工作流失败' in captured.err
    assert 'secret-key' not in captured.out + captured.err
