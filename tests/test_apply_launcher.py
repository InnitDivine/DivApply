from __future__ import annotations

import sqlite3
import json

from divapply.apply import launcher


def test_extract_result_prefers_contract_status(monkeypatch) -> None:
    events: list[str] = []
    updates: list[dict] = []
    monkeypatch.setattr(launcher, "add_event", events.append)
    monkeypatch.setattr(launcher, "update_state", lambda worker_id, **kwargs: updates.append(kwargs))

    status, duration = launcher._extract_result(
        "narrative\nRESULT:APPLIED\n",
        worker_id=2,
        job={"title": "Analyst"},
        duration_ms=2400,
    )

    assert status == "applied"
    assert duration == 2400
    assert updates[-1]["status"] == "applied"


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


def test_build_codex_command_maps_mcp_config(tmp_path, monkeypatch) -> None:
    monkeypatch.delenv("DIVAPPLY_CODEX_CMD", raising=False)
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

    assert cmd[:4] == ["codex", "exec", "--model", "gpt-5.4-mini"]
    assert "--full-auto" in cmd
    assert "mcp_servers.playwright.required=true" in cmd


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
