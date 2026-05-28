from __future__ import annotations

import sqlite3

from divapply.scoring import ultimate


def test_fetch_top_jobs_orders_by_score_before_recency(monkeypatch) -> None:
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.execute("""
        CREATE TABLE jobs (
            title TEXT,
            company TEXT,
            site TEXT,
            location TEXT,
            fit_score INTEGER,
            score_reasoning TEXT,
            full_description TEXT,
            discovered_at TEXT
        )
    """)
    conn.executemany("""
        INSERT INTO jobs (
            title, company, site, location, fit_score, score_reasoning,
            full_description, discovered_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
    """, [
        ("Newer Lower", "Company B", "Indeed", "Remote", 7, "", "Required: SQL.", "2026-01-02"),
        ("Older Higher", "Company A", "LinkedIn", "Remote", 10, "", "Required: Python.", "2025-01-01"),
    ])
    conn.commit()
    monkeypatch.setattr(ultimate, "get_connection", lambda: conn)

    jobs = ultimate._fetch_top_jobs(n=2, min_score=7)

    assert [job["title"] for job in jobs] == ["Older Higher", "Newer Lower"]
