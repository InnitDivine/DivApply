from __future__ import annotations

import hashlib
import sqlite3
from pathlib import Path

import pytest

from divapply import config
from divapply.apply import launcher
from divapply.database import archive_job
from divapply.scoring import cover_letter, tailor


def test_v126_resume_location_uses_target_market_without_changing_legal_address() -> None:
    profile = {
        "personal": {
            "address": "100 Example Street",
            "city": "Exampletown",
            "province_state": "YY",
            "postal_code": "00000",
        },
        "resume_locations": {
            "destination": {
                "use_for_resume_header": True,
                "city": "Sample City",
                "province_state": "ZZ",
                "match_patterns": ["ZZ"],
            }
        },
    }

    adjusted = config.profile_for_job_resume_location(
        profile,
        {"location": "Nearby City, ZZ"},
    )

    assert adjusted["personal"]["city"] == "Sample City"
    assert adjusted["personal"]["province_state"] == "ZZ"
    assert adjusted["personal"]["address"] == "100 Example Street"
    assert adjusted["personal"]["postal_code"] == "00000"
    assert profile["personal"]["city"] == "Exampletown"


def test_v126_resume_location_keeps_current_market_header() -> None:
    profile = {
        "personal": {"city": "Exampletown", "province_state": "YY"},
        "resume_locations": {
            "destination": {
                "use_for_resume_header": True,
                "city": "Sample City",
                "province_state": "ZZ",
                "match_patterns": ["ZZ"],
            }
        },
    }

    adjusted = config.profile_for_job_resume_location(profile, {"location": "Exampletown, YY"})

    assert adjusted["personal"] == profile["personal"]


def test_v126_resume_location_patterns_use_token_boundaries() -> None:
    target = {
        "city": "Sample City",
        "province_state": "YY",
        "match_patterns": ["ZZ"],
    }

    assert config.job_matches_application_address({"location": "Nearby, ZZ"}, target)
    assert not config.job_matches_application_address(
        {"location": "Fizziness, Sample State"},
        target,
    )


def test_v127_resume_location_overlays_exact_document_availability() -> None:
    profile = {
        "personal": {"city": "Exampletown", "province_state": "YY"},
        "resume_locations": {
            "destination": {
                "use_for_resume_header": True,
                "city": "Sample City",
                "province_state": "ZZ",
                "match_patterns": ["ZZ"],
                "availability_statement": "Available for full-time work.",
            }
        },
    }

    adjusted = config.profile_for_job_resume_location(
        profile,
        {"location": "Nearby City, ZZ", "market_label": "Destination market"},
    )

    assert adjusted["resume_availability_statement"] == "Available for full-time work."
    assert "resume_availability_statement" not in profile


def _jobs() -> list[dict[str, object]]:
    common = {
        "title": "Support Analyst",
        "company": "Example Co",
        "site": "Indeed",
        "location": "Remote",
        "fit_score": 9,
        "full_description": "Support internal users and document technical incidents. " * 5,
        "cover_letter_path": None,
        "cover_attempts": 0,
        "tailored_resume_path": None,
        "tailor_attempts": 0,
        "discovered_at": "2026-01-01",
        "application_mode": "active",
        "source_verification": "official",
    }
    return [
        common | {"url": "https://jobs.example.test/posting/one"},
        common | {"url": "https://jobs.example.test/posting/two"},
    ]


def _artifact_db(jobs: list[dict[str, object]]) -> sqlite3.Connection:
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.execute(
        """
        CREATE TABLE jobs (
            url TEXT PRIMARY KEY,
            title TEXT,
            company TEXT,
            site TEXT,
            location TEXT,
            fit_score INTEGER,
            full_description TEXT,
            tailored_resume_path TEXT,
            tailored_at TEXT,
            tailor_attempts INTEGER DEFAULT 0,
            cover_letter_path TEXT,
            cover_letter_at TEXT,
            cover_attempts INTEGER DEFAULT 0,
            discovered_at TEXT,
            apply_status TEXT,
            archived_at TEXT,
            application_mode TEXT,
            source_verification TEXT,
            availability_state TEXT DEFAULT 'open',
            archive_reason TEXT
        )
        """
    )
    conn.executemany(
        """
        INSERT INTO jobs (
            url, title, company, site, location, fit_score, full_description,
            tailored_resume_path, tailor_attempts, cover_letter_path, cover_attempts,
            discovered_at, application_mode, source_verification
        ) VALUES (
            :url, :title, :company, :site, :location, :fit_score, :full_description,
            :tailored_resume_path, :tailor_attempts, :cover_letter_path, :cover_attempts,
            :discovered_at, :application_mode, :source_verification
        )
        """,
        jobs,
    )
    conn.commit()
    return conn


def test_job_artifact_stem_is_stable_and_job_unique() -> None:
    from divapply.artifacts import job_artifact_stem

    first, second = _jobs()
    first_stem = job_artifact_stem(first)

    assert first_stem == job_artifact_stem(dict(first))
    assert first_stem != job_artifact_stem(second)
    assert first_stem.endswith(hashlib.sha256(str(first["url"]).encode()).hexdigest())
    assert first_stem.startswith("Indeed_Support_Analyst--")


def test_same_title_jobs_generate_distinct_resume_and_cover_files(tmp_path, monkeypatch) -> None:
    jobs = _jobs()
    conn = _artifact_db(jobs)
    resume_source = tmp_path / "resume.txt"
    resume_source.write_text("source resume", encoding="utf-8")
    tailored_dir = tmp_path / "tailored"
    cover_dir = tmp_path / "cover"

    monkeypatch.setattr(tailor, "RESUME_PATH", resume_source)
    monkeypatch.setattr(tailor, "TAILORED_DIR", tailored_dir)
    monkeypatch.setattr(tailor, "load_profile", lambda: {})
    monkeypatch.setattr(tailor, "get_connection", lambda: conn)
    monkeypatch.setattr(tailor, "get_jobs_by_stage", lambda **_kwargs: [dict(job) for job in jobs])
    monkeypatch.setattr(
        tailor,
        "tailor_resume",
        lambda _resume, job, _profile, **_kwargs: (
            f"tailored for {job['url']}",
            {"status": "approved", "attempts": 1},
        ),
    )

    monkeypatch.setattr(cover_letter, "TAILORED_DIR", tailored_dir)
    monkeypatch.setattr(cover_letter, "COVER_LETTER_DIR", cover_dir)
    monkeypatch.setattr(cover_letter, "load_profile", lambda: {})
    monkeypatch.setattr(cover_letter, "get_connection", lambda: conn)
    monkeypatch.setattr(
        cover_letter,
        "generate_cover_letter",
        lambda _resume, job, _profile, **_kwargs: f"cover for {job['url']}",
    )
    monkeypatch.setattr(
        cover_letter,
        "_read_tailored_resume_text",
        lambda job: Path(job["tailored_resume_path"]).read_text(encoding="utf-8"),
    )

    from divapply.scoring import pdf

    def fake_convert_to_pdf(source: Path) -> Path:
        destination = source.with_suffix(".pdf")
        destination.write_text(source.read_text(encoding="utf-8"), encoding="utf-8")
        return destination

    monkeypatch.setattr(pdf, "convert_to_pdf", fake_convert_to_pdf)

    tailored_result = tailor.run_tailoring()
    cover_result = cover_letter.run_cover_letters()

    rows = conn.execute(
        "SELECT url, tailored_resume_path, cover_letter_path FROM jobs ORDER BY url"
    ).fetchall()
    resume_paths = [Path(row["tailored_resume_path"]) for row in rows]
    cover_paths = [Path(row["cover_letter_path"]) for row in rows]

    assert tailored_result["approved"] == 2
    assert cover_result["generated"] == 2
    assert len(set(resume_paths)) == 2
    assert len(set(cover_paths)) == 2
    for row, resume_path, cover_path in zip(rows, resume_paths, cover_paths, strict=True):
        assert row["url"] in resume_path.read_text(encoding="utf-8")
        assert row["url"] in cover_path.read_text(encoding="utf-8")


def test_warning_approved_tailor_persists_text_when_inline_pdf_fails(tmp_path, monkeypatch) -> None:
    job = _jobs()[0]
    conn = _artifact_db([job])
    resume_source = tmp_path / "resume.txt"
    resume_source.write_text("source resume", encoding="utf-8")
    tailored_dir = tmp_path / "tailored"

    monkeypatch.setattr(tailor, "RESUME_PATH", resume_source)
    monkeypatch.setattr(tailor, "TAILORED_DIR", tailored_dir)
    monkeypatch.setattr(tailor, "load_profile", lambda: {})
    monkeypatch.setattr(tailor, "get_connection", lambda: conn)
    monkeypatch.setattr(tailor, "get_jobs_by_stage", lambda **_kwargs: [dict(job)])
    monkeypatch.setattr(
        tailor,
        "tailor_resume",
        lambda *_args, **_kwargs: (
            "warning-approved resume",
            {"status": "approved_with_judge_warning", "attempts": 4},
        ),
    )
    from divapply.scoring import pdf
    monkeypatch.setattr(
        pdf,
        "convert_to_pdf",
        lambda _path: (_ for _ in ()).throw(RuntimeError("browser missing")),
    )

    result = tailor.run_tailoring()
    row = conn.execute("SELECT tailored_resume_path FROM jobs WHERE url = ?", (job["url"],)).fetchone()

    assert result["approved"] == 1
    assert row["tailored_resume_path"].endswith(".txt")
    assert Path(row["tailored_resume_path"]).read_text(encoding="utf-8") == "warning-approved resume"


def test_strict_judge_failure_keeps_review_files_without_db_pointer(
    tmp_path, monkeypatch
) -> None:
    job = _jobs()[0]
    conn = _artifact_db([job])
    resume_source = tmp_path / "resume.txt"
    resume_source.write_text("source resume", encoding="utf-8")
    tailored_dir = tmp_path / "tailored"

    monkeypatch.setattr(tailor, "RESUME_PATH", resume_source)
    monkeypatch.setattr(tailor, "TAILORED_DIR", tailored_dir)
    monkeypatch.setattr(tailor, "load_profile", lambda: {})
    monkeypatch.setattr(tailor, "get_connection", lambda: conn)
    monkeypatch.setattr(tailor, "get_jobs_by_stage", lambda **_kwargs: [dict(job)])
    monkeypatch.setattr(
        tailor,
        "tailor_resume",
        lambda *_args, **_kwargs: (
            "review-only resume",
            {"status": "failed_judge", "attempts": 4, "judge": {"issues": "review"}},
        ),
    )

    result = tailor.run_tailoring(validation_mode="strict")
    row = conn.execute(
        "SELECT tailored_resume_path FROM jobs WHERE url = ?", (job["url"],)
    ).fetchone()

    assert result["approved"] == 0
    assert result["failed"] == 1
    assert row["tailored_resume_path"] is None
    assert len(list(tailored_dir.glob("*.txt"))) == 2
    assert len(list(tailored_dir.glob("*_REPORT.json"))) == 1


def test_valid_cover_persists_text_fallback_when_inline_pdf_fails(tmp_path, monkeypatch) -> None:
    job = _jobs()[0] | {"tailored_resume_path": str(tmp_path / "tailored.pdf")}
    conn = _artifact_db([job])
    resume_source = tmp_path / "resume.txt"
    resume_source.write_text("source resume", encoding="utf-8")
    cover_dir = tmp_path / "cover"

    monkeypatch.setattr(cover_letter, "COVER_LETTER_DIR", cover_dir)
    monkeypatch.setattr(cover_letter, "_read_tailored_resume_text", lambda _job: "source resume")
    monkeypatch.setattr(cover_letter, "load_profile", lambda: {})
    monkeypatch.setattr(cover_letter, "get_connection", lambda: conn)
    monkeypatch.setattr(
        cover_letter,
        "generate_cover_letter",
        lambda *_args, **_kwargs: "Dear Hiring Manager,\n\nVerified facts.\n\nJane",
    )
    from divapply.scoring import pdf
    monkeypatch.setattr(
        pdf,
        "convert_to_pdf",
        lambda _path: (_ for _ in ()).throw(RuntimeError("browser missing")),
    )

    result = cover_letter.run_cover_letters()
    row = conn.execute(
        "SELECT cover_letter_path FROM jobs WHERE url = ?", (job["url"],)
    ).fetchone()

    assert result["generated"] == 1
    assert result["errors"] == 0
    assert row["cover_letter_path"].endswith(".txt")
    assert Path(row["cover_letter_path"]).exists()


def test_cover_uses_job_specific_address_for_generation_and_pdf(tmp_path, monkeypatch) -> None:
    job = _jobs()[0] | {
        "location": "Sample City, ZZ",
        "tailored_resume_path": str(tmp_path / "tailored.pdf"),
    }
    conn = _artifact_db([job])
    resume_source = tmp_path / "resume.txt"
    resume_source.write_text("source resume", encoding="utf-8")
    cover_dir = tmp_path / "cover"
    profile = {
        "personal": {"city": "Exampletown", "province_state": "YY"},
        "application_addresses": {
            "sample_market": {
                "is_current_legal_residence": True,
                "city": "Sample City",
                "province_state": "ZZ",
            },
        },
    }
    seen: list[tuple[str, str]] = []

    monkeypatch.setattr(cover_letter, "COVER_LETTER_DIR", cover_dir)
    monkeypatch.setattr(cover_letter, "_read_tailored_resume_text", lambda _job: "source resume")
    monkeypatch.setattr(cover_letter, "load_profile", lambda: profile)
    monkeypatch.setattr(cover_letter, "get_connection", lambda: conn)

    def fake_generate(_resume, _job, job_profile, **_kwargs) -> str:
        personal = job_profile["personal"]
        seen.append((personal["city"], personal["province_state"]))
        return "Dear Hiring Manager,\n\nVerified facts.\n\nJane"

    monkeypatch.setattr(cover_letter, "generate_cover_letter", fake_generate)
    from divapply.scoring import pdf

    def fake_pdf(source: Path, *, profile: dict) -> Path:
        personal = profile["personal"]
        seen.append((personal["city"], personal["province_state"]))
        destination = source.with_suffix(".pdf")
        destination.write_text("pdf", encoding="utf-8")
        return destination

    monkeypatch.setattr(pdf, "convert_to_pdf", fake_pdf)

    result = cover_letter.run_cover_letters()

    assert result["generated"] == 1
    assert seen == [("Sample City", "ZZ"), ("Sample City", "ZZ")]


def test_cover_does_not_persist_or_leave_artifact_after_concurrent_archive(
    tmp_path, monkeypatch
) -> None:
    job = _jobs()[0] | {"tailored_resume_path": str(tmp_path / "tailored.pdf")}
    conn = _artifact_db([job])
    resume_source = tmp_path / "resume.txt"
    resume_source.write_text("source resume", encoding="utf-8")
    cover_dir = tmp_path / "cover"

    monkeypatch.setattr(cover_letter, "COVER_LETTER_DIR", cover_dir)
    monkeypatch.setattr(cover_letter, "_read_tailored_resume_text", lambda _job: "source resume")
    monkeypatch.setattr(cover_letter, "load_profile", lambda: {})
    monkeypatch.setattr(cover_letter, "get_connection", lambda: conn)

    def archive_during_generation(*_args, **_kwargs) -> str:
        conn.execute(
            "UPDATE jobs SET archived_at = '2026-07-12' WHERE url = ?", (job["url"],)
        )
        conn.commit()
        return "Dear Hiring Manager,\n\nVerified facts.\n\nJane"

    monkeypatch.setattr(cover_letter, "generate_cover_letter", archive_during_generation)
    from divapply.scoring import pdf

    def fake_pdf(source: Path, **_kwargs) -> Path:
        destination = source.with_suffix(".pdf")
        destination.write_text("pdf", encoding="utf-8")
        return destination

    monkeypatch.setattr(pdf, "convert_to_pdf", fake_pdf)

    result = cover_letter.run_cover_letters()
    row = conn.execute(
        "SELECT cover_letter_path FROM jobs WHERE url = ?", (job["url"],)
    ).fetchone()

    assert result["generated"] == 0
    assert row["cover_letter_path"] is None
    assert list(cover_dir.glob("*")) == []


def test_tailor_does_not_persist_or_leave_artifact_after_concurrent_archive(
    tmp_path, monkeypatch
) -> None:
    job = _jobs()[0]
    conn = _artifact_db([job])
    resume_source = tmp_path / "resume.txt"
    resume_source.write_text("source resume", encoding="utf-8")
    tailored_dir = tmp_path / "tailored"

    monkeypatch.setattr(tailor, "RESUME_PATH", resume_source)
    monkeypatch.setattr(tailor, "TAILORED_DIR", tailored_dir)
    monkeypatch.setattr(tailor, "load_profile", lambda: {})
    monkeypatch.setattr(tailor, "get_connection", lambda: conn)
    monkeypatch.setattr(tailor, "get_jobs_by_stage", lambda **_kwargs: [dict(job)])

    def archive_during_tailor(*_args, **_kwargs):
        conn.execute(
            "UPDATE jobs SET archived_at = '2026-07-12' WHERE url = ?", (job["url"],)
        )
        conn.commit()
        return "approved resume", {"status": "approved", "attempts": 1}

    monkeypatch.setattr(tailor, "tailor_resume", archive_during_tailor)
    from divapply.scoring import pdf

    def fake_pdf(source: Path, **_kwargs) -> Path:
        destination = source.with_suffix(".pdf")
        destination.write_text("pdf", encoding="utf-8")
        return destination

    monkeypatch.setattr(pdf, "convert_to_pdf", fake_pdf)

    result = tailor.run_tailoring()
    row = conn.execute(
        "SELECT tailored_resume_path FROM jobs WHERE url = ?", (job["url"],)
    ).fetchone()

    assert result["approved"] == 0
    assert row["tailored_resume_path"] is None
    assert list(tailored_dir.glob("*")) == []


def test_shared_legacy_artifact_is_rejected_before_run_staging(tmp_path, monkeypatch) -> None:
    from divapply.artifacts import ArtifactCollisionError, ensure_job_artifacts_unshared

    conn = _artifact_db(_jobs())
    shared = tmp_path / "Indeed_Support.pdf"
    conn.execute("UPDATE jobs SET tailored_resume_path = ?", (str(shared),))
    conn.commit()
    job = dict(conn.execute("SELECT * FROM jobs ORDER BY url LIMIT 1").fetchone())

    with pytest.raises(ArtifactCollisionError, match="shared by another active job"):
        ensure_job_artifacts_unshared(job, conn=conn)

    monkeypatch.setattr(launcher, "get_connection", lambda: conn)
    monkeypatch.setattr(
        launcher,
        "_prepare_worker_run",
        lambda *_args, **_kwargs: pytest.fail("staging ran before artifact collision check"),
    )
    with pytest.raises(ArtifactCollisionError, match="shared by another active job"):
        launcher.run_job(job, port=9222)


def test_archive_keeps_shared_artifact_until_last_active_reference(tmp_path, monkeypatch) -> None:
    jobs = _jobs()
    conn = _artifact_db(jobs)
    tailored_dir = tmp_path / "tailored"
    cover_dir = tmp_path / "cover"
    tailored_dir.mkdir()
    cover_dir.mkdir()
    monkeypatch.setattr(config, "TAILORED_DIR", tailored_dir)
    monkeypatch.setattr(config, "COVER_LETTER_DIR", cover_dir)
    shared = tailored_dir / "Indeed_Support.pdf"
    shared.write_text("shared legacy resume", encoding="utf-8")
    conn.execute("UPDATE jobs SET tailored_resume_path = ?", (str(shared),))
    conn.commit()

    assert archive_job(str(jobs[0]["url"]), conn=conn) is True
    assert shared.exists()

    assert archive_job(str(jobs[1]["url"]), conn=conn) is True
    assert not shared.exists()
