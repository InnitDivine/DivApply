from __future__ import annotations

import sqlite3
from pathlib import Path

from divapply.dashboard_data import fetch_dashboard_snapshot
from divapply import view


LONG_DESCRIPTION = "Full job description with responsibilities and minimum qualifications. " * 5


def _dashboard_db() -> sqlite3.Connection:
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.execute(
        """
        CREATE TABLE jobs (
            url TEXT,
            title TEXT,
            salary TEXT,
            description TEXT,
            location TEXT,
            site TEXT,
            strategy TEXT,
            full_description TEXT,
            application_url TEXT,
            detail_error TEXT,
            fit_score INTEGER,
            score_reasoning TEXT,
            tailored_resume_path TEXT,
            cover_letter_path TEXT,
            apply_status TEXT,
            applied_at TEXT,
            apply_error TEXT,
            verification_confidence TEXT,
            archived_at TEXT
        )
        """
    )
    conn.execute(
        """
        INSERT INTO jobs (
            url, title, salary, description, location, site, strategy,
            full_description, application_url, detail_error, fit_score, score_reasoning,
            apply_status, applied_at, archived_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            "https://example.com/job",
            "Software Engineer",
            "$100k",
            "Short posting",
            "Logan, UT",
            "RBC",
            "direct",
            LONG_DESCRIPTION,
            "https://example.com/apply",
            None,
            8,
            "Python, accessibility\nStrong local fit.",
            None,
            None,
            None,
        ),
    )
    conn.commit()
    return conn


def test_generate_dashboard_includes_accessible_controls(tmp_path, monkeypatch):
    conn = _dashboard_db()
    monkeypatch.setattr(view, "get_connection", lambda: conn)

    path = view.generate_dashboard(str(tmp_path / "dashboard.html"))
    html = (tmp_path / "dashboard.html").read_text(encoding="utf-8")

    assert path.endswith("dashboard.html")
    assert '<a class="skip-link" href="#jobs">Skip to jobs</a>' in html
    assert 'aria-label="Job filters"' in html
    assert 'aria-label="Job status"' in html
    assert 'aria-label="Generated documents"' in html
    assert 'aria-pressed="true"' in html
    assert 'role="status" aria-live="polite"' in html
    assert 'type="search"' in html
    assert 'target="_blank" rel="noopener noreferrer"' in html
    assert 'role="list"' in html
    assert 'role="listitem"' in html
    assert 'data-min-score="3"' in html
    assert "3+ Review" in html
    assert 'data-min-score="7"' in html
    assert 'data-search="software engineer rbc logan, ut $100k ready python, accessibility strong local fit.' in html
    assert "card.dataset.search || ''" in html
    assert "card.textContent.toLowerCase()" not in html
    assert "onclick=" not in html
    assert "oninput=" not in html


def test_dashboard_uses_contrast_safe_brand_accents(tmp_path, monkeypatch):
    conn = _dashboard_db()
    monkeypatch.setattr(view, "get_connection", lambda: conn)

    view.generate_dashboard(str(tmp_path / "dashboard.html"))
    html = (tmp_path / "dashboard.html").read_text(encoding="utf-8")

    assert 'class="site-name" style="border-color:#003168"' in html
    assert 'style="color:#003168"' not in html
    assert "grid-template-columns: repeat(auto-fill, minmax(min(100%, 380px), 1fr))" in html
    assert "@media (prefers-reduced-motion: reduce)" in html
    assert "min-height: 2.75rem" in html
    assert ".apply-link, .archive-btn { width: 100%; }" in html
    assert ".state-ready" in html
    assert ".score-reason" in html


def test_dashboard_empty_state_is_accessible(tmp_path, monkeypatch):
    conn = _dashboard_db()
    conn.execute("UPDATE jobs SET fit_score = 4 WHERE url = 'https://example.com/job'")
    conn.commit()
    monkeypatch.setattr(view, "get_connection", lambda: conn)

    path = view.generate_dashboard(str(tmp_path / "dashboard.html"))
    html = Path(path).read_text(encoding="utf-8")

    assert 'class="empty-state" role="status"' in html
    assert "No active scored jobs match the dashboard criteria." in html


def test_dashboard_does_not_link_unsafe_saved_urls(tmp_path, monkeypatch):
    conn = _dashboard_db()
    conn.execute(
        """
        INSERT INTO jobs (
            url, title, salary, description, location, site, strategy,
            full_description, application_url, detail_error, fit_score, score_reasoning,
            apply_status, applied_at, archived_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            "javascript:alert(1)",
            "Unsafe Job",
            "",
            "Short posting",
            "Logan, UT",
            "indeed",
            "direct",
            "Unsafe link test.",
            "http://localhost:8080/apply",
            None,
            8,
            "keywords\nreasoning",
            None,
            None,
            None,
        ),
    )
    conn.commit()
    monkeypatch.setattr(view, "get_connection", lambda: conn)

    path = view.generate_dashboard(str(tmp_path / "dashboard.html"))
    html = Path(path).read_text(encoding="utf-8")

    assert "javascript:alert" not in html
    assert "localhost:8080/apply" not in html
    assert '<span class="job-title">Unsafe Job</span>' in html
    assert 'href="https://example.com/job"' in html


def test_dashboard_shows_archive_button_for_interactive_jobs(tmp_path, monkeypatch):
    conn = _dashboard_db()
    monkeypatch.setattr(view, "get_connection", lambda: conn)

    path = view.generate_dashboard(
        str(tmp_path / "dashboard.html"),
        archive_endpoint="/archive",
        archive_token="test-token",
    )
    html = Path(path).read_text(encoding="utf-8")

    assert 'class="archive-btn"' in html
    assert 'name="token" value="test-token"' in html
    assert 'name="url" value="https://example.com/job"' in html


def test_dashboard_hides_archived_jobs(tmp_path, monkeypatch):
    conn = _dashboard_db()
    conn.execute(
        "UPDATE jobs SET archived_at = '2026-06-13T00:00:00Z' WHERE url = 'https://example.com/job'"
    )
    conn.commit()
    monkeypatch.setattr(view, "get_connection", lambda: conn)

    path = view.generate_dashboard(str(tmp_path / "dashboard.html"))
    html = Path(path).read_text(encoding="utf-8")

    assert "Software Engineer" not in html
    assert "0 active jobs" in html
    assert "1 archived" in html


def test_static_dashboard_does_not_embed_full_description_tail(tmp_path, monkeypatch):
    conn = _dashboard_db()
    conn.execute(
        "UPDATE jobs SET full_description = ? WHERE url = 'https://example.com/job'",
        ("Visible preview. " + ("detail " * 80) + "UNIQUE_FULL_DESCRIPTION_TAIL",),
    )
    conn.commit()
    monkeypatch.setattr(view, "get_connection", lambda: conn)

    path = view.generate_dashboard(str(tmp_path / "dashboard.html"))
    html = Path(path).read_text(encoding="utf-8")

    assert "Visible preview." in html
    assert "UNIQUE_FULL_DESCRIPTION_TAIL" not in html
    assert "Description preview only" in html
    assert '<details class=\'full-desc-details\' data-description-url=' not in html


def test_interactive_dashboard_uses_lazy_description_url(tmp_path, monkeypatch):
    conn = _dashboard_db()
    conn.execute(
        "UPDATE jobs SET full_description = ? WHERE url = 'https://example.com/job'",
        ("Visible preview. " + ("detail " * 80) + "UNIQUE_FULL_DESCRIPTION_TAIL",),
    )
    conn.commit()
    monkeypatch.setattr(view, "get_connection", lambda: conn)

    path = view.generate_dashboard(
        str(tmp_path / "dashboard.html"),
        archive_endpoint="/archive",
        archive_token="test-token",
        description_endpoint="/description",
    )
    html = Path(path).read_text(encoding="utf-8")

    assert "UNIQUE_FULL_DESCRIPTION_TAIL" not in html
    assert "data-description-url=" in html
    assert "/description?token=test-token" in html
    assert "Open to load description." in html
    assert "UNIQUE_FULL_DESCRIPTION_TAIL" not in html


def test_lazy_description_script_is_empty_when_interactive_descriptions_disabled() -> None:
    assert view._lazy_description_script(enabled=False) == ""
    script = view._lazy_description_script(enabled=True)
    assert "fetch(details.dataset.descriptionUrl" in script
    assert "container.dataset.loaded = 'loading'" in script
    assert "container.setAttribute('aria-busy', 'true')" in script
    assert "container.textContent = await response.text()" in script


def test_dashboard_renders_generated_doc_and_apply_states(tmp_path, monkeypatch):
    conn = _dashboard_db()
    conn.execute(
        """
        UPDATE jobs
        SET tailored_resume_path = ?, cover_letter_path = ?,
            apply_status = 'applied', applied_at = '2026-06-20T10:00:00Z',
            verification_confidence = 'high'
        WHERE url = 'https://example.com/job'
        """,
        ("C:/Users/Dearr/.divapply/tailored/private.pdf", "C:/Users/Dearr/.divapply/cover/private.pdf"),
    )
    conn.execute(
        """
        INSERT INTO jobs (
            url, title, salary, description, location, site, strategy,
            full_description, application_url, detail_error, fit_score, score_reasoning,
            apply_status, applied_at, apply_error, archived_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            "https://example.com/manual",
            "Manual ATS Role",
            "",
            "Short posting",
            "Remote",
            "indeed",
            "direct",
            "Manual posting.",
            "https://example.com/manual-apply",
            None,
            7,
            "ATS\nNeeds employer-site application.",
            "manual",
            None,
            None,
            None,
        ),
    )
    conn.execute(
        """
        INSERT INTO jobs (
            url, title, salary, description, location, site, strategy,
            full_description, application_url, detail_error, fit_score, score_reasoning,
            apply_status, applied_at, apply_error, archived_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            "https://example.com/expired",
            "Expired Role",
            "",
            "Short posting",
            "Remote",
            "indeed",
            "direct",
            "",
            "",
            "expired: posting inactive",
            6,
            "Expired\nPosting is no longer active.",
            "failed",
            None,
            "expired: posting appears inactive",
            None,
        ),
    )
    conn.commit()
    monkeypatch.setattr(view, "get_connection", lambda: conn)

    path = view.generate_dashboard(str(tmp_path / "dashboard.html"))
    html = Path(path).read_text(encoding="utf-8")

    assert "Resumes generated" in html
    assert "Cover letters generated" in html
    assert "Marked applied" in html
    assert "Manual apply needed" in html
    assert "Expired or inactive" in html
    assert '<span class="state-pill state-applied">Applied</span>' in html
    assert '<span class="state-pill state-manual">Manual</span>' in html
    assert '<span class="state-pill state-expired">Expired</span>' in html
    assert "Resume ready" in html
    assert "Cover ready" in html
    assert "Verify high" in html
    assert "private.pdf" not in html
    assert "C:/Users/Dearr" not in html
    assert "Description unavailable: expired: posting inactive" in html


def test_dashboard_description_text_returns_full_description(monkeypatch):
    conn = _dashboard_db()
    monkeypatch.setattr(view, "get_connection", lambda: conn)

    status, text = view._dashboard_description_text({"url": "https://example.com/job"})

    assert status == 200
    assert text == LONG_DESCRIPTION


def test_fetch_dashboard_snapshot_shapes_dashboard_read_model():
    conn = _dashboard_db()
    conn.execute(
        """
        INSERT INTO jobs (
            url, title, salary, description, location, site, strategy,
            full_description, application_url, detail_error, fit_score, score_reasoning,
            apply_status, applied_at, archived_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            "https://example.com/archived",
            "Archived Job",
            "",
            "Old posting",
            "Logan, UT",
            "RBC",
            "direct",
            "Already handled.",
            "https://example.com/apply-archived",
            None,
            9,
            "keywords\nreasoning",
            None,
            None,
            "2026-06-13T00:00:00Z",
        ),
    )
    conn.commit()

    snapshot = fetch_dashboard_snapshot(conn)

    assert snapshot.total == 1
    assert snapshot.archived == 1
    assert snapshot.ready == 1
    assert snapshot.scored == 1
    assert snapshot.high_fit == 1
    assert snapshot.tailored == 0
    assert snapshot.with_cover_letter == 0
    assert snapshot.applied == 0
    assert snapshot.manual == 0
    assert snapshot.expired == 0
    assert snapshot.score_dist == {8: 1}
    assert [job["url"] for job in snapshot.jobs] == ["https://example.com/job"]


def test_dashboard_cache_key_changes_after_same_connection_job_update(monkeypatch):
    conn = _dashboard_db()
    monkeypatch.setattr(view, "get_connection", lambda: conn)

    before = view._dashboard_cache_key()
    conn.execute(
        "UPDATE jobs SET archived_at = '2026-06-15T12:00:00Z' WHERE url = 'https://example.com/job'"
    )
    conn.commit()

    assert view._dashboard_cache_key() != before


def test_archive_dashboard_form_redirects_after_success(monkeypatch):
    archived: list[str] = []

    monkeypatch.setattr(view, "archive_job", lambda url: archived.append(url) or True)

    status, message, should_redirect = view._archive_dashboard_form({"url": "https://example.com/job"})

    assert (status, message, should_redirect) == (303, "", True)
    assert archived == ["https://example.com/job"]


def test_archive_dashboard_form_rejects_missing_url(monkeypatch):
    events: list[str] = []

    monkeypatch.setattr(view, "record_reliability_event", lambda category, _message, **_kwargs: events.append(category))

    status, message, should_redirect = view._archive_dashboard_form({})

    assert (status, message, should_redirect) == (400, "Missing job URL.", False)
    assert events == ["dashboard_missing_archive_url"]


def test_archive_dashboard_form_reports_missing_or_archived_job(monkeypatch):
    events: list[tuple[str, dict]] = []

    monkeypatch.setattr(view, "archive_job", lambda _url: False)
    monkeypatch.setattr(
        view,
        "record_reliability_event",
        lambda category, _message, **kwargs: events.append((category, kwargs)),
    )

    status, message, should_redirect = view._archive_dashboard_form({"url": "https://example.com/missing"})

    assert (status, message, should_redirect) == (404, "Job was not found or is already archived.", False)
    assert events[0][0] == "dashboard_archive_not_found"
    assert events[0][1]["context"] == {"url": "https://example.com/missing"}


def test_archive_dashboard_form_handles_archive_exception(monkeypatch):
    events: list[tuple[str, dict]] = []

    def fail_archive(_url: str) -> bool:
        raise RuntimeError("database is locked")

    monkeypatch.setattr(view, "archive_job", fail_archive)
    monkeypatch.setattr(
        view,
        "record_reliability_event",
        lambda category, _message, **kwargs: events.append((category, kwargs)),
    )

    status, message, should_redirect = view._archive_dashboard_form({"url": "https://example.com/job"})

    assert (status, message, should_redirect) == (500, "Archive failed.", False)
    assert events[0][0] == "dashboard_archive_failed"
    assert events[0][1]["severity"] == "error"
    assert events[0][1]["context"] == {
        "url": "https://example.com/job",
        "error": "database is locked",
    }
