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
    _add_column(conn, "application_events", "notes", "TEXT")
    _add_column(conn, "application_events", "follow_up_at", "TEXT")
    _add_column(conn, "application_events", "created_at", "TEXT DEFAULT CURRENT_TIMESTAMP")
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


def _m0004_retryable_scoring(conn: sqlite3.Connection) -> None:
    _add_column(conn, "jobs", "score_attempts", "INTEGER DEFAULT 0")
    _add_column(conn, "jobs", "score_error", "TEXT")
    _add_column(conn, "jobs", "score_retry_at", "TEXT")
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_jobs_score_retry "
        "ON jobs(fit_score, score_attempts, score_retry_at)"
    )


def _m0005_scoring_policy_v76(conn: sqlite3.Connection) -> None:
    """Invalidate unapplied output produced before structured policy/provenance gates."""
    conn.execute(
        """
        UPDATE jobs
        SET fit_score = NULL,
            llm_score = NULL,
            keyword_score = NULL,
            embedding_score = NULL,
            composite_score = NULL,
            score_breakdown = NULL,
            score_reasoning = NULL,
            matched_skills = NULL,
            missing_skills = NULL,
            keyword_hits = NULL,
            risk_flags = NULL,
            apply_or_skip_reason = NULL,
            scored_at = NULL,
            score_attempts = 0,
            score_error = NULL,
            score_retry_at = NULL,
            tailored_resume_path = NULL,
            tailored_at = NULL,
            tailor_attempts = 0,
            cover_letter_path = NULL,
            cover_letter_at = NULL,
            cover_attempts = 0
        WHERE applied_at IS NULL
          AND COALESCE(apply_status, '') NOT IN ('applied', 'screening', 'interview', 'offer')
        """
    )


def _m0006_job_availability_lifecycle(conn: sqlite3.Connection) -> None:
    """Type pre-existing archives without guessing that the user dismissed them."""
    _add_column(conn, "jobs", "archive_reason", "TEXT")
    _add_column(conn, "jobs", "availability_state", "TEXT")
    _add_column(conn, "jobs", "availability_checked_at", "TEXT")
    _add_column(conn, "jobs", "last_seen_at", "TEXT")
    conn.execute(
        """
        UPDATE jobs
        SET archive_reason = 'legacy'
        WHERE archived_at IS NOT NULL
          AND COALESCE(archive_reason, '') = ''
        """
    )
    conn.execute(
        """
        UPDATE jobs
        SET fit_score = NULL,
            llm_score = NULL,
            keyword_score = NULL,
            embedding_score = NULL,
            composite_score = NULL,
            score_breakdown = NULL,
            scored_at = NULL,
            score_attempts = MAX(1, COALESCE(score_attempts, 0)),
            score_error = COALESCE(NULLIF(score_error, ''), NULLIF(score_reasoning, ''), 'Legacy LLM scoring failure'),
            score_retry_at = NULL
        WHERE fit_score = 0
          AND lower(COALESCE(risk_flags, '')) LIKE '%llm_error%'
        """
    )


MIGRATIONS = (
    (1, "0001_baseline", _m0001_baseline),
    (2, "0002_application_events", _m0002_application_events),
    (3, "0003_hybrid_scoring_and_dedup", _m0003_hybrid_scoring_and_dedup),
    (4, "0004_retryable_scoring", _m0004_retryable_scoring),
    (5, "0005_scoring_policy_v76", _m0005_scoring_policy_v76),
    (6, "0006_job_availability_lifecycle", _m0006_job_availability_lifecycle),
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
