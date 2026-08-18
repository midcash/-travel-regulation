from __future__ import annotations

import json
from pathlib import Path
from subprocess import CompletedProcess

import pytest

from evaluation.business_travel.live_runner import EvaluationConfigurationError
from evaluation.manual_acceptance.runner import (
    _llm_execution_metadata,
    _load_requested_case,
    run_manual_acceptance,
)
from evaluation.manual_acceptance.verify import verify_artifact
from src.config import Settings


def test_m1_offline_run_writes_manual_artifact(tmp_path: Path) -> None:
    result = run_manual_acceptance(
        stage="M1",
        case_id="M1-ACC-001",
        mode="offline",
        artifact_dir=tmp_path / "M1-ACC-001",
        root=Path("."),
    )

    assert result.runner_status == "OBSERVATION_READY"
    assert (tmp_path / "M1-ACC-001" / "actual.json").is_file()
    assert (tmp_path / "M1-ACC-001" / "human-review.md").is_file()
    assert verify_artifact(tmp_path / "M1-ACC-001").gate_open is False


def test_fixed_case_remains_eligible_with_dirty_source_tree(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "evaluation.manual_acceptance.runner._source_identity",
        lambda _root: ("DIRTY", "commit-with-local-changes"),
    )

    artifact_dir = tmp_path / "M1-ACC-001"
    result = run_manual_acceptance(
        stage="M1",
        case_id="M1-ACC-001",
        mode="offline",
        artifact_dir=artifact_dir,
        root=Path("."),
    )

    actual = json.loads((artifact_dir / "actual.json").read_text(encoding="utf-8"))
    runtime = json.loads((artifact_dir / "runtime.json").read_text(encoding="utf-8"))
    assert result.runner_status == "OBSERVATION_READY"
    assert actual["acceptance_eligibility"] == "ELIGIBLE"
    assert runtime["acceptance_eligibility"] == "ELIGIBLE"
    assert runtime["source_tree_status"] == "DIRTY"


def test_source_identity_ignores_manual_acceptance_report_outputs(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fake_run(command: list[str], **_: object) -> CompletedProcess[str]:
        if command[:2] == ["git", "status"]:
            return CompletedProcess(
                args=command,
                returncode=0,
                stdout="?? evaluation/reports/manual/M1/M1-ACC-001/actual.json\n",
            )
        return CompletedProcess(args=command, returncode=0, stdout="commit-1\n")

    monkeypatch.setattr("evaluation.manual_acceptance.runner.subprocess.run", fake_run)

    from evaluation.manual_acceptance.runner import _source_identity

    status, commit = _source_identity(Path("."))

    assert status == "CLEAN"
    assert commit == "commit-1"


def test_m21_actual_contains_human_viewable_event_chain(tmp_path: Path) -> None:
    artifact_dir = tmp_path / "M2.1-ACC-001"
    run_manual_acceptance(
        stage="M2.1",
        case_id="M2.1-ACC-001",
        mode="offline",
        artifact_dir=artifact_dir,
        root=Path("."),
    )

    actual = json.loads((artifact_dir / "actual.json").read_text(encoding="utf-8"))
    events = actual["events"]
    names = [event["event"] for event in events]
    assert "workflow_started" in names
    assert "stage_completed" in names
    assert names[-1] == "workflow_completed"


def test_m2_business_observation_starts_with_human_readable_semantic_summary(
    tmp_path: Path,
) -> None:
    artifact_dir = tmp_path / "M2-BT-ACC-002"
    run_manual_acceptance(
        stage="M2",
        case_id="BT-ACC-002",
        mode="offline",
        artifact_dir=artifact_dir,
        root=Path("."),
    )

    observation = (artifact_dir / "observation.md").read_text(encoding="utf-8")
    assert observation.index("## 人工先看这里") < observation.index("## 期望判断（EXPECTED）")
    assert "商务差旅范围已经确定" in observation
    assert "会议城市为“上海”" in observation
    assert "Planner 调用 0 次" in observation
    assert "运行来源：离线固定响应；真实 LLM 调用：否；网络调用：0 次。" in observation


def test_m2_business_default_assumptions_are_visible_in_observation(
    tmp_path: Path,
) -> None:
    artifact_dir = tmp_path / "M2-BT-ACC-001"
    run_manual_acceptance(
        stage="M2",
        case_id="BT-ACC-001",
        mode="offline",
        artifact_dir=artifact_dir,
        root=Path("."),
    )

    actual = json.loads((artifact_dir / "actual.json").read_text(encoding="utf-8"))
    observation = (artifact_dir / "observation.md").read_text(encoding="utf-8")
    assert actual["route_decision"]["mode"] == "plan"
    assert actual["business_scope"]["meeting"]["timezone"] == "Asia/Shanghai"
    assert {
        item["field"] for item in actual["readiness"]["assumptions"]
    } >= {"meeting_timezone", "travelers"}
    assert "会议时区根据可识别的会议城市推导为“Asia/Shanghai”" in observation
    assert "未明确人数，当前按 1 人规划" in observation
    assert "Planner 调用 0 次" in observation


@pytest.mark.parametrize(
    ("case_id", "reason", "summary"),
    [
        (
            "BT-ACC-003",
            "MULTI_TRAVELER_UNSUPPORTED",
            "当前产品只支持单人商务差旅",
        ),
        (
            "BT-ACC-004",
            "TOURISM_UNSUPPORTED",
            "当前产品专注商务差旅，旅游请求不受支持",
        ),
    ],
)
def test_m2_business_boundaries_are_human_readable_and_do_not_plan(
    case_id: str,
    reason: str,
    summary: str,
    tmp_path: Path,
) -> None:
    artifact_dir = tmp_path / case_id
    run_manual_acceptance(
        stage="M2",
        case_id=case_id,
        mode="offline",
        artifact_dir=artifact_dir,
        root=Path("."),
    )

    actual = json.loads((artifact_dir / "actual.json").read_text(encoding="utf-8"))
    observation = (artifact_dir / "observation.md").read_text(encoding="utf-8")
    assert actual["route_decision"]["mode"] == "unsupported"
    assert reason in actual["route_decision"]["reason_codes"]
    assert actual["planner_calls"] == 0
    assert actual["route_decision"]["required_capabilities"] == []
    assert summary in observation
    assert "Planner 调用 0 次" in observation


def test_offline_artifact_labels_fixture_and_zero_network_calls(tmp_path: Path) -> None:
    artifact_dir = tmp_path / "M2-BT-ACC-002"
    run_manual_acceptance(
        stage="M2",
        case_id="BT-ACC-002",
        mode="offline",
        artifact_dir=artifact_dir,
        root=Path("."),
    )

    actual = json.loads((artifact_dir / "actual.json").read_text(encoding="utf-8"))
    assert actual["llm_execution"] == {
        "source": "offline_fixture",
        "model_id": "offline-manual",
        "real_llm_called": False,
        "network_calls": 0,
    }


def test_live_metadata_labels_real_llm_and_one_network_call() -> None:
    assert _llm_execution_metadata(live=True, model_id="deepseek-v4-flash") == {
        "source": "live_llm",
        "model_id": "deepseek-v4-flash",
        "real_llm_called": True,
        "network_calls": 1,
    }


def test_live_m2_failure_keeps_safe_stage_and_call_metadata(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class FailingGateway:
        def complete(self, *_args: object, **_kwargs: object) -> str:
            raise TimeoutError("provider timeout must not be persisted")

    monkeypatch.setattr(
        "evaluation.manual_acceptance.runner.load_live_eval_settings",
        lambda _environment: Settings(
            deepseek_api_key="test-key",
            deepseek_model="deepseek-v4-flash",
        ),
    )
    monkeypatch.setattr(
        "evaluation.manual_acceptance.runner.DeepSeekLLMGateway",
        FailingGateway,
    )

    artifact_dir = tmp_path / "M2-live-failure"
    run_manual_acceptance(
        stage="M2",
        case_id="BT-ACC-002",
        mode="live",
        artifact_dir=artifact_dir,
        root=Path("."),
    )

    actual = json.loads((artifact_dir / "actual.json").read_text(encoding="utf-8"))
    assert actual["failure"]["stage"] == "request_interpreter"
    assert actual["failure"]["cause_code"] == "LLM_TIMEOUT"
    assert actual["llm_execution"] == {
        "source": "live_llm",
        "model_id": "deepseek-v4-flash",
        "real_llm_called": True,
        "network_calls": 1,
    }
    observation = (artifact_dir / "observation.md").read_text(encoding="utf-8")
    assert "运行来源：真实 DeepSeek LLM；真实 LLM 调用：是；网络调用：1 次。" in observation
    assert (
        "失败阶段：request_interpreter；错误码：INTERPRETATION_INVALID；"
        "原因码：LLM_TIMEOUT。"
    ) in observation


def test_live_configuration_blocker_is_labeled_without_claiming_a_network_call(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "evaluation.manual_acceptance.runner.load_live_eval_settings",
        lambda _environment: (_ for _ in ()).throw(
            EvaluationConfigurationError("DEEPSEEK_MODEL is required")
        ),
    )

    artifact_dir = tmp_path / "M2-live-configuration-blocked"
    run_manual_acceptance(
        stage="M2",
        case_id="BT-ACC-001",
        mode="live",
        artifact_dir=artifact_dir,
        root=Path("."),
    )

    actual = json.loads((artifact_dir / "actual.json").read_text(encoding="utf-8"))
    observation = (artifact_dir / "observation.md").read_text(encoding="utf-8")
    assert actual["llm_execution"] == {
        "source": "live_llm",
        "model_id": "not_configured",
        "real_llm_called": False,
        "network_calls": 0,
    }
    assert actual["failure"]["stage"] == "live_configuration"
    assert "运行来源：真实 DeepSeek LLM；真实 LLM 调用：否；网络调用：0 次。" in observation


def test_exploratory_input_cannot_become_acceptance(tmp_path: Path) -> None:
    artifact_dir = tmp_path / "exploratory"
    result = run_manual_acceptance(
        stage="M2",
        input_text="我当前在杭州，下周六早上8点我在上海东方明珠塔有一场会议。",
        mode="offline",
        artifact_dir=artifact_dir,
        root=Path("."),
        exploratory=True,
    )

    assert result.runner_status == "NON_ACCEPTANCE_RUN"
    actual = json.loads((artifact_dir / "actual.json").read_text(encoding="utf-8"))
    assert actual["acceptance_eligibility"] == "OBSERVATION_ONLY"


def test_exploratory_input_is_forwarded_to_live_case_in_memory() -> None:
    input_text = "我一个人从杭州到上海参加会议。"

    case = _load_requested_case(
        Path("."),
        "M2",
        None,
        input_text,
        True,
        "run-exploratory",
    )

    assert case.input == input_text


def test_exploratory_offline_input_is_blocked_instead_of_using_a_fixture(
    tmp_path: Path,
) -> None:
    artifact_dir = tmp_path / "exploratory-offline"

    result = run_manual_acceptance(
        stage="M2",
        input_text="我一个人从杭州到上海参加会议。",
        mode="offline",
        artifact_dir=artifact_dir,
        root=Path("."),
        exploratory=True,
    )

    actual = json.loads((artifact_dir / "actual.json").read_text(encoding="utf-8"))
    assert result.runner_status == "NON_ACCEPTANCE_RUN"
    assert actual["failure"]["type"] == "BLOCKED"
    assert "live" in actual["failure"]["safe_message"]


def test_live_configuration_block_is_not_replaced_by_offline(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "evaluation.manual_acceptance.runner.load_live_eval_settings",
        lambda _environment: (_ for _ in ()).throw(
            EvaluationConfigurationError("missing live credentials")
        ),
    )

    result = run_manual_acceptance(
        stage="M1",
        case_id="M1-ACC-001",
        mode="live",
        artifact_dir=tmp_path / "live-blocked",
        root=Path("."),
    )

    assert result.runner_status == "BLOCKED"
    assert verify_artifact(tmp_path / "live-blocked").gate_open is False
