from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from divapply.database import (
    add_application_event,
    canonical_job_key,
    close_connection,
    get_application_analytics,
    get_application_timeline,
    get_due_followups,
    get_jobs_by_stage,
    get_stats,
    init_db,
    store_jobs,
)


def test_application_events_track_timeline_and_followups(tmp_path) -> None:
    db_path = tmp_path / "divapply.db"
    conn = init_db(db_path)
    conn.execute(
        "INSERT INTO jobs (url, title, company, discovered_at) VALUES (?, ?, ?, ?)",
        ("https://example.com/job", "Analyst", "Example", "2026-01-01"),
    )
    conn.commit()

    add_application_event(
        "https://example.com/job",
        "screening",
        follow_up_at="2026-01-02",
        notes="Recruiter screen",
        conn=conn,
    )

    timeline = get_application_timeline("https://example.com/job", conn)
    due = get_due_followups(today="2026-01-03", conn=conn)
    analytics = get_application_analytics(conn)

    assert timeline[0]["event_type"] == "screening"
    assert due[0]["title"] == "Analyst"
    assert ("screening", 1) in analytics["states"]
    close_connection(db_path)


def test_store_jobs_soft_dedups_by_canonical_key(tmp_path) -> None:
    db_path = tmp_path / "divapply.db"
    conn = init_db(db_path)

    jobs = [
        {
            "url": "https://board-one.example/jobs/1",
            "title": "Support Analyst",
            "company": "Acme Inc.",
            "location": "Reno, NV",
            "description": "Help customers.",
        },
        {
            "url": "https://board-two.example/jobs/2",
            "title": "Support Analyst",
            "company": "Acme",
            "location": "Reno NV",
            "description": "Same role.",
        },
    ]

    new, existing = store_jobs(conn, jobs, site="test", strategy="unit")

    assert new == 1
    assert existing == 1
    assert canonical_job_key("Support Analyst", "Acme Inc.", "Reno, NV") == canonical_job_key(
        "Support Analyst", "Acme", "Reno NV"
    )
    close_connection(db_path)


def test_get_jobs_by_stage_applies_min_score_to_scored_stage(tmp_path) -> None:
    db_path = tmp_path / "divapply.db"
    conn = init_db(db_path)
    conn.executemany(
        """
        INSERT INTO jobs (url, title, fit_score, full_description, discovered_at)
        VALUES (?, ?, ?, ?, ?)
        """,
        [
            ("https://example.com/low", "Low", 3, "Description", "2026-01-01"),
            ("https://example.com/high", "High", 8, "Description", "2026-01-02"),
        ],
    )
    conn.commit()

    rows = get_jobs_by_stage(conn=conn, stage="scored", min_score=7)

    assert [row["url"] for row in rows] == ["https://example.com/high"]
    close_connection(db_path)


def test_get_jobs_by_stage_pending_apply_requires_nonempty_application_url(tmp_path) -> None:
    db_path = tmp_path / "divapply.db"
    conn = init_db(db_path)
    conn.executemany(
        """
        INSERT INTO jobs (
            url, title, fit_score, full_description, application_url,
            tailored_resume_path, discovered_at
        )
        VALUES (?, ?, ?, ?, ?, ?, ?)
        """,
        [
            ("https://example.com/empty", "Empty", 8, "Description", "", "resume.txt", "2026-01-01"),
            (
                "https://example.com/ready",
                "Ready",
                8,
                "Description",
                "https://apply.example/ready",
                "resume.txt",
                "2026-01-02",
            ),
        ],
    )
    conn.commit()

    rows = get_jobs_by_stage(conn=conn, stage="pending_apply")
    stats = get_stats(conn)

    assert [row["url"] for row in rows] == ["https://example.com/ready"]
    assert stats["ready_to_apply"] == 1
    close_connection(db_path)


def test_get_jobs_by_stage_pending_cover_treats_empty_path_as_missing(tmp_path) -> None:
    db_path = tmp_path / "divapply.db"
    conn = init_db(db_path)
    conn.execute(
        """
        INSERT INTO jobs (
            url, title, fit_score, full_description,
            tailored_resume_path, cover_letter_path, discovered_at
        )
        VALUES (?, ?, ?, ?, ?, ?, ?)
        """,
        ("https://example.com/cover", "Cover", 8, "Description", "resume.txt", "", "2026-01-01"),
    )
    conn.commit()

    rows = get_jobs_by_stage(conn=conn, stage="pending_cover", min_score=7)

    assert [row["url"] for row in rows] == ["https://example.com/cover"]
    close_connection(db_path)


def test_get_stats_reports_apply_lock_monitoring(tmp_path) -> None:
    db_path = tmp_path / "divapply.db"
    conn = init_db(db_path)
    stale = (datetime.now(timezone.utc) - timedelta(hours=2)).isoformat()
    fresh = datetime.now(timezone.utc).isoformat()
    conn.executemany(
        """
        INSERT INTO jobs (url, title, apply_status, last_attempted_at, discovered_at)
        VALUES (?, ?, ?, ?, ?)
        """,
        [
            ("https://example.com/stale", "Stale", "in_progress", stale, "2026-01-01"),
            ("https://example.com/fresh", "Fresh", "in_progress", fresh, "2026-01-01"),
        ],
    )
    conn.commit()

    stats = get_stats(conn)

    assert stats["apply_in_progress"] == 2
    assert stats["stale_apply_locks"] == 1
    close_connection(db_path)


def test_get_stats_reports_aggregate_stage_counts(tmp_path) -> None:
    db_path = tmp_path / "divapply.db"
    conn = init_db(db_path)
    old_attempt = (datetime.now(timezone.utc) - timedelta(hours=2)).isoformat()
    conn.executemany(
        """
        INSERT INTO jobs (
            url, title, site, detail_scraped_at, full_description, detail_error,
            fit_score, tailored_resume_path, tailor_attempts, cover_letter_path,
            cover_attempts, applied_at, apply_status, apply_error, application_url,
            last_attempted_at, discovered_at
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        [
            (
                "https://example.com/pending-detail",
                "Pending Detail",
                "Indeed",
                None,
                None,
                None,
                None,
                None,
                0,
                None,
                0,
                None,
                None,
                None,
                None,
                None,
                "2026-01-01",
            ),
            (
                "https://example.com/unscored",
                "Unscored",
                "Indeed",
                "2026-01-01",
                "Description",
                None,
                None,
                None,
                5,
                None,
                0,
                None,
                None,
                None,
                None,
                None,
                "2026-01-02",
            ),
            (
                "https://example.com/ready",
                "Ready",
                "LinkedIn",
                "2026-01-01",
                "Description",
                "minor scrape issue",
                8,
                "resume.txt",
                0,
                "",
                5,
                None,
                "in_progress",
                "temporary error",
                "https://apply.example/ready",
                old_attempt,
                "2026-01-03",
            ),
            (
                "https://example.com/applied",
                "Applied",
                "LinkedIn",
                "2026-01-01",
                "Description",
                None,
                6,
                "resume2.txt",
                0,
                "cover.pdf",
                0,
                "2026-01-04",
                "applied",
                None,
                "https://apply.example/applied",
                None,
                "2026-01-04",
            ),
        ],
    )
    conn.commit()

    stats = get_stats(conn)

    assert stats["total"] == 4
    assert stats["pending_detail"] == 1
    assert stats["with_description"] == 3
    assert stats["detail_errors"] == 1
    assert stats["scored"] == 2
    assert stats["unscored"] == 1
    assert stats["tailored"] == 2
    assert stats["untailored_eligible"] == 0
    assert stats["tailor_exhausted"] == 1
    assert stats["with_cover_letter"] == 1
    assert stats["cover_exhausted"] == 1
    assert stats["applied"] == 1
    assert stats["apply_errors"] == 1
    assert stats["apply_in_progress"] == 1
    assert stats["stale_apply_locks"] == 1
    assert stats["ready_to_apply"] == 1
    assert set(stats["by_site"]) == {("LinkedIn", 2), ("Indeed", 2)}
    assert stats["score_distribution"] == [(8, 1), (6, 1)]
    close_connection(db_path)


def test_get_jobs_by_stage_rejects_unknown_stage(tmp_path) -> None:
    db_path = tmp_path / "divapply.db"
    conn = init_db(db_path)

    with pytest.raises(ValueError, match="Unknown job stage"):
        get_jobs_by_stage(conn=conn, stage="everything")

    close_connection(db_path)


def test_add_application_event_rolls_back_invalid_event_type(tmp_path) -> None:
    db_path = tmp_path / "divapply.db"
    conn = init_db(db_path)
    conn.execute(
        "INSERT INTO jobs (url, title, discovered_at) VALUES (?, ?, ?)",
        ("https://example.com/job", "Analyst", "2026-01-01"),
    )
    conn.commit()

    with pytest.raises(ValueError, match="event_type"):
        add_application_event("https://example.com/job", "", conn=conn)

    count = conn.execute("SELECT COUNT(*) FROM application_events").fetchone()[0]
    status = conn.execute("SELECT apply_status FROM jobs WHERE url = ?", ("https://example.com/job",)).fetchone()[0]

    assert count == 0
    assert status is None
    close_connection(db_path)
