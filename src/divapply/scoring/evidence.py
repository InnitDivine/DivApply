"""Bounded candidate-owned evidence shared by scoring and document generation."""

from __future__ import annotations


WORK_HISTORY_MAX_ENTRIES = 16
WORK_HISTORY_FIELD_LIMITS = {
    "title": 160,
    "company": 200,
    "dates": 120,
    "tasks": 1200,
}


def _bounded_field(value: object, *, limit: int) -> str:
    """Normalize one explicit profile field without importing adjacent metadata."""
    text = " ".join(str(value or "").split()).replace("|", "/")
    return text[:limit].strip()


def verified_work_history(profile: dict) -> tuple[dict[str, str], ...]:
    """Return only explicit, bounded work-history fields used as candidate evidence."""
    raw_history = profile.get("work_history")
    if not isinstance(raw_history, list):
        return ()

    entries: list[dict[str, str]] = []
    for raw in raw_history[:WORK_HISTORY_MAX_ENTRIES]:
        if not isinstance(raw, dict):
            continue
        entry = {
            "title": _bounded_field(raw.get("title"), limit=WORK_HISTORY_FIELD_LIMITS["title"]),
            "company": _bounded_field(raw.get("company"), limit=WORK_HISTORY_FIELD_LIMITS["company"]),
            "dates": _bounded_field(raw.get("dates"), limit=WORK_HISTORY_FIELD_LIMITS["dates"]),
            "tasks": _bounded_field(
                raw.get("tasks") or raw.get("description"),
                limit=WORK_HISTORY_FIELD_LIMITS["tasks"],
            ).rstrip("."),
        }
        if any(entry.values()):
            entries.append(entry)
    return tuple(entries)


def format_verified_work_history(profile: dict) -> str:
    """Format explicit work-history facts for prompts without inferred prompt fields."""
    lines: list[str] = []
    for entry in verified_work_history(profile):
        parts = [entry[key] for key in ("title", "company", "dates", "tasks") if entry[key]]
        lines.append(" | ".join(parts))
    return "\n".join(lines)


def verified_work_history_text(profile: dict) -> str:
    """Flatten the same explicit fields for deterministic evidence validation."""
    return " ".join(
        value
        for entry in verified_work_history(profile)
        for value in entry.values()
        if value
    )
