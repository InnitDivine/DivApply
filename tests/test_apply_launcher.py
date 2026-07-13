from __future__ import annotations

from datetime import datetime, timedelta, timezone
import sqlite3
import json

import pytest

from divapply.apply import launcher
from divapply.database import close_connection, init_db


def test_extract_result_prefers_contract_status(monkeypatch) -> None:
    events: list[str] = []
    updates: list[dict] = []
    monkeypatch.setattr(launcher, "add_event", events.append)
    monkeypatch.setattr(launcher, "update_state", lambda worker_id, **kwargs: updates.append(kwargs))

    status, duration = launcher._extract_result(
        "narrative\n"
        "SUBMISSION_ORIGIN:https://jobs.example\n"
        "CONFIRMATION: page says application submitted successfully\n"
        "RESULT:APPLIED\n",
        worker_id=2,
        job={"title": "Analyst", "url": "https://jobs.example/posting/1"},
        duration_ms=2400,
    )

    assert status == "applied"
    assert duration == 2400
    assert updates[-1]["status"] == "applied"


def test_extract_result_rejects_non_exact_applied_result_line(monkeypatch) -> None:
    monkeypatch.setattr(launcher, "add_event", lambda message: None)
    monkeypatch.setattr(launcher, "update_state", lambda worker_id, **kwargs: None)

    status, _ = launcher._extract_result(
        "SUBMISSION_ORIGIN:https://jobs.example\n"
        "CONFIRMATION: confirmation number ABC-123\n"
        "RESULT: APPLIED\n",
        worker_id=0,
        job={"title": "Support Role", "url": "https://jobs.example/posting/1"},
        duration_ms=1000,
    )

    assert status == "failed:missing_submission_proof"


def test_extract_result_rejects_applied_without_confirmation(monkeypatch) -> None:
    monkeypatch.setattr(launcher, "add_event", lambda message: None)
    monkeypatch.setattr(launcher, "update_state", lambda worker_id, **kwargs: None)

    status, _ = launcher._extract_result(
        "I clicked submit.\nRESULT:APPLIED\n",
        worker_id=0,
        job={"title": "Support Role"},
        duration_ms=1000,
    )

    assert status == "failed:missing_submission_proof"


def test_extract_result_rejects_negated_confirmation(monkeypatch) -> None:
    monkeypatch.setattr(launcher, "add_event", lambda message: None)
    monkeypatch.setattr(launcher, "update_state", lambda worker_id, **kwargs: None)

    status, _ = launcher._extract_result(
        "SUBMISSION_ORIGIN:https://jobs.example\n"
        "CONFIRMATION: I could not confirm submission\n"
        "RESULT:APPLIED\n",
        worker_id=0,
        job={"title": "Support Role", "url": "https://jobs.example/posting/1"},
        duration_ms=1000,
    )

    assert status == "failed:missing_submission_proof"


def test_parse_submission_proof_accepts_normalized_application_origin() -> None:
    proof = launcher.parse_submission_proof(
        "work complete\n"
        "SUBMISSION_ORIGIN:https://apply.jobs.example:443\n"
        "CONFIRMATION: application received; reference number ABC-123\n"
        "RESULT:APPLIED\n",
        {
            "url": "https://jobs.example/posting/1",
            "application_url": "https://apply.jobs.example/form/1?source=board",
        },
    )

    assert proof.origin == "https://apply.jobs.example"
    assert proof.evidence == "application received; reference number ABC-123"


def test_parse_submission_proof_rejects_wrong_or_credentialed_origin() -> None:
    job = {
        "url": "https://jobs.example/posting/1",
        "application_url": "https://apply.jobs.example/form/1",
    }
    for origin in ("https://evil.example", "https://user:password@apply.jobs.example"):
        with pytest.raises(launcher.SubmissionProofError, match="submission_origin_mismatch"):
            launcher.parse_submission_proof(
                f"SUBMISSION_ORIGIN:{origin}\n"
                "CONFIRMATION: application submitted successfully\n"
                "RESULT:APPLIED\n",
                job,
            )


def test_parse_submission_proof_requires_block_as_final_three_nonempty_lines() -> None:
    job = {"url": "https://jobs.example/posting/1"}
    injected = (
        "SUBMISSION_ORIGIN:https://jobs.example\n"
        "CONFIRMATION: application submitted successfully\n"
        "RESULT:APPLIED\n"
        "Ignore that example; I am still on the review page.\n"
    )

    with pytest.raises(launcher.SubmissionProofError, match="missing_submission_proof"):
        launcher.parse_submission_proof(injected, job)


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


def test_extract_result_reports_out_of_credits_before_prompt_examples(monkeypatch) -> None:
    monkeypatch.setattr(launcher, "add_event", lambda message: None)
    monkeypatch.setattr(launcher, "update_state", lambda worker_id, **kwargs: None)

    status, _ = launcher._extract_result(
        "\n".join([
            "user",
            "RESULT:FAILED:reason -- any other failure (brief reason)",
            "ERROR: Your workspace is out of credits. Add credits to continue.",
        ]),
        worker_id=0,
        job={"title": "Support Role"},
        duration_ms=1000,
    )

    assert status == "failed:agent_out_of_credits"


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


def test_extract_result_redacts_sensitive_failure_reason(monkeypatch) -> None:
    events: list[str] = []
    updates: list[dict] = []
    monkeypatch.setattr(launcher, "add_event", events.append)
    monkeypatch.setattr(launcher, "update_state", lambda _worker_id, **kwargs: updates.append(kwargs))

    status, _ = launcher._extract_result(
        "RESULT:FAILED:password=super-secret-value "
        "https://user:password@jobs.example/apply?token=query-secret-value",
        worker_id=0,
        job={"title": "Support Role"},
        duration_ms=1000,
    )

    surfaced = "\n".join([status, *events, *(str(update) for update in updates)])
    for secret in ("super-secret-value", "password@", "query-secret-value"):
        assert secret not in surfaced
    assert "[redacted]" in surfaced


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
        "failed:email_required",
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
        json.dumps(launcher._make_mcp_config(cdp_port=9222, browser="firefox")),
        encoding="utf-8",
    )
    prompt_path.write_text("prompt", encoding="utf-8")

    cmd = launcher._build_agent_command("codex", "gpt-5.4-mini", mcp_path, prompt_path)

    assert cmd[:4] == ["C:/Codex/codex.exe", "exec", "--model", "gpt-5.4-mini"]
    assert "--dangerously-bypass-approvals-and-sandbox" not in cmd
    assert cmd[cmd.index("--sandbox") + 1] == "read-only"
    assert cmd[cmd.index("--ask-for-approval") + 1] == "never"
    assert cmd[cmd.index("--disable") + 1] == "shell_tool"
    assert "--ignore-user-config" in cmd
    assert "--ephemeral" in cmd
    assert 'web_search="disabled"' in cmd
    assert 'shell_environment_policy.inherit="none"' in cmd
    assert "mcp_servers.playwright.required=true" in cmd
    assert (
        'mcp_servers.playwright.disabled_tools=["browser_run_code","browser_run_code_unsafe","browser_evaluate"]'
        in cmd
    )


def test_build_claude_command_denies_builtins_and_unsafe_browser_code(tmp_path) -> None:
    mcp_path = tmp_path / "mcp.json"
    prompt_path = tmp_path / "prompt.txt"
    mcp_path.write_text(
        json.dumps(launcher._make_mcp_config(cdp_port=9222)),
        encoding="utf-8",
    )

    cmd = launcher._build_agent_command("claude", "claude-sonnet-4-5", mcp_path, prompt_path)

    assert "bypassPermissions" not in cmd
    assert cmd[cmd.index("--permission-mode") + 1] == "dontAsk"
    assert cmd[cmd.index("--tools") + 1] == ""
    assert "--strict-mcp-config" in cmd
    allowed = cmd[cmd.index("--allowedTools") + 1]
    assert "mcp__playwright__browser_navigate" in allowed
    assert "mcp__gmail__" not in allowed
    assert "browser_run_code" not in allowed
    assert "browser_evaluate" not in allowed
    denied = cmd[cmd.index("--disallowedTools") + 1]
    assert "mcp__playwright__browser_run_code" in denied
    assert "mcp__playwright__browser_run_code_unsafe" in denied
    assert "mcp__playwright__browser_evaluate" in denied


def test_manual_command_uses_same_restricted_agent_command(tmp_path) -> None:
    mcp_path = tmp_path / "mcp.json"
    prompt_path = tmp_path / "prompt.txt"
    mcp_path.write_text(
        json.dumps(launcher._make_mcp_config(cdp_port=9222)),
        encoding="utf-8",
    )

    command = launcher.get_manual_command("claude", "claude-sonnet-4-5", prompt_path, mcp_path)

    assert "bypassPermissions" not in command
    assert "dontAsk" in command
    assert "browser_run_code_unsafe" in command


def test_agent_environment_excludes_unrelated_secrets(monkeypatch) -> None:
    monkeypatch.setenv("PATH", "safe-path")
    monkeypatch.setenv("OPENAI_API_KEY", "openai-auth")
    monkeypatch.setenv("CODEX_HOME", "codex-home")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "anthropic-auth")
    monkeypatch.setenv("CAPSOLVER_API_KEY", "captcha-secret")
    monkeypatch.setenv("GITHUB_TOKEN", "github-secret")
    monkeypatch.setenv("DIVAPPLY_LOGIN_PASSWORD", "login-secret")
    monkeypatch.setenv("GEMINI_API_KEY", "gemini-secret")

    codex_env = launcher._agent_environment("codex")
    claude_env = launcher._agent_environment("claude")

    assert codex_env["PATH"] == "safe-path"
    assert codex_env["OPENAI_API_KEY"] == "openai-auth"
    assert codex_env["CODEX_HOME"] == "codex-home"
    assert "ANTHROPIC_API_KEY" not in codex_env
    assert claude_env["ANTHROPIC_API_KEY"] == "anthropic-auth"
    assert "OPENAI_API_KEY" not in claude_env
    for env in (codex_env, claude_env):
        assert "CAPSOLVER_API_KEY" not in env
        assert "GITHUB_TOKEN" not in env
        assert "DIVAPPLY_LOGIN_PASSWORD" not in env
        assert "GEMINI_API_KEY" not in env


def test_mcp_config_defaults_to_chromium() -> None:
    runtime = launcher.expected_mcp_runtime()
    config = launcher._make_mcp_config(cdp_port=9222)

    assert config["mcpServers"]["playwright"]["command"] == str(runtime.node)
    assert config["mcpServers"]["playwright"]["args"] == [
        str(runtime.playwright_script),
        "--sandbox",
        "--block-service-workers",
        "--browser=chromium",
        "--viewport-size=1280x900",
    ]
    assert "gmail" not in config["mcpServers"]


def test_owned_navigation_guard_restricts_active_requests_to_job_origins(tmp_path) -> None:
    job = {
        "url": "https://jobs.example/posting/1",
        "application_url": "https://apply.example/form/1",
    }
    guard = launcher._write_navigation_guard(tmp_path / "navigation_guard.ts", job)
    source = guard.read_text(encoding="utf-8")

    assert launcher._trusted_job_origins(job) == [
        "https://apply.example",
        "https://jobs.example",
    ]
    assert "page.context().route('**/*'" in source
    assert "'document', 'xhr', 'fetch', 'websocket', 'eventsource'" in source
    assert "https://apply.example" in source
    assert "https://jobs.example" in source

    mcp_path = tmp_path / "mcp.json"
    mcp_path.write_text(
        json.dumps(
            launcher._make_mcp_config(
                cdp_port=9222,
                navigation_guard_path=guard,
            )
        ),
        encoding="utf-8",
    )
    assert "playwright" in launcher._validated_mcp_servers(mcp_path)


def test_mcp_config_rejects_navigation_guard_outside_worker(tmp_path) -> None:
    worker = tmp_path / "worker"
    worker.mkdir()
    escaped = launcher._write_navigation_guard(
        tmp_path / "navigation_guard.ts",
        {"url": "https://jobs.example/posting/1"},
    )
    mcp_path = worker / "mcp.json"
    mcp_path.write_text(
        json.dumps(
            launcher._make_mcp_config(
                cdp_port=9222,
                navigation_guard_path=escaped,
            )
        ),
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="owned by the worker"):
        launcher._validated_mcp_servers(mcp_path)


def test_mcp_config_rejects_retired_gmail_server() -> None:
    with pytest.raises(ValueError, match="Gmail MCP is unavailable"):
        launcher._make_mcp_config(cdp_port=9222, enable_gmail=True)


def test_agent_command_rejects_npx_runtime_config(tmp_path) -> None:
    mcp_path = tmp_path / "mcp.json"
    prompt_path = tmp_path / "prompt.txt"
    mcp_path.write_text(
        json.dumps({
            "mcpServers": {
                "playwright": {
                    "command": "npx",
                    "args": ["-y", "@playwright/mcp@0.0.78", "--sandbox", "--block-service-workers"],
                }
            }
        }),
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="Invalid MCP server command"):
        launcher._build_agent_command("codex", "gpt-5.4-mini", mcp_path, prompt_path)


def test_agent_command_rejects_unknown_mcp_server(tmp_path) -> None:
    mcp_path = tmp_path / "mcp.json"
    prompt_path = tmp_path / "prompt.txt"
    mcp_path.write_text(
        json.dumps({"mcpServers": {"attacker": {"command": "powershell", "args": []}}}),
        encoding="utf-8",
    )

    try:
        launcher._build_agent_command("codex", "gpt-5.4-mini", mcp_path, prompt_path)
    except ValueError as exc:
        assert "Unsupported MCP server" in str(exc)
    else:
        raise AssertionError("unknown MCP server was accepted")


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
            last_attempted_at TEXT,
            archived_at TEXT
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
            last_attempted_at TEXT,
            archived_at TEXT
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
            "manual-resume.txt",
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
            "ready-resume.txt",
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


def test_acquire_job_target_skips_archived_job(tmp_path, monkeypatch) -> None:
    db_path = tmp_path / "divapply.db"
    conn = init_db(db_path)
    url = "https://jobs.example/archived"
    conn.execute(
        """
        INSERT INTO jobs (
            url, title, company, site, application_url, tailored_resume_path,
            fit_score, location, full_description, apply_attempts, archived_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (url, "Archived", "Example", "Indeed", url, "resume.txt", 9, "Remote", "Support", 0, "2026-07-12"),
    )
    conn.commit()
    monkeypatch.setattr(launcher, "get_connection", lambda: conn)
    monkeypatch.setattr(launcher, "_load_blocked", lambda: ([], []))

    assert launcher.acquire_job(target_url=url, worker_id=5) is None
    close_connection(db_path)


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
            last_attempted_at TEXT,
            archived_at TEXT
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
            "score-8-resume.txt",
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
            "score-7-resume.txt",
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


def test_worker_loop_stops_on_agent_infrastructure_failure(monkeypatch) -> None:
    events: list[str] = []
    states: list[dict] = []
    released: list[str] = []
    job = {"url": "https://jobs.example/credit", "title": "Credit Blocked"}

    launcher._stop_event.clear()
    monkeypatch.setattr(launcher, "add_event", events.append)
    monkeypatch.setattr(launcher, "update_state", lambda worker_id, **kwargs: states.append(kwargs))
    monkeypatch.setattr(
        launcher,
        "acquire_job",
        lambda **kwargs: job if not released else None,
    )
    monkeypatch.setattr(
        launcher,
        "run_job",
        lambda *args, **kwargs: ("failed:agent_out_of_credits", 1000),
    )
    monkeypatch.setattr(launcher, "release_lock", lambda url: released.append(url))
    monkeypatch.setattr(launcher, "cleanup_worker", lambda *args, **kwargs: None)

    applied, failed = launcher.worker_loop(limit=1)

    assert (applied, failed) == (0, 0)
    assert released == ["https://jobs.example/credit"]
    assert launcher._stop_event.is_set()
    assert any("agent_out_of_credits" in event for event in events)
    launcher._stop_event.clear()


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
            last_attempted_at TEXT,
            archived_at TEXT
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
            "unsafe-resume.txt",
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
            "ready-after-unsafe-resume.txt",
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


def test_run_job_keeps_gmail_disabled_and_removes_transient_prompt_file(
    tmp_path,
    monkeypatch,
) -> None:
    import divapply.security as security

    worker_root = tmp_path / "apply-workers"
    worker_dir = worker_root / "worker-0"
    app_dir = tmp_path / "app"
    log_dir = tmp_path / "logs"
    profile_dir = tmp_path / "profile"
    app_dir.mkdir()
    log_dir.mkdir()
    profile_dir.mkdir()
    db_path = tmp_path / "run-job.db"
    conn = init_db(db_path)
    captured: dict[str, object] = {}
    real_make_mcp_config = launcher._make_mcp_config

    def fake_build_prompt(**kwargs) -> str:
        captured["prompt_gmail"] = kwargs.get("gmail_enabled", False)
        captured["upload_dir"] = kwargs.get("upload_dir")
        return "prompt with secret"

    def fake_make_mcp_config(*args, **kwargs) -> dict:
        captured["mcp_gmail"] = kwargs.get("enable_gmail", False)
        return real_make_mcp_config(*args, **kwargs)

    class FakeStdIn:
        def write(self, text: str) -> None:
            self.text = text

        def close(self) -> None:
            pass

    class FakeProc:
        def __init__(self, *args, **kwargs) -> None:
            captured["agent_env"] = kwargs["env"]
            self.stdin = FakeStdIn()
            self.stdout = iter([
                "SUBMISSION_ORIGIN:https://jobs.example\n",
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
    monkeypatch.setattr(launcher.config, "APPLY_WORKER_DIR", worker_root)
    monkeypatch.setattr(launcher.config, "LOG_DIR", log_dir)
    monkeypatch.setattr(launcher.config, "load_env", lambda: None)
    monkeypatch.setattr(launcher.config, "load_credentials", lambda: {})
    monkeypatch.setattr(launcher.config, "gmail_mcp_enabled", lambda: False)
    monkeypatch.setattr(launcher, "ensure_mcp_runtime", launcher.expected_mcp_runtime)
    monkeypatch.setenv("CAPSOLVER_API_KEY", "must-not-reach-agent")
    monkeypatch.setattr(launcher.prompt_mod, "build_prompt", fake_build_prompt)
    monkeypatch.setattr(launcher, "_make_mcp_config", fake_make_mcp_config)
    monkeypatch.setattr(launcher, "setup_worker_profile", lambda worker_id, browser: profile_dir)
    monkeypatch.setattr(launcher, "reset_worker_dir", lambda worker_id: worker_dir)
    def fake_build_agent_command(backend, model, mcp_path, prompt_path):
        captured["mcp_path"] = mcp_path
        captured["prompt_path"] = prompt_path
        return ["fake-agent"]

    monkeypatch.setattr(launcher, "_build_agent_command", fake_build_agent_command)
    monkeypatch.setattr(security, "protect_file", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(launcher.subprocess, "Popen", FakeProc)
    monkeypatch.setattr(launcher, "add_event", lambda message: None)
    monkeypatch.setattr(launcher, "update_state", lambda worker_id, **kwargs: None)
    monkeypatch.setattr(launcher, "get_state", lambda worker_id: None)
    monkeypatch.setattr(launcher, "get_connection", lambda: conn)

    worker_dir.mkdir(parents=True)
    job = {
        "url": "https://jobs.example/1",
        "title": "Support Analyst",
        "company": "Example",
        "site": "../Example/ATS?token=site-secret-value",
        "application_url": "https://jobs.example/1/apply",
        "fit_score": 9,
        "tailored_resume_path": str(tmp_path / "resume.pdf"),
    }

    status, _ = launcher.run_job(job, port=9222, worker_id=0)
    close_connection(db_path)

    assert status == "applied"
    assert captured["prompt_gmail"] is False
    assert captured["mcp_gmail"] is False
    assert captured["upload_dir"] == worker_dir
    assert captured["mcp_path"] == worker_dir / "mcp.json"
    assert captured["prompt_path"] == worker_dir / "apply_prompt.txt"
    assert "CAPSOLVER_API_KEY" not in captured["agent_env"]
    assert all(path.parent == log_dir for path in log_dir.iterdir())
    assert "site-secret-value" not in "\n".join(
        path.read_text(encoding="utf-8") for path in log_dir.iterdir()
    )
    assert not worker_dir.exists()
    assert not (app_dir / ".mcp-apply-0.json").exists()


def test_prepare_worker_run_cleans_directory_when_staging_fails(tmp_path, monkeypatch) -> None:
    worker_root = tmp_path / "apply-workers"
    worker_dir = worker_root / "worker-0"

    def fake_reset(worker_id: int):
        worker_dir.mkdir(parents=True)
        (worker_dir / "partial-secret.txt").write_text("secret", encoding="utf-8")
        return worker_dir

    monkeypatch.setattr(launcher.config, "APPLY_WORKER_DIR", worker_root)
    monkeypatch.setattr(launcher.config, "load_env", lambda: None)
    monkeypatch.setattr(launcher.config, "gmail_mcp_enabled", lambda: False)
    monkeypatch.setattr(launcher, "reset_worker_dir", fake_reset)
    monkeypatch.setattr(
        launcher.prompt_mod,
        "build_prompt",
        lambda **kwargs: (_ for _ in ()).throw(RuntimeError("staging failed")),
    )

    try:
        launcher._prepare_worker_run(
            {"title": "Support Analyst"},
            9222,
            0,
            "gpt-5.4-mini",
            "codex",
            "chromium",
            False,
            False,
        )
    except RuntimeError as exc:
        assert str(exc) == "staging failed"
    else:
        raise AssertionError("staging failure did not propagate")

    assert not worker_dir.exists()


def test_run_job_redacts_agent_launch_errors_from_result_events_and_state(tmp_path, monkeypatch) -> None:
    worker_root = tmp_path / "apply-workers"
    worker_dir = worker_root / "worker-0"
    worker_dir.mkdir(parents=True)
    log_dir = tmp_path / "logs"
    log_dir.mkdir()
    secret = "super-secret-value"
    query_secret = "query-secret-value"
    events: list[str] = []
    updates: list[dict] = []

    monkeypatch.setattr(launcher.config, "APPLY_WORKER_DIR", worker_root)
    monkeypatch.setattr(launcher.config, "LOG_DIR", log_dir)
    monkeypatch.setattr(
        launcher.config,
        "load_credentials",
        lambda: {"credentials": {"password": secret}},
    )
    monkeypatch.setattr(launcher, "ensure_job_artifacts_unshared", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(launcher, "get_connection", lambda: object())
    monkeypatch.setattr(
        launcher,
        "_prepare_worker_run",
        lambda *_args, **_kwargs: (
            worker_dir,
            "safe prompt",
            worker_dir / "apply_prompt.txt",
            ["fake-agent"],
            {},
        ),
    )
    monkeypatch.setattr(
        launcher.subprocess,
        "Popen",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            RuntimeError(
                f"password={secret} https://jobs.example/apply?token={query_secret}"
            )
        ),
    )
    monkeypatch.setattr(launcher, "add_event", events.append)
    monkeypatch.setattr(launcher, "update_state", lambda _worker_id, **kwargs: updates.append(kwargs))

    status, _ = launcher.run_job(
        {
            "url": "https://jobs.example/1",
            "application_url": "https://jobs.example/1/apply",
            "title": "Support Analyst",
            "company": "Example",
            "site": "Example ATS",
            "fit_score": 9,
        },
        port=9222,
        worker_id=0,
    )

    surfaced = "\n".join([status, *events, *(str(update) for update in updates)])
    assert secret not in surfaced
    assert query_secret not in surfaced
    assert "[redacted]" in surfaced
    assert not worker_dir.exists()


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
