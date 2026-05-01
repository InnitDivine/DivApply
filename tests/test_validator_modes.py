from __future__ import annotations

from divapply.scoring.validator import validate_json_fields, validate_tailored_resume


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
Example University | Reno, NV | 2018-2022
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

