"""JobSpy-based job discovery: searches Indeed, LinkedIn, Glassdoor, ZipRecruiter.

Uses python-jobspy to scrape multiple job boards, deduplicates results,
parses salary ranges, and stores everything in the DivApply database.

Search queries, locations, and filtering rules are loaded from the user's
search configuration YAML (searches.yaml) rather than being hardcoded.
"""

import logging
import re
import sqlite3
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone

from divapply import config
from divapply.database import canonical_job_key, get_connection, get_existing_canonical_keys, init_db
from divapply.discovery.filters import (
    REMOTE_TERMS,
    load_location_filter,
    load_title_excludes,
    location_ok,
    term_in_text,
    title_ok,
)

log = logging.getLogger(__name__)


def _empty_board_stats() -> dict:
    return {"calls": 0, "seconds": 0.0, "total": 0, "new": 0, "existing": 0, "errors": 0}


def _merge_board_stats(target: dict, source: dict | None) -> None:
    for site, stats in (source or {}).items():
        bucket = target.setdefault(site, _empty_board_stats())
        for key in ("calls", "total", "new", "existing", "errors"):
            bucket[key] += int(stats.get(key, 0) or 0)
        bucket["seconds"] += float(stats.get("seconds", 0.0) or 0.0)


def _record_scrape_stats(
    board_stats: dict,
    sites: list[str],
    *,
    elapsed: float,
    total: int = 0,
    errors: int = 0,
) -> None:
    if not sites:
        return
    share = total / len(sites) if total else 0
    elapsed_share = elapsed / len(sites)
    for site in sites:
        bucket = board_stats.setdefault(site, _empty_board_stats())
        bucket["calls"] += 1
        bucket["seconds"] += elapsed_share
        bucket["total"] += int(round(share))
        bucket["errors"] += errors


def _finalize_board_stats(board_stats: dict) -> dict:
    return {
        site: {
            "calls": int(stats["calls"]),
            "seconds": round(float(stats["seconds"]), 2),
            "total": int(stats["total"]),
            "new": int(stats["new"]),
            "existing": int(stats["existing"]),
            "errors": int(stats["errors"]),
        }
        for site, stats in sorted(board_stats.items())
    }


# -- Proxy parsing -----------------------------------------------------------

def parse_proxy(proxy_str: str) -> dict:
    """Parse host:port:user:pass into components."""
    parts = proxy_str.split(":")
    if len(parts) == 4:
        host, port, user, passwd = parts
        return {
            "host": host,
            "port": port,
            "user": user,
            "pass": passwd,
            "jobspy": f"{user}:{passwd}@{host}:{port}",
            "playwright": {
                "server": f"http://{host}:{port}",
                "username": user,
                "password": passwd,
            },
        }
    elif len(parts) == 2:
        host, port = parts
        return {
            "host": host,
            "port": port,
            "user": None,
            "pass": None,
            "jobspy": f"{host}:{port}",
            "playwright": {"server": f"http://{host}:{port}"},
        }
    else:
        raise ValueError(
            f"Proxy format not recognized: {proxy_str}. "
            f"Expected: host:port:user:pass or host:port"
        )


# -- Retry wrapper -----------------------------------------------------------

def _scrape_with_retry(kwargs: dict, max_retries: int = 2, backoff: float = 5.0):
    """Call scrape_jobs with retry on transient failures."""
    try:
        from jobspy import scrape_jobs
    except ImportError as exc:
        raise RuntimeError(
            "python-jobspy is required for JobSpy discovery. "
            "Install the JobSpy runtime dependencies or use other discovery backends."
        ) from exc

    for attempt in range(max_retries + 1):
        try:
            return scrape_jobs(**kwargs)
        except Exception as e:
            err = str(e).lower()
            transient = any(k in err for k in ("timeout", "429", "proxy", "connection", "reset", "refused"))
            if transient and attempt < max_retries:
                wait = backoff * (attempt + 1)
                log.warning("Retry %d/%d in %.0fs: %s", attempt + 1, max_retries, wait, e)
                time.sleep(wait)
            else:
                raise


# -- Location filtering ------------------------------------------------------

def _load_location_config(search_cfg: dict) -> tuple[list[str], list[str]]:
    """Extract accept/reject location lists from search config.

    Falls back to sensible defaults if not defined in the YAML.
    """
    return load_location_filter(search_cfg)


def _load_title_excludes(search_cfg: dict) -> list[str]:
    """Load title exclusion patterns from search config (case-insensitive)."""
    return load_title_excludes(search_cfg, include_filter_blacklist=True)


def _load_filter_rules(search_cfg: dict) -> dict:
    """Load optional AIHawk-style filters from search config."""
    filters = search_cfg.get("filters", {}) or {}
    def _list(name: str) -> list[str]:
        return [
            str(v).lower() for v in (
                search_cfg.get(name, [])
                or filters.get(name, [])
                or []
            )
            if str(v).strip()
        ]

    return {
        "company_blacklist": _list("company_blacklist"),
        "required_keywords": _list("required_keywords"),
        "excluded_keywords": _list("excluded_keywords"),
        "include_titles": _list("include_titles"),
        "customer_service_title_terms": _list("customer_service_title_terms"),
        "customer_service_require_part_time": bool(
            search_cfg.get(
                "customer_service_require_part_time",
                filters.get("customer_service_require_part_time", False),
            )
        ),
        "customer_service_max_hours_per_week": int(
            search_cfg.get(
                "customer_service_max_hours_per_week",
                filters.get("customer_service_max_hours_per_week", 0),
            )
            or 0
        ),
        "allow_unknown_location": bool(
            search_cfg.get("allow_unknown_location", filters.get("allow_unknown_location", True))
        ),
        "trusted_local_sites": _list("trusted_local_sites"),
        "remote_preference": str(
            search_cfg.get("remote_preference")
            or filters.get("remote_preference")
            or "any"
        ).strip().lower(),
    }


def _title_ok(title: str | None, excludes: list[str]) -> bool:
    """Return False if title matches any exclude pattern."""
    return title_ok(title, excludes)


def _title_include_ok(title: str | None, includes: list[str]) -> bool:
    """Return True when title matches configured target role terms."""
    if not includes:
        return True
    if not title:
        return False
    t = title.lower()
    return any(term in t for term in includes)


def _row_text(row) -> str:
    """Combine safe job fields for keyword filtering."""
    parts = []
    for key in ("title", "company", "location", "description"):
        val = row.get(key, "")
        if val is not None and str(val) != "nan":
            parts.append(str(val))
    return " ".join(parts).lower()


_REMOTE_BLOCKING_PHRASES = (
    "primarily on-site",
    "primarily onsite",
    "on-site full-time",
    "onsite full-time",
    "full-time on-site",
    "full time on-site",
    "full-time onsite",
    "full time onsite",
    "required to work on-site",
    "required to work onsite",
    "must be willing to work on-site",
    "must be willing to work onsite",
    "does not offer any virtual",
    "no virtual or telecommute",
    "no telecommute",
    "not remote",
    "not a remote",
    "not eligible for remote",
)


def _row_is_effectively_remote(row) -> bool:
    """Treat board remote tags as advisory, not authoritative."""
    text = _row_text(row)
    if any(phrase in text for phrase in _REMOTE_BLOCKING_PHRASES):
        return False

    location = str(row.get("location", "") or "").lower()
    return bool(row.get("is_remote", False)) or any(
        token in f"{location} {text}"
        for token in REMOTE_TERMS
    )


def _company_ok(company: str | None, blacklist: list[str]) -> bool:
    if not company or not blacklist:
        return True
    c = company.lower()
    return not any(blocked in c for blocked in blacklist)


def _term_in_text(text: str, term: str) -> bool:
    """Match config terms without letting short tokens hit inside words."""
    return term_in_text(text, term)


def _keywords_ok(text: str, required: list[str], excluded: list[str]) -> bool:
    if required and not all(_term_in_text(text, keyword) for keyword in required):
        return False
    return not any(_term_in_text(text, keyword) for keyword in excluded)


def _customer_service_hours_ok(title: str | None, text: str, filter_rules: dict) -> bool:
    """Keep customer-service side work only when configured as low-hour part-time."""
    terms = filter_rules.get("customer_service_title_terms", [])
    if not terms or not title:
        return True
    title_l = title.lower()
    if not any(term in title_l for term in terms):
        return True

    if not filter_rules.get("customer_service_require_part_time"):
        return True

    text_l = text.lower()
    if any(term in text_l for term in ("full-time", "full time", "40 hours", "40 hrs")):
        return False
    if not any(term in text_l for term in ("part-time", "part time", "parttime", "temporary", "seasonal")):
        return False

    max_hours = int(filter_rules.get("customer_service_max_hours_per_week") or 0)
    if max_hours <= 0:
        return True

    hour_values: list[int] = []
    for match in re.finditer(r"(\d{1,2})\s*(?:-|to)\s*(\d{1,2})\s*(?:hours|hrs)", text_l):
        hour_values.append(int(match.group(2)))
    for match in re.finditer(r"(\d{1,2})\s*(?:hours|hrs)\s*(?:per week|/week|weekly)?", text_l):
        hour_values.append(int(match.group(1)))
    if not hour_values:
        return any(term in text_l for term in ("few hours", "couple hours", "as needed", "occasional"))
    return max(hour_values) <= max_hours


def _remote_preference_ok(row, preference: str) -> bool:
    """Best-effort remote/on-site preference filter."""
    if preference in ("", "any", "all", "no_preference", "none"):
        return True

    location = str(row.get("location", "") or "").lower()
    description = str(row.get("description", "") or "").lower()
    is_remote = _row_is_effectively_remote(row)
    is_hybrid = "hybrid" in f"{location} {description}"
    is_onsite = any(token in f"{location} {description}" for token in ("onsite", "on-site", "in office"))

    if preference in ("remote", "remote_only"):
        return is_remote
    if preference in ("hybrid", "hybrid_only"):
        return is_hybrid
    if preference in ("onsite", "on_site", "office"):
        return is_onsite or not is_remote
    return True


def _job_row_passes_filters(row, filter_rules: dict) -> bool:
    """Apply optional company/keyword/remote filters to one JobSpy row."""
    title = str(row.get("title", "")) if str(row.get("title", "")) != "nan" else None
    company = str(row.get("company", "")) if str(row.get("company", "")) != "nan" else None
    text = _row_text(row)
    return (
        _title_include_ok(title, filter_rules.get("include_titles", []))
        and _company_ok(company, filter_rules.get("company_blacklist", []))
        and _keywords_ok(
            text,
            filter_rules.get("required_keywords", []),
            filter_rules.get("excluded_keywords", []),
        )
        and _customer_service_hours_ok(title, text, filter_rules)
        and _remote_preference_ok(row, filter_rules.get("remote_preference", "any"))
    )


def _location_ok(
    location: str | None,
    accept: list[str],
    reject: list[str],
    *,
    allow_unknown: bool = True,
    is_remote: bool = False,
) -> bool:
    """Check if a job location passes the user's location filter.

    Remote jobs are accepted unless their concrete location matches a rejected
    place. Non-remote jobs must match an accept pattern.
    """
    return location_ok(location, accept, reject, allow_unknown=allow_unknown, is_remote=is_remote)


# -- DB storage (JobSpy DataFrame -> SQLite) ---------------------------------

def store_jobspy_results(conn: sqlite3.Connection, df, source_label: str) -> tuple[int, int]:
    """Store JobSpy DataFrame results into the DB. Returns (new, existing)."""
    now = datetime.now(timezone.utc).isoformat()
    new = 0
    existing = 0
    prepared: list[dict] = []

    for _, row in df.iterrows():
        url = str(row.get("job_url", ""))
        if not url or url == "nan":
            continue

        title = str(row.get("title", "")) if str(row.get("title", "")) != "nan" else None
        company = str(row.get("company", "")) if str(row.get("company", "")) != "nan" else None
        location_str = str(row.get("location", "")) if str(row.get("location", "")) != "nan" else None

        # Build salary string from min/max
        salary = None
        min_amt = row.get("min_amount")
        max_amt = row.get("max_amount")
        interval = str(row.get("interval", "")) if str(row.get("interval", "")) != "nan" else ""
        currency = str(row.get("currency", "")) if str(row.get("currency", "")) != "nan" else ""
        if min_amt and str(min_amt) != "nan":
            if max_amt and str(max_amt) != "nan":
                salary = f"{currency}{int(float(min_amt)):,}-{currency}{int(float(max_amt)):,}"
            else:
                salary = f"{currency}{int(float(min_amt)):,}"
            if interval:
                salary += f"/{interval}"

        description = str(row.get("description", "")) if str(row.get("description", "")) != "nan" else None
        site_name = str(row.get("site", source_label))
        is_remote = _row_is_effectively_remote(row)
        canonical_key = canonical_job_key(title, company, location_str)

        site_label = f"{site_name}"
        if is_remote:
            location_str = f"{location_str} (Remote)" if location_str else "Remote"

        strategy = "jobspy"

        # If JobSpy gave us a full description, promote it directly
        full_description = None
        detail_scraped_at = None
        if description and len(description) > 200:
            full_description = description
            detail_scraped_at = now

        # Extract apply URL if JobSpy provided it
        apply_url = str(row.get("job_url_direct", "")) if str(row.get("job_url_direct", "")) != "nan" else None

        prepared.append({
            "url": url,
            "canonical_key": canonical_key,
            "title": title,
            "company": company,
            "salary": salary,
            "description": description,
            "location": location_str,
            "site": site_label,
            "strategy": strategy,
            "full_description": full_description,
            "application_url": apply_url,
            "detail_scraped_at": detail_scraped_at,
        })

    existing_keys = get_existing_canonical_keys(
        conn,
        {job["canonical_key"] for job in prepared if job["canonical_key"]},
    )
    seen_keys: set[str] = set()

    for job in prepared:
        try:
            canonical_key = job["canonical_key"]
            if canonical_key:
                if canonical_key in existing_keys or canonical_key in seen_keys:
                    existing += 1
                    continue
                seen_keys.add(canonical_key)
            conn.execute(
                "INSERT INTO jobs (url, canonical_key, title, company, salary, description, location, site, strategy, discovered_at, "
                "full_description, application_url, detail_scraped_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    job["url"],
                    canonical_key,
                    job["title"],
                    job["company"],
                    job["salary"],
                    job["description"],
                    job["location"],
                    job["site"],
                    job["strategy"],
                    now,
                    job["full_description"],
                    job["application_url"],
                    job["detail_scraped_at"],
                ),
            )
            new += 1
        except sqlite3.IntegrityError:
            existing += 1

    conn.commit()
    return new, existing


# -- Single search execution -------------------------------------------------

def _run_one_search(
    search: dict,
    sites: list[str],
    results_per_site: int,
    hours_old: int,
    proxy_config: dict | None,
    defaults: dict,
    max_retries: int,
    accept_locs: list[str],
    reject_locs: list[str],
    glassdoor_map: dict,
    title_excludes: list[str] | None = None,
    filter_rules: dict | None = None,
) -> dict:
    """Run a single search query and store results in DB."""
    s = search
    label = f"\"{s['query']}\" in {s['location']} {'(remote)' if s.get('remote') else ''}"
    if "tier" in s:
        label += f" [tier {s['tier']}]"

    # Split sites: Glassdoor needs simplified location, others use original
    gd_location = glassdoor_map.get(s["location"], s["location"].split(",")[0])
    has_glassdoor = "glassdoor" in sites
    other_sites = [si for si in sites if si != "glassdoor"]

    all_dfs = []
    board_stats: dict = {}

    # Run non-Glassdoor sites with original location
    if other_sites:
        kwargs = {
            "site_name": other_sites,
            "search_term": s["query"],
            "location": s["location"],
            "results_wanted": results_per_site,
            "hours_old": hours_old,
            "description_format": "markdown",
            "country_indeed": defaults.get("country_indeed", "usa"),
            "verbose": 0,
        }
        if s.get("remote"):
            kwargs["is_remote"] = True
        if proxy_config:
            kwargs["proxies"] = [proxy_config["jobspy"]]
        if "linkedin" in other_sites:
            kwargs["linkedin_fetch_description"] = True
        try:
            started = time.perf_counter()
            df = _scrape_with_retry(kwargs, max_retries=max_retries)
            _record_scrape_stats(board_stats, other_sites, elapsed=time.perf_counter() - started, total=len(df))
            all_dfs.append(df)
        except Exception as e:
            _record_scrape_stats(board_stats, other_sites, elapsed=0.0, errors=1)
            log.error("[%s] (non-gd): %s", label, e)

    # Run Glassdoor separately with simplified location
    if has_glassdoor:
        gd_kwargs = {
            "site_name": ["glassdoor"],
            "search_term": s["query"],
            "location": gd_location,
            "results_wanted": results_per_site,
            "hours_old": hours_old,
            "description_format": "markdown",
            "verbose": 0,
        }
        if s.get("remote"):
            gd_kwargs["is_remote"] = True
        if proxy_config:
            gd_kwargs["proxies"] = [proxy_config["jobspy"]]
        try:
            started = time.perf_counter()
            gd_df = _scrape_with_retry(gd_kwargs, max_retries=max_retries)
            _record_scrape_stats(board_stats, ["glassdoor"], elapsed=time.perf_counter() - started, total=len(gd_df))
            all_dfs.append(gd_df)
        except Exception as e:
            _record_scrape_stats(board_stats, ["glassdoor"], elapsed=0.0, errors=1)
            log.error("[%s] (glassdoor): %s", label, e)

    if not all_dfs:
        log.error("[%s]: all sites failed", label)
        return {"new": 0, "existing": 0, "errors": 1, "filtered": 0, "total": 0, "label": label, "board_stats": _finalize_board_stats(board_stats)}

    import pandas as pd
    import warnings
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", FutureWarning)
        df = pd.concat(all_dfs, ignore_index=True) if len(all_dfs) > 1 else all_dfs[0]

    if len(df) == 0:
        log.info("[%s] 0 results", label)
        return {"new": 0, "existing": 0, "errors": 0, "filtered": 0, "total": 0, "label": label, "board_stats": _finalize_board_stats(board_stats)}

    # Filter by location before storing
    before = len(df)
    df = df[df.apply(lambda row: _location_ok(
        str(row.get("location", "")) if str(row.get("location", "")) != "nan" else None,
        accept_locs,
        reject_locs,
        allow_unknown=(filter_rules or {}).get("allow_unknown_location", True),
        is_remote=_row_is_effectively_remote(row),
    ), axis=1)]
    filtered_loc = before - len(df)

    # Filter by title exclusion list
    filtered_title = 0
    if title_excludes:
        before_title = len(df)
        df = df[df.apply(lambda row: _title_ok(
            str(row.get("title", "")) if str(row.get("title", "")) != "nan" else None,
            title_excludes,
        ), axis=1)]
        filtered_title = before_title - len(df)

    filtered_rules = 0
    if filter_rules:
        before_rules = len(df)
        df = df[df.apply(lambda row: _job_row_passes_filters(row, filter_rules), axis=1)]
        filtered_rules = before_rules - len(df)

    conn = get_connection()
    new, existing = store_jobspy_results(conn, df, s["query"])
    if board_stats:
        total_calls = sum(max(1, int(stats.get("calls", 0))) for stats in board_stats.values())
        for stats in board_stats.values():
            weight = max(1, int(stats.get("calls", 0))) / total_calls
            stats["new"] += int(round(new * weight))
            stats["existing"] += int(round(existing * weight))

    msg = f"[{label}] {before} results -> {new} new, {existing} dupes"
    if filtered_loc:
        msg += f", {filtered_loc} filtered (location)"
    if filtered_title:
        msg += f", {filtered_title} filtered (title)"
    if filtered_rules:
        msg += f", {filtered_rules} filtered (rules)"
    log.info(msg)

    return {
        "new": new,
        "existing": existing,
        "errors": 0,
        "filtered": filtered_loc + filtered_title + filtered_rules,
        "total": before,
        "label": label,
        "board_stats": _finalize_board_stats(board_stats),
    }


# -- Single query search -----------------------------------------------------

def search_jobs(
    query: str,
    location: str,
    sites: list[str] | None = None,
    remote_only: bool = False,
    results_per_site: int = 50,
    hours_old: int = 72,
    proxy: str | None = None,
    country_indeed: str = "usa",
) -> dict:
    """Run a single job search via JobSpy and store results in DB."""
    if sites is None:
        sites = ["indeed", "linkedin", "zip_recruiter"]

    proxy_config = parse_proxy(proxy) if proxy else None

    log.info("Search: \"%s\" in %s | sites=%s | remote=%s", query, location, sites, remote_only)

    kwargs = {
        "site_name": sites,
        "search_term": query,
        "location": location,
        "results_wanted": results_per_site,
        "hours_old": hours_old,
        "description_format": "markdown",
        "country_indeed": country_indeed,
        "verbose": 2,
    }

    if remote_only:
        kwargs["is_remote"] = True

    if proxy_config:
        kwargs["proxies"] = [proxy_config["jobspy"]]

    if "linkedin" in sites:
        kwargs["linkedin_fetch_description"] = True

    try:
        df = _scrape_with_retry(kwargs)
    except Exception as e:
        log.error("JobSpy search failed: %s", e)
        return {"error": str(e), "total": 0, "new": 0, "existing": 0}

    total = len(df)
    log.info("JobSpy returned %d results", total)

    if total == 0:
        return {"total": 0, "new": 0, "existing": 0}

    if "site" in df.columns:
        site_counts = df["site"].value_counts()
        for site, count in site_counts.items():
            log.info("  %s: %d", site, count)

    conn = init_db()
    new, existing = store_jobspy_results(conn, df, query)
    log.info("Stored: %d new, %d already in DB", new, existing)

    db_total = conn.execute("SELECT COUNT(*) FROM jobs").fetchone()[0]
    pending = conn.execute("SELECT COUNT(*) FROM jobs WHERE detail_scraped_at IS NULL").fetchone()[0]
    log.info("DB total: %d jobs, %d pending detail scrape", db_total, pending)

    return {"total": total, "new": new, "existing": existing}


# -- Full crawl (all queries x all locations) --------------------------------

def _full_crawl(
    search_cfg: dict,
    tiers: list[int] | None = None,
    locations: list[str] | None = None,
    sites: list[str] | None = None,
    results_per_site: int = 100,
    hours_old: int = 72,
    proxy: str | None = None,
    max_retries: int = 2,
    workers: int = 4,
) -> dict:
    """Run all search queries from search config across all locations.

    Workers > 1 runs multiple searches in parallel (network I/O bound).
    Each worker uses a randomised delay so job boards see staggered requests.
    """
    if sites is None:
        sites = ["indeed", "linkedin", "zip_recruiter"]

    # Build search combinations from config
    queries = search_cfg.get("queries", [])
    locs = search_cfg.get("locations", [])
    defaults = search_cfg.get("defaults", {})
    glassdoor_map = search_cfg.get("glassdoor_location_map", {})
    accept_locs, reject_locs = _load_location_config(search_cfg)
    title_excludes = _load_title_excludes(search_cfg)
    filter_rules = _load_filter_rules(search_cfg)

    if tiers:
        queries = [q for q in queries if q.get("tier") in tiers]
    if locations:
        locs = [loc for loc in locs if loc.get("label") in locations]

    searches = []
    for q in queries:
        for loc in locs:
            searches.append({
                "query": q["query"],
                "location": loc["location"],
                "remote": loc.get("remote", False),
                "tier": q.get("tier", 0),
            })

    # Support per-worker proxy rotation: proxy can be a single string or
    # a comma-separated list ("host:port:user:pass,host2:port2:user2:pass2").
    proxy_list: list[dict | None] = [None]
    if proxy:
        raw_proxies = [p.strip() for p in proxy.split(",") if p.strip()]
        proxy_list = [parse_proxy(p) for p in raw_proxies]

    log.info("Full crawl: %d search combinations | workers=%d | proxies=%d",
             len(searches), workers, len([p for p in proxy_list if p]))
    log.info("Sites: %s | Results/site: %d | Hours old: %d",
             ", ".join(sites), results_per_site, hours_old)

    # Ensure DB schema is ready
    init_db()

    _lock = threading.Lock()
    total_new = 0
    total_existing = 0
    total_errors = 0
    completed = 0
    board_stats: dict = {}

    def _run_search(idx_search: tuple[int, dict]) -> dict:
        import random
        idx, s = idx_search
        # Round-robin proxy assignment per search
        proxy_cfg = proxy_list[idx % len(proxy_list)]
        # Stagger start times so workers don't all hit the same site at once
        time.sleep(random.uniform(0, 1.5) * (idx % workers))
        return _run_one_search(
            s, sites, results_per_site, hours_old,
            proxy_cfg, defaults, max_retries,
            accept_locs, reject_locs, glassdoor_map,
            title_excludes,
            filter_rules,
        )

    if workers > 1:
        with ThreadPoolExecutor(max_workers=workers,
                                thread_name_prefix="jobspy") as pool:
            futures = {
                pool.submit(_run_search, (i, s)): s
                for i, s in enumerate(searches)
            }
            for future in as_completed(futures):
                result = future.result()
                with _lock:
                    total_new += result["new"]
                    total_existing += result["existing"]
                    total_errors += result["errors"]
                    _merge_board_stats(board_stats, result.get("board_stats"))
                    completed += 1
                    if completed % 5 == 0 or completed == len(searches):
                        log.info("Progress: %d/%d queries done (%d new, %d dupes, %d errors)",
                                 completed, len(searches), total_new, total_existing, total_errors)
    else:
        for i, s in enumerate(searches):
            result = _run_search((i, s))
            total_new += result["new"]
            total_existing += result["existing"]
            total_errors += result["errors"]
            _merge_board_stats(board_stats, result.get("board_stats"))
            completed += 1
            if completed % 5 == 0 or completed == len(searches):
                log.info("Progress: %d/%d queries done (%d new, %d dupes, %d errors)",
                         completed, len(searches), total_new, total_existing, total_errors)

    # Final stats
    conn = get_connection()
    db_total = conn.execute("SELECT COUNT(*) FROM jobs").fetchone()[0]

    log.info("Full crawl complete: %d new | %d dupes | %d errors | %d total in DB",
             total_new, total_existing, total_errors, db_total)
    finalized_board_stats = _finalize_board_stats(board_stats)
    for site, stats in finalized_board_stats.items():
        log.info(
            "Board stats: %s | %.2fs | %d raw | %d new | %d dupes | %d errors",
            site,
            stats["seconds"],
            stats["total"],
            stats["new"],
            stats["existing"],
            stats["errors"],
        )

    return {
        "new": total_new,
        "existing": total_existing,
        "errors": total_errors,
        "db_total": db_total,
        "queries": len(searches),
        "board_stats": finalized_board_stats,
    }


# -- Public entry point ------------------------------------------------------

def run_discovery(cfg: dict | None = None, workers: int = 4) -> dict:
    """Main entry point for JobSpy-based job discovery.

    Loads search queries and locations from the user's search config YAML,
    then runs a full crawl across all configured job boards.

    Args:
        cfg: Override the search configuration dict. If None, loads from
             the user's searches.yaml file.

    Returns:
        Dict with stats: new, existing, errors, db_total, queries.
    """
    if cfg is None:
        cfg = config.load_search_config()

    if not cfg:
        log.warning("No search configuration found. Run `divapply init` to create one.")
        return {"new": 0, "existing": 0, "errors": 0, "db_total": 0, "queries": 0}

    proxy = cfg.get("proxy")
    sites = cfg.get("sites") or cfg.get("boards")
    defaults = cfg.setdefault("defaults", {})
    if "country_indeed" not in defaults and cfg.get("country"):
        defaults["country_indeed"] = str(cfg["country"]).lower()
    results_per_site = cfg.get("defaults", {}).get("results_per_site", 100)
    hours_old = cfg.get("defaults", {}).get("hours_old", 72)
    tiers = cfg.get("tiers")
    locations = cfg.get("location_labels")

    crawl_workers = cfg.get("defaults", {}).get("workers", workers)

    return _full_crawl(
        search_cfg=cfg,
        tiers=tiers,
        locations=locations,
        sites=sites,
        results_per_site=results_per_site,
        hours_old=hours_old,
        proxy=proxy,
        workers=crawl_workers,
    )

