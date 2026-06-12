from __future__ import annotations

import builtins

import pytest

from divapply.discovery.jobspy import (
    _job_row_passes_filters,
    _location_ok,
    _load_filter_rules,
    _load_location_config,
    _load_title_excludes,
    _row_is_effectively_remote,
    _scrape_with_retry,
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
        ["logan"],
        ["ogden"],
        allow_unknown=False,
        is_remote=_row_is_effectively_remote(row),
    )


def test_remote_location_text_does_not_bypass_rejected_place() -> None:
    assert not _location_ok(
        "Remote in Idaho",
        ["logan", "cache valley"],
        ["idaho"],
        allow_unknown=False,
    )
    assert _location_ok(
        "Remote",
        ["logan", "cache valley"],
        ["idaho"],
        allow_unknown=False,
    )
    assert not _location_ok(
        "Layton, UT, US (Remote)",
        ["logan", "cache valley"],
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
            "location": "Logan, UT",
            "description": "Full-time 40 hours per week",
        },
        rules,
    )
    assert _job_row_passes_filters(
        {
            "title": "Customer Service Representative",
            "company": "GoodCo",
            "location": "Logan, UT",
            "description": "Part-time 8 hours per week",
        },
        rules,
    )
