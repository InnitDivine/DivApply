from __future__ import annotations

import builtins

import pytest

from divapply.database import close_connection, init_db
from divapply.discovery import jobspy as jobspy_mod
from divapply.discovery.jobspy import (
    _full_crawl,
    _job_row_passes_filters,
    _location_ok,
    _load_filter_rules,
    _load_location_config,
    _load_title_excludes,
    _row_is_effectively_remote,
    _scrape_with_retry,
    _title_ok,
)


def test_search_config_supports_legacy_and_new_filter_names() -> None:
    cfg = {
        "location": {"accept_patterns": ["Remote"], "reject_patterns": ["onsite only"]},
        "exclude_titles": ["intern"],
        "filters": {
            "title_blacklist": ["director"],
            "company_blacklist": ["BadCo"],
            "required_keywords": ["python"],
            "excluded_keywords": ["clearance"],
            "remote_preference": "remote",
        },
    }

    assert _load_location_config(cfg) == (["Remote"], ["onsite only"])
    assert _load_title_excludes(cfg) == ["intern", "director"]
    rules = _load_filter_rules(cfg)
    expected = {
        "company_blacklist": ["badco"],
        "required_keywords": ["python"],
        "excluded_keywords": ["clearance"],
        "remote_preference": "remote",
    }
    for key, value in expected.items():
        assert rules[key] == value


def test_search_config_derives_accept_terms_from_locations() -> None:
    cfg = {
        "locations": [
            {"location": "Exampletown, UT", "remote": False},
            {"location": "Remote", "remote": True},
        ]
    }

    assert _load_location_config(cfg) == (
        ["Exampletown, UT", "Exampletown", "remote", "anywhere", "united states", "usa"],
        [],
    )


def test_title_excludes_match_terms_not_substrings() -> None:
    assert not _title_ok("Office Manager", ["manager"])
    assert _title_ok("Management Assistant", ["manager"])


def test_job_row_passes_filters_rejects_blacklist_and_missing_required_keyword() -> None:
    rules = {
        "company_blacklist": ["badco"],
        "required_keywords": ["python"],
        "excluded_keywords": ["clearance"],
        "remote_preference": "remote",
    }

    assert _job_row_passes_filters(
        {
            "title": "Python Analyst",
            "company": "GoodCo",
            "location": "Remote",
            "description": "Python reporting role",
            "is_remote": True,
        },
        rules,
    )
    assert not _job_row_passes_filters(
        {
            "title": "Python Analyst",
            "company": "BadCo",
            "location": "Remote",
            "description": "Python reporting role",
            "is_remote": True,
        },
        rules,
    )
    assert not _job_row_passes_filters(
        {
            "title": "Analyst",
            "company": "GoodCo",
            "location": "Remote",
            "description": "Excel reporting role",
            "is_remote": True,
        },
        rules,
    )


def test_fake_remote_onsite_job_does_not_bypass_location_reject() -> None:
    row = {
        "title": "IT Support Specialist II",
        "company": "JD Machine Corp.",
        "location": "Ogden, UT",
        "description": "This position is primarily on-site at our Ogden facility.",
        "is_remote": True,
    }

    assert not _row_is_effectively_remote(row)
    assert not _location_ok(
        row["location"],
        ["Exampletown"],
        ["ogden"],
        allow_unknown=False,
        is_remote=_row_is_effectively_remote(row),
    )


def test_remote_location_text_does_not_bypass_rejected_place() -> None:
    assert not _location_ok(
        "Remote in Idaho",
        ["Exampletown", "cache valley"],
        ["idaho"],
        allow_unknown=False,
    )
    assert _location_ok(
        "Remote",
        ["Exampletown", "cache valley"],
        ["idaho"],
        allow_unknown=False,
    )
    assert not _location_ok(
        "Layton, UT, US (Remote)",
        ["Exampletown", "cache valley"],
        ["layton"],
        allow_unknown=False,
        is_remote=True,
    )


def test_jobspy_runtime_import_is_lazy(monkeypatch) -> None:
    real_import = builtins.__import__

    def fake_import(name, *args, **kwargs):
        if name == "jobspy":
            raise ImportError("missing jobspy")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", fake_import)

    with pytest.raises(RuntimeError, match="python-jobspy is required"):
        _scrape_with_retry({})


def test_customer_service_filter_allows_only_low_hour_side_work() -> None:
    rules = {
        "company_blacklist": [],
        "required_keywords": [],
        "excluded_keywords": [],
        "include_titles": [],
        "customer_service_title_terms": ["customer service"],
        "customer_service_require_part_time": True,
        "customer_service_max_hours_per_week": 12,
        "allow_unknown_location": False,
        "trusted_local_sites": [],
        "remote_preference": "any",
    }

    assert not _job_row_passes_filters(
        {
            "title": "Customer Service Representative",
            "company": "GoodCo",
            "location": "Exampletown, UT",
            "description": "Full-time 40 hours per week",
        },
        rules,
    )
    assert _job_row_passes_filters(
        {
            "title": "Customer Service Representative",
            "company": "GoodCo",
            "location": "Exampletown, UT",
            "description": "Part-time 8 hours per week",
        },
        rules,
    )


def test_full_crawl_reports_board_timing_stats(tmp_path, monkeypatch) -> None:
    pd = pytest.importorskip("pandas")
    db_path = tmp_path / "jobs.db"
    conn = init_db(db_path)

    def fake_scrape(kwargs, max_retries=2):
        sites = kwargs["site_name"]
        return pd.DataFrame(
            [
                {
                    "job_url": f"https://example.com/{site}/job",
                    "title": f"{site} support",
                    "company": "Example Co",
                    "location": "Exampletown, UT",
                    "description": "Part-time support role in Exampletown, UT.",
                    "site": site,
                }
                for site in sites
            ]
        )

    monkeypatch.setattr(jobspy_mod, "_scrape_with_retry", fake_scrape)
    monkeypatch.setattr(jobspy_mod, "init_db", lambda: conn)
    monkeypatch.setattr(jobspy_mod, "get_connection", lambda: conn)

    result = _full_crawl(
        {
            "queries": [{"query": "support", "tier": 1}],
            "locations": [{"label": "Exampletown", "location": "Exampletown, UT"}],
            "location": {"accept_patterns": ["Exampletown"], "reject_patterns": []},
        },
        sites=["indeed", "linkedin"],
        workers=1,
        results_per_site=2,
    )

    assert result["new"] == 2
    assert result["queries"] == 1
    assert set(result["board_stats"]) == {"indeed", "linkedin"}
    assert result["board_stats"]["indeed"]["calls"] == 1
    assert result["board_stats"]["indeed"]["total"] == 1
    assert result["board_stats"]["linkedin"]["calls"] == 1
    assert result["board_stats"]["linkedin"]["total"] == 1

    close_connection(db_path)


def test_full_crawl_scopes_queries_to_location_labels_with_location_fallback(tmp_path, monkeypatch) -> None:
    db_path = tmp_path / "jobs.db"
    conn = init_db(db_path)
    captured: list[tuple[str, str]] = []

    monkeypatch.setattr(jobspy_mod, "init_db", lambda: conn)
    monkeypatch.setattr(jobspy_mod, "get_connection", lambda: conn)

    def fake_run_one(search, *_args, **_kwargs):
        captured.append((search["query"], search["location"]))
        return {"new": 0, "existing": 0, "errors": 0, "board_stats": {}}

    monkeypatch.setattr(jobspy_mod, "_run_one_search", fake_run_one)

    result = _full_crawl(
        {
            "queries": [
                {"query": "local help desk", "tier": 1, "location_labels": ["Exampletown, UT"]},
                {"query": "remote support", "tier": 1, "location_labels": ["Remote"]},
                {"query": "unscoped fallback", "tier": 2},
            ],
            "locations": [
                {"location": "Exampletown, UT"},
                {"label": "Remote", "location": "Remote", "remote": True},
            ],
        },
        sites=["indeed"],
        workers=1,
    )

    assert captured == [
        ("local help desk", "Exampletown, UT"),
        ("remote support", "Remote"),
        ("unscoped fallback", "Exampletown, UT"),
        ("unscoped fallback", "Remote"),
    ]
    assert result["queries"] == 4
    close_connection(db_path)


def test_board_remote_tag_needs_explicit_evidence_for_concrete_location() -> None:
    false_remote = {
        "title": "Desktop Support Specialist",
        "company": "Example",
        "location": "Ketchikan, AK",
        "description": "Provide desk-side break/fix and remote assistance support for campus users.",
        "is_remote": True,
    }
    explicit_remote = {
        **false_remote,
        "description": "Fully remote desktop support for users across the United States.",
    }

    assert not _row_is_effectively_remote(false_remote)
    assert _row_is_effectively_remote(explicit_remote)


def test_remote_suffix_on_concrete_location_still_needs_description_evidence() -> None:
    tagged = {
        "title": "Desktop Support Specialist",
        "company": "Example",
        "location": "Manhattan, KS (Remote)",
        "description": "Provide on-campus desktop support and occasional remote assistance.",
        "is_remote": True,
    }

    assert not _row_is_effectively_remote(tagged)
    assert _row_is_effectively_remote(
        tagged | {"description": "Fully remote desktop support across the United States."}
    )
