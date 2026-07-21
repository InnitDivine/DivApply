"""Shared job context formatting for scoring and generated documents."""

from __future__ import annotations

import re


SENSITIVE_CONTEXT_MARKERS = (
    "password",
    "passcode",
    "token",
    "api key",
    "apikey",
    "secret",
    "credential",
    "login",
)

APPLICATION_BOILERPLATE_BOUNDARIES = (
    "applicants have rights under",
    "apply for this job",
    "eeo is the law",
    "equal opportunity/affirmative action employer",
    "equal opportunity and affirmative action employer",
    "equal opportunity employer",
    "public burden statement",
    "veteran status",
    "voluntary self-identification",
)


def _clean_context_value(value: object) -> str:
    """Return safe single-line context text, dropping credential-like values."""
    if value is None:
        return ""
    text = " ".join(str(value).split())
    if not text:
        return ""
    lowered = text.lower()
    if any(marker in lowered for marker in SENSITIVE_CONTEXT_MARKERS):
        return ""
    return text[:500]


def _format_safe_extra_context(job: dict) -> str:
    """Format verified employer/referral notes if present on the job record."""
    fields = (
        ("referral_context", "REFERRAL CONTEXT"),
        ("referral_note", "REFERRAL CONTEXT"),
        ("employer_context", "EMPLOYER CONTEXT"),
        ("priority_reason", "EMPLOYER CONTEXT"),
    )
    lines: list[str] = []
    seen: set[tuple[str, str]] = set()
    for key, label in fields:
        text = _clean_context_value(job.get(key))
        if not text:
            continue
        item = (label, text)
        if item in seen:
            continue
        seen.add(item)
        lines.append(f"{label}: {text}")
    if not lines:
        return ""
    return "\n\nVERIFIED EXTRA CONTEXT:\n" + "\n".join(lines)


REQUIREMENT_CONTEXT_MARKERS = (
    "minimum qualifications",
    "minimum requirements",
    "required qualifications",
    "requirements",
    "qualifications",
    "must have",
    "required experience",
    "required education",
    "license required",
    "certification required",
    "equivalent experience",
    "\nexperience:",
    "\ntraining:",
    "\neducation:",
    "\nlicense or certificate",
)


def _requirement_window(text: str, *, start: int, budget: int) -> str:
    """Extract bounded middle text around requirement-bearing language."""
    if budget <= 0:
        return ""
    lowered = text.casefold()
    positions = sorted(
        {
            position
            for marker in REQUIREMENT_CONTEXT_MARKERS
            if (position := lowered.find(marker, start)) >= start
        }
    )
    if not positions:
        return ""

    pieces: list[str] = []
    remaining = budget
    for position in positions:
        if remaining <= 0:
            break
        window_start = max(start, position - 40)
        line_start = text.rfind("\n", start, position)
        if line_start >= start:
            window_start = line_start + 1
        window_end = min(len(text), position + min(360, remaining))
        next_heading = re.search(r"\n\s*[A-Z][A-Za-z &/\-]{2,50}\s*\n", text[position + 1 : window_end])
        if next_heading:
            window_end = position + 1 + next_heading.start()
        piece = text[window_start:window_end].strip()
        if not piece or any(piece in prior for prior in pieces):
            continue
        piece = piece[:remaining]
        pieces.append(piece)
        remaining -= len(piece) + 1
    return "\n".join(pieces)[:budget]


def _bounded_description(value: object, limit: int) -> str:
    """Keep posting opening, requirement-bearing middle, and closing caveats."""
    text = str(value or "")
    if limit <= 0:
        return ""
    if len(text) <= limit:
        return text
    marker = "\n...[middle omitted]...\n"
    if limit <= len(marker) + 2:
        return text[:limit]
    two_markers = len(marker) * 2
    if limit <= two_markers + 3:
        content_limit = limit - len(marker)
        head_length = max(1, int(content_limit * 0.6))
        tail_length = content_limit - head_length
        return f"{text[:head_length]}{marker}{text[-tail_length:]}"[:limit]

    content_limit = limit - two_markers
    head_length = max(1, int(content_limit * 0.32))
    tail_length = max(1, int(content_limit * 0.23))
    middle_budget = content_limit - head_length - tail_length
    middle = _requirement_window(text, start=head_length, budget=middle_budget)
    if not middle:
        content_limit = limit - len(marker)
        head_length = max(1, int(content_limit * 0.6))
        tail_length = content_limit - head_length
        return f"{text[:head_length]}{marker}{text[-tail_length:]}"[:limit]

    unused = middle_budget - len(middle)
    head_length += max(0, unused // 2)
    tail_length += max(0, unused - unused // 2)
    bounded = f"{text[:head_length]}{marker}{middle}{marker}{text[-tail_length:]}"
    return bounded[:limit]


def _strip_application_boilerplate(value: object) -> str:
    """Remove ATS forms and protected-condition self-ID text from job facts."""
    text = str(value or "")
    lowered = text.casefold()
    positions = [
        position
        for marker in APPLICATION_BOILERPLATE_BOUNDARIES
        if (position := lowered.find(marker)) >= 0
    ]
    return text[: min(positions)].rstrip() if positions else text


def format_job_context(job: dict, *, description_limit: int = 3000, extra: str = "") -> str:
    """Return neutral job context with employer separate from source board."""
    description = _bounded_description(
        _strip_application_boilerplate(
            job.get("full_description") or job.get("description") or ""
        ),
        description_limit,
    )
    safe_extra_context = _format_safe_extra_context(job)
    return (
        f"TITLE: {job.get('title') or 'N/A'}\n"
        f"COMPANY: {job.get('company') or 'N/A'}\n"
        f"SOURCE: {job.get('site') or 'N/A'}\n"
        f"LOCATION: {job.get('location') or 'N/A'}\n\n"
        f"DESCRIPTION:\n{description}"
        f"{safe_extra_context}"
        f"{extra}"
    )
