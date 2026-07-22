from __future__ import annotations

from divapply.scoring.tailor import assemble_resume_text
from divapply.scoring.tailor import _build_tailor_prompt, _format_job_trace
from divapply.scoring import tailor
from divapply.scoring.validator import validate_tailored_resume


def test_job_trace_keeps_company_and_source_separate() -> None:
    trace = _format_job_trace(
        {
            "title": "Support Analyst",
            "company": "Real Employer",
            "site": "Indeed",
            "location": "Remote",
            "fit_score": 8,
            "url": "https://jobs.example/1",
            "full_description": "Required: Python support.",
        }
    )

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
        "personal": {
            "full_name": "Jane Doe",
            "email": "jane@example.com",
            "city": "Exampletown",
            "province_state": "YY",
        },
        "education_schools": [
            {
                "degree": "A.A.S. Information Technology",
                "degree_received": False,
                "status": "in progress",
                "school": "Example College",
                "city_state": "Sampleville, YY",
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
    assert "\nExampletown, YY\n" in text


def test_assemble_resume_labels_major_transfer_and_selective_verified_gpa() -> None:
    data = {
        "title": "Health IT Support",
        "summary": "Factual summary.",
        "skills": {"Tools": "Excel"},
        "experience": [],
        "projects": [],
    }
    profile = {
        "personal": {"full_name": "Jane Doe"},
        "education_schools": [
            {
                "degree": "Bachelor of Science",
                "major": "Public Health",
                "degree_received": False,
                "school": "Current University",
                "city_state": "Online",
                "start_year": "2024",
                "end_year": "present",
                "gpa": "3.6",
                "minor": "General Business",
                "gpa_as_of": "2026-07-12",
                "units": "113",
                "units_scope": "total",
                "expected_graduation_year": "2027",
            },
            {
                "degree": "Associate of General Studies",
                "major": "General Studies",
                "degree_received": True,
                "school": "Community College",
                "city_state": "Sampleville, YY",
                "start_year": "2023",
                "end_year": "2024",
                "gpa": "2.92",
                "minor": "Business",
                "units": "17",
                "units_scope": "institutional",
            },
            {
                "degree": "Bachelor of Science",
                "major": "Community Health Sciences",
                "degree_received": False,
                "status": "transferred",
                "school": "Prior University",
                "city_state": "Sampleville, YY",
                "start_year": "2019",
                "end_year": "2022",
                "gpa": "3.358",
                "minor": "Business",
            },
        ],
    }

    text = assemble_resume_text(data, profile)

    assert "Bachelor of Science in Public Health (in progress; expected 2027)" in text
    assert "GPA: 3.6 (as of July 12, 2026)" in text
    assert "Earned credits: 113" in text
    assert "Associate of General Studies (conferred 2024)" in text
    assert "GPA: 2.92" not in text
    assert "Earned credits: 17" not in text
    assert "Community Health Sciences coursework (transferred)" in text
    assert "Bachelor of Science (transferred)" not in text
    assert text.count("Minor:") == 1


def test_tailor_prompt_allows_coursework_skills_without_paid_work_claims() -> None:
    prompt = _build_tailor_prompt(
        {
            "skills_boundary": {"Tools": ["Python", "Excel"]},
            "coursework_skills": ["Example College: Active Directory, device imaging"],
            "resume_facts": {"preserved_companies": ["Example Employer"]},
        }
    )

    assert "IT SUPPORT / DEVICE SUPPORT GUIDANCE" in prompt
    assert "Coursework may support the skills section" in prompt
    assert "do not present coursework exposure as job experience" in prompt
    assert "Active Directory" in prompt


def test_tailor_prompt_requires_target_positioning_without_assumed_role_or_metrics() -> None:
    prompt = _build_tailor_prompt({})

    assert "Sound like someone who's done this job" not in prompt
    assert "quantified impact" not in prompt
    assert "proving you've done this work" not in prompt
    assert "Position the candidate for the target role using verified evidence" in prompt
    assert "Use a metric only when the source resume or verified profile supplies it" in prompt
    assert "Do NOT claim phone, email, or chat support experience" in prompt
    assert "Do NOT relabel residents, members, visitors" in prompt
    assert "anchor hands-on IT claims to the lab, project, or coursework" in prompt
    assert "CORE QUALIFICATIONS" in prompt
    assert "do not force operating-system/network/cloud categories" in prompt
    assert "Provisioned and administer" in prompt
    assert "prefer a verified PC-building/hardware project" in prompt


def test_assemble_resume_preserves_allowlisted_core_qualifications_heading() -> None:
    data = {
        "title": "Client Relations Specialist",
        "summary": "Factual summary.",
        "skills_section_title": "CORE QUALIFICATIONS",
        "skills": {"Public Service": "Issue triage, records, escalation"},
        "experience": [],
        "projects": [],
    }

    text = assemble_resume_text(data, {"personal": {"full_name": "Jane Doe"}})

    assert "\nCORE QUALIFICATIONS\n" in text
    assert "\nTECHNICAL SKILLS\n" not in text


def test_one_page_shape_drops_projects_for_core_qualifications() -> None:
    data = {
        "title": "Client Relations Specialist",
        "summary": "Factual summary.",
        "skills_section_title": "CORE QUALIFICATIONS",
        "skills": {"Public Service": "records, escalation"},
        "experience": [],
        "projects": [
            {
                "header": "Cloud Lab",
                "subtitle": "Linux | 2024-Present",
                "bullets": ["Administered a server."],
            }
        ],
    }

    shaped = tailor._enforce_one_page_shape(data)

    assert shaped["projects"] == []


def test_judge_prompt_does_not_refute_allowed_targeting_or_canonical_education() -> None:
    prompt = tailor._build_judge_prompt(
        {
            "skills_boundary": {"Tools": ["Excel"]},
            "education_schools": [
                {
                    "school": "Current University",
                    "degree": "Bachelor of Science",
                    "major": "Public Health",
                    "gpa": "3.6",
                }
            ],
        }
    )

    assert "target-role headline is positioning" in prompt
    assert "Omitting original skills" in prompt
    assert "canonical transcript records" in prompt
    assert "AUTHORITATIVE CURRENT EDUCATION" in prompt
    assert "AUTHORITATIVE ALLOWED SKILLS" in prompt
    assert "- Tools: Excel" in prompt
    assert "Any exact listed profile skill is supported" in prompt
    assert "no definitive fabrication, you MUST return PASS" in prompt
    assert "School: Current University" in prompt
    assert "Degree: Bachelor of Science" in prompt
    assert "Major: Public Health" in prompt
    assert "GPA: 3.6" in prompt
    assert "explicit allowed transformations above take precedence" in prompt


def test_resume_validator_rejects_malformed_fragments() -> None:
    text = """Jane Doe
IT Technician

SUMMARY
Factual summary.

TECHNICAL SKILLS
Tools: Excel

EXPERIENCE
Assistant
Example Employer | 2022-Present
- Documented requests and.

PROJECTS
Support Lab
Python | 2023 .
- Built a support lab.
- Provisioned and administer a server.

EDUCATION
Example College
"""
    profile = {
        "personal": {"full_name": "Jane Doe"},
        "resume_facts": {"preserved_companies": ["Example Employer"]},
        "skills_boundary": {"Tools": ["Excel", "Python"]},
    }

    report = validate_tailored_resume(text, profile, original_text=text, mode="strict")

    assert not report["passed"]
    assert any("bare year" in error for error in report["errors"])
    assert any("incomplete conjunction" in error for error in report["errors"])
    assert any("inconsistent tense" in error for error in report["errors"])


def test_strict_tailor_fails_closed_when_judge_rejects(monkeypatch) -> None:
    class Client:
        def chat(self, *_args, **_kwargs) -> str:
            return "{}"

    monkeypatch.setattr(tailor, "get_client_for_stage", lambda _stage: Client())
    monkeypatch.setattr(
        tailor,
        "validate_json_fields",
        lambda *_args, **_kwargs: {"passed": True, "errors": [], "warnings": []},
    )
    monkeypatch.setattr(
        tailor,
        "validate_tailored_resume",
        lambda *_args, **_kwargs: {"passed": True, "errors": [], "warnings": []},
    )
    monkeypatch.setattr(tailor, "assemble_resume_text", lambda *_args: "factual resume")
    monkeypatch.setattr(
        tailor,
        "judge_tailored_resume",
        lambda *_args: {
            "passed": False,
            "verdict": "FAIL",
            "issues": "manual review required",
            "raw": "VERDICT: FAIL",
        },
    )

    _, strict_report = tailor.tailor_resume(
        "source",
        {"title": "Support", "full_description": "description"},
        {},
        max_retries=0,
        validation_mode="strict",
    )
    _, normal_report = tailor.tailor_resume(
        "source",
        {"title": "Support", "full_description": "description"},
        {},
        max_retries=0,
        validation_mode="normal",
    )

    assert strict_report["status"] == "failed_judge"
    assert normal_report["status"] == "approved_with_judge_warning"


def test_v115_tailor_prunes_posting_only_skills_before_validation(monkeypatch) -> None:
    class Client:
        def chat(self, *_args, **_kwargs) -> str:
            return "{}"

    data = {
        "title": "Support Technician",
        "summary": "Factual summary.",
        "skills_section_title": "TECHNICAL SKILLS",
        "skills": {"Support": "Python, asset tracking"},
        "experience": [],
        "projects": [],
    }
    captured: dict = {}
    monkeypatch.setattr(tailor, "get_client_for_stage", lambda _stage: Client())
    monkeypatch.setattr(tailor, "extract_json", lambda _raw: data)

    def validate(candidate, *_args, **_kwargs):
        captured.update(candidate)
        return {"passed": True, "errors": [], "warnings": []}

    monkeypatch.setattr(tailor, "validate_json_fields", validate)
    monkeypatch.setattr(
        tailor,
        "validate_tailored_resume",
        lambda *_args, **_kwargs: {"passed": True, "errors": [], "warnings": []},
    )
    monkeypatch.setattr(tailor, "assemble_resume_text", lambda *_args: "factual resume")
    monkeypatch.setattr(
        tailor,
        "judge_tailored_resume",
        lambda *_args: {"passed": True, "verdict": "PASS", "issues": "none", "raw": "VERDICT: PASS"},
    )

    _, report = tailor.tailor_resume(
        "Built Python reports.",
        {"title": "Support", "full_description": "Track company assets."},
        {"skills_boundary": {"Tools": ["Python"]}},
        max_retries=0,
        validation_mode="strict",
    )

    assert report["status"] == "approved"
    assert captured["skills"] == {"Support": "Python"}


def test_v116_judge_absence_rejection_yields_to_exact_candidate_evidence() -> None:
    judge = {
        "passed": False,
        "issues": (
            "The resume adds \u201chealth communication coursework\u201d, but that phrase is not supported "
            "by the authoritative evidence."
        ),
    }
    profile = {"skills_boundary": {"Coursework": ["health communication coursework"]}}

    assert tailor._judge_rejection_contradicts_candidate_evidence(judge, profile, "")
    judge["issues"] = (
        "The resume adds \u201chealth communication coursework\u201d, but the evidence does not list it."
    )
    assert tailor._judge_rejection_contradicts_candidate_evidence(judge, profile, "")
    judge["issues"] = (
        "The resume adds \u201chealth communication coursework\u201d and "
        "\u201cCommunity Health Sciences coursework (transferred)\u201d, but neither is supported."
    )
    profile["education_schools"] = [
        {
            "school": "Example University",
            "city_state": "Sampleville, YY",
            "degree": "Bachelor of Science",
            "major": "Community Health Sciences",
            "start_year": "2020",
            "end_year": "2022",
            "status": "transferred",
        }
    ]
    assert tailor._judge_rejection_contradicts_candidate_evidence(judge, profile, "")


def test_v116_judge_context_rejection_never_gets_absence_override() -> None:
    judge = {
        "passed": False,
        "issues": (
            "The paid-work bullet moves \u201chealth communication coursework\u201d into professional experience."
        ),
    }
    profile = {"skills_boundary": {"Coursework": ["health communication coursework"]}}

    assert not tailor._judge_rejection_contradicts_candidate_evidence(judge, profile, "")


def test_tailor_retry_report_clears_prior_attempt_judge(monkeypatch) -> None:
    class Client:
        def chat(self, *_args, **_kwargs) -> str:
            return "{}"

    validations = iter(
        [
            {"passed": True, "errors": [], "warnings": []},
            {"passed": False, "errors": ["current validation failure"], "warnings": []},
        ]
    )
    monkeypatch.setattr(tailor, "get_client_for_stage", lambda _stage: Client())
    monkeypatch.setattr(tailor, "extract_json", lambda _raw: {"valid": True})
    monkeypatch.setattr(tailor, "_normalize_resume_json", lambda data: data)
    monkeypatch.setattr(tailor, "_enforce_one_page_shape", lambda data: data)
    monkeypatch.setattr(
        tailor,
        "validate_json_fields",
        lambda *_args, **_kwargs: next(validations),
    )
    monkeypatch.setattr(
        tailor,
        "validate_tailored_resume",
        lambda *_args, **_kwargs: {"passed": True, "errors": [], "warnings": []},
    )
    monkeypatch.setattr(tailor, "assemble_resume_text", lambda *_args: "factual resume")
    monkeypatch.setattr(
        tailor,
        "judge_tailored_resume",
        lambda *_args: {
            "passed": False,
            "verdict": "FAIL",
            "issues": "prior-attempt issue",
            "raw": "VERDICT: FAIL",
        },
    )

    _, report = tailor.tailor_resume(
        "source",
        {"title": "Support", "full_description": "description"},
        {},
        max_retries=1,
        validation_mode="strict",
    )

    assert report["status"] == "failed_validation"
    assert report["validator"]["errors"] == ["current validation failure"]
    assert report["text_validator"] is None
    assert report["judge"] is None
