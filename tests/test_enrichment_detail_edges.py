from __future__ import annotations

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
