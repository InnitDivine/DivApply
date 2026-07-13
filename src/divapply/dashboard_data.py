"""Read models for the HTML dashboard.

This module keeps dashboard SQL and row-shaping out of the HTML/server layer.
"""

from __future__ import annotations

from dataclasses import dataclass
import sqlite3

from divapply.database import (
    ACTIONABLE_JOB_SQL,
    MEANINGFUL_FULL_DESCRIPTION_SQL,
    ensure_columns,
    get_connection,
)


@dataclass(frozen=True)
class DashboardSnapshot:
    """All data needed to render the HTML dashboard."""

    total: int
    archived: int
    ready: int
    scored: int
    high_fit: int
    tailored: int
    with_cover_letter: int
    applied: int
    manual: int
    expired: int
    score_dist: dict[int, int]
    site_stats: list[sqlite3.Row]
    jobs: list[sqlite3.Row]


def _has_index(conn: sqlite3.Connection, index_name: str) -> bool:
    return conn.execute(
        "SELECT 1 FROM pragma_index_list('jobs') WHERE name = ? LIMIT 1",
        (index_name,),
    ).fetchone() is not None


def fetch_dashboard_snapshot(conn: sqlite3.Connection | None = None) -> DashboardSnapshot:
    """Fetch and shape all database data required by the dashboard view."""
    if conn is None:
        conn = get_connection()
    ensure_columns(conn)
    dashboard_score_table = (
        "jobs INDEXED BY idx_jobs_dashboard_score"
        if _has_index(conn, "idx_jobs_dashboard_score")
        else "jobs"
    )
    dashboard_ready_table = (
        "jobs INDEXED BY idx_jobs_dashboard_ready"
        if _has_index(conn, "idx_jobs_dashboard_ready")
        else "jobs"
    )

    total = int(conn.execute("SELECT COUNT(*) FROM jobs WHERE archived_at IS NULL").fetchone()[0] or 0)
    archived = int(conn.execute("SELECT COUNT(*) FROM jobs WHERE archived_at IS NOT NULL").fetchone()[0] or 0)
    ready = int(conn.execute(
        f"SELECT COUNT(*) FROM {dashboard_ready_table} "
        "WHERE archived_at IS NULL "
        f"AND {MEANINGFUL_FULL_DESCRIPTION_SQL} "
        "AND application_url IS NOT NULL "
        "AND application_url != '' "
        f"AND {ACTIONABLE_JOB_SQL}"
    ).fetchone()[0] or 0)
    scored = int(conn.execute(
        f"SELECT COUNT(*) FROM {dashboard_score_table} "
        "WHERE archived_at IS NULL AND fit_score IS NOT NULL"
    ).fetchone()[0] or 0)
    high_fit = int(conn.execute(
        f"SELECT COUNT(*) FROM {dashboard_score_table} "
        "WHERE archived_at IS NULL AND fit_score >= 7"
    ).fetchone()[0] or 0)
    tailored = int(conn.execute(
        f"SELECT COUNT(*) FROM {dashboard_score_table} "
        "WHERE archived_at IS NULL "
        "AND tailored_resume_path IS NOT NULL "
        "AND tailored_resume_path != '' "
        f"AND {ACTIONABLE_JOB_SQL}"
    ).fetchone()[0] or 0)
    with_cover_letter = int(conn.execute(
        f"SELECT COUNT(*) FROM {dashboard_score_table} "
        "WHERE archived_at IS NULL "
        "AND cover_letter_path IS NOT NULL "
        "AND cover_letter_path != '' "
        f"AND {ACTIONABLE_JOB_SQL}"
    ).fetchone()[0] or 0)
    applied = int(conn.execute(
        f"SELECT COUNT(*) FROM {dashboard_score_table} "
        "WHERE archived_at IS NULL "
        "AND (apply_status = 'applied' OR applied_at IS NOT NULL)"
    ).fetchone()[0] or 0)
    manual = int(conn.execute(
        f"SELECT COUNT(*) FROM {dashboard_score_table} "
        "WHERE archived_at IS NULL AND apply_status = 'manual'"
    ).fetchone()[0] or 0)
    expired = int(conn.execute(
        f"SELECT COUNT(*) FROM {dashboard_score_table} "
        "WHERE archived_at IS NULL "
        "AND (apply_status = 'expired' OR apply_error LIKE 'expired:%' OR detail_error LIKE 'expired:%')"
    ).fetchone()[0] or 0)

    score_dist: dict[int, int] = {}
    if scored:
        rows = conn.execute(
            f"SELECT fit_score, COUNT(*) FROM {dashboard_score_table} "
            "WHERE archived_at IS NULL AND fit_score IS NOT NULL "
            "GROUP BY fit_score ORDER BY fit_score DESC"
        ).fetchall()
        for row in rows:
            score_dist[int(row[0])] = int(row[1])

    site_stats = conn.execute(f"""
        SELECT site,
               COUNT(*) as total,
               SUM(CASE WHEN fit_score >= 7 THEN 1 ELSE 0 END) as high_fit,
               SUM(CASE WHEN fit_score BETWEEN 5 AND 6 THEN 1 ELSE 0 END) as mid_fit,
               SUM(CASE WHEN fit_score < 5 AND fit_score IS NOT NULL THEN 1 ELSE 0 END) as low_fit,
               SUM(CASE WHEN fit_score IS NULL THEN 1 ELSE 0 END) as unscored,
               ROUND(AVG(fit_score), 1) as avg_score
        FROM {dashboard_score_table}
        WHERE archived_at IS NULL
        GROUP BY site ORDER BY high_fit DESC, total DESC
    """).fetchall()

    jobs = conn.execute(f"""
        SELECT url, title, salary, description, location, site, strategy,
               full_description, application_url, detail_error,
               fit_score, score_reasoning, tailored_resume_path, cover_letter_path,
               apply_status, applied_at, apply_error, verification_confidence,
               market_label, application_mode, source_verification
        FROM {dashboard_score_table}
        WHERE archived_at IS NULL AND fit_score >= 5
        ORDER BY fit_score DESC, site, title
    """).fetchall()

    return DashboardSnapshot(
        total=total,
        archived=archived,
        ready=ready,
        scored=scored,
        high_fit=high_fit,
        tailored=tailored,
        with_cover_letter=with_cover_letter,
        applied=applied,
        manual=manual,
        expired=expired,
        score_dist=score_dist,
        site_stats=site_stats,
        jobs=jobs,
    )
