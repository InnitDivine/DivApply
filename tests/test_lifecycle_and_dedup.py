from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from divapply.database import (
    MIN_FULL_DESCRIPTION_CHARS,
    add_application_event,
    archive_job,
    canonical_job_key,
    close_connection,
    delete_scored_jobs_at_or_below,
    get_application_analytics,
    get_application_timeline,
    get_connection,
    get_due_followups,
    get_jobs_by_stage,
    get_stats,
    init_db,
    record_reliability_event,
    store_jobs,
)


LONG_DESCRIPTION = "Full job description with responsibilities and minimum qualifications. " * 5


def test_get_connection_creates_missing_parent_directory(tmp_path) -> None:
    db_path = tmp_path / "fresh" / "divapply.db"

    conn = get_connection(db_path)

    assert db_path.exists()
    conn.execute("SELECT 1").fetchone()
    close_connection(db_path)


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


def test_canonical_job_key_requires_title_and_company_to_avoid_sparse_false_matches() -> None:
    assert canonical_job_key("Support Analyst", None, "Reno, NV") is None
    assert canonical_job_key(None, "Acme", "Reno, NV") is None
    assert canonical_job_key("Support Analyst", "Acme", None) is not None


def test_store_jobs_keeps_sparse_jobs_that_lack_company(tmp_path) -> None:
    db_path = tmp_path / "divapply.db"
    conn = init_db(db_path)

    jobs = [
        {"url": "https://example.com/one", "title": "Support Analyst", "location": "Remote"},
        {"url": "https://example.com/two", "title": "Support Analyst", "location": "Remote"},
    ]

    new, existing = store_jobs(conn, jobs, site="test", strategy="unit")

    assert new == 2
    assert existing == 0
    assert conn.execute("SELECT COUNT(*) FROM jobs").fetchone()[0] == 2
    close_connection(db_path)


def test_store_jobs_rolls_back_batch_when_unexpected_insert_error_occurs(tmp_path) -> None:
    db_path = tmp_path / "divapply.db"
    conn = init_db(db_path)

    jobs = [
        {"url": "https://example.com/good", "title": "Good", "company": "Acme"},
        {"url": "https://example.com/bad", "title": "Bad", "company": "Acme", "salary": object()},
    ]

    with pytest.raises(Exception):
        store_jobs(conn, jobs, site="test", strategy="unit")

    assert conn.execute("SELECT COUNT(*) FROM jobs").fetchone()[0] == 0
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
            ("https://example.com/empty", "Empty", 8, LONG_DESCRIPTION, "", "resume.txt", "2026-01-01"),
            (
                "https://example.com/ready",
                "Ready",
                8,
                LONG_DESCRIPTION,
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
        ("https://example.com/cover", "Cover", 8, LONG_DESCRIPTION, "resume.txt", "", "2026-01-01"),
    )
    conn.commit()

    rows = get_jobs_by_stage(conn=conn, stage="pending_cover", min_score=7)

    assert [row["url"] for row in rows] == ["https://example.com/cover"]
    close_connection(db_path)


def test_get_jobs_by_stage_pending_score_requires_meaningful_description(tmp_path) -> None:
    db_path = tmp_path / "divapply.db"
    conn = init_db(db_path)
    conn.executemany(
        """
        INSERT INTO jobs (url, title, full_description, discovered_at)
        VALUES (?, ?, ?, ?)
        """,
        [
            ("https://example.com/snippet", "Snippet", "One-line metadata.", "2026-01-01"),
            (
                "https://example.com/full",
                "Full",
                "A" * MIN_FULL_DESCRIPTION_CHARS,
                "2026-01-02",
            ),
        ],
    )
    conn.commit()

    rows = get_jobs_by_stage(conn=conn, stage="pending_score")
    stats = get_stats(conn)

    assert [row["url"] for row in rows] == ["https://example.com/full"]
    assert stats["with_description"] == 1
    assert stats["unscored"] == 1
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


def test_archive_job_hides_job_from_ready_apply_counts(tmp_path) -> None:
    db_path = tmp_path / "divapply.db"
    conn = init_db(db_path)
    conn.execute(
        """
        INSERT INTO jobs (
            url, title, fit_score, full_description, tailored_resume_path,
            application_url, discovered_at
        )
        VALUES (?, ?, ?, ?, ?, ?, ?)
        """,
        (
            "https://example.com/archive-me",
            "Archive Me",
            8,
            "Description",
            "resume.txt",
            "https://example.com/apply",
            "2026-01-01",
        ),
    )
    conn.commit()

    assert get_stats(conn)["ready_to_apply"] == 1
    assert archive_job("https://example.com/archive-me", conn=conn) is True
    assert archive_job("https://example.com/archive-me", conn=conn) is False

    row = conn.execute(
        "SELECT archived_at FROM jobs WHERE url = ?",
        ("https://example.com/archive-me",),
    ).fetchone()
    assert row["archived_at"]
    assert get_stats(conn)["ready_to_apply"] == 0
    assert get_stats(conn)["archived"] == 1
    assert get_jobs_by_stage(conn=conn, stage="archived")[0]["url"] == "https://example.com/archive-me"
    close_connection(db_path)


def test_archive_job_deletes_generated_artifacts(tmp_path, monkeypatch) -> None:
    import divapply.config as config

    tailored_dir = tmp_path / "tailored_resumes"
    cover_dir = tmp_path / "cover_letters"
    tailored_dir.mkdir()
    cover_dir.mkdir()
    monkeypatch.setattr(config, "TAILORED_DIR", tailored_dir)
    monkeypatch.setattr(config, "COVER_LETTER_DIR", cover_dir)

    resume = tailored_dir / "Indeed_Support.txt"
    resume_pdf = tailored_dir / "Indeed_Support.pdf"
    job_trace = tailored_dir / "Indeed_Support_JOB.txt"
    report = tailored_dir / "Indeed_Support_REPORT.json"
    cover = cover_dir / "Indeed_Support_CL.txt"
    cover_pdf = cover_dir / "Indeed_Support_CL.pdf"
    for path in (resume, resume_pdf, job_trace, report, cover, cover_pdf):
        path.write_text("generated", encoding="utf-8")

    db_path = tmp_path / "divapply.db"
    conn = init_db(db_path)
    conn.execute(
        """
        INSERT INTO jobs (
            url, title, fit_score, full_description, tailored_resume_path,
            cover_letter_path, application_url, discovered_at
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            "https://example.com/archive-artifacts",
            "Archive Artifacts",
            8,
            "Description",
            str(resume),
            str(cover),
            "https://example.com/apply",
            "2026-01-01",
        ),
    )
    conn.commit()

    assert archive_job("https://example.com/archive-artifacts", conn=conn) is True

    for path in (resume, resume_pdf, job_trace, report, cover, cover_pdf):
        assert not path.exists()
    close_connection(db_path)


def test_archive_job_deletes_generated_artifacts_when_db_points_to_pdfs(tmp_path, monkeypatch) -> None:
    import divapply.config as config

    tailored_dir = tmp_path / "tailored_resumes"
    cover_dir = tmp_path / "cover_letters"
    tailored_dir.mkdir()
    cover_dir.mkdir()
    monkeypatch.setattr(config, "TAILORED_DIR", tailored_dir)
    monkeypatch.setattr(config, "COVER_LETTER_DIR", cover_dir)

    resume = tailored_dir / "Indeed_Support.txt"
    resume_pdf = tailored_dir / "Indeed_Support.pdf"
    job_trace = tailored_dir / "Indeed_Support_JOB.txt"
    report = tailored_dir / "Indeed_Support_REPORT.json"
    cover = cover_dir / "Indeed_Support_CL.txt"
    cover_pdf = cover_dir / "Indeed_Support_CL.pdf"
    for path in (resume, resume_pdf, job_trace, report, cover, cover_pdf):
        path.write_text("generated", encoding="utf-8")

    db_path = tmp_path / "divapply.db"
    conn = init_db(db_path)
    conn.execute(
        """
        INSERT INTO jobs (
            url, title, fit_score, full_description, tailored_resume_path,
            cover_letter_path, application_url, discovered_at
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            "https://example.com/archive-pdf-artifacts",
            "Archive PDF Artifacts",
            8,
            "Description",
            str(resume_pdf),
            str(cover_pdf),
            "https://example.com/apply",
            "2026-01-01",
        ),
    )
    conn.commit()

    assert archive_job("https://example.com/archive-pdf-artifacts", conn=conn) is True

    for path in (resume, resume_pdf, job_trace, report, cover, cover_pdf):
        assert not path.exists()
    close_connection(db_path)


def test_archive_job_does_not_delete_paths_outside_generated_dirs(tmp_path, monkeypatch) -> None:
    import divapply.config as config

    tailored_dir = tmp_path / "tailored_resumes"
    cover_dir = tmp_path / "cover_letters"
    tailored_dir.mkdir()
    cover_dir.mkdir()
    monkeypatch.setattr(config, "TAILORED_DIR", tailored_dir)
    monkeypatch.setattr(config, "COVER_LETTER_DIR", cover_dir)

    outside = tmp_path / "outside-resume.txt"
    outside.write_text("keep me", encoding="utf-8")
    db_path = tmp_path / "divapply.db"
    conn = init_db(db_path)
    conn.execute(
        """
        INSERT INTO jobs (url, title, tailored_resume_path, discovered_at)
        VALUES (?, ?, ?, ?)
        """,
        ("https://example.com/archive-outside", "Archive Outside", str(outside), "2026-01-01"),
    )
    conn.commit()

    assert archive_job("https://example.com/archive-outside", conn=conn) is True

    assert outside.exists()
    assert outside.read_text(encoding="utf-8") == "keep me"
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
                LONG_DESCRIPTION,
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
                LONG_DESCRIPTION,
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
                LONG_DESCRIPTION,
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


def test_add_application_event_applied_sets_timestamp_and_failed_clears_stale_timestamp(tmp_path) -> None:
    db_path = tmp_path / "divapply.db"
    conn = init_db(db_path)
    conn.execute(
        "INSERT INTO jobs (url, title, discovered_at) VALUES (?, ?, ?)",
        ("https://example.com/job", "Analyst", "2026-01-01"),
    )
    conn.commit()

    add_application_event("https://example.com/job", "applied", ts="2026-01-02T00:00:00+00:00", conn=conn)
    applied = conn.execute(
        "SELECT apply_status, applied_at FROM jobs WHERE url = ?",
        ("https://example.com/job",),
    ).fetchone()

    assert applied["apply_status"] == "applied"
    assert applied["applied_at"] == "2026-01-02T00:00:00+00:00"

    add_application_event("https://example.com/job", "failed", ts="2026-01-03T00:00:00+00:00", conn=conn)
    failed = conn.execute(
        "SELECT apply_status, applied_at FROM jobs WHERE url = ?",
        ("https://example.com/job",),
    ).fetchone()

    assert failed["apply_status"] == "failed"
    assert failed["applied_at"] is None
    close_connection(db_path)


def test_add_application_event_rejects_unknown_job_url(tmp_path) -> None:
    db_path = tmp_path / "divapply.db"
    conn = init_db(db_path)

    with pytest.raises(ValueError, match="job_url does not exist"):
        add_application_event("https://example.com/missing", "applied", conn=conn)

    count = conn.execute("SELECT COUNT(*) FROM application_events").fetchone()[0]
    event = conn.execute(
        "SELECT severity, category FROM reliability_events WHERE category = ?",
        ("application_event_orphan_rejected",),
    ).fetchone()

    assert count == 0
    assert event["severity"] == "error"
    close_connection(db_path)


def test_delete_scored_jobs_at_or_below_removes_lifecycle_events_first(tmp_path) -> None:
    db_path = tmp_path / "divapply.db"
    conn = init_db(db_path)
    conn.execute(
        "INSERT INTO jobs (url, title, fit_score, discovered_at) VALUES (?, ?, ?, ?)",
        ("https://example.com/low", "Low Fit", 4, "2026-01-01"),
    )
    conn.execute(
        "INSERT INTO jobs (url, title, fit_score, discovered_at) VALUES (?, ?, ?, ?)",
        ("https://example.com/high", "High Fit", 8, "2026-01-01"),
    )
    conn.commit()
    add_application_event("https://example.com/low", "applied", conn=conn)

    deleted = delete_scored_jobs_at_or_below(4, conn=conn)

    assert deleted == 1
    assert conn.execute("SELECT COUNT(*) FROM jobs WHERE url = ?", ("https://example.com/low",)).fetchone()[0] == 0
    assert conn.execute("SELECT COUNT(*) FROM jobs WHERE url = ?", ("https://example.com/high",)).fetchone()[0] == 1
    assert conn.execute("SELECT COUNT(*) FROM application_events").fetchone()[0] == 0
    close_connection(db_path)


def test_get_stats_reports_reliability_error_monitoring(tmp_path) -> None:
    db_path = tmp_path / "divapply.db"
    conn = init_db(db_path)

    record_reliability_event(
        "unit_test_failure",
        "Simulated reliability event",
        severity="error",
        conn=conn,
    )

    assert get_stats(conn)["reliability_errors"] == 1
    close_connection(db_path)
