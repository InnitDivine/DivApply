from __future__ import annotations

from divapply.scoring.context import format_job_context
from divapply.scoring.cover_letter import _strip_preamble
from divapply.scoring.validator import validate_cover_letter


def _profile() -> dict:
    return {
        "skills_boundary": {
            "languages": ["Python", "SQL"],
            "tools": ["Excel"],
        }
    }


def _job() -> dict:
    return {
        "title": "Reporting Analyst",
        "company": "Example Health",
        "site": "Indeed",
        "location": "Remote",
        "full_description": "Build Python and SQL reporting for patient support workflows.",
    }


def _valid_letter(body: str = "I built Python reporting workflows that match this role's reporting work.") -> str:
    return "\n\n".join(
        [
            "Dear Hiring Manager,",
            body,
            "Example Health needs clear reporting for patient support workflows. Let's discuss.",
            "Jane",
        ]
    )


def test_strip_preamble_removes_leaked_intro() -> None:
    text = "Here is the cover letter:\n\nDear Hiring Manager,\nI built reports.\nJane"

    assert _strip_preamble(text).startswith("Dear Hiring Manager,")


def test_validate_cover_letter_blocks_generic_ai_phrase() -> None:
    report = validate_cover_letter(
        _valid_letter("I am writing to express my interest in the Reporting Analyst role."),
        mode="normal",
        profile=_profile(),
        job=_job(),
    )

    assert not report["passed"]
    assert any("Generic cover-letter phrase" in error for error in report["errors"])


def test_validate_cover_letter_blocks_job_only_tool_claim() -> None:
    job = _job() | {"full_description": "Build dashboards in Salesforce and SQL."}
    letter = _valid_letter("I have built Salesforce dashboards and SQL reporting workflows.")

    report = validate_cover_letter(
        letter,
        mode="normal",
        profile=_profile(),
        resume_text="Built SQL reports in Excel.",
        job=job,
    )

    assert not report["passed"]
    assert any("salesforce" in error.lower() for error in report["errors"])


def test_validate_cover_letter_blocks_private_credential_language() -> None:
    report = validate_cover_letter(
        _valid_letter("I used login tokens to automate Python reporting workflows."),
        mode="normal",
        profile=_profile(),
        resume_text="Built Python reports in Excel.",
        job=_job(),
    )

    assert not report["passed"]
    assert any("credential" in error.lower() for error in report["errors"])


def test_validate_cover_letter_blocks_too_long_normal_mode() -> None:
    long_body = " ".join(["Python reporting"] * 140)

    report = validate_cover_letter(
        _valid_letter(long_body),
        mode="normal",
        profile=_profile(),
        job=_job(),
    )

    assert not report["passed"]
    assert any("Too long" in error for error in report["errors"])


def test_format_job_context_includes_safe_referral_context_only() -> None:
    text = format_job_context(
        _job()
        | {
            "referral_context": "Referred by a current analyst for reporting work.",
            "employer_context": "password: secret",
        }
    )

    assert "REFERRAL CONTEXT: Referred by a current analyst for reporting work." in text
    assert "password" not in text.lower()
    assert "secret" not in text.lower()
