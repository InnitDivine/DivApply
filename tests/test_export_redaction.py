from __future__ import annotations

from divapply.cli import _safe_apply_error


def test_safe_apply_error_redacts_email_and_phone() -> None:
    out = _safe_apply_error("Failed for jane@example.com from 415-555-1212")
    assert "jane@example.com" not in out
    assert "[email]" in out
    assert "415-555-1212" not in out
    assert "[phone]" in out


def test_safe_apply_error_redacts_credential_kv_pairs() -> None:
    out = _safe_apply_error(
        "request failed: api_key=ABCDEFG12345HIJK token: zzzzzzzz1234 password = hunter2"
    )
    assert "ABCDEFG12345HIJK" not in out
    assert "zzzzzzzz1234" not in out
    assert "hunter2" not in out
    assert "api_key=[redacted]" in out
    assert "token=[redacted]" in out
    assert "password=[redacted]" in out


def test_safe_apply_error_redacts_bearer_and_oauth() -> None:
    out = _safe_apply_error("Authorization: Bearer eyJhbGciOiJIUzI1NiJ9.payload.sig")
    assert "eyJhbGciOiJIUzI1NiJ9" not in out
    assert "Bearer [redacted]" in out

    out2 = _safe_apply_error("token oauth:abcdef0123456789")
    assert "abcdef0123456789" not in out2
    assert "oauth:[redacted]" in out2


def test_safe_apply_error_redacts_long_opaque_strings() -> None:
    long_token = "A" * 40
    out = _safe_apply_error(f"unexpected response cookie={long_token}")
    assert long_token not in out
    assert "[redacted-key]" in out


def test_safe_apply_error_handles_blank_input() -> None:
    assert _safe_apply_error(None) == ""
    assert _safe_apply_error("") == ""
