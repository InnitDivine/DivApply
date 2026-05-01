from __future__ import annotations

from divapply.scoring.validator import validate_json_fields


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

