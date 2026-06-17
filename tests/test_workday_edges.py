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


def test_workday_title_include_filter_keeps_target_roles(monkeypatch) -> None:
    employers = {
        "imh": {
            "name": "Intermountain Health",
            "tenant": "imh",
            "site_id": "IntermountainCareers",
            "base_url": "https://imh.wd108.myworkdayjobs.com",
        }
    }
    jobs = [
        {"title": "Patient Service Representative", "location": "Logan", "external_path": "/patient"},
        {"title": "Police Officer", "location": "Logan", "external_path": "/police"},
    ]
    captured = {}

    monkeypatch.setattr(workday, "search_employer", lambda *_args, **_kwargs: list(jobs))
    monkeypatch.setattr(workday, "fetch_details", lambda _emp, selected: selected)

    def fake_store(_conn, selected, _employers):
        captured["titles"] = [job["title"] for job in selected]
        return len(selected), 0

    monkeypatch.setattr(workday, "store_results", fake_store)

    result = workday._process_one(
        "imh",
        employers,
        "patient service representative",
        True,
        ["logan"],
        [],
        include_titles=["patient service"],
    )

    assert result["new"] == 1
    assert captured["titles"] == ["Patient Service Representative"]


def test_process_one_allows_relocation_employer_to_bypass_location_filter(monkeypatch) -> None:
    employers = {
        "sutter_health": {
            "name": "Sutter Health",
            "relocation_ok": True,
        }
    }
    captured = {}

    def fake_search(_key, _emp, _text, **kwargs):
        captured["location_filter"] = kwargs["location_filter"]
        return [{"title": "IT Support", "location": "Sacramento, CA", "external_path": "/job"}]

    monkeypatch.setattr(workday, "search_employer", fake_search)
    monkeypatch.setattr(workday, "fetch_details", lambda _emp, selected: selected)
    monkeypatch.setattr(workday, "store_results", lambda _conn, selected, _employers: (len(selected), 0))

    result = workday._process_one(
        "sutter_health",
        employers,
        "IT support",
        True,
        ["logan"],
        [],
    )

    assert captured["location_filter"] is False
    assert result["new"] == 1


def test_scrape_employers_continues_when_parallel_worker_crashes(monkeypatch) -> None:
    events: list[tuple[str, dict | None]] = []
    employers = {
        "ok": {"name": "OK Employer"},
        "bad": {"name": "Bad Employer"},
    }

    monkeypatch.setattr(workday, "init_db", lambda: None)
    monkeypatch.setattr(
        workday,
        "record_reliability_event",
        lambda category, _message, **kwargs: events.append((category, kwargs.get("context"))),
    )

    def fake_process_one(key, *_args, **_kwargs):
        if key == "bad":
            raise RuntimeError("worker exploded")
        return {"new": 2, "existing": 1, "found": 3}

    monkeypatch.setattr(workday, "_process_one", fake_process_one)

    result = workday.scrape_employers(
        "support",
        employers,
        employer_keys=["ok", "bad"],
        workers=2,
    )

    assert result["new"] == 2
    assert result["existing"] == 1
    assert result["found"] == 3
    assert events == [("workday_worker_crashed", {"employer": "bad", "search_text": "support", "error": "worker exploded"})]
