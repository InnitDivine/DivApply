from __future__ import annotations

from divapply.database import (
    close_connection,
    count_jobs_by_stage,
    get_jobs_by_stage,
    init_db,
)


LONG_DESCRIPTION = "Responsibilities and minimum qualifications for this role. " * 8


def test_pending_stage_count_and_selection_share_one_policy(tmp_path) -> None:
    db_path = tmp_path / "divapply.db"
    conn = init_db(db_path)
    rows = [
        ("score-ready", LONG_DESCRIPTION, None, None, 0, None, None, 0, None),
        ("score-future", LONG_DESCRIPTION, None, None, 1, "2099-01-01", None, 0, None),
        ("score-exhausted", LONG_DESCRIPTION, None, None, 5, None, None, 0, None),
        ("score-short", "Metadata", None, None, 0, None, None, 0, None),
        ("score-archived", LONG_DESCRIPTION, None, None, 0, None, None, 0, "2026-01-01"),
        ("tailor-ready", LONG_DESCRIPTION, 8, None, 0, None, None, 0, None),
        ("tailor-low", LONG_DESCRIPTION, 6, None, 0, None, None, 0, None),
        ("tailor-exhausted", LONG_DESCRIPTION, 8, None, 0, None, None, 5, None),
        ("cover-ready", LONG_DESCRIPTION, 9, "resume.pdf", 0, None, None, 0, None),
        ("cover-done", LONG_DESCRIPTION, 8, "resume.pdf", 0, None, "cover.pdf", 0, None),
        ("cover-exhausted", LONG_DESCRIPTION, 8, "resume.pdf", 0, None, None, 5, None),
    ]
    conn.executemany(
        """
        INSERT INTO jobs (
            url, title, full_description, fit_score, tailored_resume_path,
            score_attempts, score_retry_at, cover_letter_path, cover_attempts,
            archived_at, discovered_at, tailor_attempts
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, '2026-01-01', ?)
        """,
        [
            (
                f"https://example.com/{name}",
                name,
                description,
                score,
                resume,
                score_attempts,
                retry_at,
                cover,
                cover_attempts,
                archived_at,
                5 if name == "tailor-exhausted" else 0,
            )
            for (
                name,
                description,
                score,
                resume,
                score_attempts,
                retry_at,
                cover,
                cover_attempts,
                archived_at,
            ) in rows
        ],
    )
    conn.commit()

    expected = {
        "pending_score": {"score-ready"},
        "pending_tailor": {"tailor-ready"},
        "pending_cover": {"cover-ready"},
    }
    for stage, expected_titles in expected.items():
        selected = get_jobs_by_stage(
            conn=conn,
            stage=stage,
            min_score=7,
            limit=0,
        )
        assert {row["title"] for row in selected} == expected_titles
        assert count_jobs_by_stage(conn=conn, stage=stage, min_score=7) == len(selected)

    assert (
        get_jobs_by_stage(
            conn=conn,
            stage="pending_cover",
            min_score=7,
            limit=1,
        )[0]["title"]
        == "cover-ready"
    )
    close_connection(db_path)
