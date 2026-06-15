import socket

import pytest

from divapply.local_server import find_free_port


def _find_consecutive_free_ports(host: str) -> int:
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
                return base
    raise RuntimeError("No consecutive free localhost ports available for test.")


def test_find_free_port_skips_occupied_port() -> None:
    host = "127.0.0.1"
    occupied_port = _find_consecutive_free_ports(host)
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as occupied:
        occupied.bind((host, occupied_port))
        occupied.listen()

        free_port = find_free_port(host, occupied_port, attempts=2)

    assert free_port == occupied_port + 1


def test_find_free_port_raises_when_attempts_are_exhausted() -> None:
    host = "127.0.0.1"
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as occupied:
        occupied.bind((host, 0))
        occupied.listen()
        occupied_port = occupied.getsockname()[1]

        with pytest.raises(RuntimeError, match="No free localhost port found"):
            find_free_port(host, occupied_port, attempts=1)
