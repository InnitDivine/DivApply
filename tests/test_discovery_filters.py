from __future__ import annotations

from divapply.discovery.jobspy import (
    _job_row_passes_filters,
    _load_filter_rules,
    _load_location_config,
    _load_title_excludes,
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
    assert _load_filter_rules(cfg) == {
        "company_blacklist": ["badco"],
        "required_keywords": ["python"],
        "excluded_keywords": ["clearance"],
        "remote_preference": "remote",
    }


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

