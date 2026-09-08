"""Canonical education-status and resume-label helpers.

Education facts can come from the user-maintained profile and from an optional
structured academic-record overlay.  Keeping the precedence rules here avoids
different answers in scoring, resume generation, and application forms.
"""

from __future__ import annotations

import calendar
import re
from typing import Literal


EducationCompletionStatus = Literal["transferred", "received", "in progress", "not completed"]
EARNED_CERTIFICATION_STATUSES = frozenset(
    {"active", "certified", "completed", "current", "earned", "valid"}
)


def _normalized_status(value: object) -> str:
    return " ".join(str(value or "").strip().casefold().replace("-", " ").split())


def certification_is_earned(certification: object) -> bool:
    """Return whether a structured certification record is safe to present as earned."""
    if not isinstance(certification, dict):
        return False
    return _normalized_status(certification.get("status")) in EARNED_CERTIFICATION_STATUSES


def _status_from_text(value: object) -> EducationCompletionStatus | None:
    """Map a free-form status to a conservative canonical completion state."""
    status = _normalized_status(value)
    if not status:
        return None

    # A positive transfer marker is authoritative for entries such as
    # "not completed - transferred", but a negated marker ("not transferred")
    # must not be mistaken for transferred coursework.
    transfer_status = re.sub(
        r"\b(?:(?:not|never)\s+(?:a\s+)?|no\s+)transfer(?:s|red|ring)?\b",
        "",
        status,
    )
    if re.search(r"\btransfer(?:s|red|ring)?\b", transfer_status):
        return "transferred"

    # Explicit non-completion takes precedence over positive substrings inside
    # the same phrase (for example, "not completed").
    if re.search(
        r"\b(?:(?:not|never)\s+(?:degree\s+)?(?:completed|conferred|awarded|graduated|received|earned)"
        r"|(?:degree|credential)\s+(?:not|never)\s+(?:completed|conferred|awarded|received|earned)"
        r"|incomplete|no\s+(?:degree|credential))\b",
        status,
    ):
        return "not completed"
    if re.search(
        r"\b(?:conferred|awarded|completed|graduated|received|(?:degree|credential)\s+earned)\b",
        status,
    ):
        return "received"

    # Test negative participation states before active-state words. Word
    # boundaries also prevent "inactive" from matching "active".
    if re.search(
        r"\b(?:inactive|withdrawn|discontinued|"
        r"(?:not|never)\s+(?:currently\s+)?(?:enrolled|active|current|expected)|"
        r"no\s+longer\s+(?:enrolled|active|current))\b",
        status,
    ):
        return "not completed"
    if re.search(r"\b(?:in progress|enrolled|active|expected|current(?:ly)?)\b", status):
        return "in progress"
    return None


def education_completion_status(school: dict) -> EducationCompletionStatus:
    """Return one completion state, honoring academic-record facts first."""
    record_status = _status_from_text(school.get("education_record_degree_status"))
    if record_status:
        return record_status

    profile_status = _status_from_text(school.get("status"))
    if profile_status:
        return profile_status
    if school.get("degree_received") is True:
        return "received"
    if _normalized_status(school.get("end_year")) == "present":
        return "in progress"
    if str(school.get("expected_graduation_year") or "").strip():
        return "in progress"
    return "not completed"


def education_is_active_program(school: dict) -> bool:
    """Return whether the school entry represents a current unfinished program."""
    return education_completion_status(school) == "in progress"


def education_credential_label(school: dict) -> str:
    """Build a degree/major label without assigning a degree to transfer coursework."""
    completion = education_completion_status(school)
    degree = str(school.get("degree") or "").strip()
    major = str(school.get("major") or "").strip()

    if completion == "transferred":
        # A transferred record proves attendance/coursework, not receipt of
        # the degree named in a stale form field.  Only the subject is safe to
        # carry into the resume label.
        return f"{major} coursework" if major else "Coursework"

    credential = degree or major or "Education"
    if degree and major and major.casefold() not in degree.casefold():
        credential = f"{degree} in {major}"
    return credential


def education_resume_status_note(school: dict) -> str:
    """Return the concise parenthetical status used in generated resumes."""
    completion = education_completion_status(school)
    if completion == "transferred":
        return "transferred"
    if completion == "in progress":
        expected_year = str(school.get("expected_graduation_year") or "").strip()
        month = str(school.get("expected_graduation_month") or "").strip()
        if expected_year and month.isdecimal() and 1 <= int(month) <= 12:
            expected_year = f"{calendar.month_name[int(month)]} {expected_year}"
        return f"in progress; expected {expected_year}" if expected_year else "in progress"
    if completion == "received":
        end_year = str(school.get("end_year") or "").strip()
        return f"conferred {end_year}" if end_year and _normalized_status(end_year) != "present" else "conferred"
    return "not completed"
