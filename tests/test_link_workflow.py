from __future__ import annotations

from pathlib import Path

import pytest
from typer.testing import CliRunner

from divapply import cli, database
from divapply.cli import app


runner = CliRunner()


def test_user_confirmed_manual_url_persists_terminal_application_url(tmp_path) -> None:
    conn = database.init_db(tmp_path / "divapply.db")
    source_url = "https://short.example/jobs/1"
    application_url = "https://ats.example/apply/1"

    cli._persist_manual_url(
        conn,
        safe_url=source_url,
        metadata={
            "final_url": application_url,
            "employment_type": "full_time",
        },
        title_value="IT Assistant",
        company_value="Example",
        site_value="Example",
        location_value="Example City, CA",
        description_value="Support users, endpoints, accounts, and business applications. " * 5,
        inactive=False,
        now="2026-09-01T00:00:00+00:00",
        market_label="California",
        market_policy={"application_mode": "active"},
        search_config={},
        official_source=None,
        closed_official_source=None,
        user_confirmed=True,
    )

    row = conn.execute(
        "SELECT application_url, application_mode, source_verification, verification_confidence FROM jobs"
    ).fetchone()
    assert dict(row) == {
        "application_url": application_url,
        "application_mode": "manual_review",
        "source_verification": "user_confirmed_direct",
        "verification_confidence": "user_confirmed_direct",
    }
    database.close_connection(tmp_path / "divapply.db")


@pytest.mark.parametrize(
    ("apply_status", "applied_at", "agent_id", "apply_attempts"),
    [
        ("applied", "2026-08-30T10:00:00+00:00", None, 2),
        ("in_progress", None, "worker-2", 2),
        ("screening", "2026-08-30T10:00:00+00:00", None, 2),
        ("interview", "2026-08-30T10:00:00+00:00", None, 2),
        ("offer", "2026-08-30T10:00:00+00:00", None, 2),
        ("rejected", "2026-08-30T10:00:00+00:00", None, 2),
        ("withdrawn", "2026-08-30T10:00:00+00:00", None, 2),
        ("failed", None, None, 99),
    ],
)
def test_manual_url_reingest_preserves_existing_application_lifecycle(
    tmp_path,
    apply_status: str,
    applied_at: str | None,
    agent_id: str | None,
    apply_attempts: int,
) -> None:
    db_path = tmp_path / "divapply.db"
    conn = database.init_db(db_path)
    url = "https://jobs.example/roles/it-assistant"
    expected = {
        "apply_status": apply_status,
        "applied_at": applied_at,
        "apply_error": "existing lifecycle detail",
        "apply_attempts": apply_attempts,
        "agent_id": agent_id,
        "last_attempted_at": "2026-08-31T11:00:00+00:00",
        "apply_duration_ms": 4321,
        "apply_task_id": "existing-task-id",
    }
    conn.execute(
        """
        INSERT INTO jobs (
            url, title, company, discovered_at, apply_status, applied_at,
            apply_error, apply_attempts, agent_id, last_attempted_at,
            apply_duration_ms, apply_task_id
        ) VALUES (?, 'Old title', 'Old employer', ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            url,
            "2026-08-01T00:00:00+00:00",
            apply_status,
            applied_at,
            expected["apply_error"],
            expected["apply_attempts"],
            agent_id,
            expected["last_attempted_at"],
            expected["apply_duration_ms"],
            expected["apply_task_id"],
        ),
    )
    conn.commit()

    cli._persist_manual_url(
        conn,
        safe_url=url,
        metadata={"employment_type": "full_time"},
        title_value="Refreshed title",
        company_value="Refreshed employer",
        site_value="Refreshed source",
        location_value="Example City, CA",
        description_value="Refreshed current job description. " * 10,
        inactive=False,
        now="2026-09-02T00:00:00+00:00",
        market_label="California",
        market_policy={"application_mode": "active"},
        search_config={},
        official_source=None,
        closed_official_source=None,
        user_confirmed=True,
    )

    row = conn.execute(
        """
        SELECT apply_status, applied_at, apply_error, apply_attempts, agent_id,
               last_attempted_at, apply_duration_ms, apply_task_id
        FROM jobs WHERE url = ?
        """,
        (url,),
    ).fetchone()
    assert dict(row) == expected
    assert conn.execute("SELECT title FROM jobs WHERE url = ?", (url,)).fetchone()[0] == "Refreshed title"
    database.close_connection(db_path)


def test_apply_assist_requires_one_explicit_url(monkeypatch) -> None:
    monkeypatch.setattr(cli, "_bootstrap", lambda: None)

    result = runner.invoke(app, ["apply", "--assist"])

    assert result.exit_code == 1
    assert "--assist requires --url" in result.output


def test_apply_links_help_documents_one_url_per_line() -> None:
    result = runner.invoke(app, ["apply-links", "--help"])

    assert result.exit_code == 0
    assert "one direct job URL" in result.output
    assert "per line" in result.output
    assert "--prepare-only" in result.output


def test_prepare_manual_url_promotes_resume_text_fallback_to_pdf(tmp_path, monkeypatch) -> None:
    from divapply import config
    from divapply.scoring import cover_letter, pdf, scorer, tailor

    db_path = tmp_path / "divapply.db"
    conn = database.init_db(db_path)
    url = "https://jobs.example.test/posting/one"
    resume_text = tmp_path / "Example_Job.txt"
    resume_pdf = resume_text.with_suffix(".pdf")
    cover_pdf = tmp_path / "Example_Job_CL.pdf"
    resume_text.write_text("Example resume", encoding="utf-8")
    cover_pdf.write_bytes(b"%PDF-1.4\n")
    conn.execute(
        """
        INSERT INTO jobs (
            url, title, company, fit_score, tailored_resume_path,
            cover_letter_path, application_mode, source_verification
        ) VALUES (?, 'Example Job', 'Example Employer', 7, ?, ?, 'active', 'official')
        """,
        (url, str(resume_text), str(cover_pdf)),
    )
    conn.commit()

    monkeypatch.setattr(config, "check_tier", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(config, "TAILORED_DIR", tmp_path)
    monkeypatch.setattr(scorer, "run_scoring", lambda **_kwargs: {"scored": 1})
    monkeypatch.setattr(tailor, "run_tailoring", lambda **_kwargs: {"approved": 0})
    monkeypatch.setattr(cover_letter, "run_cover_letters", lambda **_kwargs: {"generated": 0})

    def fake_convert(source: Path, *, output_path: Path) -> Path:
        assert source == resume_text
        output_path.write_bytes(b"%PDF-1.4\n")
        return output_path

    monkeypatch.setattr(pdf, "convert_to_pdf", fake_convert)

    result = cli._prepare_manual_url(
        conn,
        safe_url=url,
        min_score=5,
        validation="normal",
    )
    row = conn.execute(
        "SELECT tailored_resume_path, cover_letter_path FROM jobs WHERE url = ?",
        (url,),
    ).fetchone()

    assert result["status"] == "prepared"
    assert result["tailored_resume_path"] == str(resume_pdf)
    assert result["cover_letter_path"] == str(cover_pdf)
    assert row["tailored_resume_path"] == str(resume_pdf)
    assert row["cover_letter_path"] == str(cover_pdf)
    assert resume_pdf.is_file()
    assert cover_pdf.is_file()
    database.close_connection(db_path)


def test_manual_resume_pdf_promotion_discards_stale_concurrent_result(tmp_path, monkeypatch) -> None:
    from divapply import config
    from divapply.scoring import pdf

    db_path = tmp_path / "divapply.db"
    conn = database.init_db(db_path)
    url = "https://jobs.example.test/posting/race"
    old_text = tmp_path / "Old_Resume.txt"
    new_pdf = tmp_path / "New_Resume.pdf"
    old_text.write_text("Old resume", encoding="utf-8")
    new_pdf.write_bytes(b"%PDF-1.4\nnew")
    conn.execute(
        "INSERT INTO jobs (url, tailored_resume_path) VALUES (?, ?)",
        (url, str(old_text)),
    )
    conn.commit()
    monkeypatch.setattr(config, "TAILORED_DIR", tmp_path)

    def change_pointer_during_conversion(_source: Path, *, output_path: Path) -> Path:
        output_path.write_bytes(b"%PDF-1.4\nstale")
        conn.execute(
            "UPDATE jobs SET tailored_resume_path = ? WHERE url = ?",
            (str(new_pdf), url),
        )
        conn.commit()
        return output_path

    monkeypatch.setattr(pdf, "convert_to_pdf", change_pointer_during_conversion)

    result = cli._ensure_manual_resume_pdf(
        conn,
        safe_url=url,
        resume_path=str(old_text),
    )

    saved = conn.execute("SELECT tailored_resume_path FROM jobs WHERE url = ?", (url,)).fetchone()[0]
    assert result is None
    assert saved == str(new_pdf)
    assert not old_text.with_suffix(".pdf").exists()
    assert list(tmp_path.glob(".Old_Resume.manual-*.pdf")) == []
    database.close_connection(db_path)


def test_manual_resume_pdf_promotion_rejects_source_outside_owned_directory(
    tmp_path,
    monkeypatch,
) -> None:
    from divapply import config
    from divapply.scoring import pdf

    owned_dir = tmp_path / "owned"
    owned_dir.mkdir()
    outside_text = tmp_path / "Outside.txt"
    outside_text.write_text("Outside resume", encoding="utf-8")
    conn = database.init_db(tmp_path / "divapply.db")
    url = "https://jobs.example.test/posting/outside"
    conn.execute(
        "INSERT INTO jobs (url, tailored_resume_path) VALUES (?, ?)",
        (url, str(outside_text)),
    )
    conn.commit()
    monkeypatch.setattr(config, "TAILORED_DIR", owned_dir)
    monkeypatch.setattr(
        pdf,
        "convert_to_pdf",
        lambda *_args, **_kwargs: pytest.fail("unsafe source reached PDF converter"),
    )

    result = cli._ensure_manual_resume_pdf(
        conn,
        safe_url=url,
        resume_path=str(outside_text),
    )

    assert result is None
    assert not outside_text.with_suffix(".pdf").exists()
    database.close_connection(tmp_path / "divapply.db")


def test_manual_resume_pdf_promotion_rejects_corrupt_existing_pdf(tmp_path, monkeypatch) -> None:
    from divapply import config

    corrupt_pdf = tmp_path / "Corrupt.pdf"
    corrupt_pdf.write_bytes(b"not a pdf")
    db_path = tmp_path / "divapply.db"
    conn = database.init_db(db_path)
    url = "https://jobs.example.test/posting/corrupt"
    conn.execute(
        "INSERT INTO jobs (url, tailored_resume_path) VALUES (?, ?)",
        (url, str(corrupt_pdf)),
    )
    conn.commit()
    monkeypatch.setattr(config, "TAILORED_DIR", tmp_path)

    result = cli._ensure_manual_resume_pdf(
        conn,
        safe_url=url,
        resume_path=str(corrupt_pdf),
    )

    assert result is None
    assert conn.execute("SELECT tailored_resume_path FROM jobs WHERE url = ?", (url,)).fetchone()[0] == str(
        corrupt_pdf
    )
    database.close_connection(db_path)
