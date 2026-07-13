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
    """Extract location filters, deriving default accepts from configured locations."""
    if search_cfg is None:
        search_cfg = config.load_search_config()
    location_cfg = search_cfg.get("location", {}) or {}
    accept = (
        search_cfg.get("location_accept")
        or location_cfg.get("accept_patterns")
        or _accept_terms_from_locations(search_cfg.get("locations", []) or [])
    )
    reject = search_cfg.get("location_reject_non_remote") or location_cfg.get("reject_patterns") or []
    return accept, reject


def _accept_terms_from_locations(locations: list[dict] | list[str]) -> list[str]:
    """Build practical location-match terms from the configured search locations."""
    terms: list[str] = []

    def add(value: str | None) -> None:
        text = str(value or "").strip()
        if text and text.casefold() not in {item.casefold() for item in terms}:
            terms.append(text)

    for item in locations:
        if isinstance(item, dict):
            location = str(item.get("location") or item.get("label") or "").strip()
            label = str(item.get("label") or "").strip()
            is_remote = bool(item.get("remote")) or location.casefold() == "remote"
        else:
            location = str(item or "").strip()
            label = ""
            is_remote = location.casefold() == "remote"

        if is_remote:
            for term in ("remote", "anywhere", "united states", "usa"):
                add(term)
            continue

        add(location)
        add(label)
        if "," in location:
            add(location.split(",", 1)[0])

    return terms


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
    return not any(term_in_text(title, exclude) for exclude in excludes)


def location_ok(
    location: str | None,
    accept: list[str],
    reject: list[str],
    *,
    allow_unknown: bool = True,
    is_remote: bool = False,
) -> bool:
    """Check whether a job location passes accept/reject filters."""
    if not location:
        return True if is_remote else allow_unknown

    loc = location.lower()
    if any(term_in_text(loc, term) for term in reject):
        return False
    if is_remote:
        return True
    if any(term in loc for term in REMOTE_TERMS):
        return True
    return any(term_in_text(loc, term) for term in accept)
