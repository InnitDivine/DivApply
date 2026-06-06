"""Shared discovery filter helpers."""

from __future__ import annotations

import re

from divapply import config

REMOTE_TERMS = ("remote", "anywhere", "work from home", "wfh", "distributed")


def term_in_text(text: str | None, term: str | None) -> bool:
    """Match config terms without letting short tokens hit inside words."""
    haystack = str(text or "").lower()
    needle = str(term or "").strip().lower()
    if not needle:
        return False
    if re.fullmatch(r"[a-z0-9]+", needle):
        return re.search(rf"\b{re.escape(needle)}\b", haystack) is not None
    return needle in haystack


def load_location_filter(search_cfg: dict | None = None) -> tuple[list[str], list[str]]:
    """Extract accept/reject location lists from current or legacy config names."""
    if search_cfg is None:
        search_cfg = config.load_search_config()
    location_cfg = search_cfg.get("location", {}) or {}
    accept = search_cfg.get("location_accept") or location_cfg.get("accept_patterns") or []
    reject = search_cfg.get("location_reject_non_remote") or location_cfg.get("reject_patterns") or []
    return accept, reject


def load_title_excludes(search_cfg: dict | None = None, *, include_filter_blacklist: bool = False) -> list[str]:
    """Load title exclusion patterns from supported config keys."""
    if search_cfg is None:
        search_cfg = config.load_search_config()

    raw = list(search_cfg.get("exclude_titles", []) or [])
    if include_filter_blacklist:
        raw.extend(search_cfg.get("title_blacklist", []) or [])
        filters = search_cfg.get("filters", {}) or {}
        raw.extend(filters.get("title_blacklist", []) or [])
    return [str(value).lower() for value in raw if str(value).strip()]


def title_ok(title: str | None, excludes: list[str]) -> bool:
    """Return False if title matches any exclude pattern."""
    if not title or not excludes:
        return True
    lowered = title.lower()
    return not any(exclude in lowered for exclude in excludes)


def location_ok(
    location: str | None,
    accept: list[str],
    reject: list[str],
    *,
    allow_unknown: bool = True,
    is_remote: bool = False,
) -> bool:
    """Check whether a job location passes accept/reject filters."""
    if is_remote:
        return True

    if not location:
        return allow_unknown

    loc = location.lower()
    if any(term in loc for term in REMOTE_TERMS):
        return True
    if any(term_in_text(loc, term) for term in reject):
        return False
    return any(term_in_text(loc, term) for term in accept)
