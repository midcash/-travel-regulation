from __future__ import annotations

import os

import pytest

from evaluation.business_travel.live_runner import run_live_semantic_from_environment


@pytest.mark.slow
def test_live_semantic_requires_explicit_environment() -> None:
    if not os.environ.get("DEEPSEEK_API_KEY") or not os.environ.get("DEEPSEEK_MODEL"):
        pytest.skip("explicit live credentials are not configured")

    result = run_live_semantic_from_environment()
    assert result.status in {"LIVE_BASELINE_SUCCESS", "LIVE_ATTEMPT_RECORDED"}
