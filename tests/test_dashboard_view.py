from __future__ import annotations

import sqlite3
from pathlib import Path

from divapply import view


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
            score_reasoning TEXT
        )
        """
    )
    conn.execute(
        """
        INSERT INTO jobs (
            url, title, salary, description, location, site, strategy,
            full_description, application_url, detail_error, fit_score, score_reasoning
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            "https://example.com/job",
            "Software Engineer",
            "$100k",
            "Short posting",
            "Logan, UT",
            "RBC",
            "direct",
            "Build accessible tools for job search workflows.",
            "https://example.com/apply",
            None,
            8,
            "Python, accessibility\nStrong local fit.",
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
    assert 'aria-pressed="true"' in html
    assert 'role="status" aria-live="polite"' in html
    assert 'type="search"' in html
    assert 'target="_blank" rel="noopener noreferrer"' in html


def test_dashboard_uses_contrast_safe_brand_accents(tmp_path, monkeypatch):
    conn = _dashboard_db()
    monkeypatch.setattr(view, "get_connection", lambda: conn)

    view.generate_dashboard(str(tmp_path / "dashboard.html"))
    html = (tmp_path / "dashboard.html").read_text(encoding="utf-8")

    assert 'class="site-name" style="border-color:#003168"' in html
    assert 'style="color:#003168"' not in html
    assert "grid-template-columns: repeat(auto-fill, minmax(min(100%, 380px), 1fr))" in html
    assert "@media (prefers-reduced-motion: reduce)" in html


def test_dashboard_does_not_link_unsafe_saved_urls(tmp_path, monkeypatch):
    conn = _dashboard_db()
    conn.execute(
        """
        INSERT INTO jobs (
            url, title, salary, description, location, site, strategy,
            full_description, application_url, detail_error, fit_score, score_reasoning
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
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
