from __future__ import annotations

import pytest

from divapply.security import UnsafeUrlError, safe_join_external_url, validate_external_url


def test_safe_join_external_url_keeps_relative_paths_on_base_host() -> None:
    assert (
        safe_join_external_url("https://jobs.example.com/careers", "/job/123")
        == "https://jobs.example.com/careers/job/123"
    )


def test_safe_join_external_url_rejects_absolute_override() -> None:
    with pytest.raises(UnsafeUrlError):
        safe_join_external_url("https://jobs.example.com/careers", "https://evil.example/job/123")


def test_validate_external_url_rejects_localhost_by_default() -> None:
    with pytest.raises(UnsafeUrlError):
        validate_external_url("http://localhost:8080/jobs")
