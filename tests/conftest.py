from __future__ import annotations

import pytest

from tests.support.live_tool_contract import write_report
from tests.support.network import block_network


@pytest.fixture(autouse=True)
def network_guard(request: pytest.FixtureRequest) -> object:
    if request.node.get_closest_marker('slow') is not None:
        yield None
        return
    with block_network():
        yield None


def pytest_sessionfinish(session: pytest.Session, exitstatus: int) -> None:
    """Persist a report only when the live-tool contract was explicitly selected."""
    if any(item.get_closest_marker("live_tool") is not None for item in session.items):
        write_report(exit_status=exitstatus)
