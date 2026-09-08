from __future__ import annotations

import pytest

from divapply.education import (
    education_completion_status,
    education_credential_label,
    education_is_active_program,
    education_resume_status_note,
)


def test_academic_record_completion_status_overrides_stale_profile_flags() -> None:
    school = {
        "degree_received": False,
        "status": "in progress",
        "end_year": "present",
        "education_record_degree_status": "conferred",
    }

    assert education_completion_status(school) == "received"
    assert not education_is_active_program(school)


@pytest.mark.parametrize(
    "school",
    [
        {"end_year": "Present", "degree_received": False},
        {"end_year": "2026", "expected_graduation_year": "2027"},
        {"status": "current"},
    ],
)
def test_current_or_expected_program_is_in_progress(school: dict) -> None:
    assert education_completion_status(school) == "in progress"
    assert education_is_active_program(school)


@pytest.mark.parametrize(
    ("status", "expected"),
    [
        ("inactive", "not completed"),
        ("not enrolled", "not completed"),
        ("not currently enrolled", "not completed"),
        ("completed - inactive", "received"),
        ("not transferred", "not completed"),
    ],
)
def test_negative_or_mixed_statuses_use_conservative_precedence(status: str, expected: str) -> None:
    assert education_completion_status({"status": status}) == expected


def test_tmcc_completed_degree_keeps_its_own_credential_and_confer_year() -> None:
    school = {
        "school": "Example Community College",
        "degree": "Associate of General Studies",
        "major": "General Studies",
        "degree_received": True,
        "end_year": "2024",
    }

    assert education_completion_status(school) == "received"
    assert education_credential_label(school) == "Associate of General Studies"
    assert education_resume_status_note(school) == "conferred 2024"


def test_unr_transfer_entry_is_coursework_not_a_received_degree() -> None:
    school = {
        "school": "Prior Regional University",
        "degree": "No degree (coursework transferred)",
        "major": "Community Health Sciences",
        "degree_received": False,
        "status": "transferred",
        "end_year": "2022",
    }

    assert education_completion_status(school) == "transferred"
    assert education_credential_label(school) == "Community Health Sciences coursework"
    assert education_resume_status_note(school) == "transferred"
    assert not education_is_active_program(school)


def test_transcript_transfer_status_wins_over_present_end_year() -> None:
    school = {
        "degree_received": False,
        "end_year": "Present",
        "education_record_degree_status": "not completed - transferred",
    }

    assert education_completion_status(school) == "transferred"


def test_transfer_without_major_does_not_render_stale_degree_as_earned() -> None:
    school = {
        "degree": "Bachelor of Science",
        "degree_received": False,
        "status": "transferred",
    }

    assert education_credential_label(school) == "Coursework"


def test_expected_month_is_shown_without_claiming_graduation() -> None:
    school = {
        "school": "Example State University",
        "degree": "Bachelor of Science",
        "major": "Public Health",
        "degree_received": False,
        "end_year": "present",
        "expected_graduation_year": "2026",
        "expected_graduation_month": 12,
    }
    assert education_completion_status(school) == "in progress"
    assert education_resume_status_note(school) == "in progress; expected December 2026"
    assert school["degree_received"] is False


@pytest.mark.parametrize("month", [None, "", 0, 13, -1, "unknown", 1.5, True])
def test_invalid_expected_month_keeps_the_known_year(month: object) -> None:
    assert education_resume_status_note({
        "expected_graduation_year": "2026", "expected_graduation_month": month,
    }) == "in progress; expected 2026"


def test_expected_month_needs_a_year() -> None:
    assert education_resume_status_note({
        "end_year": "present", "expected_graduation_month": 12,
    }) == "in progress"
