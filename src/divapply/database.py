"""DivApply database layer: schema, migrations, stats, and connection helpers.

Single source of truth for the jobs table schema. All columns from every
pipeline stage are created up front so any stage can run independently
without migration ordering issues.
"""

import hashlib
import json
import logging
import re
import sqlite3
import threading
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Iterator

from divapply.config import DB_PATH, LEGACY_DB_PATH
from divapply.migrations import run_migrations

log = logging.getLogger(__name__)

# Thread-local connection storage â€” each thread gets its own connection
# (required for SQLite thread safety with parallel workers)
_local = threading.local()


@contextmanager
def _transaction(conn: sqlite3.Connection) -> Iterator[None]:
    """Commit a DB mutation atomically, rolling back only transactions we start."""
    already_in_transaction = conn.in_transaction
    try:
        yield
        if not already_in_transaction:
            conn.commit()
    except Exception:
        if not already_in_transaction:
            conn.rollback()
        raise


def _resolve_db_path(db_path: Path | str | None = None) -> Path:
    """Resolve the active database path, preferring existing legacy data."""
    if db_path is not None:
        return Path(db_path)
    if DB_PATH.exists():
        return DB_PATH
    if LEGACY_DB_PATH.exists():
        return LEGACY_DB_PATH
    return DB_PATH


def get_active_db_path(db_path: Path | str | None = None) -> Path:
    """Return the database path DivApply will use."""
    return _resolve_db_path(db_path)


def get_connection(db_path: Path | str | None = None) -> sqlite3.Connection:
    """Get a thread-local cached SQLite connection with WAL mode enabled.

    Each thread gets its own connection (required for SQLite thread safety).
    Connections are cached and reused within the same thread.

    Args:
        db_path: Override the default DB_PATH. Useful for testing.

    Returns:
        sqlite3.Connection configured with WAL mode and row factory.
    """
    resolved_path = _resolve_db_path(db_path)
    resolved_path.parent.mkdir(parents=True, exist_ok=True)
    path = str(resolved_path)

    if not hasattr(_local, 'connections'):
        _local.connections = {}

    conn = _local.connections.get(path)
    if conn is not None:
        try:
            conn.execute("SELECT 1")
            return conn
        except sqlite3.ProgrammingError:
            pass

    conn = sqlite3.connect(path, timeout=30)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA busy_timeout=10000")
    conn.row_factory = sqlite3.Row
    _local.connections[path] = conn
    return conn


def close_connection(db_path: Path | str | None = None) -> None:
    """Close the cached connection for the current thread."""
    path = str(_resolve_db_path(db_path))
    if hasattr(_local, 'connections'):
        conn = _local.connections.pop(path, None)
        if conn is not None:
            conn.close()


def init_db(db_path: Path | str | None = None) -> sqlite3.Connection:
    """Create the full jobs table with all columns from every pipeline stage.

    This is idempotent -- safe to call on every startup. Uses CREATE TABLE IF NOT EXISTS
    so it won't destroy existing data.

    Schema columns by stage:
      - Discovery:  url, canonical_key, title, company, salary, description,
                   location, site, strategy, discovered_at
      - Enrichment: full_description, application_url, detail_scraped_at, detail_error
      - Scoring:    fit_score, llm_score, keyword_score, embedding_score,
                   composite_score, score_breakdown, score_reasoning,
                   matched_skills, missing_skills, keyword_hits, risk_flags,
                   apply_or_skip_reason, scored_at
      - Tailoring:  tailored_resume_path, tailored_at, tailor_attempts
      - Cover:      cover_letter_path, cover_letter_at, cover_attempts
      - Apply:      applied_at, apply_status, apply_error, apply_attempts,
                   agent_id, last_attempted_at, apply_duration_ms, apply_task_id,
                   verification_confidence, archived_at

    Args:
        db_path: Override the default DB_PATH.

    Returns:
        sqlite3.Connection with the schema initialized.
    """
    path = _resolve_db_path(db_path)

    # Ensure parent directory exists
    Path(path).parent.mkdir(parents=True, exist_ok=True)

    conn = get_connection(path)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS jobs (
            -- Discovery stage (smart_extract / job_search)
            url                   TEXT PRIMARY KEY,
            canonical_key         TEXT,
            title                 TEXT,
            company               TEXT,
            salary                TEXT,
            description           TEXT,
            location              TEXT,
            site                  TEXT,
            strategy              TEXT,
            discovered_at         TEXT,

            -- Enrichment stage (detail_scraper)
            full_description      TEXT,
            application_url       TEXT,
            detail_scraped_at     TEXT,
            detail_error          TEXT,

            -- Scoring stage (job_scorer)
            fit_score             INTEGER,
            llm_score             INTEGER,
            keyword_score         REAL,
            embedding_score       REAL,
            composite_score       REAL,
            score_breakdown       TEXT,
            score_reasoning       TEXT,
            matched_skills        TEXT,
            missing_skills        TEXT,
            keyword_hits          TEXT,
            risk_flags            TEXT,
            apply_or_skip_reason  TEXT,
            scored_at             TEXT,

            -- Tailoring stage (resume tailor)
            tailored_resume_path  TEXT,
            tailored_at           TEXT,
            tailor_attempts       INTEGER DEFAULT 0,

            -- Cover letter stage
            cover_letter_path     TEXT,
            cover_letter_at       TEXT,
            cover_attempts        INTEGER DEFAULT 0,

            -- Application stage
            applied_at            TEXT,
            apply_status          TEXT,
            apply_error           TEXT,
            apply_attempts        INTEGER DEFAULT 0,
            agent_id              TEXT,
            last_attempted_at     TEXT,
            apply_duration_ms     INTEGER,
            apply_task_id         TEXT,
            verification_confidence TEXT,
            archived_at           TEXT
        )
    """)
    conn.commit()

    # Create auxiliary knowledge tables used by the profile layer.
    ensure_coursework_table(conn)
    seed_coursework_if_empty(conn)

    # Run schema-versioned migrations, then the additive column safety net.
    run_migrations(conn)
    ensure_columns(conn)
    ensure_job_indexes(conn)
    ensure_application_events_table(conn)
    backfill_application_events(conn)

    return conn


# Complete column registry: column_name -> SQL type with optional default.
# This is the single source of truth. Adding a column here is all that's needed
# for it to appear in both new databases and migrated ones.
_ALL_COLUMNS: dict[str, str] = {
    # Discovery
    "url": "TEXT PRIMARY KEY",
    "canonical_key": "TEXT",
    "title": "TEXT",
    "company": "TEXT",
    "salary": "TEXT",
    "description": "TEXT",
    "location": "TEXT",
    "site": "TEXT",
    "strategy": "TEXT",
    "discovered_at": "TEXT",
    # Enrichment
    "full_description": "TEXT",
    "application_url": "TEXT",
    "detail_scraped_at": "TEXT",
    "detail_error": "TEXT",
    # Scoring
    "fit_score": "INTEGER",
    "llm_score": "INTEGER",
    "keyword_score": "REAL",
    "embedding_score": "REAL",
    "composite_score": "REAL",
    "score_breakdown": "TEXT",
    "score_reasoning": "TEXT",
    "matched_skills": "TEXT",
    "missing_skills": "TEXT",
    "keyword_hits": "TEXT",
    "risk_flags": "TEXT",
    "apply_or_skip_reason": "TEXT",
    "scored_at": "TEXT",
    # Tailoring
    "tailored_resume_path": "TEXT",
    "tailored_at": "TEXT",
    "tailor_attempts": "INTEGER DEFAULT 0",
    # Cover letter
    "cover_letter_path": "TEXT",
    "cover_letter_at": "TEXT",
    "cover_attempts": "INTEGER DEFAULT 0",
    # Application
    "applied_at": "TEXT",
    "apply_status": "TEXT",
    "apply_error": "TEXT",
    "apply_attempts": "INTEGER DEFAULT 0",
    "agent_id": "TEXT",
    "last_attempted_at": "TEXT",
    "apply_duration_ms": "INTEGER",
    "apply_task_id": "TEXT",
    "verification_confidence": "TEXT",
    "archived_at": "TEXT",
}


def ensure_columns(conn: sqlite3.Connection | None = None) -> list[str]:
    """Add any missing columns to the jobs table (forward migration).

    Reads the current table schema via PRAGMA table_info and compares against
    the full column registry. Any missing columns are added with ALTER TABLE.

    This makes it safe to upgrade the database from any previous version --
    columns are only added, never removed or renamed.

    Args:
        conn: Database connection. Uses get_connection() if None.

    Returns:
        List of column names that were added (empty if schema was already current).
    """
    if conn is None:
        conn = get_connection()

    existing = {row[1] for row in conn.execute("PRAGMA table_info(jobs)").fetchall()}
    added = []

    for col, dtype in _ALL_COLUMNS.items():
        if col not in existing:
            # PRIMARY KEY columns can't be added via ALTER TABLE, but url
            # is always created with the table itself so this is safe
            if "PRIMARY KEY" in dtype:
                continue
            conn.execute(f"ALTER TABLE jobs ADD COLUMN {col} {dtype}")
            conn.commit()  # commit each column individually so partial crashes don't corrupt schema
            added.append(col)

    return added


def ensure_job_indexes(conn: sqlite3.Connection | None = None) -> None:
    """Create lightweight lookup indexes used by dedup and CRM commands."""
    if conn is None:
        conn = get_connection()

    conn.execute("CREATE INDEX IF NOT EXISTS idx_jobs_canonical_key ON jobs(canonical_key)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_jobs_apply_status ON jobs(apply_status)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_jobs_site ON jobs(site)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_jobs_detail_pending ON jobs(detail_scraped_at)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_jobs_score_pending ON jobs(full_description, fit_score)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_jobs_fit_discovered ON jobs(fit_score, discovered_at)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_jobs_tailor_pending ON jobs(fit_score, tailored_resume_path)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_jobs_cover_pending ON jobs(tailored_resume_path, cover_letter_path)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_jobs_apply_ready ON jobs(tailored_resume_path, applied_at, application_url)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_jobs_archived_at ON jobs(archived_at)")
    try:
        conn.execute(
            "CREATE UNIQUE INDEX IF NOT EXISTS idx_jobs_canonical_key_unique "
            "ON jobs(canonical_key) WHERE canonical_key IS NOT NULL"
        )
    except sqlite3.IntegrityError:
        log.warning("Existing duplicate canonical job keys prevent unique dedup index creation")
    conn.commit()


def ensure_application_events_table(conn: sqlite3.Connection | None = None) -> None:
    """Create the append-only application lifecycle table."""
    if conn is None:
        conn = get_connection()

    should_commit = not conn.in_transaction
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
    if should_commit:
        conn.commit()


def backfill_application_events(conn: sqlite3.Connection | None = None) -> int:
    """Backfill one synthetic applied event for legacy rows with applied_at."""
    if conn is None:
        conn = get_connection()

    ensure_application_events_table(conn)
    rows = conn.execute("""
        SELECT url, applied_at
        FROM jobs
        WHERE applied_at IS NOT NULL
          AND NOT EXISTS (
              SELECT 1 FROM application_events
              WHERE application_events.job_url = jobs.url
                AND application_events.event_type = 'applied'
          )
    """).fetchall()

    inserted = 0
    with _transaction(conn):
        for row in rows:
            conn.execute(
                """
                INSERT INTO application_events (job_url, event_type, ts, notes)
                VALUES (?, 'applied', ?, ?)
                """,
                (row["url"], row["applied_at"], "Backfilled from jobs.applied_at"),
            )
            inserted += 1
    return inserted


def add_application_event(
    job_url: str,
    event_type: str,
    *,
    notes: str | None = None,
    follow_up_at: str | None = None,
    ts: str | None = None,
    conn: sqlite3.Connection | None = None,
) -> int:
    """Append one lifecycle event and sync the legacy job status columns."""
    if conn is None:
        conn = get_connection()

    ensure_application_events_table(conn)
    event = event_type.strip().lower().replace("-", "_")
    if not event:
        raise ValueError("event_type must not be empty")

    now = ts or datetime.now(timezone.utc).isoformat()

    with _transaction(conn):
        cursor = conn.execute(
            """
            INSERT INTO application_events (job_url, event_type, ts, notes, follow_up_at)
            VALUES (?, ?, ?, ?, ?)
            """,
            (job_url, event, now, notes, follow_up_at),
        )

        status_map = {
            "applied": "applied",
            "screening": "screening",
            "interview": "interview",
            "offer": "offer",
            "rejection": "rejected",
            "rejected": "rejected",
            "withdrawn": "withdrawn",
            "failed": "failed",
        }
        if event in status_map:
            applied_at_sql = ", applied_at = COALESCE(applied_at, ?)" if event == "applied" else ""
            params: tuple
            if event == "applied":
                params = (status_map[event], now, job_url)
            else:
                params = (status_map[event], job_url)
            conn.execute(
                f"UPDATE jobs SET apply_status = ?{applied_at_sql} WHERE url = ?",
                params,
            )
    return int(cursor.lastrowid)


def get_due_followups(
    *,
    today: str | None = None,
    conn: sqlite3.Connection | None = None,
) -> list[dict]:
    """Return lifecycle events with follow-ups due today or earlier."""
    if conn is None:
        conn = get_connection()

    ensure_application_events_table(conn)
    cutoff = today or datetime.now(timezone.utc).date().isoformat()
    rows = conn.execute(
        """
        SELECT e.id, e.job_url, e.event_type, e.ts, e.notes, e.follow_up_at,
               j.title, j.company, j.site, j.fit_score, j.apply_status
        FROM application_events e
        LEFT JOIN jobs j ON j.url = e.job_url
        WHERE e.follow_up_at IS NOT NULL
          AND e.follow_up_at <= ?
          AND COALESCE(j.apply_status, '') NOT IN ('rejected', 'withdrawn', 'failed')
        ORDER BY e.follow_up_at ASC, e.ts DESC
        """,
        (cutoff,),
    ).fetchall()
    return [dict(row) for row in rows]


def get_application_analytics(conn: sqlite3.Connection | None = None) -> dict:
    """Return compact lifecycle analytics for status/CLI display."""
    if conn is None:
        conn = get_connection()

    ensure_application_events_table(conn)
    state_rows = conn.execute(
        """
        SELECT COALESCE(apply_status, 'untracked') AS state, COUNT(*) AS count
        FROM jobs
        GROUP BY COALESCE(apply_status, 'untracked')
        ORDER BY count DESC
        """
    ).fetchall()
    event_rows = conn.execute(
        """
        SELECT event_type, COUNT(*) AS count
        FROM application_events
        GROUP BY event_type
        ORDER BY count DESC
        """
    ).fetchall()
    return {
        "states": [(row["state"], row["count"]) for row in state_rows],
        "events": [(row["event_type"], row["count"]) for row in event_rows],
        "due_followups": count_due_followups(conn=conn),
    }


def count_due_followups(
    *,
    today: str | None = None,
    conn: sqlite3.Connection | None = None,
) -> int:
    """Return the number of active lifecycle follow-ups due today or earlier."""
    if conn is None:
        conn = get_connection()

    ensure_application_events_table(conn)
    cutoff = today or datetime.now(timezone.utc).date().isoformat()
    return int(conn.execute(
        """
        SELECT COUNT(*)
        FROM application_events e
        LEFT JOIN jobs j ON j.url = e.job_url
        WHERE e.follow_up_at IS NOT NULL
          AND e.follow_up_at <= ?
          AND COALESCE(j.apply_status, '') NOT IN ('rejected', 'withdrawn', 'failed')
        """,
        (cutoff,),
    ).fetchone()[0])


def get_application_timeline(job_url: str, conn: sqlite3.Connection | None = None) -> list[dict]:
    """Return lifecycle events for one job in chronological order."""
    if conn is None:
        conn = get_connection()

    ensure_application_events_table(conn)
    rows = conn.execute(
        """
        SELECT id, job_url, event_type, ts, notes, follow_up_at
        FROM application_events
        WHERE job_url = ?
        ORDER BY ts ASC, id ASC
        """,
        (job_url,),
    ).fetchall()
    return [dict(row) for row in rows]


def ensure_coursework_table(conn: sqlite3.Connection | None = None) -> None:
    """Create the hidden coursework knowledge table if it does not exist."""
    if conn is None:
        conn = get_connection()

    conn.execute("""
        CREATE TABLE IF NOT EXISTS coursework (
            id              INTEGER PRIMARY KEY AUTOINCREMENT,
            school          TEXT,
            course_code     TEXT,
            course_title    TEXT,
            subject_area    TEXT,
            term            TEXT,
            status          TEXT,
            credits         REAL,
            grade           TEXT,
            source          TEXT,
            notes           TEXT,
            skills          TEXT,
            raw_text        TEXT,
            created_at      TEXT DEFAULT CURRENT_TIMESTAMP
        )
    """)
    conn.commit()


def _infer_course_skills(entry: dict) -> list[str]:
    """Infer a compact skill tag list from coursework metadata."""
    text = " ".join(
        str(entry.get(key, "")).lower()
        for key in ("school", "course_code", "course_title", "subject_area", "notes", "raw_text")
    )

    rules: list[tuple[tuple[str, ...], list[str]]] = [
        (("accounting", "taxation", "finance", "financial"), ["accounting", "financial records", "reconciliation"]),
        (("business communications", "business english", "composition", "technical writing", "writing"), ["professional writing", "documentation", "communication"]),
        (("information systems", "computer", "information technology", "is 101"), ["information systems", "digital workflows", "business software"]),
        (("marketing",), ["marketing", "customer awareness", "communication"]),
        (("management", "operations", "entrepreneurship", "legal environment", "personal finance"), ["business operations", "management", "compliance", "planning"]),
        (("public health", "health science", "health and wellness", "community health", "epidemiology", "disease", "public health administration", "community and environmental health", "health education", "substance abuse"), ["public health", "health education", "community services", "program support"]),
        (("nutrition", "medical terminology", "anatomy", "physiology", "disability"), ["health literacy", "human services", "wellness"]),
        (("biostat", "statistics"), ["data analysis", "statistics", "research literacy"]),
        (("biology", "chemistry"), ["scientific reasoning", "lab methods", "quantitative reasoning"]),
        (("psychology", "human diversity", "history", "culture", "arts", "music", "new testament"), ["interpersonal communication", "cultural awareness", "behavioral insight"]),
        (("precalculus", "math"), ["quantitative reasoning", "problem solving"]),
        (("swimming", "strength training"), ["physical fitness", "discipline", "wellness"]),
        (("nevadafit", "welcome"), ["orientation", "college readiness", "self-management"]),
    ]

    tags: list[str] = []
    for needles, inferred in rules:
        if any(needle in text for needle in needles):
            tags.extend(inferred)

    if not tags:
        tags = ["academic knowledge", "general problem solving"]

    seen: set[str] = set()
    ordered: list[str] = []
    for tag in tags:
        if tag not in seen:
            seen.add(tag)
            ordered.append(tag)
    return ordered[:6]


def _normalize_coursework_entry(entry: dict, now: str) -> dict:
    """Normalize one coursework row before persisting it."""
    normalized = {
        "school": entry.get("school"),
        "course_code": entry.get("course_code"),
        "course_title": entry.get("course_title"),
        "subject_area": entry.get("subject_area"),
        "term": entry.get("term"),
        "status": entry.get("status") or entry.get("course_status"),
        "credits": entry.get("credits"),
        "grade": entry.get("grade"),
        "source": entry.get("source"),
        "notes": entry.get("notes"),
        "skills": entry.get("skills"),
        "raw_text": entry.get("raw_text"),
        "created_at": entry.get("created_at") or now,
    }

    if not normalized["skills"]:
        normalized["skills"] = json.dumps(_infer_course_skills(normalized), ensure_ascii=True)
    elif isinstance(normalized["skills"], list):
        normalized["skills"] = json.dumps(normalized["skills"], ensure_ascii=True)

    return normalized


def _seed_coursework_path() -> Path:
    return Path(__file__).parent / "config" / "coursework.seed.json"


def load_coursework_seed() -> list[dict]:
    """Load bundled coursework seed data from the package config directory."""
    path = _seed_coursework_path()
    if not path.exists():
        return []
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return []
    if isinstance(data, dict):
        data = data.get("coursework") or data.get("courses") or []
    return [row for row in data if isinstance(row, dict)]


def seed_coursework_if_empty(conn: sqlite3.Connection | None = None) -> int:
    """Populate coursework knowledge from the bundled seed file if empty."""
    if conn is None:
        conn = get_connection()

    ensure_coursework_table(conn)
    count = conn.execute("SELECT COUNT(*) FROM coursework").fetchone()[0]
    if count:
        return 0

    seed_rows = load_coursework_seed()
    if not seed_rows:
        return 0

    return replace_coursework(seed_rows, conn=conn)


def replace_coursework(entries: list[dict], conn: sqlite3.Connection | None = None) -> int:
    """Replace all stored coursework rows with a new set of entries.

    Destructive: deletes everything in the coursework table first. Prefer
    append_coursework() when importing additional transcripts so prior data
    is preserved.
    """
    if conn is None:
        conn = get_connection()

    ensure_coursework_table(conn)
    conn.execute("DELETE FROM coursework")
    return _insert_coursework_rows(entries, conn)


def append_coursework(entries: list[dict], conn: sqlite3.Connection | None = None) -> dict:
    """Append coursework rows, skipping duplicates already in the table.

    Two rows are treated as duplicates when (school, course_code,
    course_title, term) all match (case-insensitive, trimmed). Rows that
    duplicate something already stored are skipped, not updated.

    Returns counts: {"inserted": int, "skipped": int}.
    """
    if conn is None:
        conn = get_connection()

    ensure_coursework_table(conn)

    existing_keys: set[tuple[str, str, str, str]] = set()
    for row in conn.execute(
        "SELECT school, course_code, course_title, term FROM coursework"
    ).fetchall():
        existing_keys.add(_coursework_dedup_key(row[0], row[1], row[2], row[3]))

    now = datetime.now(timezone.utc).isoformat()
    inserted = 0
    skipped = 0
    for entry in entries:
        normalized = _normalize_coursework_entry(entry, now)
        key = _coursework_dedup_key(
            normalized.get("school"),
            normalized.get("course_code"),
            normalized.get("course_title"),
            normalized.get("term"),
        )
        if key in existing_keys:
            skipped += 1
            continue
        existing_keys.add(key)
        _insert_coursework_row(normalized, conn)
        inserted += 1

    conn.commit()
    return {"inserted": inserted, "skipped": skipped}


def _coursework_dedup_key(
    school: str | None,
    course_code: str | None,
    course_title: str | None,
    term: str | None,
) -> tuple[str, str, str, str]:
    def _norm(value: str | None) -> str:
        return str(value or "").strip().casefold()

    return (_norm(school), _norm(course_code), _norm(course_title), _norm(term))


def _insert_coursework_rows(entries: list[dict], conn: sqlite3.Connection) -> int:
    now = datetime.now(timezone.utc).isoformat()
    inserted = 0
    for entry in entries:
        normalized = _normalize_coursework_entry(entry, now)
        _insert_coursework_row(normalized, conn)
        inserted += 1
    conn.commit()
    return inserted


def _insert_coursework_row(normalized: dict, conn: sqlite3.Connection) -> None:
    conn.execute(
        """
        INSERT INTO coursework (
            school, course_code, course_title, subject_area,
            term, status, credits, grade, source, notes, skills, raw_text, created_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            normalized.get("school"),
            normalized.get("course_code"),
            normalized.get("course_title"),
            normalized.get("subject_area"),
            normalized.get("term"),
            normalized.get("status"),
            normalized.get("credits"),
            normalized.get("grade"),
            normalized.get("source"),
            normalized.get("notes"),
            normalized.get("skills"),
            normalized.get("raw_text"),
            normalized.get("created_at"),
        ),
    )


def get_coursework(conn: sqlite3.Connection | None = None) -> list[dict]:
    """Return stored coursework rows sorted newest-last within each school."""
    if conn is None:
        conn = get_connection()

    ensure_coursework_table(conn)
    rows = conn.execute(
        """
        SELECT school, course_code, course_title, subject_area, term, status, credits,
               grade, source, notes, skills, raw_text, created_at
        FROM coursework
        ORDER BY school, term, course_title
        """
    ).fetchall()

    if not rows:
        return []

    columns = rows[0].keys()
    return [dict(zip(columns, row)) for row in rows]


def get_coursework_summary(conn: sqlite3.Connection | None = None) -> dict:
    """Return safe coursework metadata without transcript text."""
    if conn is None:
        conn = get_connection()

    ensure_coursework_table(conn)
    rows = conn.execute(
        """
        SELECT school, subject_area, source, skills
        FROM coursework
        ORDER BY school, subject_area, source
        """
    ).fetchall()

    schools: set[str] = set()
    subject_areas: set[str] = set()
    import_sources: set[str] = set()
    inferred_skills: set[str] = set()

    for row in rows:
        if row["school"]:
            schools.add(str(row["school"]).strip())
        if row["subject_area"]:
            subject_areas.add(str(row["subject_area"]).strip())
        if row["source"]:
            import_sources.add(str(row["source"]).strip())

        raw_skills = row["skills"] or ""
        parsed: list[str]
        if isinstance(raw_skills, str):
            try:
                loaded = json.loads(raw_skills)
                parsed = loaded if isinstance(loaded, list) else []
            except json.JSONDecodeError:
                parsed = [part.strip() for part in raw_skills.split(",") if part.strip()]
        else:
            parsed = []
        inferred_skills.update(str(skill).strip() for skill in parsed if str(skill).strip())

    return {
        "row_count": len(rows),
        "schools": sorted(schools),
        "subject_areas": sorted(subject_areas),
        "inferred_skills": sorted(inferred_skills),
        "import_sources": sorted(import_sources),
    }


def get_stats(conn: sqlite3.Connection | None = None) -> dict:
    """Return job counts by pipeline stage.

    Provides a snapshot of how many jobs are at each stage, useful for
    dashboard display and pipeline progress tracking.

    Args:
        conn: Database connection. Uses get_connection() if None.

    Returns:
        Dictionary with keys:
            total, by_site, pending_detail, with_description,
            scored, unscored, tailored, untailored_eligible,
            with_cover_letter, applied, score_distribution
    """
    if conn is None:
        conn = get_connection()

    stale_cutoff = (datetime.now(timezone.utc) - timedelta(seconds=3600)).isoformat()
    count_row = conn.execute(
        """
        SELECT
            COUNT(*) AS total,
            SUM(CASE WHEN detail_scraped_at IS NULL THEN 1 ELSE 0 END) AS pending_detail,
            SUM(CASE WHEN full_description IS NOT NULL THEN 1 ELSE 0 END) AS with_description,
            SUM(CASE WHEN detail_error IS NOT NULL THEN 1 ELSE 0 END) AS detail_errors,
            SUM(CASE WHEN fit_score IS NOT NULL THEN 1 ELSE 0 END) AS scored,
            SUM(CASE WHEN full_description IS NOT NULL AND fit_score IS NULL THEN 1 ELSE 0 END) AS unscored,
            SUM(CASE WHEN tailored_resume_path IS NOT NULL THEN 1 ELSE 0 END) AS tailored,
            SUM(CASE
                WHEN fit_score >= 7
                 AND full_description IS NOT NULL
                 AND tailored_resume_path IS NULL
                THEN 1 ELSE 0
            END) AS untailored_eligible,
            SUM(CASE
                WHEN COALESCE(tailor_attempts, 0) >= 5
                 AND tailored_resume_path IS NULL
                THEN 1 ELSE 0
            END) AS tailor_exhausted,
            SUM(CASE WHEN cover_letter_path IS NOT NULL AND cover_letter_path != '' THEN 1 ELSE 0 END) AS with_cover_letter,
            SUM(CASE
                WHEN COALESCE(cover_attempts, 0) >= 5
                 AND (cover_letter_path IS NULL OR cover_letter_path = '')
                THEN 1 ELSE 0
            END) AS cover_exhausted,
            SUM(CASE WHEN applied_at IS NOT NULL THEN 1 ELSE 0 END) AS applied,
            SUM(CASE WHEN archived_at IS NOT NULL THEN 1 ELSE 0 END) AS archived,
            SUM(CASE WHEN apply_error IS NOT NULL THEN 1 ELSE 0 END) AS apply_errors,
            SUM(CASE WHEN apply_status = 'in_progress' THEN 1 ELSE 0 END) AS apply_in_progress,
            SUM(CASE
                WHEN apply_status = 'in_progress'
                 AND last_attempted_at IS NOT NULL
                 AND last_attempted_at < ?
                THEN 1 ELSE 0
            END) AS stale_apply_locks,
            SUM(CASE
                WHEN tailored_resume_path IS NOT NULL
                 AND applied_at IS NULL
                 AND COALESCE(application_url, '') != ''
                 AND archived_at IS NULL
                THEN 1 ELSE 0
            END) AS ready_to_apply
        FROM jobs
        """,
        (stale_cutoff,),
    ).fetchone()
    stats: dict = {key: int(count_row[key] or 0) for key in count_row.keys()}

    # By site breakdown
    rows = conn.execute(
        "SELECT site, COUNT(*) as cnt FROM jobs GROUP BY site ORDER BY cnt DESC"
    ).fetchall()
    stats["by_site"] = [(row[0], row[1]) for row in rows]

    # Score distribution
    dist_rows = conn.execute(
        "SELECT fit_score, COUNT(*) as cnt FROM jobs "
        "WHERE fit_score IS NOT NULL "
        "GROUP BY fit_score ORDER BY fit_score DESC"
    ).fetchall()
    stats["score_distribution"] = [(row[0], row[1]) for row in dist_rows]

    try:
        stats["due_followups"] = count_due_followups(conn=conn)
    except Exception:
        stats["due_followups"] = 0

    return stats


def archive_job(url: str, conn: sqlite3.Connection | None = None) -> bool:
    """Archive one job by URL without deleting its application history."""
    if conn is None:
        conn = get_connection()
    now = datetime.now(timezone.utc).isoformat()
    with _transaction(conn):
        row = conn.execute(
            "SELECT tailored_resume_path, cover_letter_path FROM jobs WHERE url = ? AND archived_at IS NULL",
            (url,),
        ).fetchone()
        if row is None:
            return False
        cursor = conn.execute(
            """
            UPDATE jobs
            SET archived_at = ?
            WHERE url = ?
              AND archived_at IS NULL
            """,
            (now, url),
        )
    _delete_job_artifacts(dict(row))
    return cursor.rowcount > 0


def _is_safe_generated_path(path: Path, allowed_roots: list[Path]) -> bool:
    """Return True when a generated artifact path is inside an output directory."""
    try:
        candidate = path.parent.resolve() / path.name if path.is_symlink() else path.resolve()
    except OSError:
        return False
    for root in allowed_roots:
        try:
            candidate.relative_to(root.resolve())
            return True
        except (OSError, ValueError):
            continue
    return False


def _artifact_siblings(path: Path) -> set[Path]:
    """Return known generated files associated with a tailored/cover text file."""
    siblings = {path}
    siblings.add(path.with_suffix(".pdf"))
    siblings.add(path.with_suffix(".html"))
    name = path.name
    if name.endswith("_CL.txt"):
        return siblings
    if path.suffix == ".txt" and not name.endswith(("_JOB.txt", "_REPORT.txt")):
        siblings.add(path.with_name(f"{path.stem}_JOB.txt"))
        siblings.add(path.with_name(f"{path.stem}_REPORT.json"))
    return siblings


def _delete_job_artifacts(job: dict) -> list[Path]:
    """Best-effort cleanup of generated resume/cover files for an archived job."""
    from divapply import config

    allowed_roots = [config.TAILORED_DIR, config.COVER_LETTER_DIR]
    deleted: list[Path] = []
    candidates: set[Path] = set()
    for key in ("tailored_resume_path", "cover_letter_path"):
        raw_path = job.get(key)
        if raw_path:
            candidates.update(_artifact_siblings(Path(raw_path)))

    for candidate in sorted(candidates):
        if not _is_safe_generated_path(candidate, allowed_roots):
            continue
        try:
            if candidate.exists() or candidate.is_symlink():
                candidate.unlink()
                deleted.append(candidate)
        except OSError:
            log.warning("Could not delete archived job artifact: %s", candidate)
    return deleted


_PUNCT_RE = re.compile(r"[^a-z0-9]+")


def _normalize_key_part(value: str | None) -> str:
    text = str(value or "").casefold()
    text = _PUNCT_RE.sub(" ", text)
    text = re.sub(r"\b(inc|llc|ltd|corp|corporation|company|co)\b", " ", text)
    return " ".join(text.split())


def canonical_job_key(title: str | None, company: str | None, location: str | None) -> str | None:
    """Return a stable soft-dedup key for the same role across boards."""
    parts = [_normalize_key_part(title), _normalize_key_part(company), _normalize_key_part(location)]
    if not any(parts):
        return None
    raw = "|".join(parts)
    return hashlib.sha1(raw.encode("utf-8")).hexdigest()


def store_jobs(conn: sqlite3.Connection, jobs: list[dict],
               site: str, strategy: str) -> tuple[int, int]:
    """Store discovered jobs, skipping duplicates by URL or canonical role key.

    Args:
        conn: Database connection.
        jobs: List of job dicts with keys: url, title, salary, description, location.
        site: Source site name (e.g. "RemoteOK", "Dice").
        strategy: Extraction strategy used (e.g. "json_ld", "api_response", "css_selectors").

    Returns:
        Tuple of (new_count, duplicate_count).
    """
    now = datetime.now(timezone.utc).isoformat()
    new = 0
    existing = 0

    with _transaction(conn):
        for job in jobs:
            url = job.get("url")
            if not url:
                continue
            title = job.get("title")
            company = job.get("company")
            location = job.get("location")
            canonical_key = canonical_job_key(title, company, location)
            if canonical_key:
                found = conn.execute(
                    "SELECT 1 FROM jobs WHERE canonical_key = ? LIMIT 1",
                    (canonical_key,),
                ).fetchone()
                if found:
                    existing += 1
                    continue
            try:
                conn.execute(
                    """
                    INSERT INTO jobs (
                        url, canonical_key, title, company, salary, description,
                        location, site, strategy, discovered_at
                    )
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        url,
                        canonical_key,
                        title,
                        company,
                        job.get("salary"),
                        job.get("description"),
                        location,
                        site,
                        strategy,
                        now,
                    ),
                )
                new += 1
            except sqlite3.IntegrityError:
                existing += 1
    return new, existing


_STAGE_CONDITIONS = {
    "discovered": "1=1",
    "pending_detail": "detail_scraped_at IS NULL",
    "enriched": "full_description IS NOT NULL",
    "pending_score": "full_description IS NOT NULL AND fit_score IS NULL",
    "scored": "fit_score IS NOT NULL",
    "pending_tailor": (
        "fit_score >= ? AND full_description IS NOT NULL "
        "AND tailored_resume_path IS NULL AND COALESCE(tailor_attempts, 0) < 5"
    ),
    "tailored": "tailored_resume_path IS NOT NULL",
    "pending_cover": (
        "fit_score >= ? AND full_description IS NOT NULL "
        "AND tailored_resume_path IS NOT NULL "
        "AND (cover_letter_path IS NULL OR cover_letter_path = '') "
        "AND COALESCE(cover_attempts, 0) < 5"
    ),
    "pending_apply": (
        "tailored_resume_path IS NOT NULL AND applied_at IS NULL "
        "AND COALESCE(application_url, '') != '' AND archived_at IS NULL"
    ),
    "applied": "applied_at IS NOT NULL",
    "archived": "archived_at IS NOT NULL",
}


def get_jobs_by_stage(conn: sqlite3.Connection | None = None,
                      stage: str = "discovered",
                      min_score: int | None = None,
                      limit: int = 100) -> list[dict]:
    """Fetch jobs filtered by pipeline stage.

    Args:
        conn: Database connection. Uses get_connection() if None.
        stage: One of "discovered", "enriched", "scored", "tailored", "applied".
        min_score: Minimum fit_score filter (only relevant for scored+ stages).
        limit: Maximum number of rows to return.

    Returns:
        List of job dicts.
    """
    if conn is None:
        conn = get_connection()

    try:
        where = _STAGE_CONDITIONS[stage]
    except KeyError as exc:
        valid = ", ".join(sorted(_STAGE_CONDITIONS))
        raise ValueError(f"Unknown job stage '{stage}'. Valid stages: {valid}") from exc

    if limit < 0:
        raise ValueError("limit must be >= 0")

    params: list = []

    if "?" in where and min_score is not None:
        params.append(min_score)
    elif "?" in where:
        params.append(7)  # default min_score

    if min_score is not None and stage in ("scored", "tailored", "applied"):
        where += " AND fit_score >= ?"
        params.append(min_score)

    query = f"SELECT * FROM jobs WHERE {where} ORDER BY CASE WHEN fit_score IS NULL THEN 1 ELSE 0 END, fit_score DESC, discovered_at DESC"
    if limit > 0:
        query += " LIMIT ?"
        params.append(limit)

    rows = conn.execute(query, params).fetchall()

    # Convert sqlite3.Row objects to dicts
    if rows:
        columns = rows[0].keys()
        return [dict(zip(columns, row)) for row in rows]
    return []

