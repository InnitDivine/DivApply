from __future__ import annotations

from datetime import datetime, timedelta, timezone
import sqlite3
import json

from divapply.apply import launcher


def test_extract_result_prefers_contract_status(monkeypatch) -> None:
    events: list[str] = []
    updates: list[dict] = []
    monkeypatch.setattr(launcher, "add_event", events.append)
    monkeypatch.setattr(launcher, "update_state", lambda worker_id, **kwargs: updates.append(kwargs))

    status, duration = launcher._extract_result(
        "narrative\nCONFIRMATION: page says application submitted successfully\nRESULT:APPLIED\n",
        worker_id=2,
        job={"title": "Analyst"},
        duration_ms=2400,
    )

    assert status == "applied"
    assert duration == 2400
    assert updates[-1]["status"] == "applied"


def test_extract_result_accepts_result_line_with_space_after_colon(monkeypatch) -> None:
    monkeypatch.setattr(launcher, "add_event", lambda message: None)
    monkeypatch.setattr(launcher, "update_state", lambda worker_id, **kwargs: None)

    status, _ = launcher._extract_result(
        "Confirmation number ABC-123.\nRESULT: APPLIED\n",
        worker_id=0,
        job={"title": "Support Role"},
        duration_ms=1000,
    )

    assert status == "applied"


def test_extract_result_rejects_applied_without_confirmation(monkeypatch) -> None:
    monkeypatch.setattr(launcher, "add_event", lambda message: None)
    monkeypatch.setattr(launcher, "update_state", lambda worker_id, **kwargs: None)

    status, _ = launcher._extract_result(
        "I clicked submit.\nRESULT:APPLIED\n",
        worker_id=0,
        job={"title": "Support Role"},
        duration_ms=1000,
    )

    assert status == "failed:missing_submission_confirmation"


def test_extract_result_rejects_negated_confirmation(monkeypatch) -> None:
    monkeypatch.setattr(launcher, "add_event", lambda message: None)
    monkeypatch.setattr(launcher, "update_state", lambda worker_id, **kwargs: None)

    status, _ = launcher._extract_result(
        "I could not confirm submission.\nRESULT:APPLIED\n",
        worker_id=0,
        job={"title": "Support Role"},
        duration_ms=1000,
    )

    assert status == "failed:missing_submission_confirmation"


def test_extract_result_promotes_known_failure_reason(monkeypatch) -> None:
    monkeypatch.setattr(launcher, "add_event", lambda message: None)
    monkeypatch.setattr(launcher, "update_state", lambda worker_id, **kwargs: None)

    status, _ = launcher._extract_result(
        "RESULT:FAILED:captcha",
        worker_id=0,
        job={"title": "Support Role"},
        duration_ms=1000,
    )

    assert status == "captcha"


def test_extract_result_promotes_verbose_blocker_reasons(monkeypatch) -> None:
    monkeypatch.setattr(launcher, "add_event", lambda message: None)
    monkeypatch.setattr(launcher, "update_state", lambda worker_id, **kwargs: None)

    cases = {
        "RESULT:FAILED:captcha required after submit": "captcha",
        "RESULT:FAILED:expired posting no longer accepting applications": "expired",
        "RESULT:FAILED:login issue after two redirects": "login_issue",
    }
    for output, expected in cases.items():
        status, _ = launcher._extract_result(
            output,
            worker_id=0,
            job={"title": "Support Role"},
            duration_ms=1000,
        )
        assert status == expected


def test_extract_result_uses_final_agent_result_not_prompt_contract(monkeypatch) -> None:
    monkeypatch.setattr(launcher, "add_event", lambda message: None)
    monkeypatch.setattr(launcher, "update_state", lambda worker_id, **kwargs: None)

    status, _ = launcher._extract_result(
        "\n".join([
            "user",
            "RESULT:APPLIED -- prompt contract example",
            "RESULT:LOGIN_ISSUE -- prompt contract example",
            "codex",
            "I could not continue because the form requires sensitive data.",
            "RESULT:FAILED:reason requires SSN last 4 digits, which I cannot enter",
        ]),
        worker_id=0,
        job={"title": "Support Role"},
        duration_ms=1000,
    )

    assert status == "failed:reason requires SSN last 4 digits, which I cannot enter"


def test_extract_result_ignores_prompt_result_codes_without_agent_result(monkeypatch) -> None:
    monkeypatch.setattr(launcher, "add_event", lambda message: None)
    monkeypatch.setattr(launcher, "update_state", lambda worker_id, **kwargs: None)

    status, _ = launcher._extract_result(
        "\n".join([
            "user",
            "RESULT:APPLIED -- prompt contract example",
            "RESULT:LOGIN_ISSUE -- prompt contract example",
            "codex",
            "I am still working through the form.",
        ]),
        worker_id=0,
        job={"title": "Support Role"},
        duration_ms=1000,
    )

    assert status == "failed:no_result_line"


def test_extract_result_reports_unsupported_agent_model_before_prompt_examples(monkeypatch) -> None:
    monkeypatch.setattr(launcher, "add_event", lambda message: None)
    monkeypatch.setattr(launcher, "update_state", lambda worker_id, **kwargs: None)

    status, _ = launcher._extract_result(
        "\n".join([
            "user",
            "RESULT:FAILED:reason -- any other failure (brief reason)",
            'ERROR: {"type":"error","status":400,"error":{"type":"invalid_request_error",'
            '"message":"The model is not supported when using Codex with a ChatGPT account."}}',
        ]),
        worker_id=0,
        job={"title": "Support Role"},
        duration_ms=1000,
    )

    assert status == "failed:agent_model_unsupported"


def test_extract_result_requires_explicit_applied_result(monkeypatch) -> None:
    monkeypatch.setattr(launcher, "add_event", lambda message: None)
    monkeypatch.setattr(launcher, "update_state", lambda worker_id, **kwargs: None)

    status, _ = launcher._extract_result(
        "The page says your application was submitted and shows a reference number.",
        worker_id=0,
        job={"title": "Support Role"},
        duration_ms=1000,
    )

    assert status == "failed:no_result_line"


def test_extract_result_normalizes_failure_reason_for_retry_logic(monkeypatch) -> None:
    monkeypatch.setattr(launcher, "add_event", lambda message: None)
    monkeypatch.setattr(launcher, "update_state", lambda worker_id, **kwargs: None)

    status, _ = launcher._extract_result(
        "RESULT:FAILED: CAPTCHA.",
        worker_id=0,
        job={"title": "Support Role"},
        duration_ms=1000,
    )

    assert status == "captcha"


def test_ssn_failure_is_permanent() -> None:
    assert launcher._is_permanent_failure("failed:reason requires SSN last 4 digits")
    assert launcher._is_permanent_failure("failed:requires social security number")
    assert launcher._is_permanent_failure("failed:requires SIN before interview")


def test_prompt_permanent_failures_are_not_retried() -> None:
    for result in [
        "expired",
        "captcha",
        "login_issue",
        "failed:not_eligible_location",
        "failed:not_eligible_work_auth",
        "failed:unsafe_permissions",
        "failed:unsafe_verification",
        "failed:sso_required",
        "failed:not_a_job_application",
        "failed:scam",
        "failed:blocked_by_cloudflare",
        "failed:bank account required",
        "failed:payment required",
        "failed:biometric verification",
    ]:
        assert launcher._is_permanent_failure(result), result


def test_transient_failures_remain_retryable() -> None:
    for result in ["failed:timeout", "failed:stuck", "failed:page_error", "failed:no_result_line"]:
        assert not launcher._is_permanent_failure(result), result


def test_apply_idle_timeout_defaults_are_bounded(monkeypatch) -> None:
    monkeypatch.delenv("DIVAPPLY_APPLY_IDLE_TIMEOUT", raising=False)
    monkeypatch.delenv("APPLYPILOT_APPLY_IDLE_TIMEOUT", raising=False)

    assert launcher._get_apply_idle_timeout(2700) == 300
    assert launcher._get_apply_idle_timeout(90) == 30
    assert launcher._get_apply_idle_timeout(None) == 300


def test_apply_idle_timeout_env_override(monkeypatch) -> None:
    monkeypatch.setenv("DIVAPPLY_APPLY_IDLE_TIMEOUT", "45")
    assert launcher._get_apply_idle_timeout(2700) == 45

    monkeypatch.setenv("DIVAPPLY_APPLY_IDLE_TIMEOUT", "off")
    assert launcher._get_apply_idle_timeout(2700) is None


def test_build_codex_command_maps_mcp_config(tmp_path, monkeypatch) -> None:
    monkeypatch.delenv("DIVAPPLY_CODEX_CMD", raising=False)
    monkeypatch.setattr(launcher.config, "get_apply_backend_executable", lambda backend: "C:/Codex/codex.exe")
    mcp_path = tmp_path / "mcp.json"
    prompt_path = tmp_path / "prompt.txt"
    mcp_path.write_text(
        json.dumps({
            "mcpServers": {
                "playwright": {
                    "command": "npx",
                    "args": ["@playwright/mcp@0.0.70", "--browser=firefox"],
                }
            }
        }),
        encoding="utf-8",
    )
    prompt_path.write_text("prompt", encoding="utf-8")

    cmd = launcher._build_agent_command("codex", "gpt-5.4-mini", mcp_path, prompt_path)

    assert cmd[:4] == ["C:/Codex/codex.exe", "exec", "--model", "gpt-5.4-mini"]
    assert "--dangerously-bypass-approvals-and-sandbox" in cmd
    assert "--ignore-user-config" in cmd
    assert "--ephemeral" in cmd
    assert "mcp_servers.playwright.required=true" in cmd


def test_mcp_config_defaults_to_chromium() -> None:
    config = launcher._make_mcp_config(cdp_port=9222)

    assert config["mcpServers"]["playwright"]["args"] == [
        "@playwright/mcp@0.0.70",
        "--browser=chromium",
        "--viewport-size=1280x900",
    ]


def test_acquire_job_returns_company_separate_from_site(monkeypatch) -> None:
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.execute("""
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
            apply_status TEXT,
            apply_error TEXT,
            apply_attempts INTEGER,
            agent_id TEXT,
            last_attempted_at TEXT
        )
    """)
    conn.execute("""
        INSERT INTO jobs (
            url, title, company, site, application_url, tailored_resume_path,
            fit_score, location, full_description, apply_attempts
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, (
        "https://jobs.example/1",
        "Support Analyst",
        "Real Employer",
        "Indeed",
        "https://apply.example/1",
        "resume.txt",
        9,
        "Remote",
        "Required: Python support.",
        0,
    ))
    conn.commit()

    monkeypatch.setattr(launcher, "get_connection", lambda: conn)
    monkeypatch.setattr(launcher, "_load_blocked", lambda: ([], []))
    monkeypatch.setattr(launcher.config, "is_manual_ats", lambda url: False, raising=False)

    job = launcher.acquire_job(min_score=7, worker_id=3)

    assert job is not None
    assert job["company"] == "Real Employer"
    assert job["site"] == "Indeed"


def test_acquire_job_skips_manual_ats_and_claims_next_job(monkeypatch) -> None:
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.execute("""
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
            apply_status TEXT,
            apply_error TEXT,
            apply_attempts INTEGER,
            agent_id TEXT,
            last_attempted_at TEXT
        )
    """)
    conn.executemany("""
        INSERT INTO jobs (
            url, title, company, site, application_url, tailored_resume_path,
            fit_score, location, full_description, apply_attempts
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, [
        (
            "https://jobs.example/manual",
            "Manual ATS",
            "Manual Co",
            "Indeed",
            "https://manual.example/apply",
            "resume.txt",
            10,
            "Remote",
            "Requires manual ATS.",
            0,
        ),
        (
            "https://jobs.example/ready",
            "Ready Role",
            "Ready Co",
            "Indeed",
            "https://apply.example/ready",
            "resume.txt",
            9,
            "Remote",
            "Ready to apply.",
            0,
        ),
    ])
    conn.commit()

    monkeypatch.setattr(launcher, "get_connection", lambda: conn)
    monkeypatch.setattr(launcher, "_load_blocked", lambda: ([], []))
    monkeypatch.setattr(launcher.config, "is_manual_ats", lambda url: "manual.example" in url, raising=False)

    job = launcher.acquire_job(min_score=7, worker_id=4)

    assert job is not None
    assert job["url"] == "https://jobs.example/ready"
    manual = conn.execute("SELECT apply_status FROM jobs WHERE url = ?", ("https://jobs.example/manual",)).fetchone()
    ready = conn.execute("SELECT apply_status, agent_id FROM jobs WHERE url = ?", ("https://jobs.example/ready",)).fetchone()
    assert manual["apply_status"] == "manual"
    assert ready["apply_status"] == "in_progress"
    assert ready["agent_id"] == "worker-4"


def test_acquire_job_honors_max_score(monkeypatch) -> None:
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.execute("""
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
            apply_status TEXT,
            apply_error TEXT,
            apply_attempts INTEGER,
            agent_id TEXT,
            last_attempted_at TEXT
        )
    """)
    conn.executemany("""
        INSERT INTO jobs (
            url, title, company, site, application_url, tailored_resume_path,
            fit_score, location, full_description, apply_attempts
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, [
        (
            "https://jobs.example/score-8",
            "Higher Score",
            "Higher Co",
            "Indeed",
            "https://apply.example/score-8",
            "resume.txt",
            8,
            "Remote",
            "Higher scoring role.",
            0,
        ),
        (
            "https://jobs.example/score-7",
            "Tier Seven",
            "Seven Co",
            "Indeed",
            "https://apply.example/score-7",
            "resume.txt",
            7,
            "Remote",
            "Tier seven role.",
            0,
        ),
    ])
    conn.commit()

    monkeypatch.setattr(launcher, "get_connection", lambda: conn)
    monkeypatch.setattr(launcher, "_load_blocked", lambda: ([], []))
    monkeypatch.setattr(launcher.config, "is_manual_ats", lambda url: False, raising=False)

    job = launcher.acquire_job(min_score=7, max_score=7, worker_id=6)

    assert job is not None
    assert job["url"] == "https://jobs.example/score-7"
    skipped = conn.execute(
        "SELECT apply_status FROM jobs WHERE url = ?",
        ("https://jobs.example/score-8",),
    ).fetchone()
    claimed = conn.execute(
        "SELECT apply_status, agent_id FROM jobs WHERE url = ?",
        ("https://jobs.example/score-7",),
    ).fetchone()
    assert skipped["apply_status"] is None
    assert claimed["apply_status"] == "in_progress"
    assert claimed["agent_id"] == "worker-6"


def test_acquire_job_skips_unsafe_apply_url_and_claims_next_job(monkeypatch) -> None:
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.execute("""
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
            apply_status TEXT,
            apply_error TEXT,
            apply_attempts INTEGER,
            agent_id TEXT,
            last_attempted_at TEXT
        )
    """)
    conn.executemany("""
        INSERT INTO jobs (
            url, title, company, site, application_url, tailored_resume_path,
            fit_score, location, full_description, apply_attempts
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, [
        (
            "https://jobs.example/unsafe",
            "Unsafe URL",
            "Unsafe Co",
            "Indeed",
            "http://localhost:8080/apply",
            "resume.txt",
            10,
            "Remote",
            "Unsafe local URL.",
            0,
        ),
        (
            "https://jobs.example/ready-after-unsafe",
            "Ready Role",
            "Ready Co",
            "Indeed",
            "https://apply.example/ready",
            "resume.txt",
            9,
            "Remote",
            "Ready to apply.",
            0,
        ),
    ])
    conn.commit()

    monkeypatch.setattr(launcher, "get_connection", lambda: conn)
    monkeypatch.setattr(launcher, "_load_blocked", lambda: ([], []))
    monkeypatch.setattr(launcher.config, "is_manual_ats", lambda url: False, raising=False)

    job = launcher.acquire_job(min_score=7, worker_id=5)

    assert job is not None
    assert job["url"] == "https://jobs.example/ready-after-unsafe"
    unsafe = conn.execute(
        "SELECT apply_status, apply_error, apply_attempts FROM jobs WHERE url = ?",
        ("https://jobs.example/unsafe",),
    ).fetchone()
    ready = conn.execute(
        "SELECT apply_status, agent_id FROM jobs WHERE url = ?",
        ("https://jobs.example/ready-after-unsafe",),
    ).fetchone()
    assert unsafe["apply_status"] == "failed"
    assert unsafe["apply_attempts"] == 99
    assert "unsafe apply URL" in unsafe["apply_error"]
    assert ready["apply_status"] == "in_progress"
    assert ready["agent_id"] == "worker-5"


def test_recover_stale_apply_locks_marks_abandoned_jobs_failed() -> None:
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.execute("""
        CREATE TABLE jobs (
            url TEXT PRIMARY KEY,
            apply_status TEXT,
            apply_error TEXT,
            apply_attempts INTEGER,
            agent_id TEXT,
            last_attempted_at TEXT
        )
    """)
    stale = (datetime.now(timezone.utc) - timedelta(hours=2)).isoformat()
    fresh = datetime.now(timezone.utc).isoformat()
    conn.executemany(
        "INSERT INTO jobs (url, apply_status, apply_attempts, agent_id, last_attempted_at) VALUES (?, ?, ?, ?, ?)",
        [
            ("https://jobs.example/stale", "in_progress", 1, "worker-1", stale),
            ("https://jobs.example/fresh", "in_progress", 0, "worker-2", fresh),
        ],
    )
    conn.commit()

    recovered = launcher.recover_stale_apply_locks(conn=conn, timeout_seconds=3600)

    stale_row = conn.execute("SELECT apply_status, apply_error, apply_attempts, agent_id FROM jobs WHERE url = ?", ("https://jobs.example/stale",)).fetchone()
    fresh_row = conn.execute("SELECT apply_status, apply_attempts, agent_id FROM jobs WHERE url = ?", ("https://jobs.example/fresh",)).fetchone()
    assert recovered == 1
    assert stale_row["apply_status"] == "failed"
    assert stale_row["apply_error"] == "stale in_progress lock recovered"
    assert stale_row["apply_attempts"] == 2
    assert stale_row["agent_id"] is None
    assert fresh_row["apply_status"] == "in_progress"
    assert fresh_row["apply_attempts"] == 0
    assert fresh_row["agent_id"] == "worker-2"


def test_recover_stale_apply_locks_recovers_missing_timestamp() -> None:
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.execute("""
        CREATE TABLE jobs (
            url TEXT PRIMARY KEY,
            apply_status TEXT,
            apply_error TEXT,
            apply_attempts INTEGER,
            agent_id TEXT,
            last_attempted_at TEXT
        )
    """)
    conn.execute(
        "INSERT INTO jobs (url, apply_status, apply_attempts, agent_id, last_attempted_at) VALUES (?, ?, ?, ?, ?)",
        ("https://jobs.example/missing-ts", "in_progress", 0, "worker-9", None),
    )
    conn.commit()

    recovered = launcher.recover_stale_apply_locks(conn=conn, timeout_seconds=3600)

    row = conn.execute(
        "SELECT apply_status, apply_error, apply_attempts, agent_id FROM jobs WHERE url = ?",
        ("https://jobs.example/missing-ts",),
    ).fetchone()
    assert recovered == 1
    assert row["apply_status"] == "failed"
    assert row["apply_error"] == "stale in_progress lock recovered"
    assert row["apply_attempts"] == 1
    assert row["agent_id"] is None


def test_mark_result_rolls_back_when_event_insert_fails(monkeypatch) -> None:
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.execute("""
        CREATE TABLE jobs (
            url TEXT PRIMARY KEY,
            apply_status TEXT,
            applied_at TEXT,
            apply_error TEXT,
            apply_attempts INTEGER,
            agent_id TEXT,
            apply_duration_ms INTEGER,
            apply_task_id TEXT
        )
    """)
    conn.execute(
        "INSERT INTO jobs (url, apply_status, apply_attempts, agent_id) VALUES (?, ?, ?, ?)",
        ("https://jobs.example/rollback", "in_progress", 0, "worker-1"),
    )
    conn.commit()

    monkeypatch.setattr(launcher, "get_connection", lambda: conn)

    def fail_event(*args, **kwargs):
        raise RuntimeError("event store unavailable")

    monkeypatch.setattr(launcher, "add_application_event", fail_event)

    try:
        launcher.mark_result("https://jobs.example/rollback", "applied", duration_ms=100)
    except RuntimeError:
        pass
    else:
        raise AssertionError("mark_result should raise when lifecycle event insert fails")

    row = conn.execute("SELECT apply_status, applied_at, apply_attempts, agent_id FROM jobs WHERE url = ?", ("https://jobs.example/rollback",)).fetchone()
    assert row["apply_status"] == "in_progress"
    assert row["applied_at"] is None
    assert row["apply_attempts"] == 0
    assert row["agent_id"] == "worker-1"


def test_mark_result_repairs_existing_event_schema(monkeypatch) -> None:
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.execute("""
        CREATE TABLE jobs (
            url TEXT PRIMARY KEY,
            apply_status TEXT,
            applied_at TEXT,
            apply_error TEXT,
            apply_attempts INTEGER,
            agent_id TEXT,
            apply_duration_ms INTEGER,
            apply_task_id TEXT
        )
    """)
    conn.execute("""
        CREATE TABLE application_events (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            job_url TEXT NOT NULL,
            event_type TEXT NOT NULL,
            ts TEXT NOT NULL
        )
    """)
    conn.execute(
        "INSERT INTO jobs (url, apply_status, apply_attempts, agent_id) VALUES (?, ?, ?, ?)",
        ("https://jobs.example/schema-rollback", "in_progress", 0, "worker-1"),
    )
    conn.commit()

    monkeypatch.setattr(launcher, "get_connection", lambda: conn)

    launcher.mark_result("https://jobs.example/schema-rollback", "applied", duration_ms=100)

    row = conn.execute(
        "SELECT apply_status, applied_at, apply_attempts, agent_id FROM jobs WHERE url = ?",
        ("https://jobs.example/schema-rollback",),
    ).fetchone()
    event = conn.execute(
        "SELECT event_type, notes, follow_up_at, created_at FROM application_events WHERE job_url = ?",
        ("https://jobs.example/schema-rollback",),
    ).fetchone()
    assert row["apply_status"] == "applied"
    assert row["applied_at"] is not None
    assert row["apply_attempts"] == 0
    assert row["agent_id"] is None
    assert event["event_type"] == "applied"
    assert event["notes"] == "Auto-apply submitted"
    assert event["follow_up_at"] is None
    assert event["created_at"] is not None


def test_mark_result_failed_clears_prior_applied_at(monkeypatch) -> None:
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.execute("""
        CREATE TABLE jobs (
            url TEXT PRIMARY KEY,
            apply_status TEXT,
            applied_at TEXT,
            apply_error TEXT,
            apply_attempts INTEGER,
            agent_id TEXT,
            apply_duration_ms INTEGER,
            apply_task_id TEXT
        )
    """)
    conn.execute(
        """
        CREATE TABLE application_events (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            job_url TEXT NOT NULL,
            event_type TEXT NOT NULL,
            notes TEXT,
            ts TEXT NOT NULL,
            source TEXT,
            metadata_json TEXT
        )
        """
    )
    conn.execute(
        "INSERT INTO jobs (url, apply_status, applied_at, apply_attempts) VALUES (?, ?, ?, ?)",
        ("https://jobs.example/corrected", "applied", "2026-06-20T00:00:00+00:00", 0),
    )
    conn.commit()

    monkeypatch.setattr(launcher, "get_connection", lambda: conn)

    launcher.mark_result(
        "https://jobs.example/corrected",
        "failed",
        "expired",
        permanent=True,
        duration_ms=100,
    )

    row = conn.execute(
        "SELECT apply_status, applied_at, apply_error, apply_attempts FROM jobs WHERE url = ?",
        ("https://jobs.example/corrected",),
    ).fetchone()
    assert row["apply_status"] == "failed"
    assert row["applied_at"] is None
    assert row["apply_error"] == "expired"
    assert row["apply_attempts"] == 99


def test_mark_dry_run_does_not_mark_job_applied(monkeypatch) -> None:
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.execute("""
        CREATE TABLE jobs (
            url TEXT PRIMARY KEY,
            apply_status TEXT,
            applied_at TEXT,
            apply_error TEXT,
            apply_attempts INTEGER,
            agent_id TEXT,
            apply_duration_ms INTEGER,
            apply_task_id TEXT
        )
    """)
    conn.execute(
        "INSERT INTO jobs (url, apply_status, apply_attempts, agent_id) VALUES (?, ?, ?, ?)",
        ("https://jobs.example/dry-run", "in_progress", 0, "worker-1"),
    )
    conn.commit()

    monkeypatch.setattr(launcher, "get_connection", lambda: conn)

    launcher.mark_dry_run("https://jobs.example/dry-run", duration_ms=2500, result="failed:timeout")

    row = conn.execute(
        "SELECT apply_status, applied_at, apply_error, apply_attempts, agent_id, apply_duration_ms FROM jobs WHERE url = ?",
        ("https://jobs.example/dry-run",),
    ).fetchone()
    event = conn.execute(
        "SELECT event_type, notes FROM application_events WHERE job_url = ?",
        ("https://jobs.example/dry-run",),
    ).fetchone()

    assert row["apply_status"] is None
    assert row["applied_at"] is None
    assert row["apply_error"] == "Dry run result: failed:timeout"
    assert row["apply_attempts"] == 0
    assert row["agent_id"] is None
    assert row["apply_duration_ms"] == 2500
    assert event["event_type"] == "dry_run"
    assert event["notes"] == "Dry run result: failed:timeout"


def test_worker_loop_dry_run_failure_does_not_mark_failed(monkeypatch) -> None:
    calls: list[tuple] = []
    jobs = [{
        "url": "https://jobs.example/dry-run-failure",
        "title": "Support Analyst",
        "company": "Example",
        "site": "Example ATS",
        "application_url": "https://jobs.example/dry-run-failure/apply",
        "fit_score": 9,
    }]

    def fake_acquire_job(*args, **kwargs):
        return jobs.pop(0) if jobs else None

    monkeypatch.setattr(launcher, "acquire_job", fake_acquire_job)
    monkeypatch.setattr(launcher, "run_job", lambda *args, **kwargs: ("failed:timeout", 1200))
    monkeypatch.setattr(launcher, "mark_dry_run", lambda *args, **kwargs: calls.append(("dry_run", args, kwargs)))
    monkeypatch.setattr(launcher, "mark_result", lambda *args, **kwargs: calls.append(("mark_result", args, kwargs)))
    monkeypatch.setattr(launcher, "add_event", lambda message: None)
    monkeypatch.setattr(launcher, "update_state", lambda worker_id, **kwargs: None)

    applied, failed = launcher.worker_loop(limit=1, dry_run=True)

    assert (applied, failed) == (0, 0)
    assert [call[0] for call in calls] == ["dry_run"]
    assert calls[0][2]["result"] == "failed:timeout"


def test_worker_loop_marks_blockers_permanent(monkeypatch) -> None:
    calls: list[dict] = []
    jobs = [{
        "url": "https://jobs.example/blocker",
        "title": "Support Analyst",
        "company": "Example",
        "site": "Example ATS",
        "application_url": "https://jobs.example/blocker/apply",
        "fit_score": 9,
    }]

    def fake_acquire_job(*args, **kwargs):
        return jobs.pop(0) if jobs else None

    def fake_mark_result(*args, **kwargs):
        calls.append({"args": args, "kwargs": kwargs})

    monkeypatch.setattr(launcher, "acquire_job", fake_acquire_job)
    monkeypatch.setattr(launcher, "run_job", lambda *args, **kwargs: ("captcha", 1200))
    monkeypatch.setattr(launcher, "mark_result", fake_mark_result)
    monkeypatch.setattr(launcher, "add_event", lambda message: None)
    monkeypatch.setattr(launcher, "update_state", lambda worker_id, **kwargs: None)

    applied, failed = launcher.worker_loop(limit=1)

    assert (applied, failed) == (0, 1)
    assert calls == [{
        "args": ("https://jobs.example/blocker", "failed", "captcha"),
        "kwargs": {"permanent": True, "duration_ms": 1200},
    }]


def test_reset_failed_only_resets_failed_jobs(monkeypatch) -> None:
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.execute("""
        CREATE TABLE jobs (
            url TEXT PRIMARY KEY,
            apply_status TEXT,
            apply_error TEXT,
            apply_attempts INTEGER,
            agent_id TEXT
        )
    """)
    conn.executemany(
        "INSERT INTO jobs (url, apply_status, apply_error, apply_attempts, agent_id) VALUES (?, ?, ?, ?, ?)",
        [
            ("https://jobs.example/failed", "failed", "timeout", 2, "worker-1"),
            ("https://jobs.example/manual", "manual", "manual ATS", 0, None),
            ("https://jobs.example/interview", "interview", None, 0, None),
            ("https://jobs.example/rejected", "rejected", None, 0, None),
            ("https://jobs.example/withdrawn", "withdrawn", None, 0, None),
            ("https://jobs.example/offer", "offer", None, 0, None),
        ],
    )
    conn.commit()

    monkeypatch.setattr(launcher, "get_connection", lambda: conn)

    count = launcher.reset_failed()

    rows = {
        row["url"]: dict(row)
        for row in conn.execute("SELECT url, apply_status, apply_error, apply_attempts, agent_id FROM jobs")
    }
    assert count == 1
    assert rows["https://jobs.example/failed"]["apply_status"] is None
    assert rows["https://jobs.example/failed"]["apply_error"] is None
    assert rows["https://jobs.example/failed"]["apply_attempts"] == 0
    assert rows["https://jobs.example/failed"]["agent_id"] is None
    assert rows["https://jobs.example/manual"]["apply_status"] == "manual"
    assert rows["https://jobs.example/interview"]["apply_status"] == "interview"
    assert rows["https://jobs.example/rejected"]["apply_status"] == "rejected"
    assert rows["https://jobs.example/withdrawn"]["apply_status"] == "withdrawn"
    assert rows["https://jobs.example/offer"]["apply_status"] == "offer"


def test_run_job_removes_transient_prompt_file(tmp_path, monkeypatch) -> None:
    worker_dir = tmp_path / "worker"
    app_dir = tmp_path / "app"
    log_dir = tmp_path / "logs"
    profile_dir = tmp_path / "profile"
    app_dir.mkdir()
    log_dir.mkdir()
    profile_dir.mkdir()

    class FakeStdIn:
        def write(self, text: str) -> None:
            self.text = text

        def close(self) -> None:
            pass

    class FakeProc:
        def __init__(self, *args, **kwargs) -> None:
            self.stdin = FakeStdIn()
            self.stdout = iter([
                "CONFIRMATION: page says application submitted successfully\n",
                "RESULT:APPLIED\n",
            ])
            self.returncode = 0
            self.pid = 12345

        def wait(self, timeout: int | None = None) -> None:
            return None

        def poll(self) -> int:
            return 0

    monkeypatch.setattr(launcher.config, "APP_DIR", app_dir)
    monkeypatch.setattr(launcher.config, "LOG_DIR", log_dir)
    monkeypatch.setattr(launcher.config, "load_credentials", lambda: {})
    monkeypatch.setattr(launcher.prompt_mod, "build_prompt", lambda **kwargs: "prompt with secret")
    monkeypatch.setattr(launcher, "setup_worker_profile", lambda worker_id, browser: profile_dir)
    monkeypatch.setattr(launcher, "reset_worker_dir", lambda worker_id: worker_dir)
    monkeypatch.setattr(launcher, "_build_agent_command", lambda *args, **kwargs: ["fake-agent"])
    monkeypatch.setattr(launcher.subprocess, "Popen", FakeProc)
    monkeypatch.setattr(launcher, "add_event", lambda message: None)
    monkeypatch.setattr(launcher, "update_state", lambda worker_id, **kwargs: None)
    monkeypatch.setattr(launcher, "get_state", lambda worker_id: None)

    worker_dir.mkdir()
    job = {
        "url": "https://jobs.example/1",
        "title": "Support Analyst",
        "company": "Example",
        "site": "Example ATS",
        "application_url": "https://jobs.example/1/apply",
        "fit_score": 9,
        "tailored_resume_path": str(tmp_path / "resume.pdf"),
    }

    status, _ = launcher.run_job(job, port=9222, worker_id=0)

    assert status == "applied"
    assert not (worker_dir / "apply_prompt.txt").exists()


def test_main_records_parallel_worker_crashes(monkeypatch) -> None:
    events: list[tuple[str, dict | None]] = []

    class FakeLive:
        def __init__(self, *_args, **_kwargs) -> None:
            pass

        def __enter__(self):
            return self

        def __exit__(self, *_exc) -> bool:
            return False

        def update(self, *_args, **_kwargs) -> None:
            return None

    monkeypatch.setattr(launcher.config, "ensure_dirs", lambda: None)
    monkeypatch.setattr(launcher, "recover_stale_apply_locks", lambda: 0)
    monkeypatch.setattr(launcher, "init_worker", lambda _worker_id: None)
    monkeypatch.setattr(launcher, "render_full", lambda: "")
    monkeypatch.setattr(launcher, "Live", FakeLive)
    monkeypatch.setattr(launcher, "kill_all_chrome", lambda: None)
    monkeypatch.setattr(launcher, "get_totals", lambda: {"cost": 0})
    monkeypatch.setattr(launcher.signal, "signal", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(
        launcher,
        "record_reliability_event",
        lambda category, _message, **kwargs: events.append((category, kwargs.get("context"))),
    )

    def fake_worker_loop(*, worker_id, **_kwargs):
        if worker_id == 0:
            raise RuntimeError("worker exploded")
        return (1, 0)

    monkeypatch.setattr(launcher, "worker_loop", fake_worker_loop)

    launcher.main(limit=2, workers=2)

    assert events == [("apply_worker_crashed", {"worker_id": 0, "error": "worker exploded"})]


def test_main_rejects_unsafe_worker_and_limit_values() -> None:
    for kwargs in [
        {"workers": 0},
        {"workers": launcher.MAX_RUNTIME_WORKERS + 1},
        {"limit": -1},
        {"poll_interval": 0},
    ]:
        try:
            launcher.main(**kwargs)
        except ValueError:
            pass
        else:
            raise AssertionError(f"main should reject {kwargs}")
