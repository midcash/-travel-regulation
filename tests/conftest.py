from __future__ import annotations

import pytest

from tests.support.network import block_network


@pytest.fixture(autouse=True)
def network_guard(request: pytest.FixtureRequest) -> object:
    if request.node.get_closest_marker('slow') is not None:
        yield None
        return
    with block_network():
        yield None
