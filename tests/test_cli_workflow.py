"""Offline contracts for the small CLI and complete, restartable job packets."""

from pathlib import Path

import pytest
from typer.testing import CliRunner

from divapply import cli, config, database, job_health, pipeline
from divapply.scoring import cover_letter, pdf, scorer, tailor
from divapply.scoring.requirements import SCORING_VERSION

runner = CliRunner()


def test_main_menu_has_only_eight_everyday_commands():
    commands = {c.name or c.callback.__name__.replace("_", "-") for c in cli.app.registered_commands if not c.hidden}
    commands.update(g.name for g in cli.app.registered_groups if not g.hidden)
    assert commands == {"run", "add", "status", "dashboard", "apply", "settings", "jobs", "system"}


@pytest.mark.parametrize("args", [["run"], ["run", "all"]])
def test_explicit_run_starts_non_submitting_workflow(monkeypatch, args):
    monkeypatch.setattr(cli, "_bootstrap", lambda: None)
    monkeypatch.setattr(config, "check_tier", lambda *a, **k: None)
    calls = []
    monkeypatch.setattr(pipeline, "run_preparation", lambda **kw: calls.append(kw) or {"errors": {}})
    result = runner.invoke(cli.app, args)
    assert result.exit_code == 0, result.output
    assert calls == [{"saved": False, "limit": 0, "min_score": 7, "refresh": False,
                      "workers": 1, "validation_mode": "normal", "dry_run": False}]


def test_bare_command_restores_home_menu_without_starting_work(monkeypatch):
    monkeypatch.setattr(cli, "_bootstrap", lambda: pytest.fail("Home menu started the pipeline"))
    monkeypatch.setattr(pipeline, "run_preparation", lambda **kw: pytest.fail("Home menu started preparation"))
    result = runner.invoke(cli.app, [])
    assert result.exit_code == 0, result.output
    assert result.output == runner.invoke(cli.app, ["--help"]).output
    for command in ("run", "add", "status", "dashboard", "apply", "settings", "jobs", "system"):
        assert command in result.output


@pytest.mark.parametrize("args", [[], ["--help"], ["settings", "--help"], ["jobs", "--help"], ["system", "--help"], ["--version"]])
def test_help_never_starts_work(monkeypatch, args):
    monkeypatch.setattr(cli, "_bootstrap", lambda: pytest.fail("Help started the pipeline"))
    assert runner.invoke(cli.app, args).exit_code == 0


def test_run_preview_needs_no_ai_key_and_honors_packet_limit(monkeypatch):
    monkeypatch.setattr(cli, "_bootstrap", lambda: None)
    monkeypatch.setattr(config, "check_tier", lambda *a, **k: pytest.fail("Preview required AI access"))
    calls = []
    monkeypatch.setattr(pipeline, "run_preparation", lambda **kw: calls.append(kw) or {"errors": {}})
    result = runner.invoke(cli.app, ["run", "--saved", "--limit", "3", "--dry-run"])
    assert result.exit_code == 0, result.output
    assert calls[0]["limit"] == 3 and calls[0]["saved"] and calls[0]["dry_run"]


def test_run_failures_have_nonzero_exit_code(monkeypatch):
    monkeypatch.setattr(cli, "_bootstrap", lambda: None)
    monkeypatch.setattr(config, "check_tier", lambda *a, **k: None)
    monkeypatch.setattr(pipeline, "run_preparation", lambda **kw: {"errors": {"preparation": "failed"}})
    assert runner.invoke(cli.app, ["run"]).exit_code == 1


@pytest.mark.parametrize("args", [["run", "--limit", "-1"], ["run", "--min-score", "11"],
                                  ["run", "--workers", "0"], ["add"], ["add", "--min-score", "0"]])
def test_invalid_options_fail_without_starting(monkeypatch, args):
    monkeypatch.setattr(cli, "_bootstrap", lambda: pytest.fail("Invalid options started work"))
    assert runner.invoke(cli.app, args).exit_code == 2


def test_add_url_prepares_by_default_without_applying(monkeypatch):
    calls = []
    monkeypatch.setattr(cli, "_invoke_root_command", lambda ctx, name, **kw: calls.append((name, kw)))
    result = runner.invoke(cli.app, ["add", "https://example.com/job"])
    assert result.exit_code == 0, result.output
    assert calls == [("add-url", {"job_url": "https://example.com/job", "prepare": True, "min_score": 7, "confirm_source": False})]


def test_add_file_is_prepare_only(monkeypatch, tmp_path):
    source = tmp_path / "links.txt"
    source.write_text("https://example.com/job", encoding="utf-8")
    calls = []
    monkeypatch.setattr(cli, "_invoke_root_command", lambda ctx, name, **kw: calls.append(kw))
    result = runner.invoke(cli.app, ["add", "--file", str(source)])
    assert result.exit_code == 0, result.output
    assert calls[0]["prepare_only"] is True and calls[0]["yes"] is False


def test_old_check_names_share_one_implementation():
    callbacks = {c.name: c.callback for c in cli.app.registered_commands}
    assert callbacks["doctor"] is callbacks["selfcheck"] is cli.doctor


@pytest.fixture
def queue(tmp_path, monkeypatch):
    db_path = tmp_path / "test.db"
    conn = database.init_db(db_path)
    monkeypatch.setattr(job_health, "get_connection", lambda: conn)
    monkeypatch.setattr(database, "get_connection", lambda: conn)
    monkeypatch.setattr(tailor, "get_connection", lambda: conn)
    monkeypatch.setattr(cover_letter, "get_connection", lambda: conn)
    for n in range(5):
        conn.execute(
            "INSERT INTO jobs(url,title,company,site,full_description,fit_score,scoring_version,"
            "source_verification,application_mode,eligibility_status) VALUES (?,?,?,?,?,8,?,'official','active','meets')",
            (f"https://example.com/{n}", f"Role {n}", "Example", "Example", "Support staff with systems and records. " * 10, SCORING_VERSION),
        )
    conn.commit()
    yield conn
    database.close_connection(db_path)


def fake_documents(conn, tmp_path, monkeypatch):
    calls = []

    def generate(column, **kw):
        url = kw["target_url"]
        calls.append((column, url))
        old = conn.execute(f"SELECT {column} FROM jobs WHERE url=?", (url,)).fetchone()[0]
        if not old:
            path = tmp_path / f"{url.rsplit('/', 1)[-1]}-{column}.pdf"
            path.write_bytes(b"fixture PDF")
            conn.execute(f"UPDATE jobs SET {column}=? WHERE url=?", (str(path), url))
            conn.commit()
        return {"approved": 1, "generated": 1, "errors": 0}

    monkeypatch.setattr(tailor, "run_tailoring", lambda **kw: generate("tailored_resume_path", **kw))
    monkeypatch.setattr(cover_letter, "run_cover_letters", lambda **kw: generate("cover_letter_path", **kw))
    monkeypatch.setattr(pdf, "batch_convert", lambda **kw: 0)
    monkeypatch.setattr(scorer, "run_scoring", lambda **kw: pytest.fail("Ready grade was unnecessarily regenerated"))
    monkeypatch.setattr(job_health, "refresh_job", lambda *a: pytest.fail("Current graded job was unnecessarily fetched"))
    return calls


@pytest.mark.parametrize("limit,expected", [(1, 1), (3, 3), (0, 5)])
def test_limit_counts_complete_packets_not_different_stage_batches(queue, tmp_path, monkeypatch, limit, expected):
    calls = fake_documents(queue, tmp_path, monkeypatch)
    result = job_health.repair_jobs(limit=limit, refresh=False, rescore=False, only_pending=True)
    assert result["errors"] == 0 and result["selected"] == expected
    assert len(calls) == expected * 2
    assert all(item["after"] == "Packet ready" for item in result["jobs"])
    again = job_health.repair_jobs(limit=0, refresh=False, rescore=False, only_pending=True)
    assert again["selected"] == 5 - expected
    assert job_health.repair_jobs(refresh=False, rescore=False, only_pending=True)["selected"] == 0


def test_missing_document_files_recover_but_existing_edited_pdf_is_kept(queue, tmp_path, monkeypatch):
    edited = tmp_path / "my-edited-resume.pdf"
    edited.write_bytes(b"user edited document")
    queue.execute("UPDATE jobs SET tailored_resume_path=?, cover_letter_path=? WHERE url='https://example.com/0'",
                  (str(edited), str(tmp_path / "missing-cover.pdf")))
    queue.commit()
    fake_documents(queue, tmp_path, monkeypatch)
    result = job_health.repair_jobs(urls=["https://example.com/0"], refresh=False, rescore=False, only_pending=True)
    assert result["errors"] == 0 and result["jobs"][0]["after"] == "Packet ready"
    assert edited.read_bytes() == b"user edited document"
    assert queue.execute("SELECT tailored_resume_path FROM jobs WHERE url='https://example.com/0'").fetchone()[0] == str(edited)


def test_noop_document_generator_is_reported_as_failure(queue, monkeypatch):
    monkeypatch.setattr(tailor, "run_tailoring", lambda **kw: {"approved": 0})
    monkeypatch.setattr(cover_letter, "run_cover_letters", lambda **kw: {"generated": 0})
    monkeypatch.setattr(pdf, "batch_convert", lambda **kw: 0)
    result = job_health.repair_jobs(limit=1, refresh=False, rescore=False, only_pending=True)
    assert result["errors"] == 1 and "Resume waiting" in result["jobs"][0]["error"]


def test_stale_grade_is_refreshed_before_scoring(queue, tmp_path, monkeypatch):
    fake_documents(queue, tmp_path, monkeypatch)
    queue.execute("UPDATE jobs SET scoring_version='old' WHERE url='https://example.com/0'")
    queue.commit()
    calls = []

    def refresh(job, conn):
        calls.append("page")
        return job

    def score(**kw):
        calls.append("score")
        queue.execute("UPDATE jobs SET scoring_version=? WHERE url=?", (SCORING_VERSION, kw["target_url"]))
        queue.commit()
        return {"scored": 1}

    monkeypatch.setattr(job_health, "refresh_job", refresh)
    monkeypatch.setattr(scorer, "run_scoring", score)
    result = job_health.repair_jobs(limit=1, refresh=False, rescore=False, only_pending=True)
    assert calls == ["page", "score"] and result["errors"] == 0


def test_normal_run_never_reopens_closed_or_applied_jobs(queue, monkeypatch):
    queue.execute("UPDATE jobs SET availability_state='closed'")
    queue.execute("UPDATE jobs SET availability_state='open', applied_at='2026-01-01' WHERE url='https://example.com/0'")
    queue.commit()
    monkeypatch.setattr(job_health, "refresh_job", lambda *a: pytest.fail("Reopened closed/applied job"))
    assert job_health.repair_jobs(only_pending=True, refresh=True)["selected"] == 0


def test_legacy_pdf_stage_has_no_silent_fifty_document_limit(monkeypatch):
    calls = []
    monkeypatch.setattr(pdf, "batch_convert", lambda **kw: calls.append(kw) or 120)
    assert pipeline._run_pdf() == {"status": "ok", "converted": 120}
    assert calls == [{"limit": 0}]


def test_exhausted_resume_does_not_create_endless_cover_work(queue):
    queue.execute("UPDATE jobs SET tailor_attempts=5")
    queue.commit()
    result = job_health.repair_jobs(only_pending=True, refresh=False, rescore=False, dry_run=True)
    assert result["selected"] == 0
    retry = job_health.repair_jobs(only_pending=True, refresh=False, rescore=False, dry_run=True, retry_failed=True)
    assert retry["selected"] == 3


def test_incomplete_school_metadata_has_no_dangling_separators():
    lines = tailor._resume_education_lines([
        {"school": "Community College", "degree": "Associate of General Studies", "degree_received": True, "end_year": "2024"},
        {"school": "University", "degree": "Bachelor of Science", "degree_received": False, "status": "in progress"},
    ])
    assert "2024" in lines
    assert not any(line.strip().startswith(("|", "-")) for line in lines if line.strip())


@pytest.mark.parametrize("kind", ["resume", "cover"])
def test_batch_interrupt_keeps_first_document_committed(queue, tmp_path, monkeypatch, kind):
    module = tailor if kind == "resume" else cover_letter
    monkeypatch.setattr(module, "load_profile", lambda: {})
    monkeypatch.setattr(module, "protect_file", lambda *a, **kw: None)
    master = tmp_path / "master.txt"
    master.write_text("Source resume", encoding="utf-8")
    monkeypatch.setattr(tailor, "RESUME_PATH", master)
    monkeypatch.setattr(tailor, "TAILORED_DIR", tmp_path / "resumes")
    monkeypatch.setattr(cover_letter, "COVER_LETTER_DIR", tmp_path / "covers")
    monkeypatch.setattr(cover_letter, "_read_tailored_resume_text", lambda job: "Source resume")

    def convert(path, **kw):
        out = Path(path).with_suffix(".pdf")
        out.write_bytes(b"fixture PDF")
        return out

    monkeypatch.setattr(pdf, "convert_to_pdf", convert)
    calls = []

    def generate(*a, **kw):
        if calls:
            raise KeyboardInterrupt()
        calls.append(True)
        return ("Approved resume", {"status": "approved", "attempts": 1}) if kind == "resume" else "Dear Hiring Manager, letter"

    if kind == "resume":
        monkeypatch.setattr(tailor, "tailor_resume", generate)
        run = tailor.run_tailoring
        column = "tailored_resume_path"
    else:
        queue.execute("UPDATE jobs SET tailored_resume_path=?", (str(master),))
        queue.commit()
        monkeypatch.setattr(cover_letter, "generate_cover_letter", generate)
        run = cover_letter.run_cover_letters
        column = "cover_letter_path"
    with pytest.raises(KeyboardInterrupt):
        run(limit=2)
    assert queue.execute(f"SELECT COUNT(*) FROM jobs WHERE {column} LIKE '%.pdf'").fetchone()[0] == 1
    assert not queue.in_transaction
