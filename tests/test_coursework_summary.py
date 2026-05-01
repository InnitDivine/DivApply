from __future__ import annotations

from pathlib import Path

from divapply.database import close_connection, get_coursework_summary, init_db, replace_coursework


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

