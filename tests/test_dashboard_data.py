from __future__ import annotations

from divapply.dashboard_data import fetch_dashboard_snapshot
from divapply.database import close_connection, init_db


def _insert_job(conn, url: str, **overrides) -> None:
    values = {
        "title": "Support Analyst",
        "site": "indeed",
        "full_description": "Help users with technical issues.",
        "application_url": "https://apply.example/job",
        "fit_score": 7,
        "archived_at": None,
        "discovered_at": "2026-01-01",
    }
    values.update(overrides)
    conn.execute(
        """
        INSERT INTO jobs (
            url, title, site, full_description, application_url,
            fit_score, archived_at, discovered_at
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            url,
            values["title"],
            values["site"],
            values["full_description"],
            values["application_url"],
            values["fit_score"],
            values["archived_at"],
            values["discovered_at"],
        ),
    )


def test_dashboard_snapshot_excludes_archived_rows_from_all_active_metrics(tmp_path) -> None:
    db_path = tmp_path / "divapply.db"
    conn = init_db(db_path)
    _insert_job(conn, "https://example.com/active", title="Active", fit_score=7)
    _insert_job(
        conn,
        "https://example.com/archived",
        title="Archived",
        fit_score=10,
        archived_at="2026-06-15T00:00:00+00:00",
    )
    conn.commit()

    snapshot = fetch_dashboard_snapshot(conn)

    assert snapshot.total == 1
    assert snapshot.archived == 1
    assert snapshot.ready == 1
    assert snapshot.scored == 1
    assert snapshot.high_fit == 1
    assert snapshot.score_dist == {7: 1}
    assert [row["title"] for row in snapshot.jobs] == ["Active"]
    assert [(row["site"], row["total"]) for row in snapshot.site_stats] == [("indeed", 1)]
    close_connection(db_path)


def test_dashboard_snapshot_counts_score_boundaries_without_displaying_low_fit_jobs(tmp_path) -> None:
    db_path = tmp_path / "divapply.db"
    conn = init_db(db_path)
    _insert_job(conn, "https://example.com/six", title="Six", fit_score=6)
    _insert_job(conn, "https://example.com/seven", title="Seven", fit_score=7)
    _insert_job(conn, "https://example.com/four", title="Four", fit_score=4)
    conn.commit()

    snapshot = fetch_dashboard_snapshot(conn)

    assert snapshot.scored == 3
    assert snapshot.high_fit == 1
    assert snapshot.score_dist == {7: 1, 6: 1, 4: 1}
    assert [row["title"] for row in snapshot.jobs] == ["Seven", "Six"]
    site = snapshot.site_stats[0]
    assert site["high_fit"] == 1
    assert site["mid_fit"] == 1
    assert site["low_fit"] == 1
    close_connection(db_path)


def test_dashboard_snapshot_ready_requires_description_and_nonempty_application_url(tmp_path) -> None:
    db_path = tmp_path / "divapply.db"
    conn = init_db(db_path)
    _insert_job(conn, "https://example.com/ready", title="Ready")
    _insert_job(conn, "https://example.com/no-description", title="No Description", full_description=None)
    _insert_job(conn, "https://example.com/blank-apply", title="Blank Apply", application_url="")
    conn.commit()

    snapshot = fetch_dashboard_snapshot(conn)

    assert snapshot.total == 3
    assert snapshot.ready == 1
    assert {row["title"] for row in snapshot.jobs} == {"Ready", "No Description", "Blank Apply"}
    close_connection(db_path)


def test_dashboard_snapshot_handles_unscored_and_unknown_site_rows(tmp_path) -> None:
    db_path = tmp_path / "divapply.db"
    conn = init_db(db_path)
    _insert_job(
        conn,
        "https://example.com/unscored",
        title="Unscored",
        site=None,
        fit_score=None,
    )
    conn.commit()

    snapshot = fetch_dashboard_snapshot(conn)

    assert snapshot.scored == 0
    assert snapshot.high_fit == 0
    assert snapshot.score_dist == {}
    assert snapshot.jobs == []
    assert len(snapshot.site_stats) == 1
    assert snapshot.site_stats[0]["site"] is None
    assert snapshot.site_stats[0]["unscored"] == 1
    close_connection(db_path)
