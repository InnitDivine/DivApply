"""Shared helpers for DivApply localhost tools."""

from __future__ import annotations

import socket


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
