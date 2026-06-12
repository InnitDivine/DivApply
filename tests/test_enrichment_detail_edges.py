from __future__ import annotations

from divapply.database import init_db
from divapply.enrichment import detail


def test_resolve_url_cleans_jsessionid_and_joins_base(monkeypatch) -> None:
    monkeypatch.setattr(detail, "_load_base_urls", lambda: {"Cache Site": "https://jobs.example.com/careers/"})

    assert detail.resolve_url("/jobs/42;jsessionid=abc123?ignored=true", "Cache Site") == "https://jobs.example.com/jobs/42"


def test_resolve_url_keeps_absolute_and_rejects_known_bad_relative_sites() -> None:
    absolute = "https://example.com/jobs/42"

    assert detail.resolve_url(absolute, "Any Site") == absolute
    assert detail.resolve_url("frontend-developer", "WelcomeToTheJungle") is None
    assert detail.resolve_url("/", "4DayWeek") is None


def test_resolve_url_rejects_scheme_relative_host_override(monkeypatch) -> None:
    monkeypatch.setattr(detail, "_load_base_urls", lambda: {"Cache Site": "https://jobs.example.com/careers/"})

    assert detail.resolve_url("//evil.example/jobs/42", "Cache Site") is None


def test_extract_from_json_ld_finds_nested_graph_jobposting() -> None:
    description = "<p>Help local users with hardware, software, tickets, and documentation.</p>" * 3
    intel = {
        "json_ld": [
            {
                "@context": "https://schema.org",
                "@graph": [
                    {"@type": "Organization", "name": "Cache Employer"},
                    {
                        "@type": "JobPosting",
                        "description": description,
                        "directApply": True,
                        "url": "https://example.com/apply",
                    },
                ],
            }
        ]
    }

    result = detail.extract_from_json_ld(intel)

    assert result == {
        "full_description": "\n".join(
            ["Help local users with hardware, software, tickets, and documentation."] * 3
        ),
        "application_url": "https://example.com/apply",
    }


def test_extract_from_json_ld_ignores_too_short_descriptions() -> None:
    intel = {"json_ld": [{"@type": "JobPosting", "description": "Short", "url": "https://example.com/apply"}]}

    assert detail.extract_from_json_ld(intel) is None


def test_title_prefilter_allows_it_senior_specialist_but_rejects_public_safety() -> None:
    assert detail._title_is_irrelevant("Senior IT Support Specialist") is False
    assert detail._title_is_irrelevant("Police Records Clerk") is False
    assert detail._title_is_irrelevant("Police Officer") is True


def test_scrape_site_batch_commits_before_inter_job_delay(tmp_path, monkeypatch) -> None:
    conn = init_db(tmp_path / "jobs.db")
    conn.executemany(
        "INSERT INTO jobs (url, title, site) VALUES (?, ?, ?)",
        [
            ("https://example.com/1", "Front Desk", "Example"),
            ("https://example.com/2", "Office Assistant", "Example"),
        ],
    )
    conn.commit()

    class FakePage:
        pass

    class FakeContext:
        def new_page(self):
            return FakePage()

    class FakeBrowser:
        def new_context(self, **_kwargs):
            return FakeContext()

        def close(self):
            pass

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

    monkeypatch.setattr(detail, "sync_playwright", lambda: FakeSyncPlaywright())
    monkeypatch.setattr(
        detail,
        "scrape_detail_page",
        lambda _page, _url: {
            "status": "ok",
            "tier_used": 1,
            "full_description": "Part-time front desk support.",
            "application_url": "https://example.com/apply",
            "elapsed": 0.1,
        },
    )

    def assert_committed_before_sleep(_delay):
        assert not conn.in_transaction

    monkeypatch.setattr(detail.time, "sleep", assert_committed_before_sleep)

    stats = detail.scrape_site_batch(
        conn,
        "Example",
        [("https://example.com/1", "Front Desk"), ("https://example.com/2", "Office Assistant")],
        delay=1,
    )

    assert stats["ok"] == 2
