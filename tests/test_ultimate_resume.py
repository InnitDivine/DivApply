from __future__ import annotations

import sqlite3

from divapply.scoring import ultimate


def _make_jobs_conn() -> sqlite3.Connection:
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.execute("""
        CREATE TABLE jobs (
            url TEXT PRIMARY KEY,
            application_url TEXT,
            title TEXT,
            company TEXT,
            site TEXT,
            location TEXT,
            fit_score INTEGER,
            discovered_at TEXT,
            full_description TEXT,
            tailored_resume_path TEXT,
            tailored_at TEXT,
            tailor_attempts INTEGER
        )
    """)
    conn.executemany("""
        INSERT INTO jobs (
            url, application_url, title, company, site, location, fit_score,
            discovered_at, full_description, tailor_attempts
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, [
        (
            "https://jobs.example/lower",
            "https://apply.example/lower",
            "Patient Access Customer Service Representative",
            "Clinic",
            "SimplyHired",
            "Logan, UT",
            3,
            "2026-01-02",
            "Required: customer service and scheduling.",
            0,
        ),
        (
            "https://jobs.example/higher",
            "https://apply.example/higher",
            "Network and End User Support Specialist",
            "USU",
            "SimplyHired",
            "Logan, UT",
            7,
            "2026-01-01",
            "Required: desktop support, networking, and user support.",
            0,
        ),
    ])
    conn.commit()
    return conn


def test_fetch_target_job_matches_url_or_title_fragment(monkeypatch) -> None:
    conn = _make_jobs_conn()
    monkeypatch.setattr(ultimate, "get_connection", lambda: conn)

    by_url = ultimate._fetch_target_job("apply.example/higher")
    by_title = ultimate._fetch_target_job("Network and End User")

    assert by_url is not None
    assert by_url["title"] == "Network and End User Support Specialist"
    assert by_title is not None
    assert by_title["url"] == "https://jobs.example/higher"


def test_generate_targeted_resume_writes_files_without_llm(monkeypatch, tmp_path) -> None:
    conn = _make_jobs_conn()
    resume_path = tmp_path / "resume.txt"
    resume_path.write_text("Base resume", encoding="utf-8")

    monkeypatch.setattr(ultimate, "get_connection", lambda: conn)
    monkeypatch.setattr(ultimate, "load_env", lambda: None)
    monkeypatch.setattr(ultimate, "ensure_dirs", lambda: None)
    monkeypatch.setattr(ultimate, "init_db", lambda: None)
    monkeypatch.setattr(ultimate, "load_profile", lambda: {"personal": {"full_name": "Test User"}})
    monkeypatch.setattr(ultimate, "RESUME_PATH", resume_path)
    monkeypatch.setattr(
        ultimate,
        "tailor_resume",
        lambda resume_text, job, profile, validation_mode="normal": (
            "Targeted resume text",
            {"status": "failed_validation", "attempts": 1},
        ),
    )

    result = ultimate.generate_targeted_resume("higher", output_dir=tmp_path, validation_mode="none")

    assert result["status"] == "failed_validation"
    assert "Network_and_End_User_Support_Specialist" in result["text_path"]
    assert (tmp_path / "targeted_SimplyHired_Network_and_End_User_Support_Specialist.txt").read_text(
        encoding="utf-8"
    ) == "Targeted resume text"
    assert (tmp_path / "targeted_SimplyHired_Network_and_End_User_Support_Specialist_REPORT.json").exists()
