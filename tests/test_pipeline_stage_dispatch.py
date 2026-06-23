from __future__ import annotations

import threading

from divapply import pipeline
from divapply.database import close_connection, init_db
from divapply.discovery import jobspy
from divapply.discovery import smartextract
from divapply.discovery import workday


LONG_DESCRIPTION = "Full job description with responsibilities and minimum qualifications. " * 5


def test_discover_stage_preserves_jobspy_board_stats(monkeypatch) -> None:
    expected = {
        "indeed": {"calls": 1, "seconds": 0.2, "total": 3, "new": 2, "existing": 1, "errors": 0}
    }

    monkeypatch.setattr(
        jobspy,
        "run_discovery",
        lambda workers=4: {"new": 2, "existing": 1, "errors": 0, "board_stats": expected},
    )
    monkeypatch.setattr(workday, "run_workday_discovery", lambda workers=1: {"status": "ok"})
    monkeypatch.setattr(smartextract, "run_smart_extract", lambda workers=1: {"status": "ok"})

    result = pipeline._run_discover(workers=1)

    assert result["jobspy"] == "ok"
    assert result["jobspy_board_stats"] == expected


def test_streaming_discover_normalizes_partial_substage_errors(monkeypatch) -> None:
    monkeypatch.setitem(
        pipeline.STAGE_SPECS,
        "discover",
        pipeline.StageSpec(
            name="discover",
            desc="Discovery",
            runner=lambda: {"jobspy": "error: unavailable", "workday": "ok"},
        ),
    )
    tracker = pipeline._StageTracker()

    pipeline._run_stage_streaming("discover", tracker, threading.Event())

    assert tracker.get_results()["discover"]["status"] == "partial"


def test_streaming_stage_records_error_status_and_stops(monkeypatch) -> None:
    calls = 0

    def fail_once() -> dict:
        nonlocal calls
        calls += 1
        return {"status": "error: scoring unavailable"}

    monkeypatch.setitem(
        pipeline.STAGE_SPECS,
        "score",
        pipeline.StageSpec(
            name="score",
            desc="Scoring",
            runner=fail_once,
            upstream="enrich",
        ),
    )
    monkeypatch.setattr(pipeline, "_count_pending", lambda stage, min_score=7: 1)
    tracker = pipeline._StageTracker()
    tracker.mark_done("enrich", {"status": "ok"})

    pipeline._run_stage_streaming("score", tracker, threading.Event())

    assert calls == 1
    assert tracker.get_results()["score"]["status"] == "error: scoring unavailable"


def test_streaming_pending_counts_require_meaningful_full_description(tmp_path, monkeypatch) -> None:
    db_path = tmp_path / "divapply.db"
    conn = init_db(db_path)
    conn.executemany(
        """
        INSERT INTO jobs (
            url, title, full_description, fit_score, tailored_resume_path,
            tailor_attempts, discovered_at
        )
        VALUES (?, ?, ?, ?, ?, ?, ?)
        """,
        [
            ("https://example.com/score-short", "Score Short", "Metadata.", None, None, 0, "2026-01-01"),
            ("https://example.com/score-full", "Score Full", LONG_DESCRIPTION, None, None, 0, "2026-01-02"),
            ("https://example.com/tailor-short", "Tailor Short", "Metadata.", 8, None, 0, "2026-01-03"),
            ("https://example.com/tailor-full", "Tailor Full", LONG_DESCRIPTION, 8, None, 0, "2026-01-04"),
        ],
    )
    conn.commit()
    monkeypatch.setattr(pipeline, "get_connection", lambda: conn)

    assert pipeline._count_pending("score") == 1
    assert pipeline._count_pending("tailor", min_score=7) == 1
    close_connection(db_path)
