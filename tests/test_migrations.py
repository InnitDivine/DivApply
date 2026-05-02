from __future__ import annotations

from divapply.database import close_connection, init_db


def test_init_db_sets_schema_user_version(tmp_path) -> None:
    db_path = tmp_path / "divapply.db"
    conn = init_db(db_path)

    version = conn.execute("PRAGMA user_version").fetchone()[0]
    event_table = conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name='application_events'"
    ).fetchone()

    assert version >= 3
    assert event_table is not None
    close_connection(db_path)
