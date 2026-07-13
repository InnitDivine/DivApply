from __future__ import annotations

import pytest
from bs4 import BeautifulSoup

from divapply.manual_url import extract_job_posting_schema, extract_manual_job_metadata, job_location_text
from divapply.security import UnsafeUrlError


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
                {"address": {"addressLocality": "Sampleville", "addressRegion": "YY"}}
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
        "location": "Sampleville, YY",
    }


def test_job_location_text_accepts_strings_and_address_objects() -> None:
    assert job_location_text([
        "Remote",
        {"address": {"addressLocality": "Salt Lake City", "addressRegion": "UT", "addressCountry": "USA"}},
    ]) == "Remote; Salt Lake City, UT, USA"


def test_extract_manual_metadata_prefers_visible_body_over_meta_summary(monkeypatch) -> None:
    html = """
    <html>
      <head>
        <title>IT Support Technician</title>
        <meta name="description" content="Short summary for sharing.">
      </head>
      <body>
        <main>
          <h1>IT Support Technician</h1>
          <p>Troubleshoot laptops, user accounts, printers, phones, and network access.</p>
          <p>Experience with Windows, Active Directory, ticket documentation, and customer support.</p>
        </main>
      </body>
    </html>
    """

    class Response:
        text = html

        def raise_for_status(self) -> None:
            return None

    class Client:
        def __init__(self, *args, **kwargs) -> None:
            pass

        def __enter__(self):
            return self

        def __exit__(self, *args) -> None:
            return None

        def get(self, *args, **kwargs):
            return Response()

    monkeypatch.setattr("httpx.Client", Client)

    metadata = extract_manual_job_metadata("https://careers.example.com/jobs/it-support-technician")

    assert "Troubleshoot laptops" in str(metadata["description"])
    assert "Active Directory" in str(metadata["description"])
    assert metadata["description"] != "Short summary for sharing."


def test_extract_manual_metadata_ignores_hidden_inactive_banner_without_schema(monkeypatch) -> None:
    html = """
    <html>
      <head><title>Device Support Technician I</title></head>
      <body>
        <main>
          <h1>Device Support Technician I</h1>
          <section class="job-description">
            <p>Position overview: support endpoints, mobile devices, Windows, Apple OS, and network access.</p>
            <p>Pay range is $25.89 to $37.55 per hour.</p>
          </section>
          <section class="phenom-hidden" aria-hidden="true">
            <h2>We're Sorry, This Job Is Inactive</h2>
            <p>This opportunity has passed. The posting has expired.</p>
          </section>
        </main>
      </body>
    </html>
    """

    class Response:
        text = html

        def raise_for_status(self) -> None:
            return None

    class Client:
        def __init__(self, *args, **kwargs) -> None:
            pass

        def __enter__(self):
            return self

        def __exit__(self, *args) -> None:
            return None

        def get(self, *args, **kwargs):
            return Response()

    monkeypatch.setattr("httpx.Client", Client)

    metadata = extract_manual_job_metadata(
        "https://jobs.sutterhealth.org/us/en/job/R-133284/Device-Support-Technician-I"
    )

    assert metadata["inactive"] is False
    assert metadata["site"] == "jobs.sutterhealth.org"
    assert metadata["title"] == "Device Support Technician I"
    assert "support endpoints" in str(metadata["description"])
    assert "posting has expired" not in str(metadata["description"]).lower()


def test_extract_manual_metadata_rejects_redirect_to_private_address(monkeypatch) -> None:
    requested: list[str] = []

    class RedirectResponse:
        text = ""
        is_redirect = True
        headers = {"location": "http://127.0.0.1:8080/admin"}
        url = "https://jobs.example.com/posting/1"

        def raise_for_status(self) -> None:
            return None

    class Client:
        def __init__(self, *args, **kwargs) -> None:
            assert kwargs["follow_redirects"] is False

        def __enter__(self):
            return self

        def __exit__(self, *args) -> None:
            return None

        def get(self, url, **kwargs):
            requested.append(str(url))
            return RedirectResponse()

    monkeypatch.setattr("httpx.Client", Client)

    with pytest.raises(UnsafeUrlError, match="private or local"):
        extract_manual_job_metadata("https://jobs.example.com/posting/1")

    assert requested == ["https://jobs.example.com/posting/1"]
