from __future__ import annotations

from divapply.scoring.validator import sanitize_text, validate_json_fields, validate_tailored_resume


def test_sanitize_text_repairs_known_compound_tense_fragment() -> None:
    assert (
        sanitize_text("Provisioned and administer a headless server.") == "Provision and administer a headless server."
    )


def _profile() -> dict:
    return {
        "skills_boundary": {"tools": ["Python", "Excel"]},
        "resume_facts": {"preserved_companies": ["Example Employer"]},
    }


def test_validation_none_accepts_unchecked_output() -> None:
    assert validate_json_fields({}, _profile(), mode="none") == {
        "passed": True,
        "errors": [],
        "warnings": [],
    }


def test_validation_catches_fabricated_credentials() -> None:
    data = {
        "title": "Analyst",
        "summary": "Built reports.",
        "skills": {"Tools": "Python, AWS Certified"},
        "experience": [{"header": "Analyst", "subtitle": "Example Employer", "bullets": ["Built reports."]}],
        "projects": [],
    }

    report = validate_json_fields(data, _profile(), mode="normal")

    assert not report["passed"]
    assert any("Fabricated skill" in error for error in report["errors"])


def test_validation_allows_coursework_skill_in_skills_section() -> None:
    profile = {
        "skills_boundary": {"tools": ["Python", "Excel"]},
        "coursework_skills": ["Example College: Active Directory, device imaging"],
        "resume_facts": {"preserved_companies": ["Example Employer"]},
    }
    data = {
        "title": "IT Support Technician",
        "summary": "Troubleshot user requests and documented support steps.",
        "skills": {"Tools": "Python, Excel, Active Directory"},
        "experience": [
            {
                "header": "Support Assistant",
                "subtitle": "Example Employer",
                "bullets": ["Documented customer issues and escalated unresolved requests."],
            }
        ],
        "projects": [],
    }

    report = validate_json_fields(data, profile, mode="normal")

    assert report["passed"], report["errors"]


def test_validation_rejects_posting_only_skill_from_candidate_skills() -> None:
    data = {
        "title": "IT Support Technician",
        "summary": "Troubleshot user requests and documented support steps.",
        "skills": {"Support": "Python, asset tracking"},
        "experience": [
            {
                "header": "Support Assistant",
                "subtitle": "Example Employer",
                "bullets": ["Documented customer issues and escalated unresolved requests."],
            }
        ],
        "projects": [],
    }

    report = validate_json_fields(
        data,
        _profile(),
        mode="strict",
        original_text="Built Python reports and managed general event inventory.",
    )

    assert not report["passed"]
    assert "Candidate-unsupported skill: 'asset tracking'" in report["errors"]


def test_validation_rejects_coursework_skill_rewritten_as_paid_work() -> None:
    profile = {
        "skills_boundary": {"tools": ["Python", "Excel"]},
        "coursework_skills": ["Example College: Active Directory, device imaging"],
        "resume_facts": {"preserved_companies": ["Example Employer"]},
    }
    data = {
        "title": "IT Support Technician",
        "summary": "Troubleshot user requests and documented support steps.",
        "skills": {"Tools": "Python, Excel, Active Directory"},
        "experience": [
            {
                "header": "Support Assistant",
                "subtitle": "Example Employer",
                "bullets": ["Resolved employee account issues in Active Directory."],
            }
        ],
        "projects": [],
    }

    report = validate_json_fields(data, profile, mode="normal")

    assert not report["passed"]
    assert any("Coursework-only skill used as paid work" in error for error in report["errors"])


def test_json_validation_allows_coursework_overlap_proven_in_paid_source_resume() -> None:
    profile = {
        "skills_boundary": {"tools": ["Excel"]},
        "coursework_skills": ["Example College: accounting"],
        "resume_facts": {"preserved_companies": ["County Treasurer"]},
    }
    data = {
        "title": "Accounting Assistant",
        "summary": "Maintained financial records and reconciliations.",
        "skills": {"Tools": "Excel, accounting"},
        "experience": [
            {
                "header": "Senior Accounting Assistant",
                "subtitle": "County Treasurer",
                "bullets": ["Maintained accounting records and reconciled transactions."],
            }
        ],
        "projects": [],
    }

    report = validate_json_fields(
        data,
        profile,
        original_text="Senior Accounting Assistant prepared accounting records for County Treasurer.",
        mode="strict",
    )

    assert report["passed"], report["errors"]


def test_validation_rejects_llm_supplied_education() -> None:
    data = {
        "title": "Analyst",
        "summary": "Built reports.",
        "skills": {"Tools": "Python, Excel"},
        "experience": [{"header": "Analyst", "subtitle": "Example Employer", "bullets": ["Built reports."]}],
        "projects": [],
        "education": "Invented University | Completed Degree",
    }

    report = validate_json_fields(data, _profile(), mode="normal")

    assert not report["passed"]
    assert any("Education must be injected" in error for error in report["errors"])


_RESUME_NO_PROJECTS = """\
Jane Doe
Analyst
jane@example.com | 555-555-5555

SUMMARY
Built reports for Example Employer.

TECHNICAL SKILLS
Tools: Python, Excel

EXPERIENCE
Analyst
Example Employer | 2022-Present
- Built reports

EDUCATION
B.S. (conferred 2022)
Example University | Sampleville, YY | 2018-2022
"""


def test_validate_tailored_resume_allows_missing_projects_section() -> None:
    profile = {
        "personal": {"full_name": "Jane Doe", "email": "jane@example.com", "phone": "555-555-5555"},
        "resume_facts": {"preserved_companies": ["Example Employer"]},
    }
    report = validate_tailored_resume(_RESUME_NO_PROJECTS, profile)

    # No PROJECTS section is fine: the tailor prompt allows an empty
    # projects array, and assemble_resume_text drops the heading entirely.
    assert all("PROJECTS" not in err for err in report["errors"]), report["errors"]


def test_validate_tailored_resume_banned_words_warn_in_normal_mode() -> None:
    profile = {
        "personal": {"full_name": "Jane Doe", "email": "jane@example.com", "phone": "555-555-5555"},
        "resume_facts": {"preserved_companies": ["Example Employer"]},
    }
    text_with_banned = _RESUME_NO_PROJECTS.replace(
        "Built reports for Example Employer.",
        "Passionate analyst who utilized data to drive results.",
    )

    normal = validate_tailored_resume(text_with_banned, profile, mode="normal")
    strict = validate_tailored_resume(text_with_banned, profile, mode="strict")
    lenient = validate_tailored_resume(text_with_banned, profile, mode="lenient")

    assert any("Banned words" in warn for warn in normal["warnings"])
    assert all("Banned words" not in err for err in normal["errors"])
    assert any("Banned words" in err for err in strict["errors"])
    assert all("Banned words" not in warn for warn in lenient["warnings"])
    assert all("Banned words" not in err for err in lenient["errors"])


def test_validate_tailored_resume_none_mode_skips_all() -> None:
    report = validate_tailored_resume("garbage text only", {}, mode="none")
    assert report == {"passed": True, "errors": [], "warnings": []}


def test_validate_tailored_resume_rejects_coursework_skill_in_experience() -> None:
    profile = {
        "personal": {"full_name": "Jane Doe", "email": "jane@example.com", "phone": "555-555-5555"},
        "skills_boundary": {"tools": ["Python", "Excel"]},
        "coursework_skills": ["Example College: Active Directory"],
        "resume_facts": {"preserved_companies": ["Example Employer"]},
    }
    tailored = _RESUME_NO_PROJECTS.replace(
        "- Built reports",
        "- Resolved account requests in Active Directory",
    )

    report = validate_tailored_resume(
        tailored,
        profile,
        original_text="Example Employer work included reports and customer support.",
        mode="normal",
    )

    assert not report["passed"]
    assert any("Coursework-only skill used as paid work" in error for error in report["errors"])


def test_validate_tailored_resume_rejects_unsupported_license_claim() -> None:
    tailored = _RESUME_NO_PROJECTS.replace(
        "Built reports for Example Employer.",
        "Built reports for Example Employer while maintaining a CPA license.",
    )

    report = validate_tailored_resume(
        tailored,
        {
            "personal": {"full_name": "Jane Doe", "email": "jane@example.com", "phone": "555-555-5555"},
            "resume_facts": {"preserved_companies": ["Example Employer"]},
        },
        original_text="Example Employer work included reporting.",
        mode="normal",
    )

    assert not report["passed"]
    assert any("Unsupported credential or degree claim" in error for error in report["errors"])
