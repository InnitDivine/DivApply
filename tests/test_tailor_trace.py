from __future__ import annotations

from divapply.scoring.tailor import assemble_resume_text
from divapply.scoring.tailor import _build_tailor_prompt, _format_job_trace


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


def test_assemble_resume_ignores_llm_education_and_injects_profile_education() -> None:
    data = {
        "title": "IT Support Technician",
        "summary": "Troubleshot user requests and documented support steps.",
        "skills": {"Tools": "Python, Excel"},
        "experience": [
            {
                "header": "Support Assistant",
                "subtitle": "Example Employer | 2022-Present",
                "bullets": ["Documented customer issues and escalated unresolved requests."],
            }
        ],
        "projects": [],
        "education": "Invented University | Completed Degree",
    }
    profile = {
        "personal": {"full_name": "Jane Doe", "email": "jane@example.com"},
        "education_schools": [
            {
                "degree": "A.A.S. Information Technology",
                "degree_received": False,
                "status": "in progress",
                "school": "Example College",
                "city_state": "Reno, NV",
                "start_year": "2024",
                "end_year": "present",
            }
        ],
    }

    text = assemble_resume_text(data, profile)

    assert "Example College" in text
    assert "A.A.S. Information Technology (in progress)" in text
    assert "Invented University" not in text
    assert "Completed Degree" not in text


def test_tailor_prompt_allows_coursework_skills_without_paid_work_claims() -> None:
    prompt = _build_tailor_prompt({
        "skills_boundary": {"Tools": ["Python", "Excel"]},
        "coursework_skills": ["Example College: Active Directory, device imaging"],
        "resume_facts": {"preserved_companies": ["Example Employer"]},
    })

    assert "IT SUPPORT / DEVICE SUPPORT GUIDANCE" in prompt
    assert "Coursework may support the skills section" in prompt
    assert "do not present coursework exposure as job experience" in prompt
    assert "Active Directory" in prompt
