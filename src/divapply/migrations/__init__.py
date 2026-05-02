"""SQLite schema migration registry for DivApply."""

from __future__ import annotations

import sqlite3


def _columns(conn: sqlite3.Connection, table: str) -> set[str]:
    return {row[1] for row in conn.execute(f"PRAGMA table_info({table})").fetchall()}


def _add_column(conn: sqlite3.Connection, table: str, name: str, sql_type: str) -> None:
    if name not in _columns(conn, table):
        conn.execute(f"ALTER TABLE {table} ADD COLUMN {name} {sql_type}")


def _m0001_baseline(conn: sqlite3.Connection) -> None:
    """Baseline marker for databases created before the registry existed."""
    conn.execute("SELECT 1")


def _m0002_application_events(conn: sqlite3.Connection) -> None:
    conn.execute("""
        CREATE TABLE IF NOT EXISTS application_events (
            id              INTEGER PRIMARY KEY AUTOINCREMENT,
            job_url         TEXT NOT NULL,
            event_type      TEXT NOT NULL,
            ts              TEXT NOT NULL,
            notes           TEXT,
            follow_up_at    TEXT,
            created_at      TEXT DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY(job_url) REFERENCES jobs(url)
        )
    """)
    conn.execute("CREATE INDEX IF NOT EXISTS idx_application_events_job_url ON application_events(job_url)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_application_events_follow_up ON application_events(follow_up_at)")


def _m0003_hybrid_scoring_and_dedup(conn: sqlite3.Connection) -> None:
    _add_column(conn, "jobs", "canonical_key", "TEXT")
    _add_column(conn, "jobs", "company", "TEXT")
    _add_column(conn, "jobs", "llm_score", "INTEGER")
    _add_column(conn, "jobs", "keyword_score", "REAL")
    _add_column(conn, "jobs", "embedding_score", "REAL")
    _add_column(conn, "jobs", "composite_score", "REAL")
    _add_column(conn, "jobs", "score_breakdown", "TEXT")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_jobs_canonical_key ON jobs(canonical_key)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_jobs_apply_status ON jobs(apply_status)")


MIGRATIONS = (
    (1, "0001_baseline", _m0001_baseline),
    (2, "0002_application_events", _m0002_application_events),
    (3, "0003_hybrid_scoring_and_dedup", _m0003_hybrid_scoring_and_dedup),
)


def run_migrations(conn: sqlite3.Connection) -> list[str]:
    """Run missing migrations in version order inside transactions."""
    current = int(conn.execute("PRAGMA user_version").fetchone()[0])
    applied: list[str] = []
    for version, name, migration in MIGRATIONS:
        if version <= current:
            continue
        conn.execute("BEGIN")
        try:
            migration(conn)
            conn.execute(f"PRAGMA user_version = {version}")
            conn.commit()
            applied.append(name)
        except Exception:
            conn.rollback()
            raise
    return applied
