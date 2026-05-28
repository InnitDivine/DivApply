from __future__ import annotations

from divapply.scoring.tailor import _format_job_trace


def test_job_trace_keeps_company_and_source_separate() -> None:
    trace = _format_job_trace({
        "title": "Support Analyst",
        "company": "Real Employer",
        "site": "Indeed",
        "location": "Remote",
        "fit_score": 8,
        "url": "https://jobs.example/1",
        "full_description": "Required: Python support.",
    })

    assert "Company: Real Employer" in trace
    assert "Source: Indeed" in trace
    assert "Company: Indeed" not in trace
