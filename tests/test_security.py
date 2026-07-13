from __future__ import annotations

import socket
import sys

import pytest

from divapply.security import (
    PrivateFileError,
    UnsafeUrlError,
    collect_known_secret_values,
    copy_private_file,
    local_request_is_same_origin,
    open_private_text,
    parse_local_form_length,
    redact_known_secrets,
    redact_url_for_log,
    safe_join_external_url,
    sanitize_external_url,
    validate_external_url,
    write_private_text,
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
    for value in (
        "http://10.0.0.5/jobs",
        "http://[::1]:8080/jobs",
        "http://169.254.169.254/latest/meta-data",
        "http://metadata.google.internal/computeMetadata/v1/",
    ):
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


def test_local_form_length_rejects_invalid_or_large_bodies() -> None:
    assert parse_local_form_length("42") == 42

    with pytest.raises(ValueError):
        parse_local_form_length("-1")

    with pytest.raises(ValueError):
        parse_local_form_length("not-a-number")

    with pytest.raises(ValueError):
        parse_local_form_length(str(64 * 1024 + 1))


def test_local_same_origin_accepts_local_origin_and_rejects_cross_site() -> None:
    assert local_request_is_same_origin(
        {"Host": "127.0.0.1:8765", "Origin": "http://127.0.0.1:8765"},
        "127.0.0.1",
        8765,
    )
    assert local_request_is_same_origin(
        {"Host": "localhost:8765", "Referer": "http://localhost:8765/?saved=1"},
        "127.0.0.1",
        8765,
    )

    assert not local_request_is_same_origin({"Origin": "https://evil.example"}, "127.0.0.1", 8765)
    assert not local_request_is_same_origin({"Referer": "https://evil.example/form"}, "127.0.0.1", 8765)


def test_local_same_origin_rejects_host_header_mismatch() -> None:
    assert not local_request_is_same_origin(
        {
            "Host": "evil.example:8765",
            "Origin": "http://127.0.0.1:8765",
        },
        "127.0.0.1",
        8765,
    )
    assert not local_request_is_same_origin({"Host": "127.0.0.1:9999"}, "127.0.0.1", 8765)


def test_write_private_text_writes_content(tmp_path) -> None:
    path = tmp_path / "nested" / "secret.txt"

    write_private_text(path, "secret-value")

    assert path.read_text(encoding="utf-8") == "secret-value"


def test_copy_private_file_promotes_protected_content(tmp_path) -> None:
    source = tmp_path / "source.txt"
    target = tmp_path / "private" / "target.txt"
    source.write_text("private-copy", encoding="utf-8")

    copy_private_file(source, target)

    assert target.read_text(encoding="utf-8") == "private-copy"
    assert list(target.parent.glob(f".{target.name}.*.tmp")) == []


def test_copy_private_file_cleans_temporary_on_acl_failure(tmp_path, monkeypatch) -> None:
    import divapply.security as security

    source = tmp_path / "source.txt"
    target = tmp_path / "private" / "target.txt"
    source.write_text("private-copy", encoding="utf-8")
    monkeypatch.setattr(
        security,
        "protect_file",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(PrivateFileError("ACL denied")),
    )

    with pytest.raises(PrivateFileError, match="ACL denied"):
        security.copy_private_file(source, target)

    assert not target.exists()
    assert list(target.parent.glob(f".{target.name}.*.tmp")) == []


def test_open_private_text_creates_strict_user_private_file(tmp_path) -> None:
    path = tmp_path / "private.log"

    with open_private_text(path, mode="w", strict=True) as handle:
        handle.write("private")

    assert path.read_text(encoding="utf-8") == "private"
    if sys.platform != "win32":
        assert path.stat().st_mode & 0o777 == 0o600


def test_open_private_text_refuses_symlink_target(tmp_path) -> None:
    outside = tmp_path / "outside.txt"
    outside.write_text("keep", encoding="utf-8")
    linked = tmp_path / "linked.log"
    try:
        linked.symlink_to(outside)
    except OSError as exc:
        pytest.skip(f"symlinks unavailable: {exc}")

    with pytest.raises(PrivateFileError, match="link or reparse"):
        with open_private_text(linked, mode="w", strict=True):
            pass
    assert outside.read_text(encoding="utf-8") == "keep"


def test_windows_private_file_acl_uses_current_user_sid(tmp_path, monkeypatch) -> None:
    import divapply.security as security

    path = tmp_path / "windows-private.log"
    path.write_text("private", encoding="utf-8")
    calls: list[list[str]] = []
    monkeypatch.setattr(security.sys, "platform", "win32")
    monkeypatch.setattr(security, "_windows_current_sid", lambda: "S-1-5-21-1234")
    monkeypatch.setattr(security, "_set_windows_user_only_dacl", lambda _path, _sid: None)
    monkeypatch.setattr(
        security.subprocess,
        "run",
        lambda command, **_kwargs: calls.append(command),
    )

    security.protect_file(path, strict=True)

    assert calls == [
        [
            "icacls",
            str(path),
            "/inheritancelevel:r",
            "/grant:r",
            "*S-1-5-21-1234:F",
            "/Q",
        ]
    ]


def test_strict_windows_private_file_acl_failure_is_explicit(tmp_path, monkeypatch) -> None:
    import divapply.security as security

    path = tmp_path / "windows-private.log"
    path.write_text("private", encoding="utf-8")
    monkeypatch.setattr(security.sys, "platform", "win32")
    monkeypatch.setattr(security, "_windows_current_sid", lambda: "S-1-5-21-1234")
    monkeypatch.setattr(
        security.subprocess,
        "run",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(OSError("ACL denied")),
    )

    with pytest.raises(PrivateFileError, match="private permissions"):
        security.protect_file(path)


def test_database_connection_hardens_sqlite_files(tmp_path, monkeypatch) -> None:
    from divapply import database
    import divapply.security as security

    db_path = tmp_path / "private" / "divapply.db"
    files: list[tuple[object, bool]] = []
    monkeypatch.setattr(
        security,
        "protect_file",
        lambda path, *, strict=False: files.append((path, strict)),
    )

    conn = database.get_connection(db_path)
    conn.execute("CREATE TABLE secure_test (id INTEGER)")
    conn.commit()
    database.close_connection(db_path)

    assert (db_path, True) in files


def test_redact_url_for_log_drops_credentials_query_and_fragment() -> None:
    redacted = redact_url_for_log(
        "https://user:password@jobs.example.test/apply?token=secret-value&candidate=42#private"
    )

    assert redacted == "https://jobs.example.test/apply"
