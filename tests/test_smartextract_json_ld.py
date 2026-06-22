from __future__ import annotations

from divapply.discovery import smartextract


def test_execute_json_ld_flattens_graph_and_type_lists() -> None:
    intel = {
        "json_ld": [
            {
                "@graph": [
                    {"@type": "Organization", "name": "Example Health"},
                    {
                        "@type": ["Thing", "JobPosting"],
                        "title": "Desktop Support Technician",
                        "description": "Endpoint support and ticket triage.",
                        "jobLocation": {"address": {"addressLocality": "Logan", "addressRegion": "UT"}},
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

    assert smartextract.execute_json_ld(intel, plan) == [
        {
            "title": "Desktop Support Technician",
            "salary": None,
            "description": "Endpoint support and ticket triage.",
            "location": "Logan",
            "url": "https://example.com/jobs/live",
        }
    ]
