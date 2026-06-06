from __future__ import annotations

import socket

import pytest

from divapply.security import (
    UnsafeUrlError,
    collect_known_secret_values,
    redact_known_secrets,
    safe_join_external_url,
    sanitize_external_url,
    validate_external_url,
)


def test_safe_join_external_url_keeps_relative_paths_on_base_host() -> None:
    assert (
        safe_join_external_url("https://jobs.example.com/careers", "/job/123")
        == "https://jobs.example.com/careers/job/123"
    )


def test_safe_join_external_url_rejects_absolute_override() -> None:
    with pytest.raises(UnsafeUrlError):
        safe_join_external_url("https://jobs.example.com/careers", "https://evil.example/job/123")


def test_safe_join_external_url_rejects_scheme_relative_override() -> None:
    with pytest.raises(UnsafeUrlError):
        safe_join_external_url("https://jobs.example.com/careers", "//evil.example/job/123")


def test_validate_external_url_rejects_localhost_by_default() -> None:
    with pytest.raises(UnsafeUrlError):
        validate_external_url("http://localhost:8080/jobs")


def test_validate_external_url_rejects_non_http_and_embedded_credentials() -> None:
    for value in ("file:///C:/Users/Dearr/.ssh/id_rsa", "https://user:pass@jobs.example.com/apply"):
        with pytest.raises(UnsafeUrlError):
            validate_external_url(value)


def test_validate_external_url_rejects_private_and_metadata_addresses() -> None:
    for value in ("http://10.0.0.5/jobs", "http://169.254.169.254/latest/meta-data"):
        with pytest.raises(UnsafeUrlError):
            validate_external_url(value)


def test_validate_external_url_rejects_dns_names_resolving_private(monkeypatch) -> None:
    monkeypatch.setattr(
        socket,
        "getaddrinfo",
        lambda *args, **kwargs: [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("192.168.1.10", 443))],
    )

    with pytest.raises(UnsafeUrlError):
        validate_external_url("https://jobs.example.com/posting")


def test_validate_external_url_allows_private_urls_only_when_explicitly_enabled(monkeypatch) -> None:
    monkeypatch.setenv("DIVAPPLY_ALLOW_PRIVATE_URLS", "true")

    assert validate_external_url("http://127.0.0.1:8080/jobs") == "http://127.0.0.1:8080/jobs"


def test_sanitize_external_url_returns_none_for_optional_unsafe_links() -> None:
    assert sanitize_external_url("file:///tmp/secret") is None
    assert sanitize_external_url("https://jobs.example.com/apply") == "https://jobs.example.com/apply"


def test_redact_known_secrets_removes_values_and_common_credentials(monkeypatch) -> None:
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test-secret-token")
    secrets = collect_known_secret_values({"credentials": {"password": "hunter2secret"}})
    text = "password=hunter2secret token=abc12345 Authorization: Bearer sk-test-secret-token"

    redacted = redact_known_secrets(text, secrets)

    assert "hunter2secret" not in redacted
    assert "sk-test-secret-token" not in redacted
    assert "abc12345" not in redacted
    assert "[redacted]" in redacted
