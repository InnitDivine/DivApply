from __future__ import annotations

import csv
import sqlite3

from divapply import cli
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


def test_export_jobs_includes_company_and_sorts_by_score(tmp_path, monkeypatch) -> None:
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.execute("""
        CREATE TABLE jobs (
            title TEXT,
            company TEXT,
            site TEXT,
            url TEXT,
            application_url TEXT,
            fit_score INTEGER,
            apply_status TEXT,
            discovered_at TEXT,
            scored_at TEXT,
            tailored_at TEXT,
            applied_at TEXT,
            apply_error TEXT
        )
    """)
    conn.executemany("""
        INSERT INTO jobs (
            title, company, site, url, application_url, fit_score, apply_status,
            discovered_at, scored_at, tailored_at, applied_at, apply_error
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, [
        ("Newer Lower", "Company B", "Indeed", "https://job-b", "https://apply-b", 7, None, "2026-01-02", None, None, None, None),
        ("Older Higher", "Company A", "LinkedIn", "https://job-a", "https://apply-a", 10, None, "2025-01-01", None, None, None, None),
    ])
    conn.commit()

    monkeypatch.setattr(cli, "_bootstrap", lambda: None)
    import divapply.database as database
    monkeypatch.setattr(database, "get_connection", lambda: conn)

    out = tmp_path / "jobs.csv"
    cli.export_jobs(out=out, fmt="csv")

    rows = list(csv.DictReader(out.read_text(encoding="utf-8").splitlines()))
    assert rows[0]["title"] == "Older Higher"
    assert rows[0]["company"] == "Company A"
    assert rows[0]["site"] == "LinkedIn"
