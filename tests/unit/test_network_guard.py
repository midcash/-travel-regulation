from __future__ import annotations

import socket

import pytest

from tests.support.network import NetworkAccessError


def test_default_test_fixture_blocks_socket_connections() -> None:
    with pytest.raises(NetworkAccessError):
        socket.create_connection(('example.com', 443), timeout=0.1)
