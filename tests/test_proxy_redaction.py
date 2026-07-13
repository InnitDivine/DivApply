from __future__ import annotations

import logging

import pytest

from divapply.discovery.jobspy import parse_proxy
from divapply.discovery import workday


def test_jobspy_invalid_proxy_error_never_echoes_secret() -> None:
    with pytest.raises(ValueError) as captured:
        parse_proxy("proxy.example:8080:user:super-secret-password:extra")

    assert "super-secret-password" not in str(captured.value)
    assert "Expected: host:port:user:pass or host:port" in str(captured.value)


def test_workday_invalid_proxy_warning_never_echoes_secret(caplog) -> None:
    with caplog.at_level(logging.WARNING):
        workday.setup_proxy("proxy.example:8080:user:super-secret-password:extra")

    assert "super-secret-password" not in caplog.text
    assert "Proxy format not recognized" in caplog.text
