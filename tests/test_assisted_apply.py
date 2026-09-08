from __future__ import annotations

import json
import sqlite3
import threading
from datetime import datetime, timedelta, timezone

import pytest

from divapply.apply import launcher
from divapply.apply.prompt import ApplicationAuthorization


class _FakeProcess:
    pid = 1234

    def poll(self):
        return None


class _FakeThread:
    def __init__(self) -> None:
        self.joined = False

    def join(self, timeout=None) -> None:
        self.joined = True


def _authorization() -> ApplicationAuthorization:
    return ApplicationAuthorization(
        profile_fields=True,
        final_submit=False,
        source="assisted_review",
    )


def test_ready_for_review_is_a_first_class_agent_result(monkeypatch) -> None:
    events: list[str] = []
    monkeypatch.setattr(launcher, "add_event", events.append)
    monkeypatch.setattr(launcher, "update_state", lambda *_args, **_kwargs: None)

    result, _duration = launcher._extract_result(
        "work complete\nRESULT:READY_FOR_REVIEW\n",
        worker_id=0,
        job={"title": "Support Technician", "url": "https://jobs.example/1"},
        duration_ms=1500,
    )

    assert result == "ready_for_review"
    assert any("READY_FOR_REVIEW" in event for event in events)


def test_assisted_acquisition_accepts_only_explicit_confirmed_target(monkeypatch) -> None:
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.execute(
        """
        CREATE TABLE jobs (
            url TEXT PRIMARY KEY,
            title TEXT,
            company TEXT,
            site TEXT,
            application_url TEXT,
            tailored_resume_path TEXT,
            fit_score INTEGER,
            location TEXT,
            full_description TEXT,
            cover_letter_path TEXT,
            application_mode TEXT,
            source_verification TEXT,
            availability_state TEXT,
            archived_at TEXT,
            apply_status TEXT,
            apply_attempts INTEGER,
            apply_error TEXT,
            agent_id TEXT,
            last_attempted_at TEXT
        )
        """
    )
    url = "https://manual.example/jobs/1"
    conn.execute(
        """
        INSERT INTO jobs (
            url, title, company, site, application_url, tailored_resume_path,
            fit_score, location, full_description, application_mode,
            source_verification, availability_state, apply_attempts
        ) VALUES (?, 'IT Assistant', 'Example', 'Example', ?, 'resume.pdf',
                  8, 'Example City, CA', 'Long description', 'manual_review',
                  'user_confirmed_direct', 'open', 0)
        """,
        (url, url),
    )
    conn.commit()
    monkeypatch.setattr(launcher, "get_connection", lambda: conn)
    monkeypatch.setattr(launcher, "recover_stale_apply_locks", lambda **_kwargs: 0)
    monkeypatch.setattr(launcher, "_load_blocked", lambda: (set(), []))
    monkeypatch.setattr(launcher.config, "is_manual_ats", lambda _url: True)
    monkeypatch.setattr(launcher, "ensure_job_artifacts_unshared", lambda *_args, **_kwargs: None)

    assert launcher.acquire_job(target_url=url, worker_id=0) is None
    job = launcher.acquire_job(target_url=url, worker_id=0, assisted=True, agent_id="assisted-test-owner")

    assert job is not None
    assert job["source_verification"] == "user_confirmed_direct"
    state = conn.execute("SELECT apply_status, agent_id FROM jobs WHERE url = ?", (url,)).fetchone()
    assert tuple(state) == ("in_progress", "assisted-test-owner")


def test_assisted_target_acquisition_enforces_score_and_attempt_bounds(monkeypatch) -> None:
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.execute(
        """
        CREATE TABLE jobs (
            url TEXT PRIMARY KEY, title TEXT, company TEXT, site TEXT,
            application_url TEXT, tailored_resume_path TEXT, fit_score INTEGER,
            location TEXT, full_description TEXT, cover_letter_path TEXT,
            application_mode TEXT, source_verification TEXT, availability_state TEXT,
            archived_at TEXT, apply_status TEXT, apply_attempts INTEGER,
            apply_error TEXT, agent_id TEXT, last_attempted_at TEXT
        )
        """
    )
    url = "https://manual.example/jobs/bounded"
    conn.execute(
        """
        INSERT INTO jobs (
            url, title, application_url, tailored_resume_path, fit_score,
            application_mode, source_verification, availability_state, apply_attempts
        ) VALUES (?, 'Bounded Role', ?, 'resume.pdf', 8,
                  'manual_review', 'user_confirmed_direct', 'open', 0)
        """,
        (url, url),
    )
    conn.commit()
    monkeypatch.setattr(launcher, "get_connection", lambda: conn)
    monkeypatch.setattr(launcher, "recover_stale_apply_locks", lambda **_kwargs: 0)
    monkeypatch.setattr(launcher, "_load_blocked", lambda: (set(), []))
    monkeypatch.setattr(launcher, "ensure_job_artifacts_unshared", lambda *_args, **_kwargs: None)

    assert launcher.acquire_job(target_url=url, min_score=9, assisted=True) is None
    assert launcher.acquire_job(target_url=url, min_score=0, max_score=7, assisted=True) is None

    conn.execute(
        "UPDATE jobs SET apply_attempts = ? WHERE url = ?",
        (launcher.config.DEFAULTS["max_apply_attempts"], url),
    )
    conn.commit()
    assert launcher.acquire_job(target_url=url, min_score=0, assisted=True) is None


def test_assisted_agent_commands_structurally_remove_browser_close(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(launcher.config, "get_apply_backend_executable", lambda backend: backend)
    mcp_path = tmp_path / "mcp.json"
    prompt_path = tmp_path / "prompt.txt"
    mcp_path.write_text(json.dumps(launcher._make_mcp_config(cdp_port=9222)), encoding="utf-8")

    codex = launcher._build_agent_command("codex", "gpt-test", mcp_path, prompt_path, assisted=True)
    claude = launcher._build_agent_command("claude", "gpt-test", mcp_path, prompt_path, assisted=True)

    codex_enabled = next(item for item in codex if "playwright.enabled_tools=" in item)
    codex_disabled = next(item for item in codex if "playwright.disabled_tools=" in item)
    assert "browser_close" not in codex_enabled
    assert "browser_close" in codex_disabled
    assert "mcp__playwright__browser_close" not in claude[claude.index("--allowedTools") + 1]
    assert "mcp__playwright__browser_close" in claude[claude.index("--disallowedTools") + 1]


def test_assisted_lease_refresh_prevents_stale_recovery(monkeypatch) -> None:
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.execute(
        """
        CREATE TABLE jobs (
            url TEXT PRIMARY KEY, apply_status TEXT, apply_error TEXT,
            apply_attempts INTEGER, agent_id TEXT, last_attempted_at TEXT
        )
        """
    )
    url = "https://jobs.example/handoff"
    stale = (datetime.now(timezone.utc) - timedelta(hours=2)).isoformat()
    conn.execute(
        "INSERT INTO jobs VALUES (?, 'in_progress', NULL, 0, 'assisted-owner', ?)",
        (url, stale),
    )
    conn.commit()
    monkeypatch.setattr(launcher, "get_connection", lambda: conn)

    assert launcher._refresh_assisted_lease(url, "wrong-owner") is False
    assert launcher._refresh_assisted_lease(url, "assisted-owner") is True
    assert launcher.recover_stale_apply_locks(conn=conn, timeout_seconds=3600) == 0
    row = conn.execute("SELECT apply_status, agent_id FROM jobs WHERE url = ?", (url,)).fetchone()
    assert tuple(row) == ("in_progress", "assisted-owner")


def test_lost_heartbeat_invalidates_assisted_session(monkeypatch) -> None:
    stop_event = threading.Event()
    lease_lost_event = threading.Event()
    monkeypatch.setattr(launcher, "_refresh_assisted_lease", lambda *_args: False)

    launcher._maintain_assisted_lease(
        "https://jobs.example/handoff",
        "assisted-owner",
        stop_event,
        lease_lost_event,
        interval_seconds=0,
    )

    assert lease_lost_event.is_set()


def test_lost_lease_blocks_resume_and_finish_without_browser_cleanup(monkeypatch) -> None:
    process = _FakeProcess()
    lease_lost_event = threading.Event()
    lease_lost_event.set()
    calls: list[str] = []
    monkeypatch.setattr(launcher, "run_job", lambda *_args, **_kwargs: calls.append("run"))
    monkeypatch.setattr(launcher, "mark_job", lambda *_args, **_kwargs: calls.append("mark"))
    monkeypatch.setattr(launcher, "cleanup_worker", lambda *_args: calls.append("cleanup"))
    session = launcher.AssistedApplySession(
        job={"url": "https://jobs.example/1"},
        browser_process=process,
        result="ready_for_review",
        duration_ms=1200,
        model="gpt-test",
        backend="codex",
        authorization=_authorization(),
        agent_id="assisted-owner",
        lease_lost_event=lease_lost_event,
    )

    with pytest.raises(launcher.AssistedApplyLeaseLostError, match="lost its database lease"):
        launcher.resume_assisted_apply(session)
    with pytest.raises(launcher.AssistedApplyLeaseLostError, match="lost its database lease"):
        launcher.finish_assisted_apply(session, "submitted")

    assert calls == []
    assert session.closed is False


def test_owner_qualified_transition_cannot_overwrite_reclaimed_job(monkeypatch) -> None:
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.execute(
        """
        CREATE TABLE jobs (
            url TEXT PRIMARY KEY, apply_status TEXT, applied_at TEXT,
            apply_error TEXT, apply_attempts INTEGER, agent_id TEXT
        )
        """
    )
    url = "https://jobs.example/reclaimed"
    conn.execute("INSERT INTO jobs VALUES (?, 'in_progress', NULL, NULL, 0, 'new-owner')", (url,))
    conn.commit()
    monkeypatch.setattr(launcher, "get_connection", lambda: conn)
    monkeypatch.setattr(launcher, "add_application_event", lambda *_args, **_kwargs: None)

    with pytest.raises(launcher.AssistedApplyLeaseLostError, match="no longer owns"):
        launcher.mark_job(url, "applied", agent_id="old-owner")

    row = conn.execute("SELECT apply_status, applied_at, agent_id FROM jobs WHERE url = ?", (url,)).fetchone()
    assert tuple(row) == ("in_progress", None, "new-owner")


def test_start_assisted_apply_keeps_owned_chrome_open(monkeypatch) -> None:
    job = {
        "url": "https://jobs.example/1",
        "title": "IT Assistant",
        "company": "Example",
        "fit_score": 8,
    }
    process = _FakeProcess()
    cleaned: list[object] = []
    monkeypatch.setattr(launcher, "init_worker", lambda _worker_id: None)
    monkeypatch.setattr(launcher, "recover_stale_apply_locks", lambda **_kwargs: 0)
    monkeypatch.setattr(launcher, "acquire_job", lambda **_kwargs: job)
    monkeypatch.setattr(launcher, "launch_chrome", lambda *_args, **_kwargs: process)
    lease_stop = threading.Event()
    lease_thread = _FakeThread()
    monkeypatch.setattr(
        launcher,
        "_start_assisted_lease_heartbeat",
        lambda *_args: (lease_stop, lease_thread),
    )
    monkeypatch.setattr(
        launcher,
        "run_job",
        lambda *_args, **_kwargs: ("ready_for_review", 1200),
    )
    monkeypatch.setattr(launcher, "cleanup_worker", lambda *args: cleaned.append(args))

    session = launcher.start_assisted_apply(
        job["url"],
        model="gpt-test",
        backend="codex",
        authorization=_authorization(),
    )

    assert session is not None
    assert session.browser_process is process
    assert session.result == "ready_for_review"
    assert session.closed is False
    assert session.agent_id is not None and session.agent_id.startswith("assisted-")
    assert cleaned == []


def test_resume_assisted_apply_continues_from_current_browser_page(monkeypatch) -> None:
    process = _FakeProcess()
    run_kwargs: dict[str, object] = {}

    def run_job(*_args, **kwargs):
        run_kwargs.update(kwargs)
        return "ready_for_review", 300

    monkeypatch.setattr(launcher, "run_job", run_job)
    monkeypatch.setattr(launcher, "_assert_assisted_session_owns_lease", lambda _session: "assisted-owner")
    session = launcher.AssistedApplySession(
        job={"url": "https://jobs.example/1"},
        browser_process=process,
        result="captcha",
        duration_ms=1200,
        model="gpt-test",
        backend="codex",
        authorization=_authorization(),
    )

    assert launcher.resume_assisted_apply(session) == "ready_for_review"
    assert run_kwargs["resume_current_page"] is True
    assert session.duration_ms == 1500


def test_finish_assisted_apply_records_user_submission_and_cleans_chrome(monkeypatch) -> None:
    process = _FakeProcess()
    marked: list[tuple[str, str]] = []
    cleaned: list[tuple[int, object]] = []
    monkeypatch.setattr(
        launcher,
        "mark_job",
        lambda url, status, *, agent_id=None: marked.append((url, status, agent_id)),
    )
    monkeypatch.setattr(launcher, "cleanup_worker", lambda worker, proc: cleaned.append((worker, proc)))
    session = launcher.AssistedApplySession(
        job={"url": "https://jobs.example/1"},
        browser_process=process,
        result="ready_for_review",
        duration_ms=1200,
        model="gpt-test",
        backend="codex",
        authorization=_authorization(),
        agent_id="assisted-owner",
    )

    outcome = launcher.finish_assisted_apply(session, "submitted")

    assert outcome == "user_confirmed_applied"
    assert marked == [("https://jobs.example/1", "applied", "assisted-owner")]
    assert cleaned == [(0, process)]
    assert session.closed is True


def test_finish_assisted_apply_keeps_session_open_when_db_transition_fails(monkeypatch) -> None:
    process = _FakeProcess()
    cleaned: list[object] = []
    monkeypatch.setattr(
        launcher,
        "mark_job",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(RuntimeError("db busy")),
    )
    monkeypatch.setattr(launcher, "cleanup_worker", lambda *args: cleaned.append(args))
    session = launcher.AssistedApplySession(
        job={"url": "https://jobs.example/1"},
        browser_process=process,
        result="ready_for_review",
        duration_ms=1200,
        model="gpt-test",
        backend="codex",
        authorization=_authorization(),
        agent_id="assisted-owner",
    )

    with pytest.raises(RuntimeError, match="db busy"):
        launcher.finish_assisted_apply(session, "submitted")

    assert session.closed is False
    assert cleaned == []


def test_abort_assisted_apply_releases_owned_lock_and_cleans_chrome(monkeypatch) -> None:
    process = _FakeProcess()
    released: list[tuple[str, str | None]] = []
    cleaned: list[object] = []
    monkeypatch.setattr(
        launcher,
        "release_lock",
        lambda url, *, agent_id=None: released.append((url, agent_id)),
    )
    monkeypatch.setattr(launcher, "cleanup_worker", lambda *args: cleaned.append(args))
    session = launcher.AssistedApplySession(
        job={"url": "https://jobs.example/1"},
        browser_process=process,
        result="ready_for_review",
        duration_ms=1200,
        model="gpt-test",
        backend="codex",
        authorization=_authorization(),
        agent_id="assisted-owner",
    )

    assert launcher.abort_assisted_apply(session) == "aborted"
    assert released == [("https://jobs.example/1", "assisted-owner")]
    assert cleaned == [(0, process)]
    assert session.closed is True


def test_start_assisted_apply_cleans_owned_state_on_keyboard_interrupt(monkeypatch) -> None:
    job = {"url": "https://jobs.example/1", "title": "IT Assistant", "fit_score": 8}
    process = _FakeProcess()
    lease_stop = threading.Event()
    lease_thread = _FakeThread()
    released: list[tuple[str, str | None]] = []
    cleaned: list[object] = []
    monkeypatch.setattr(launcher, "init_worker", lambda _worker_id: None)
    monkeypatch.setattr(launcher, "recover_stale_apply_locks", lambda **_kwargs: 0)
    monkeypatch.setattr(launcher, "acquire_job", lambda **_kwargs: job)
    monkeypatch.setattr(launcher, "launch_chrome", lambda *_args, **_kwargs: process)
    monkeypatch.setattr(launcher, "_start_assisted_lease_heartbeat", lambda *_args: (lease_stop, lease_thread))
    monkeypatch.setattr(launcher, "run_job", lambda *_args, **_kwargs: (_ for _ in ()).throw(KeyboardInterrupt()))
    monkeypatch.setattr(
        launcher,
        "release_lock",
        lambda url, *, agent_id=None: released.append((url, agent_id)),
    )
    monkeypatch.setattr(launcher, "cleanup_worker", lambda *args: cleaned.append(args))

    with pytest.raises(KeyboardInterrupt):
        launcher.start_assisted_apply(job["url"], authorization=_authorization())

    assert lease_stop.is_set()
    assert lease_thread.joined is True
    assert released and released[0][0] == job["url"] and released[0][1].startswith("assisted-")
    assert cleaned == [(0, process)]


def test_start_cleanup_preserves_interrupt_and_closes_chrome_when_lock_release_fails(monkeypatch) -> None:
    job = {"url": "https://jobs.example/1", "title": "IT Assistant", "fit_score": 8}
    process = _FakeProcess()
    lease_stop = threading.Event()
    lease_thread = _FakeThread()
    cleaned: list[object] = []
    monkeypatch.setattr(launcher, "init_worker", lambda _worker_id: None)
    monkeypatch.setattr(launcher, "recover_stale_apply_locks", lambda **_kwargs: 0)
    monkeypatch.setattr(launcher, "acquire_job", lambda **_kwargs: job)
    monkeypatch.setattr(launcher, "launch_chrome", lambda *_args, **_kwargs: process)
    monkeypatch.setattr(launcher, "_start_assisted_lease_heartbeat", lambda *_args: (lease_stop, lease_thread))
    monkeypatch.setattr(launcher, "run_job", lambda *_args, **_kwargs: (_ for _ in ()).throw(KeyboardInterrupt()))
    monkeypatch.setattr(
        launcher,
        "release_lock",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(sqlite3.OperationalError("database is locked")),
    )
    monkeypatch.setattr(launcher, "cleanup_worker", lambda *args: cleaned.append(args))

    with pytest.raises(KeyboardInterrupt):
        launcher.start_assisted_apply(job["url"], authorization=_authorization())

    assert lease_stop.is_set()
    assert lease_thread.joined is True
    assert cleaned == [(0, process)]
