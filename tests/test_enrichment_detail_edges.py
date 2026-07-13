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


def test_extract_from_json_ld_prefers_longest_jobposting_in_nested_graph() -> None:
    short_description = "This job is inactive."
    full_description = """
    <section>
      <h2>Position Overview</h2>
      <p>Support endpoints, ticket queues, network troubleshooting, asset imaging, and onboarding.</p>
      <h2>Requirements</h2>
      <ul><li>Windows support</li><li>Active Directory</li><li>Mobile device support</li></ul>
    </section>
    """
    intel = {
        "json_ld": [
            "{bad json is ignored by collection before this point}",
            {
                "@graph": [
                    {
                        "@type": ["Thing", "JobPosting"],
                        "title": "Hidden inactive duplicate",
                        "description": short_description,
                        "url": "https://example.com/expired",
                    },
                    {
                        "@type": "JobPosting",
                        "title": "Device Support Technician",
                        "description": full_description,
                    },
                ]
            },
        ]
    }

    result = detail.extract_from_json_ld(intel)

    assert result is not None
    assert "Support endpoints" in result["full_description"]
    assert "Active Directory" in result["full_description"]
    assert "This job is inactive" not in result["full_description"]
    assert result["application_url"] is None


def test_extract_from_json_ld_ignores_too_short_descriptions() -> None:
    intel = {"json_ld": [{"@type": "JobPosting", "description": "Short", "url": "https://example.com/apply"}]}

    assert detail.extract_from_json_ld(intel) is None


def test_extract_from_json_ld_handles_missing_apply_url() -> None:
    description = "<p>Maintain laptops, document support work, and troubleshoot account access.</p>" * 3
    intel = {"json_ld": [{"@type": "JobPosting", "description": description}]}

    result = detail.extract_from_json_ld(intel)

    assert result is not None
    assert "Maintain laptops" in result["full_description"]
    assert result["application_url"] is None


def test_extract_description_deterministic_skips_hidden_inactive_block() -> None:
    class FakeElement:
        def __init__(self, text: str, visible: bool = True) -> None:
            self.text = text
            self.visible = visible

        def evaluate(self, _script: str) -> bool:
            return self.visible

        def inner_text(self) -> str:
            return self.text

    class FakePage:
        def __init__(self) -> None:
            self.matches = {
                "#job-description": FakeElement(
                    "This job is inactive. This opportunity has passed. The posting has expired.",
                    visible=False,
                ),
                ".job-description": FakeElement(
                    "Position Overview\n"
                    "Troubleshoot hardware, software, account access, and mobile devices.\n"
                    "Requirements\n"
                    "Document tickets, support Windows, and communicate with users.",
                    visible=True,
                ),
            }

        def query_selector(self, selector: str):
            return self.matches.get(selector)

    result = detail.extract_description_deterministic(FakePage())

    assert result is not None
    assert "Troubleshoot hardware" in result
    assert "This job is inactive" not in result


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


def test_scrape_detail_page_rejects_redirect_to_private_url() -> None:
    class FakeResponse:
        status = 200
        url = "http://127.0.0.1:8080/admin"

    class FakePage:
        url = "http://127.0.0.1:8080/admin"

        def goto(self, _url, timeout):
            return FakeResponse()

        def wait_for_load_state(self, *_args, **_kwargs):
            return None

    result = detail.scrape_detail_page(FakePage(), "https://jobs.example.com/posting")

    assert result["status"] == "error"
    assert "private or local address" in result["error"]
