from __future__ import annotations

from types import SimpleNamespace

import typer

from divapply import cli
from divapply.apply import launcher


def _session() -> SimpleNamespace:
    return SimpleNamespace(result="ready_for_review", closed=False)


def _patch_start(monkeypatch, session: SimpleNamespace) -> None:
    monkeypatch.setattr(launcher, "start_assisted_apply", lambda *_args, **_kwargs: session)


def test_assisted_cli_can_save_after_resume_error(monkeypatch) -> None:
    session = _session()
    choices = iter(["r", "l"])
    decisions: list[tuple[str, str | None]] = []
    _patch_start(monkeypatch, session)
    monkeypatch.setattr(launcher, "resume_assisted_apply", lambda _session: (_ for _ in ()).throw(RuntimeError("closed")))

    def finish(_session, decision: str, *, reason: str | None = None) -> str:
        decisions.append((decision, reason))
        session.closed = True
        return "saved_for_later"

    monkeypatch.setattr(launcher, "finish_assisted_apply", finish)
    monkeypatch.setattr(launcher, "abort_assisted_apply", lambda _session: "aborted")
    monkeypatch.setattr(typer, "prompt", lambda *_args, **_kwargs: next(choices))

    outcome = cli._run_assisted_cli(
        "https://jobs.example/1",
        min_score=5,
        max_score=None,
        model="gpt-test",
        backend="codex",
    )

    assert outcome == "saved_for_later"
    assert decisions == [("later", None)]


def test_assisted_cli_keeps_handoff_open_when_finish_persistence_fails(monkeypatch) -> None:
    session = _session()
    choices = iter(["a", "l"])
    decisions: list[str] = []
    _patch_start(monkeypatch, session)
    monkeypatch.setattr(launcher, "resume_assisted_apply", lambda _session: "ready_for_review")

    def finish(_session, decision: str, *, reason: str | None = None) -> str:
        del reason
        decisions.append(decision)
        if decision == "submitted":
            assert session.closed is False
            raise RuntimeError("database busy")
        session.closed = True
        return "saved_for_later"

    monkeypatch.setattr(launcher, "finish_assisted_apply", finish)
    monkeypatch.setattr(launcher, "abort_assisted_apply", lambda _session: "aborted")
    monkeypatch.setattr(typer, "prompt", lambda *_args, **_kwargs: next(choices))

    outcome = cli._run_assisted_cli(
        "https://jobs.example/1",
        min_score=5,
        max_score=None,
        model="gpt-test",
        backend="codex",
    )

    assert outcome == "saved_for_later"
    assert decisions == ["submitted", "later"]


def test_assisted_cli_aborts_if_interrupted_state_cannot_be_saved(monkeypatch) -> None:
    session = _session()
    aborted: list[SimpleNamespace] = []
    _patch_start(monkeypatch, session)
    monkeypatch.setattr(launcher, "resume_assisted_apply", lambda _session: "ready_for_review")
    monkeypatch.setattr(
        launcher,
        "finish_assisted_apply",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(RuntimeError("database busy")),
    )

    def abort(target: SimpleNamespace) -> str:
        aborted.append(target)
        target.closed = True
        return "aborted"

    monkeypatch.setattr(launcher, "abort_assisted_apply", abort)
    monkeypatch.setattr(typer, "prompt", lambda *_args, **_kwargs: (_ for _ in ()).throw(KeyboardInterrupt()))

    outcome = cli._run_assisted_cli(
        "https://jobs.example/1",
        min_score=5,
        max_score=None,
        model="gpt-test",
        backend="codex",
    )

    assert outcome == "aborted"
    assert aborted == [session]


def test_assisted_cli_handles_startup_keyboard_interrupt(monkeypatch) -> None:
    monkeypatch.setattr(
        launcher,
        "start_assisted_apply",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(KeyboardInterrupt()),
    )

    outcome = cli._run_assisted_cli(
        "https://jobs.example/1",
        min_score=5,
        max_score=None,
        model="gpt-test",
        backend="codex",
    )

    assert outcome == "interrupted"


def test_assisted_cli_reports_cleanup_failure_truthfully(monkeypatch) -> None:
    session = _session()
    _patch_start(monkeypatch, session)
    monkeypatch.setattr(launcher, "resume_assisted_apply", lambda _session: "ready_for_review")
    monkeypatch.setattr(
        launcher,
        "finish_assisted_apply",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(RuntimeError("database busy")),
    )
    monkeypatch.setattr(
        launcher,
        "abort_assisted_apply",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(RuntimeError("cleanup failed")),
    )
    monkeypatch.setattr(typer, "prompt", lambda *_args, **_kwargs: (_ for _ in ()).throw(KeyboardInterrupt()))

    outcome = cli._run_assisted_cli(
        "https://jobs.example/1",
        min_score=5,
        max_score=None,
        model="gpt-test",
        backend="codex",
    )

    assert outcome == "cleanup_failed"
    assert session.closed is False
