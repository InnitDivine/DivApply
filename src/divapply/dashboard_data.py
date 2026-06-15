"""Read models for the HTML dashboard.

This module keeps dashboard SQL and row-shaping out of the HTML/server layer.
"""

from __future__ import annotations

from dataclasses import dataclass
import sqlite3

from divapply.database import get_connection


@dataclass(frozen=True)
class DashboardSnapshot:
    """All data needed to render the HTML dashboard."""

    total: int
    archived: int
    ready: int
    scored: int
    high_fit: int
    score_dist: dict[int, int]
    site_stats: list[sqlite3.Row]
    jobs: list[sqlite3.Row]


def fetch_dashboard_snapshot(conn: sqlite3.Connection | None = None) -> DashboardSnapshot:
    """Fetch and shape all database data required by the dashboard view."""
    if conn is None:
        conn = get_connection()

    counts = conn.execute(
        """
        SELECT
            SUM(CASE WHEN archived_at IS NULL THEN 1 ELSE 0 END) AS total,
            SUM(CASE WHEN archived_at IS NOT NULL THEN 1 ELSE 0 END) AS archived,
            SUM(CASE
                WHEN archived_at IS NULL
                 AND full_description IS NOT NULL
                 AND COALESCE(application_url, '') != ''
                THEN 1 ELSE 0
            END) AS ready,
            SUM(CASE
                WHEN archived_at IS NULL
                 AND fit_score IS NOT NULL
                THEN 1 ELSE 0
            END) AS scored,
            SUM(CASE
                WHEN archived_at IS NULL
                 AND fit_score >= 7
                THEN 1 ELSE 0
            END) AS high_fit
        FROM jobs
        """
    ).fetchone()
    total = int(counts["total"] or 0)
    archived = int(counts["archived"] or 0)
    ready = int(counts["ready"] or 0)
    scored = int(counts["scored"] or 0)
    high_fit = int(counts["high_fit"] or 0)

    score_dist: dict[int, int] = {}
    if scored:
        rows = conn.execute(
            "SELECT fit_score, COUNT(*) FROM jobs "
            "WHERE archived_at IS NULL AND fit_score IS NOT NULL "
            "GROUP BY fit_score ORDER BY fit_score DESC"
        ).fetchall()
        for row in rows:
            score_dist[int(row[0])] = int(row[1])

    site_stats = conn.execute("""
        SELECT site,
               COUNT(*) as total,
               SUM(CASE WHEN fit_score >= 7 THEN 1 ELSE 0 END) as high_fit,
               SUM(CASE WHEN fit_score BETWEEN 5 AND 6 THEN 1 ELSE 0 END) as mid_fit,
               SUM(CASE WHEN fit_score < 5 AND fit_score IS NOT NULL THEN 1 ELSE 0 END) as low_fit,
               SUM(CASE WHEN fit_score IS NULL THEN 1 ELSE 0 END) as unscored,
               ROUND(AVG(fit_score), 1) as avg_score
        FROM jobs
        WHERE archived_at IS NULL
        GROUP BY site ORDER BY high_fit DESC, total DESC
    """).fetchall()

    jobs = conn.execute("""
        SELECT url, title, salary, description, location, site, strategy,
               full_description, application_url, detail_error,
               fit_score, score_reasoning, apply_status, applied_at
        FROM jobs
        WHERE archived_at IS NULL AND fit_score >= 5
        ORDER BY fit_score DESC, site, title
    """).fetchall()

    return DashboardSnapshot(
        total=total,
        archived=archived,
        ready=ready,
        scored=scored,
        high_fit=high_fit,
        score_dist=score_dist,
        site_stats=site_stats,
        jobs=jobs,
    )
