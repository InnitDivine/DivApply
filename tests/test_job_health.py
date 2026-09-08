from __future__ import annotations

from divapply import database, job_health
from divapply.scoring import scorer


def test_failed_page_refresh_removes_stale_grade_without_losing_job_or_documents(tmp_path, monkeypatch):
    path = tmp_path / "jobs.db"
    conn = database.init_db(path)
    conn.execute("INSERT INTO jobs(url,title,fit_score,qualification_score,tailored_resume_path) VALUES (?,?,?,?,?)",
                 ("https://example.com/job", "Analyst", 8, 8, "edited-resume.pdf"))
    conn.commit()
    monkeypatch.setattr(job_health, "get_connection", lambda: conn)
    monkeypatch.setattr(job_health, "refresh_job", lambda *_: (_ for _ in ()).throw(ValueError("Posting unreadable")))
    calls = []
    monkeypatch.setattr(scorer, "run_scoring", lambda **kwargs: calls.append(kwargs))
    result = job_health.repair_jobs(limit=1)
    assert result["errors"] == 1
    assert calls == []
    saved = conn.execute("SELECT * FROM jobs").fetchone()
    assert saved["fit_score"] is None
    assert saved["qualification_score"] is None
    assert saved["tailored_resume_path"] == "edited-resume.pdf"
    assert saved["archived_at"] is None
    assert "unreadable" in saved["detail_error"]
    database.close_connection(path)


def test_document_status_does_not_claim_a_missing_file_is_ready(tmp_path):
    from divapply.scoring.requirements import SCORING_VERSION
    job = {"title": "Assistant", "scoring_version": SCORING_VERSION, "fit_score": 8,
           "eligibility_status": "meets", "source_verification": "official", "application_mode": "active",
           "tailored_resume_path": str(tmp_path / "renamed-away.pdf")}
    assert job_health.document_issue(job) == "Saved resume file is missing"
