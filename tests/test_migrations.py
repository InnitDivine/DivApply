from __future__ import annotations

import sqlite3

from divapply.database import close_connection, ensure_coursework_table, init_db


def test_init_db_sets_schema_user_version(tmp_path) -> None:
    db_path = tmp_path / "divapply.db"
    conn = init_db(db_path)

    version = conn.execute("PRAGMA user_version").fetchone()[0]
    event_table = conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name='application_events'"
    ).fetchone()

    columns = {row[1] for row in conn.execute("PRAGMA table_info(jobs)").fetchall()}

    assert version >= 4
    assert {"score_attempts", "score_error", "score_retry_at"}.issubset(columns)
    assert event_table is not None
    close_connection(db_path)


def test_init_db_repairs_legacy_jobs_table_missing_apply_status_before_indexes(tmp_path) -> None:
    db_path = tmp_path / "legacy.db"
    legacy = sqlite3.connect(db_path)
    legacy.execute("""
        CREATE TABLE jobs (
            url TEXT PRIMARY KEY,
            title TEXT,
            discovered_at TEXT
        )
    """)
    legacy.execute(
        "INSERT INTO jobs (url, title, discovered_at) VALUES (?, ?, ?)",
        ("https://example.com/old", "Old Job", "2025-01-01"),
    )
    legacy.commit()
    legacy.close()

    conn = init_db(db_path)
    columns = {row[1] for row in conn.execute("PRAGMA table_info(jobs)").fetchall()}
    indexes = {row[1] for row in conn.execute("PRAGMA index_list(jobs)").fetchall()}
    row = conn.execute("SELECT url, apply_status, archived_at FROM jobs").fetchone()

    assert "apply_status" in columns
    assert "canonical_key" in columns
    assert "archived_at" in columns
    assert "idx_jobs_apply_status" in indexes
    assert row["url"] == "https://example.com/old"
    assert row["apply_status"] is None
    assert row["archived_at"] is None
    close_connection(db_path)


def test_init_db_repairs_legacy_application_events_missing_nullable_columns(tmp_path) -> None:
    db_path = tmp_path / "events.db"
    legacy = sqlite3.connect(db_path)
    legacy.execute("CREATE TABLE jobs (url TEXT PRIMARY KEY, applied_at TEXT)")
    legacy.execute(
        "INSERT INTO jobs (url, applied_at) VALUES (?, ?)",
        ("https://example.com/applied", "2026-06-20T00:00:00+00:00"),
    )
    legacy.execute(
        """
        CREATE TABLE application_events (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            job_url TEXT NOT NULL,
            event_type TEXT NOT NULL,
            ts TEXT NOT NULL
        )
        """
    )
    legacy.commit()
    legacy.close()

    conn = init_db(db_path)

    event_columns = {row[1] for row in conn.execute("PRAGMA table_info(application_events)").fetchall()}
    event = conn.execute(
        "SELECT event_type, notes, follow_up_at, created_at FROM application_events WHERE job_url = ?",
        ("https://example.com/applied",),
    ).fetchone()

    assert {"notes", "follow_up_at", "created_at"}.issubset(event_columns)
    assert event["event_type"] == "applied"
    assert event["notes"] == "Backfilled from jobs.applied_at"
    assert event["follow_up_at"] is None
    assert event["created_at"] is not None
    close_connection(db_path)


def test_retryable_scoring_migration_requeues_legacy_llm_error(tmp_path) -> None:
    db_path = tmp_path / "legacy-score.db"
    legacy = sqlite3.connect(db_path)
    legacy.execute(
        """
        CREATE TABLE jobs (
            url TEXT PRIMARY KEY,
            fit_score INTEGER,
            score_reasoning TEXT,
            risk_flags TEXT,
            scored_at TEXT
        )
        """
    )
    legacy.execute(
        "INSERT INTO jobs (url, fit_score, score_reasoning, risk_flags, scored_at) VALUES (?, ?, ?, ?, ?)",
        (
            "https://example.com/retry-score",
            0,
            "LLM error: temporary outage",
            "llm_error",
            "2026-07-10T00:00:00+00:00",
        ),
    )
    legacy.execute("PRAGMA user_version = 3")
    legacy.commit()
    legacy.close()

    conn = init_db(db_path)
    row = conn.execute(
        "SELECT fit_score, scored_at, score_attempts, score_error, score_retry_at FROM jobs"
    ).fetchone()

    assert row["fit_score"] is None
    assert row["scored_at"] is None
    assert row["score_attempts"] == 1
    assert row["score_error"] == "LLM error: temporary outage"
    assert row["score_retry_at"] is None
    close_connection(db_path)


def test_ensure_coursework_table_does_not_commit_outer_transaction(tmp_path) -> None:
    db_path = tmp_path / "coursework.db"
    conn = sqlite3.connect(db_path)

    conn.execute("BEGIN")
    ensure_coursework_table(conn)
    conn.execute("CREATE TABLE rolled_back_marker (id INTEGER)")
    conn.rollback()

    tables = {
        row[0]
        for row in conn.execute(
            "SELECT name FROM sqlite_master WHERE type = 'table'"
        ).fetchall()
    }

    assert "coursework" not in tables
    assert "rolled_back_marker" not in tables
    conn.close()
