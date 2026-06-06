from __future__ import annotations

from divapply import config
from divapply.database import close_connection, init_db
from divapply.discovery import smartextract


def test_smartextract_site_loader_treats_empty_yaml_as_no_sites(tmp_path, monkeypatch) -> None:
    user_config = tmp_path / "user"
    user_config.mkdir()
    (user_config / "sites.yaml").write_text("", encoding="utf-8")

    monkeypatch.setattr(config, "USER_CONFIG_DIR", user_config)
    monkeypatch.setattr(config, "CONFIG_DIR", tmp_path / "package")

    assert smartextract.load_sites() == []


def test_smartextract_stores_company_for_direct_site_jobs(tmp_path) -> None:
    db_path = tmp_path / "divapply.db"
    conn = init_db(db_path)

    smartextract._store_jobs_filtered(
        conn,
        [
            {
                "url": "https://loganutah.applicantpro.com/jobs/1",
                "title": "IT Support Technician",
                "company": "City of Logan",
                "location": "Logan, UT",
                "description": "Local IT support role",
            }
        ],
        site="City of Logan",
        strategy="unit",
        accept_locs=["logan"],
        reject_locs=[],
        filter_rules={},
    )

    row = conn.execute("SELECT company FROM jobs WHERE url = ?", ("https://loganutah.applicantpro.com/jobs/1",)).fetchone()

    assert row["company"] == "City of Logan"
    close_connection(db_path)
