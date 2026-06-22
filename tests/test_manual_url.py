from __future__ import annotations

from bs4 import BeautifulSoup

from divapply.manual_url import extract_job_posting_schema, job_location_text


def test_extract_job_posting_schema_handles_nested_graph() -> None:
    soup = BeautifulSoup(
        """
        <script type="application/ld+json">
        {
          "@graph": [
            {"@type": "BreadcrumbList"},
            {
              "@type": ["Thing", "JobPosting"],
              "title": "Support Analyst",
              "description": "Help desk role",
              "hiringOrganization": {"name": "Example Co"},
              "jobLocation": [
                {"address": {"addressLocality": "Reno", "addressRegion": "NV"}}
              ]
            }
          ]
        }
        </script>
        """,
        "html.parser",
    )

    assert extract_job_posting_schema(soup) == {
        "description": "Help desk role",
        "title": "Support Analyst",
        "company": "Example Co",
        "location": "Reno, NV",
    }


def test_job_location_text_accepts_strings_and_address_objects() -> None:
    assert job_location_text([
        "Remote",
        {"address": {"addressLocality": "Salt Lake City", "addressRegion": "UT", "addressCountry": "USA"}},
    ]) == "Remote; Salt Lake City, UT, USA"
