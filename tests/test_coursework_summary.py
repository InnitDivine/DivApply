from __future__ import annotations

from pathlib import Path

from divapply.database import (
    append_coursework,
    close_connection,
    get_coursework_summary,
    init_db,
    replace_coursework,
)


def test_coursework_summary_excludes_raw_text(tmp_path: Path) -> None:
    db_path = tmp_path / "divapply.db"
    conn = init_db(db_path)
    replace_coursework(
        [
            {
                "school": "Example College",
                "course_title": "Intro to Data",
                "subject_area": "Data",
                "source": "fake_transcript.txt",
                "skills": ["statistics", "research literacy"],
                "raw_text": "private transcript text must not appear",
            }
        ],
        conn=conn,
    )

    summary = get_coursework_summary(conn)
    close_connection(db_path)

    assert summary["row_count"] == 1
    assert summary["schools"] == ["Example College"]
    assert summary["subject_areas"] == ["Data"]
    assert summary["import_sources"] == ["fake_transcript.txt"]
    assert "statistics" in summary["inferred_skills"]
    assert "private transcript text must not appear" not in str(summary)


def test_append_coursework_keeps_prior_rows(tmp_path: Path) -> None:
    db_path = tmp_path / "divapply.db"
    conn = init_db(db_path)
    # Wipe the bundled seed rows so the assertions only see what this test adds.
    replace_coursework([], conn=conn)

    replace_coursework(
        [
            {
                "school": "First College",
                "course_code": "DATA 101",
                "course_title": "Intro to Data",
                "term": "Fall 2024",
                "source": "first_transcript.txt",
            }
        ],
        conn=conn,
    )

    result = append_coursework(
        [
            {
                "school": "Second University",
                "course_code": "BIO 200",
                "course_title": "Microbiology",
                "term": "Spring 2025",
                "source": "second_transcript.txt",
            }
        ],
        conn=conn,
    )

    summary = get_coursework_summary(conn)
    close_connection(db_path)

    assert result == {"inserted": 1, "skipped": 0}
    assert summary["row_count"] == 2
    assert set(summary["schools"]) == {"First College", "Second University"}
    assert set(summary["import_sources"]) == {"first_transcript.txt", "second_transcript.txt"}


def test_append_coursework_skips_exact_duplicates(tmp_path: Path) -> None:
    db_path = tmp_path / "divapply.db"
    conn = init_db(db_path)
    replace_coursework([], conn=conn)

    entry = {
        "school": "Example College",
        "course_code": "DATA 101",
        "course_title": "Intro to Data",
        "term": "Fall 2024",
    }

    append_coursework([entry], conn=conn)
    second = append_coursework([entry, {**entry, "course_code": "data 101 ", "term": "FALL 2024"}], conn=conn)

    summary = get_coursework_summary(conn)
    close_connection(db_path)

    # Both passes refer to the same (school, course_code, course_title, term)
    # tuple after normalization, so nothing new should land in the table.
    assert second == {"inserted": 0, "skipped": 2}
    assert summary["row_count"] == 1

