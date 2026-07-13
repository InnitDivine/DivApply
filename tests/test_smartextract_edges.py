from __future__ import annotations

import json

import pytest

from divapply import config
from divapply.database import close_connection, init_db
from divapply.discovery import smartextract
from divapply.security import UnsafeUrlError


def test_extract_json_strips_thinking_and_code_fences() -> None:
    raw = '<think>draft</think>\n```json\n{"strategy": "api_response", "ok": true}\n```'

    assert smartextract.extract_json(raw) == {"strategy": "api_response", "ok": True}


def test_extract_json_raises_for_non_json_text() -> None:
    with pytest.raises(json.JSONDecodeError):
        smartextract.extract_json("No structured response")


def test_clean_page_html_removes_hidden_inactive_blocks() -> None:
    html = """
    <main>
      <section class="jobs-list">
        <article class="job-card"><a href="/jobs/live">Device Support Technician I</a></article>
      </section>
      <section class="phenom-hidden" aria-hidden="true">
        We're Sorry, This Job Is Inactive. This opportunity has passed.
      </section>
      <div style="display:none">posting has expired</div>
    </main>
    """

    cleaned = smartextract.clean_page_html(html)

    assert "Device Support Technician I" in cleaned
    assert "This Job Is Inactive" not in cleaned
    assert "posting has expired" not in cleaned


def test_resolve_json_path_handles_nested_lists_and_dict_display_values() -> None:
    data = {
        "results": [
            {
                "hits": [
                    {
                        "title": {"text": "IT Support Technician"},
                        "locations": [{"name": "Exampletown, UT"}, {"name": "Remote"}],
                    }
                ]
            }
        ]
    }

    assert smartextract.resolve_json_path_raw(data, "results[0].hits")[0]["title"]["text"] == "IT Support Technician"
    assert smartextract.resolve_json_path(data, "results[0].hits[0].title") == "IT Support Technician"
    assert smartextract.resolve_json_path(data, "results[0].hits[0].locations") == "Exampletown, UT, Remote"


def test_resolve_json_path_invalid_index_returns_none() -> None:
    data = {"results": [{"hits": []}]}

    assert smartextract.resolve_json_path_raw(data, "results[bad].hits") is None
    assert smartextract.resolve_json_path(data, "results[bad].hits") is None


def test_execute_api_response_uses_fallback_applicantpro_url(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(config, "load_base_urls", lambda: {"City of Exampletown": "https://Exampletownutah.applicantpro.com"})
    intel = {
        "api_responses": [
            {
                "url": "https://Exampletownutah.applicantpro.com/api/jobs",
                "_raw_data": {
                    "items": [
                        {
                            "id": 123,
                            "name": "Help Desk Technician",
                            "place": {"name": "Exampletown, UT"},
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

    jobs = smartextract.execute_api_response(intel, plan, site="City of Exampletown")

    assert jobs == [
        {
            "title": "Help Desk Technician",
            "salary": None,
            "description": None,
            "location": "Exampletown, UT",
            "url": "https://Exampletownutah.applicantpro.com/jobs/123",
        }
    ]


def test_execute_json_ld_handles_nested_graph_and_multiple_jobpostings() -> None:
    intel = {
        "json_ld": [
            {
                "@graph": [
                    {"@type": "Organization", "name": "Example Health"},
                    {
                        "@type": ["Thing", "JobPosting"],
                        "title": "Expired duplicate",
                        "description": "This job is inactive.",
                        "url": "https://example.com/jobs/expired",
                    },
                    {
                        "@type": "JobPosting",
                        "title": "Desktop Support Technician",
                        "description": "Full responsibilities include endpoint support, imaging, and ticket triage.",
                        "jobLocation": {"address": {"addressLocality": "Exampletown", "addressRegion": "UT"}},
                        "url": "https://example.com/jobs/live",
                    },
                ]
            }
        ]
    }
    plan = {
        "extraction": {
            "title": "title",
            "salary": None,
            "description": "description",
            "location": "jobLocation.address",
            "url": "url",
        }
    }

    jobs = smartextract.execute_json_ld(intel, plan)

    assert jobs == [
        {
            "title": "Expired duplicate",
            "salary": None,
            "description": "This job is inactive.",
            "location": None,
            "url": "https://example.com/jobs/expired",
        },
        {
            "title": "Desktop Support Technician",
            "salary": None,
            "description": "Full responsibilities include endpoint support, imaging, and ticket triage.",
            "location": "Exampletown",
            "url": "https://example.com/jobs/live",
        },
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


def test_run_all_continues_when_parallel_worker_crashes(tmp_path, monkeypatch) -> None:
    db_path = tmp_path / "divapply.db"
    conn = init_db(db_path)
    events: list[tuple[str, dict | None]] = []

    monkeypatch.setattr(smartextract, "init_db", lambda: conn)
    monkeypatch.setattr(smartextract, "get_stats", lambda _conn: {"total": 0, "pending_detail": 0})
    monkeypatch.setattr(smartextract, "_load_plan_cache", lambda: {})
    monkeypatch.setattr(smartextract, "_save_plan_cache", lambda _cache: None)
    monkeypatch.setattr(
        smartextract,
        "record_reliability_event",
        lambda category, _message, **kwargs: events.append((category, kwargs.get("context"))),
    )

    def fake_run_one_site(name, url, cached_plan=None):
        if name == "Bad Site":
            raise RuntimeError("site exploded")
        return {
            "name": name,
            "status": "PASS",
            "total": 0,
            "titles": 0,
            "strategy": "unit",
            "jobs": [],
        }

    monkeypatch.setattr(smartextract, "_run_one_site", fake_run_one_site)

    result = smartextract._run_all(
        [
            {"name": "Good Site", "url": "https://good.example/jobs"},
            {"name": "Bad Site", "url": "https://bad.example/jobs"},
        ],
        accept_locs=[],
        reject_locs=[],
        workers=2,
    )

    assert result == {"total_new": 0, "total_existing": 0, "passed": 1, "total": 2}
    assert events == [
        (
            "smartextract_worker_crashed",
            {"target": "Bad Site", "url": "https://bad.example/jobs", "error": "site exploded"},
        )
    ]
    close_connection(db_path)


def test_collect_page_intelligence_rejects_redirect_to_private_url(monkeypatch) -> None:
    class FakeResponse:
        status = 200
        url = "http://127.0.0.1:8080/admin"

    class FakePage:
        url = "http://127.0.0.1:8080/admin"

        def on(self, *_args):
            return None

        def goto(self, _url, timeout):
            return FakeResponse()

    class FakeBrowser:
        def new_page(self, **_kwargs):
            return FakePage()

    class FakeChromium:
        def launch(self, **_kwargs):
            return FakeBrowser()

    class FakePlaywright:
        chromium = FakeChromium()

    class FakeSyncPlaywright:
        def __enter__(self):
            return FakePlaywright()

        def __exit__(self, *_exc):
            return False

    monkeypatch.setattr(smartextract, "sync_playwright", lambda: FakeSyncPlaywright())

    with pytest.raises(UnsafeUrlError):
        smartextract.collect_page_intelligence("https://jobs.example.com")


def test_collect_page_intelligence_skips_private_response_capture(monkeypatch) -> None:
    class PrivateResponse:
        status = 200
        url = "http://127.0.0.1:8080/api/secrets"
        headers = {"content-type": "application/json"}

        def text(self):
            raise AssertionError("private response body should not be read")

    class SafeResponse:
        status = 200
        url = "https://jobs.example.com"

    class FakePage:
        url = "https://jobs.example.com"

        def on(self, _event, callback):
            self._callback = callback

        def goto(self, _url, timeout):
            self._callback(PrivateResponse())
            return SafeResponse()

        def wait_for_load_state(self, *_args, **_kwargs):
            return None

        def title(self):
            return "Jobs"

        def query_selector_all(self, _selector):
            return []

        def query_selector(self, _selector):
            return None

        def evaluate(self, _script):
            return [] if "querySelectorAll" in _script else {}

        def content(self):
            return "<html><body></body></html>"

    class FakeBrowser:
        def new_page(self, **_kwargs):
            return FakePage()

        def close(self):
            return None

    class FakeChromium:
        def launch(self, **_kwargs):
            return FakeBrowser()

    class FakePlaywright:
        chromium = FakeChromium()

    class FakeSyncPlaywright:
        def __enter__(self):
            return FakePlaywright()

        def __exit__(self, *_exc):
            return False

    monkeypatch.setattr(smartextract, "sync_playwright", lambda: FakeSyncPlaywright())

    intel = smartextract.collect_page_intelligence("https://jobs.example.com")

    assert intel["api_responses"] == []
