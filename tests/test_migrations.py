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

    assert version >= 3
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
