from __future__ import annotations

import threading

from divapply import pipeline


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
