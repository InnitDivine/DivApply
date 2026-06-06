from __future__ import annotations

from divapply.database import close_connection, init_db
from divapply.discovery import workday


def test_search_employer_paginates_and_filters_locations(monkeypatch) -> None:
    calls: list[tuple[int, int]] = []
    pages = {
        0: {
            "total": 21,
            "jobPostings": [
                {"title": "IT Technician", "locationsText": "Logan, UT", "externalPath": "/job/1"},
                {"title": "Systems Analyst", "locationsText": "Salt Lake City, UT", "externalPath": "/job/2"},
            ],
        },
        20: {
            "total": 21,
            "jobPostings": [
                {"title": "Help Desk", "locationsText": "Remote", "externalPath": "/job/3"},
            ],
        },
    }

    def fake_search(employer: dict, search_text: str, limit: int, offset: int) -> dict:
        calls.append((limit, offset))
        return pages[offset]

    monkeypatch.setattr(workday, "workday_search", fake_search)

    jobs = workday.search_employer(
        "cache",
        {"name": "Cache Employer"},
        "it",
        accept_locs=["logan"],
        reject_locs=["salt lake"],
    )

    assert calls == [(20, 0), (20, 20)]
    assert [job["title"] for job in jobs] == ["IT Technician", "Help Desk"]


def test_fetch_one_detail_records_error_without_leaking_prior_fields(monkeypatch) -> None:
    def fail_detail(employer: dict, external_path: str) -> dict:
        raise RuntimeError("HTTP 500")

    monkeypatch.setattr(workday, "workday_detail", fail_detail)
    job = {"external_path": "/job/1"}

    result = workday._fetch_one_detail({"name": "Cache Employer"}, job)

    assert result["full_description"] == ""
    assert result["apply_url"] == ""
    assert result["detail_error"] == "HTTP 500"


def test_store_results_uses_external_path_fallback_and_short_description_rules(tmp_path) -> None:
    db_path = tmp_path / "divapply.db"
    conn = init_db(db_path)
    long_description = "Local IT support responsibilities. " * 10

    new, existing = workday.store_results(
        conn,
        [
            {
                "title": "IT Support Technician",
                "location": "Logan, UT",
                "external_path": "/job/123",
                "employer_key": "cache",
                "employer_name": "Cache Employer",
                "full_description": long_description,
            },
            {
                "title": "Duplicate IT Support Technician",
                "location": "Logan, UT",
                "external_path": "/job/123",
                "employer_key": "cache",
                "employer_name": "Cache Employer",
                "full_description": "Too short",
            },
        ],
        {"cache": {"base_url": "https://cache.wd1.myworkdayjobs.com", "site_id": "External"}},
    )

    row = conn.execute("SELECT url, description, full_description, detail_scraped_at FROM jobs").fetchone()

    assert (new, existing) == (1, 1)
    assert row["url"] == "https://cache.wd1.myworkdayjobs.com/External/job/123"
    assert row["description"] == long_description[:500]
    assert row["full_description"] == long_description
    assert row["detail_scraped_at"]
    close_connection(db_path)


def test_store_results_skips_external_path_that_overrides_base_host(tmp_path) -> None:
    db_path = tmp_path / "divapply.db"
    conn = init_db(db_path)

    new, existing = workday.store_results(
        conn,
        [
            {
                "title": "Unsafe Job",
                "location": "Logan, UT",
                "external_path": "https://evil.example/job/123",
                "employer_key": "cache",
                "employer_name": "Cache Employer",
                "full_description": "Local IT support responsibilities. " * 10,
            }
        ],
        {"cache": {"base_url": "https://cache.wd1.myworkdayjobs.com", "site_id": "External"}},
    )

    count = conn.execute("SELECT COUNT(*) FROM jobs").fetchone()[0]

    assert (new, existing) == (0, 0)
    assert count == 0
    close_connection(db_path)
