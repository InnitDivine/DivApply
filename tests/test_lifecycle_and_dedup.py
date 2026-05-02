from __future__ import annotations

from divapply.database import (
    add_application_event,
    canonical_job_key,
    close_connection,
    get_application_analytics,
    get_application_timeline,
    get_due_followups,
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
