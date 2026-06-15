"""Shared helpers for DivApply localhost tools."""

from __future__ import annotations

import socket
from http.server import ThreadingHTTPServer
from typing import TypeVar

ServerT = TypeVar("ServerT", bound=ThreadingHTTPServer)


def find_free_port(host: str, preferred: int, *, attempts: int = 25) -> int:
    """Return the first bindable port starting at ``preferred``."""
    for port in range(preferred, preferred + attempts):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
            try:
                sock.bind((host, port))
            except OSError:
                continue
            return port
    raise RuntimeError(f"No free localhost port found from {preferred} to {preferred + attempts - 1}.")


def bind_local_server(
    server_cls: type[ServerT],
    handler_cls: type,
    host: str,
    preferred: int,
    *,
    attempts: int = 25,
) -> tuple[ServerT, int]:
    """Bind a localhost HTTP server atomically while scanning fallback ports."""
    last_error: OSError | None = None
    for port in range(preferred, preferred + attempts):
        try:
            return server_cls((host, port), handler_cls), port
        except OSError as exc:
            last_error = exc
            continue
    message = f"No free localhost port found from {preferred} to {preferred + attempts - 1}."
    if last_error is not None:
        raise RuntimeError(message) from last_error
    raise RuntimeError(message)
