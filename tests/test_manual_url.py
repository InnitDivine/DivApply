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


def test_extract_manual_metadata_prefers_visible_body_over_meta_summary(monkeypatch) -> None:
    from divapply.manual_url import extract_manual_job_metadata

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
