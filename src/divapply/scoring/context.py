"""Shared job context formatting for scoring and generated documents."""

from __future__ import annotations


def format_job_context(job: dict, *, description_limit: int = 3000, extra: str = "") -> str:
    """Return neutral job context with employer separate from source board."""
    description = (job.get("full_description") or job.get("description") or "")[:description_limit]
    return (
        f"TITLE: {job.get('title') or 'N/A'}\n"
        f"COMPANY: {job.get('company') or 'N/A'}\n"
        f"SOURCE: {job.get('site') or 'N/A'}\n"
        f"LOCATION: {job.get('location') or 'N/A'}\n\n"
        f"DESCRIPTION:\n{description}"
        f"{extra}"
    )
