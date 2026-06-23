"""Shared job context formatting for scoring and generated documents."""

from __future__ import annotations


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


def format_job_context(job: dict, *, description_limit: int = 3000, extra: str = "") -> str:
    """Return neutral job context with employer separate from source board."""
    description = (job.get("full_description") or job.get("description") or "")[:description_limit]
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
