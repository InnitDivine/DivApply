from __future__ import annotations

from datetime import datetime, timedelta, timezone
import sqlite3

import httpx

from divapply.database import close_connection, get_jobs_by_stage, init_db
from divapply.scoring import scorer


def _scoring_db() -> sqlite3.Connection:
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.execute(
        """
        CREATE TABLE jobs (
            url TEXT PRIMARY KEY,
            title TEXT,
            site TEXT,
            description TEXT,
            full_description TEXT,
            fit_score INTEGER,
            llm_score INTEGER,
            keyword_score REAL,
            embedding_score REAL,
            composite_score REAL,
            score_breakdown TEXT,
            score_reasoning TEXT,
            matched_skills TEXT,
            missing_skills TEXT,
            keyword_hits TEXT,
            risk_flags TEXT,
            apply_or_skip_reason TEXT,
            scored_at TEXT,
            score_attempts INTEGER DEFAULT 0,
            score_error TEXT,
            score_retry_at TEXT,
            archived_at TEXT,
            discovered_at TEXT
        )
        """
    )
    return conn


def _job(url: str = "https://jobs.example.test/retry") -> dict[str, object]:
    return {
        "url": url,
        "title": "Retryable Role",
        "site": "Example",
        "description": "",
        "full_description": "Support users and document incidents. " * 10,
        "fit_score": None,
        "score_attempts": 0,
        "score_error": None,
        "score_retry_at": None,
        "discovered_at": "2026-07-11T00:00:00+00:00",
    }


def _insert_job(conn: sqlite3.Connection, job: dict[str, object]) -> None:
    conn.execute(
        """
        INSERT INTO jobs (
            url, title, site, description, full_description, fit_score,
            score_attempts, score_error, score_retry_at, discovered_at
        ) VALUES (
            :url, :title, :site, :description, :full_description, :fit_score,
            :score_attempts, :score_error, :score_retry_at, :discovered_at
        )
        """,
        job,
    )
    conn.commit()


def test_score_job_marks_provider_exception_separately_from_valid_zero(monkeypatch) -> None:
    class FailingClient:
        def chat(self, *_args, **_kwargs):
            raise httpx.ConnectError("provider unavailable")

    monkeypatch.setattr(scorer, "get_client_for_stage", lambda _stage: FailingClient())

    result = scorer.score_job("resume", _job())

    assert result["score"] == 0
    assert result["error"] == "provider unavailable"
    assert result["risk_flags"] == "llm_error"


def test_run_scoring_leaves_provider_failure_retryable_then_clears_state_on_success(
    tmp_path,
    monkeypatch,
) -> None:
    conn = _scoring_db()
    job = _job()
    _insert_job(conn, job)
    resume = tmp_path / "resume.txt"
    resume.write_text("resume", encoding="utf-8")
    monkeypatch.setattr(scorer, "RESUME_PATH", resume)
    monkeypatch.setattr(scorer, "load_profile", lambda: {})
    monkeypatch.setattr(scorer, "load_search_config", lambda: {})
    monkeypatch.setattr(scorer, "get_connection", lambda: conn)
    monkeypatch.setattr(scorer, "get_jobs_by_stage", lambda **_kwargs: [dict(job)])
    monkeypatch.setattr(
        scorer,
        "score_job",
        lambda *_args, **_kwargs: {
            "score": 0,
            "reasoning": "LLM error: provider unavailable",
            "risk_flags": "llm_error",
            "error": "provider unavailable",
        },
    )

    failed = scorer.run_scoring()
    failed_row = conn.execute("SELECT * FROM jobs WHERE url = ?", (job["url"],)).fetchone()

    assert failed == {"scored": 0, "errors": 1, "elapsed": failed["elapsed"], "distribution": [], "pruned": 0}
    assert failed_row["fit_score"] is None
    assert failed_row["scored_at"] is None
    assert failed_row["score_attempts"] == 1
    assert failed_row["score_error"] == "provider unavailable"
    retry_at = datetime.fromisoformat(failed_row["score_retry_at"])
    assert datetime.now(timezone.utc) < retry_at <= datetime.now(timezone.utc) + timedelta(hours=24)

    monkeypatch.setattr(
        scorer,
        "score_job",
        lambda *_args, **_kwargs: {
            "score": 8,
            "llm_score": 8,
            "keyword_score": 75.0,
            "embedding_score": 70.0,
            "composite_score": 8.0,
            "score_breakdown": "{}",
            "reasoning": "strong match",
            "matched_skills": "support",
            "missing_skills": "",
            "keyword_hits": "support",
            "risk_flags": "",
            "apply_or_skip_reason": "Apply",
        },
    )

    succeeded = scorer.run_scoring(target_url=str(job["url"]))
    success_row = conn.execute("SELECT * FROM jobs WHERE url = ?", (job["url"],)).fetchone()

    assert succeeded["scored"] == 1
    assert succeeded["errors"] == 0
    assert success_row["fit_score"] == 8
    assert success_row["scored_at"] is not None
    assert success_row["score_attempts"] == 0
    assert success_row["score_error"] is None
    assert success_row["score_retry_at"] is None


def test_pending_score_stage_honors_retry_time_and_attempt_cap() -> None:
    conn = _scoring_db()
    now = datetime.now(timezone.utc)
    due = _job("https://jobs.example.test/due") | {
        "score_attempts": 2,
        "score_retry_at": (now - timedelta(minutes=1)).isoformat(),
    }
    future = _job("https://jobs.example.test/future") | {
        "score_attempts": 1,
        "score_retry_at": (now + timedelta(hours=1)).isoformat(),
    }
    exhausted = _job("https://jobs.example.test/exhausted") | {
        "score_attempts": 5,
        "score_retry_at": (now - timedelta(days=1)).isoformat(),
    }
    for job in (due, future, exhausted):
        _insert_job(conn, job)

    rows = get_jobs_by_stage(conn=conn, stage="pending_score", limit=0)

    assert [row["url"] for row in rows] == [due["url"]]


def test_rescore_skips_archived_jobs(tmp_path, monkeypatch) -> None:
    db_path = tmp_path / "divapply.db"
    conn = init_db(db_path)
    conn.execute(
        "INSERT INTO jobs (url, title, full_description, fit_score, archived_at) VALUES (?, ?, ?, ?, ?)",
        ("https://jobs.example.test/archived", "Archived", "Support users. " * 30, 7, "2026-07-12"),
    )
    conn.commit()
    resume_path = tmp_path / "resume.txt"
    resume_path.write_text("Resume", encoding="utf-8")
    monkeypatch.setattr(scorer, "get_connection", lambda: conn)
    monkeypatch.setattr(scorer, "load_profile", lambda: {})
    monkeypatch.setattr(scorer, "load_search_config", lambda: {})
    monkeypatch.setattr(scorer, "RESUME_PATH", resume_path)
    monkeypatch.setattr(
        scorer,
        "score_job",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("archived job must not rescore")),
    )

    result = scorer.run_scoring(rescore=True)

    assert result == {"scored": 0, "errors": 0, "elapsed": 0.0, "distribution": []}
    close_connection(db_path)
