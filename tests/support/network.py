from __future__ import annotations

import socket
import urllib.request
from collections.abc import Iterator
from contextlib import contextmanager


class NetworkAccessError(AssertionError):
    pass


class GuardedSocket(socket.socket):
    def connect(self, address: object) -> None:
        raise NetworkAccessError('默认测试禁止网络访问')

    def connect_ex(self, address: object) -> int:
        raise NetworkAccessError('默认测试禁止网络访问')


@contextmanager
def block_network() -> Iterator[None]:
    original_socket = socket.socket
    original_create_connection = socket.create_connection
    original_urlopen = urllib.request.urlopen

    def denied_create_connection(*args: object, **kwargs: object) -> None:
        raise NetworkAccessError('默认测试禁止网络访问')

    def denied_urlopen(*args: object, **kwargs: object) -> None:
        raise NetworkAccessError('默认测试禁止网络访问')

    socket.socket = GuardedSocket
    socket.create_connection = denied_create_connection
    urllib.request.urlopen = denied_urlopen
    try:
        yield
    finally:
        socket.socket = original_socket
        socket.create_connection = original_create_connection
        urllib.request.urlopen = original_urlopen
