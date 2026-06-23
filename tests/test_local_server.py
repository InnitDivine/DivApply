import socket
from contextlib import contextmanager
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Iterator

import pytest

from divapply.local_server import bind_local_server, find_free_port


@contextmanager
def _reserve_first_of_consecutive_free_ports(host: str) -> Iterator[socket.socket]:
    for base in range(20000, 65000):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as first:
            try:
                first.bind((host, base))
            except OSError:
                continue
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as second:
                try:
                    second.bind((host, base + 1))
                except OSError:
                    continue
                first.listen()
                yield first
                return
    raise RuntimeError("No consecutive free localhost ports available for test.")


def test_find_free_port_skips_occupied_port() -> None:
    host = "127.0.0.1"
    with _reserve_first_of_consecutive_free_ports(host) as occupied:
        occupied_port = occupied.getsockname()[1]
        free_port = find_free_port(host, occupied_port, attempts=25)

    assert free_port != occupied_port


def test_find_free_port_raises_when_attempts_are_exhausted() -> None:
    host = "127.0.0.1"
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as occupied:
        occupied.bind((host, 0))
        occupied.listen()
        occupied_port = occupied.getsockname()[1]

        with pytest.raises(RuntimeError, match="No free localhost port found"):
            find_free_port(host, occupied_port, attempts=1)


def test_bind_local_server_skips_occupied_port_atomically() -> None:
    class Handler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:  # noqa: N802
            self.send_response(204)
            self.end_headers()

    host = "127.0.0.1"
    with _reserve_first_of_consecutive_free_ports(host) as occupied:
        occupied_port = occupied.getsockname()[1]
        server, actual_port = bind_local_server(ThreadingHTTPServer, Handler, host, occupied_port, attempts=25)

    try:
        assert actual_port != occupied_port
        assert server.server_address[1] == actual_port
    finally:
        server.server_close()
