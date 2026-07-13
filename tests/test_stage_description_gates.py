from __future__ import annotations

from divapply import pipeline
from divapply.database import MIN_FULL_DESCRIPTION_CHARS, close_connection, init_db
from divapply.scoring import cover_letter, tailor


SHORT_DESCRIPTION = "Metadata snippet."
LONG_DESCRIPTION = "A" * MIN_FULL_DESCRIPTION_CHARS


def _insert_job(conn, url: str, description: str, **overrides) -> None:
    values = {
        "title": "Support Analyst",
        "site": "Example ATS",
        "fit_score": 8,
        "full_description": description,
        "tailored_resume_path": None,
        "cover_letter_path": None,
        "archived_at": None,
        "discovered_at": "2026-06-23",
    }
    values.update(overrides)
    conn.execute(
        """
        INSERT INTO jobs (
            url, title, site, fit_score, full_description,
            tailored_resume_path, cover_letter_path, archived_at, discovered_at
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            url,
            values["title"],
            values["site"],
            values["fit_score"],
            values["full_description"],
            values["tailored_resume_path"],
            values["cover_letter_path"],
            values["archived_at"],
            values["discovered_at"],
        ),
    )


def test_streaming_pending_counts_require_meaningful_descriptions(tmp_path, monkeypatch) -> None:
    db_path = tmp_path / "divapply.db"
    conn = init_db(db_path)
    _insert_job(conn, "https://example.com/short-score", SHORT_DESCRIPTION, fit_score=None)
    _insert_job(conn, "https://example.com/full-score", LONG_DESCRIPTION, fit_score=None)
    _insert_job(conn, "https://example.com/short-tailor", SHORT_DESCRIPTION, fit_score=8)
    _insert_job(conn, "https://example.com/full-tailor", LONG_DESCRIPTION, fit_score=8)
    _insert_job(conn, "https://example.com/archived-score", LONG_DESCRIPTION, fit_score=None, archived_at="2026-07-12")
    _insert_job(conn, "https://example.com/archived-tailor", LONG_DESCRIPTION, fit_score=8, archived_at="2026-07-12")
    conn.commit()
    monkeypatch.setattr(pipeline, "get_connection", lambda: conn)

    assert pipeline._count_pending("score") == 1
    assert pipeline._count_pending("tailor", min_score=7) == 1
    close_connection(db_path)


def test_targeted_tailor_skips_short_metadata_descriptions(tmp_path, monkeypatch) -> None:
    db_path = tmp_path / "divapply.db"
    conn = init_db(db_path)
    resume_path = tmp_path / "resume.txt"
    resume_path.write_text("Resume text", encoding="utf-8")
    _insert_job(conn, "https://example.com/short-tailor", SHORT_DESCRIPTION, fit_score=8)
    conn.commit()
    monkeypatch.setattr(tailor, "get_connection", lambda: conn)
    monkeypatch.setattr(tailor, "load_profile", lambda: {})
    monkeypatch.setattr(tailor, "RESUME_PATH", resume_path)
    monkeypatch.setattr(
        tailor,
        "tailor_resume",
        lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("short description should not tailor")),
    )

    result = tailor.run_tailoring(target_url="https://example.com/short-tailor")

    assert result == {"approved": 0, "failed": 0, "errors": 0, "elapsed": 0.0}
    close_connection(db_path)


def test_cover_letters_skip_short_metadata_descriptions(tmp_path, monkeypatch) -> None:
    db_path = tmp_path / "divapply.db"
    conn = init_db(db_path)
    resume_path = tmp_path / "resume.txt"
    resume_path.write_text("Resume text", encoding="utf-8")
    _insert_job(
        conn,
        "https://example.com/short-cover",
        SHORT_DESCRIPTION,
        fit_score=8,
        tailored_resume_path=str(tmp_path / "resume.pdf"),
        cover_letter_path="",
    )
    conn.commit()
    monkeypatch.setattr(cover_letter, "get_connection", lambda: conn)
    monkeypatch.setattr(cover_letter, "load_profile", lambda: {})
    monkeypatch.setattr(cover_letter, "RESUME_PATH", resume_path)
    monkeypatch.setattr(
        cover_letter,
        "generate_cover_letter",
        lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("short description should not get cover")),
    )

    result = cover_letter.run_cover_letters(target_url="https://example.com/short-cover")

    assert result == {"generated": 0, "errors": 0, "elapsed": 0.0}
    close_connection(db_path)


def test_targeted_tailor_and_cover_skip_archived_jobs(tmp_path, monkeypatch) -> None:
    db_path = tmp_path / "divapply.db"
    conn = init_db(db_path)
    resume_path = tmp_path / "resume.txt"
    resume_path.write_text("Resume text", encoding="utf-8")
    _insert_job(
        conn,
        "https://example.com/archived",
        LONG_DESCRIPTION,
        fit_score=8,
        tailored_resume_path=str(tmp_path / "resume.pdf"),
        cover_letter_path="",
        archived_at="2026-07-12",
    )
    conn.commit()
    for module in (tailor, cover_letter):
        monkeypatch.setattr(module, "get_connection", lambda: conn)
        monkeypatch.setattr(module, "load_profile", lambda: {})
        monkeypatch.setattr(module, "RESUME_PATH", resume_path)

    cover_result = cover_letter.run_cover_letters(target_url="https://example.com/archived")
    conn.execute("UPDATE jobs SET tailored_resume_path = NULL WHERE url = ?", ("https://example.com/archived",))
    conn.commit()
    tailor_result = tailor.run_tailoring(target_url="https://example.com/archived")

    assert cover_result == {"generated": 0, "errors": 0, "elapsed": 0.0}
    assert tailor_result == {"approved": 0, "failed": 0, "errors": 0, "elapsed": 0.0}
    close_connection(db_path)
