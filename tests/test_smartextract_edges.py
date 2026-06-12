from __future__ import annotations

import json

import pytest

from divapply import config
from divapply.discovery import smartextract


def test_extract_json_strips_thinking_and_code_fences() -> None:
    raw = '<think>draft</think>\n```json\n{"strategy": "api_response", "ok": true}\n```'

    assert smartextract.extract_json(raw) == {"strategy": "api_response", "ok": True}


def test_extract_json_raises_for_non_json_text() -> None:
    with pytest.raises(json.JSONDecodeError):
        smartextract.extract_json("No structured response")


def test_resolve_json_path_handles_nested_lists_and_dict_display_values() -> None:
    data = {
        "results": [
            {
                "hits": [
                    {
                        "title": {"text": "IT Support Technician"},
                        "locations": [{"name": "Logan, UT"}, {"name": "Remote"}],
                    }
                ]
            }
        ]
    }

    assert smartextract.resolve_json_path_raw(data, "results[0].hits")[0]["title"]["text"] == "IT Support Technician"
    assert smartextract.resolve_json_path(data, "results[0].hits[0].title") == "IT Support Technician"
    assert smartextract.resolve_json_path(data, "results[0].hits[0].locations") == "Logan, UT, Remote"


def test_resolve_json_path_invalid_index_returns_none() -> None:
    data = {"results": [{"hits": []}]}

    assert smartextract.resolve_json_path_raw(data, "results[bad].hits") is None
    assert smartextract.resolve_json_path(data, "results[bad].hits") is None


def test_execute_api_response_uses_fallback_applicantpro_url(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(config, "load_base_urls", lambda: {"City of Logan": "https://loganutah.applicantpro.com"})
    intel = {
        "api_responses": [
            {
                "url": "https://loganutah.applicantpro.com/api/jobs",
                "_raw_data": {
                    "items": [
                        {
                            "id": 123,
                            "name": "Help Desk Technician",
                            "place": {"name": "Logan, UT"},
                        }
                    ]
                },
            }
        ]
    }
    plan = {
        "extraction": {
            "url_pattern": "/api/jobs",
            "items_path": "items",
            "title": "name",
            "salary": None,
            "description": None,
            "location": "place.name",
            "url": None,
        }
    }

    jobs = smartextract.execute_api_response(intel, plan, site="City of Logan")

    assert jobs == [
        {
            "title": "Help Desk Technician",
            "salary": None,
            "description": None,
            "location": "Logan, UT",
            "url": "https://loganutah.applicantpro.com/jobs/123",
        }
    ]


def test_normalize_job_url_rejects_scheme_relative_host_override(monkeypatch) -> None:
    monkeypatch.setattr(config, "load_base_urls", lambda: {"Cache Site": "https://jobs.example.com/careers/"})

    assert smartextract._normalize_job_url("Cache Site", "//evil.example/jobs/42") is None


def test_normalize_applicantpro_numeric_url_uses_jobs_path(monkeypatch) -> None:
    monkeypatch.setattr(config, "load_base_urls", lambda: {"Cache County": "https://cachecounty.applicantpro.com"})

    assert (
        smartextract._normalize_job_url("Cache County", "4110020")
        == "https://cachecounty.applicantpro.com/jobs/4110020"
    )
