from __future__ import annotations

import threading

from divapply import pipeline
from divapply.database import close_connection, init_db
from divapply.discovery import jobspy
from divapply.discovery import smartextract
from divapply.discovery import workday
from divapply.scoring import cover_letter, tailor


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


def test_streaming_stage_preserves_partial_result(monkeypatch) -> None:
    counts = iter((1, 0, 0))
    monkeypatch.setitem(
        pipeline.STAGE_SPECS,
        "score",
        pipeline.StageSpec(
            name="score",
            desc="Scoring",
            runner=lambda: {"status": "partial"},
            upstream="enrich",
        ),
    )
    monkeypatch.setattr(
        pipeline, "_count_pending", lambda _stage, min_score=7: next(counts)
    )
    tracker = pipeline._StageTracker()
    tracker.mark_done("enrich", {"status": "ok"})

    pipeline._run_stage_streaming("score", tracker, threading.Event())

    assert tracker.get_results()["score"]["status"] == "partial"


def test_streaming_stage_stops_after_bounded_no_progress(monkeypatch) -> None:
    calls = 0

    def no_progress() -> dict:
        nonlocal calls
        calls += 1
        return {"status": "ok"}

    monkeypatch.setitem(
        pipeline.STAGE_SPECS,
        "score",
        pipeline.StageSpec(
            name="score",
            desc="Scoring",
            runner=no_progress,
            upstream="enrich",
        ),
    )
    monkeypatch.setattr(pipeline, "_count_pending", lambda _stage, min_score=7: 1)
    monkeypatch.setattr(pipeline, "_STREAM_POLL_INTERVAL", 0)
    tracker = pipeline._StageTracker()
    tracker.mark_done("enrich", {"status": "ok"})

    pipeline._run_stage_streaming("score", tracker, threading.Event())

    assert calls == 2
    assert tracker.get_results()["score"]["status"] == "partial"
    assert tracker.get_results()["score"]["reason"] == "no progress"


def test_tailor_and_cover_stage_statuses_propagate_runner_failures(monkeypatch) -> None:
    monkeypatch.setattr(
        tailor,
        "run_tailoring",
        lambda **_kwargs: {"approved": 0, "failed": 8, "errors": 0, "elapsed": 1.0},
    )
    monkeypatch.setattr(
        cover_letter,
        "run_cover_letters",
        lambda **_kwargs: {"generated": 2, "errors": 1, "elapsed": 1.0},
    )

    tailor_result = pipeline._run_tailor(min_score=7, validation_mode="strict")
    cover_result = pipeline._run_cover(min_score=7, validation_mode="strict")

    assert tailor_result["status"].startswith("error:")
    assert cover_result["status"] == "partial"


def test_enrich_and_score_stage_statuses_propagate_runner_failures(monkeypatch) -> None:
    from divapply.enrichment import detail
    from divapply.scoring import scorer

    monkeypatch.setattr(
        detail,
        "run_enrichment",
        lambda **_kwargs: {"processed": 3, "ok": 2, "partial": 0, "error": 1},
    )
    monkeypatch.setattr(
        scorer,
        "run_scoring",
        lambda **_kwargs: {"scored": 0, "errors": 2, "pruned": 0},
    )

    assert pipeline._run_enrich(workers=1)["status"] == "partial"
    assert pipeline._run_score()["status"].startswith("error:")


def test_streaming_pending_counts_require_meaningful_full_description(tmp_path, monkeypatch) -> None:
    db_path = tmp_path / "divapply.db"
    conn = init_db(db_path)
    conn.executemany(
        """
        INSERT INTO jobs (
            url, title, full_description, fit_score, tailored_resume_path,
            tailor_attempts, discovered_at, application_mode, source_verification
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, 'active', 'official')
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


def test_streaming_pending_counts_match_worker_eligibility(tmp_path, monkeypatch) -> None:
    db_path = tmp_path / "divapply.db"
    conn = init_db(db_path)
    text_missing_pdf = tmp_path / "missing-pdf.txt"
    text_with_pdf = tmp_path / "existing-pdf.txt"
    text_missing_pdf.write_text("resume", encoding="utf-8")
    text_with_pdf.write_text("resume", encoding="utf-8")
    text_with_pdf.with_suffix(".pdf").write_text("pdf", encoding="utf-8")
    rows = [
        ("score-future", "indeed", LONG_DESCRIPTION, None, None, 1, "2099-01-01", "done", None),
        ("score-exhausted", "indeed", LONG_DESCRIPTION, None, None, 5, None, "done", None),
        ("cover-low", "indeed", LONG_DESCRIPTION, 6, "tailored.pdf", 0, None, "done", None),
        ("cover-short", "indeed", "Metadata", 8, "tailored.pdf", 0, None, "done", None),
        ("cover-ready", "indeed", LONG_DESCRIPTION, 8, "tailored.pdf", 0, None, "done", None),
        ("enrich-skip", "google", None, None, None, 0, None, None, None),
        ("enrich-ready", "indeed", None, None, None, 0, None, None, None),
        ("pdf-missing", "indeed", LONG_DESCRIPTION, 8, str(text_missing_pdf), 0, None, "done", "cover.pdf"),
        ("pdf-existing", "indeed", LONG_DESCRIPTION, 8, str(text_with_pdf), 0, None, "done", "cover.pdf"),
    ]
    conn.executemany(
        """
        INSERT INTO jobs (
            url, title, site, full_description, fit_score, tailored_resume_path,
            score_attempts, score_retry_at, detail_scraped_at, cover_letter_path,
            discovered_at, application_mode, source_verification
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, '2026-01-01', 'active', 'official')
        """,
        [
            (f"https://example.com/{name}", name, site, description, score, tailored,
             attempts, retry_at, detail_at, cover)
            for name, site, description, score, tailored, attempts, retry_at, detail_at, cover in rows
        ],
    )
    conn.commit()
    monkeypatch.setattr(pipeline, "get_connection", lambda: conn)

    assert pipeline._count_pending("score") == 0
    assert pipeline._count_pending("cover", min_score=7) == 1
    assert pipeline._count_pending("enrich") == 1
    assert pipeline._count_pending("pdf") == 1
    close_connection(db_path)
