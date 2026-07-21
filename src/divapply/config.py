"""DivApply configuration: paths, platform detection, user data."""

import copy
import math
import os
import re
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

# User data directory - all user-specific files live here.
#
# New installs default to ~/.divapply, but we still read legacy ~/.applypilot
# files so existing users can migrate without losing data.
APP_DIR = Path(os.environ.get("DIVAPPLY_DIR", os.environ.get("APPLYPILOT_DIR", Path.home() / ".divapply")))
LEGACY_APP_DIR = Path(os.environ.get("APPLYPILOT_DIR", Path.home() / ".applypilot"))

# Core paths
DB_PATH = APP_DIR / "divapply.db"
PROFILE_PATH = APP_DIR / "profile.json"
RESUME_PATH = APP_DIR / "resume.txt"
RESUME_PDF_PATH = APP_DIR / "resume.pdf"
SEARCH_CONFIG_PATH = APP_DIR / "searches.yaml"
ENV_PATH = APP_DIR / ".env"
ANSWERS_PATH = APP_DIR / "answers.yaml"
CREDENTIALS_PATH = APP_DIR / "credentials.yaml"
LEGACY_DB_PATH = LEGACY_APP_DIR / "applypilot.db"
LEGACY_PROFILE_PATH = LEGACY_APP_DIR / "profile.json"
LEGACY_SEARCH_CONFIG_PATH = LEGACY_APP_DIR / "searches.yaml"
LEGACY_ENV_PATH = LEGACY_APP_DIR / ".env"

# Generated output
TAILORED_DIR = APP_DIR / "tailored_resumes"
COVER_LETTER_DIR = APP_DIR / "cover_letters"
LOG_DIR = APP_DIR / "logs"

# Chrome worker isolation
CHROME_WORKER_DIR = APP_DIR / "chrome-workers"
APPLY_WORKER_DIR = APP_DIR / "apply-workers"

# Package-shipped config (YAML registries)
PACKAGE_DIR = Path(__file__).parent
CONFIG_DIR = PACKAGE_DIR / "config"
USER_CONFIG_DIR = APP_DIR / "config"

_YAML_CACHE: dict[Path, tuple[int, int, dict[str, Any]]] = {}
_PRIVATE_USER_FILENAMES = (
    "profile.json",
    "resume.txt",
    "resume.pdf",
    "searches.yaml",
    "answers.yaml",
    "credentials.yaml",
    ".env",
    "divapply.db",
    "divapply.db-wal",
    "divapply.db-shm",
)


def _protect_private_user_root(root: Path) -> None:
    """Harden recognized sensitive files without locking nested workspaces."""
    from divapply.security import protect_file

    for name in _PRIVATE_USER_FILENAMES:
        path = root / name
        if path.exists():
            protect_file(path, strict=True)


def resolve_config_file(name: str) -> Path:
    """Return user-overridden config file if present, otherwise package default."""
    user_path = USER_CONFIG_DIR / name
    if user_path.exists():
        from divapply.security import protect_file

        protect_file(user_path, strict=True)
        return user_path
    return CONFIG_DIR / name


def ensure_dirs() -> None:
    """Create all required directories."""
    for directory in [APP_DIR, TAILORED_DIR, COVER_LETTER_DIR, LOG_DIR, CHROME_WORKER_DIR, APPLY_WORKER_DIR]:
        directory.mkdir(parents=True, exist_ok=True)


def job_matches_application_address(job: dict, address: dict) -> bool:
    """Return whether a job location matches a profile-defined alternate address."""
    location = str(job.get("location") or "").casefold()
    configured_patterns = address.get("match_patterns") or address.get("match_locations") or []
    if isinstance(configured_patterns, str):
        configured_patterns = [configured_patterns]
    if isinstance(configured_patterns, list) and any(
        str(pattern).strip().casefold() in location for pattern in configured_patterns if str(pattern).strip()
    ):
        return True

    city = str(address.get("city") or "").strip().casefold()
    state = str(address.get("province_state") or "").strip().casefold()
    return bool((city and city in location) or (state and re.search(rf"\b{re.escape(state)}\b", location)))


def profile_for_job_address(profile: dict, job: dict) -> dict:
    """Return a copy using the verified job-specific application address."""
    addresses = profile.get("application_addresses", {}) or {}
    if not isinstance(addresses, dict):
        return profile

    for address in addresses.values():
        if (
            not isinstance(address, dict)
            or address.get("is_current_legal_residence") is not True
            or not job_matches_application_address(job, address)
        ):
            continue
        adjusted = copy.deepcopy(profile)
        personal = adjusted.setdefault("personal", {})
        for key in ("address", "city", "province_state", "country", "postal_code"):
            if address.get(key):
                personal[key] = address[key]
        return adjusted
    return profile


def _read_text_with_legacy(current: Path, legacy: Path | None = None, *, encoding: str = "utf-8") -> str | None:
    """Read current user data, falling back to a legacy file."""
    if current.exists():
        return current.read_text(encoding=encoding)
    if legacy is not None and legacy.exists():
        return legacy.read_text(encoding=encoding)
    return None


def _copy_if_present(source: Path, target: Path, *, overwrite: bool = False) -> str:
    """Copy a file when available and report the action taken."""
    if not source.exists():
        return "missing"
    try:
        if source.resolve() == target.resolve():
            return "skipped"
    except Exception:
        pass
    if target.exists() and not overwrite:
        return "skipped"
    from divapply.security import copy_private_file

    copy_private_file(source, target)
    return "copied"


def migrate_legacy_user_data(
    *,
    source_dir: Path | None = None,
    target_dir: Path | None = None,
    overwrite: bool = False,
) -> dict[str, str]:
    """Copy legacy files into the current DivApply layout.

    This intentionally preserves the current files unless overwrite=True.
    The helper is used by the CLI migrate command and is safe to call on a
    fresh install or repeatedly during upgrade troubleshooting.
    """
    source_root = Path(source_dir or LEGACY_APP_DIR)
    target_root = Path(target_dir or APP_DIR)
    results = {
        "profile": _copy_if_present(source_root / "profile.json", target_root / "profile.json", overwrite=overwrite),
        "searches": _copy_if_present(source_root / "searches.yaml", target_root / "searches.yaml", overwrite=overwrite),
        "env": _copy_if_present(source_root / ".env", target_root / ".env", overwrite=overwrite),
        "resume_txt": _copy_if_present(source_root / "resume.txt", target_root / "resume.txt", overwrite=overwrite),
        "resume_pdf": _copy_if_present(source_root / "resume.pdf", target_root / "resume.pdf", overwrite=overwrite),
        "database": _copy_if_present(source_root / "applypilot.db", target_root / "divapply.db", overwrite=overwrite),
    }
    return results


def load_profile() -> dict:
    """Load user profile from ~/.divapply/profile.json."""
    import json

    source_path = PROFILE_PATH if PROFILE_PATH.exists() else LEGACY_PROFILE_PATH
    if source_path.exists():
        _protect_private_user_root(source_path.parent)
    raw = _read_text_with_legacy(PROFILE_PATH, LEGACY_PROFILE_PATH)
    if raw is None:
        raise FileNotFoundError(f"Profile not found at {PROFILE_PATH}. Run `divapply init` first.")
    profile = _normalize_profile(json.loads(raw))

    # Structured transcript facts are canonical for objective academic values.
    # Keep profile narrative editable, but never allow a stale GPA/credit count
    # to override a newer imported school record.
    try:
        from divapply.database import get_education_records

        profile = _overlay_transcript_education(profile, get_education_records())
    except Exception:
        pass

    # Hidden coursework knowledge is stored in SQLite so it can inform
    # scoring/tailoring without being exposed in the generated resume text.
    # New installs do not ship with applicant-specific coursework; users add
    # their own data through `divapply import-coursework`.
    try:
        from divapply.database import get_coursework

        coursework = get_coursework()
    except Exception:
        coursework = []

    profile["coursework"] = coursework
    try:
        search_config = load_search_config()
    except Exception:
        search_config = {}
    profile["coursework_summary"] = _summarize_coursework(coursework, search_config=search_config)
    profile["coursework_skills"] = _summarize_coursework_skills(coursework, search_config=search_config)
    return profile


def _academic_number(value: Any) -> str:
    """Format an imported numeric fact without inventing extra precision."""
    try:
        number = float(value)
    except (TypeError, ValueError):
        return str(value).strip()
    return f"{number:.3f}".rstrip("0").rstrip(".")


def _school_match_key(value: Any) -> str:
    return re.sub(r"[^a-z0-9]+", "", str(value or "").casefold())


def _overlay_transcript_education(profile: dict, records: list[dict]) -> dict:
    """Overlay canonical GPA/credit facts onto matching profile schools."""
    schools = profile.get("education_schools")
    if not isinstance(schools, list) or not records:
        return profile

    by_name = {
        _school_match_key(record.get("name")): record
        for record in records
        if isinstance(record, dict) and _school_match_key(record.get("name"))
    }
    merged_schools: list[Any] = []
    for school in schools:
        if not isinstance(school, dict):
            merged_schools.append(school)
            continue
        merged = dict(school)
        record = by_name.get(_school_match_key(school.get("school")))
        if record:
            overlaid = False
            gpa = record.get("institutional_gpa")
            earned = record.get("total_earned")
            units_scope = "total"
            if earned is None:
                earned = record.get("institutional_earned")
                units_scope = "institutional"
            if gpa is not None:
                merged["gpa"] = _academic_number(gpa)
                overlaid = True
            if earned is not None:
                merged["units"] = _academic_number(earned)
                merged["units_scope"] = units_scope
                overlaid = True
            if record.get("gpa_as_of"):
                merged["gpa_as_of"] = str(record["gpa_as_of"])
                overlaid = True
            if overlaid:
                for key in ("degree", "major", "minor"):
                    if record.get(key):
                        merged[key] = str(record[key])
                if record.get("expected_graduation_year"):
                    merged["expected_graduation_year"] = str(record["expected_graduation_year"])
                merged["education_record_source"] = "structured transcript"
        merged_schools.append(merged)

    result = dict(profile)
    result["education_schools"] = merged_schools
    return result


def _normalize_profile(profile: dict) -> dict:
    """Normalize applicant facts and discard legacy search-policy fields."""
    profile = dict(profile or {})
    profile.pop("job_search", None)
    profile.pop("availability", None)
    profile.pop("experience_inference", None)

    exp = profile.get("experience")
    if isinstance(exp, dict):
        exp = dict(exp)
        # Job-search intent belongs in searches.yaml. Keeping it out of the
        # profile prevents stale role policy from biasing scoring or applying.
        for key in ("target_role", "target_roles", "years_of_experience_total"):
            exp.pop(key, None)
        profile["experience"] = exp

    skills = profile.get("skills")
    if skills and not profile.get("skills_boundary"):
        if isinstance(skills, list):
            profile["skills_boundary"] = {"skills": skills}
        elif isinstance(skills, dict):
            profile["skills_boundary"] = skills

    comp = profile.get("compensation")
    if isinstance(comp, dict) and comp.get("hourly_expectation") and not comp.get("part_time_hourly_expectation"):
        comp = dict(comp)
        comp["part_time_hourly_expectation"] = comp["hourly_expectation"]
        profile["compensation"] = comp

    return profile


def profile_skills(profile: dict) -> dict[str, list[str]]:
    """Return profile skills from either simple `skills` or legacy `skills_boundary`."""
    boundary = profile.get("skills_boundary")
    if isinstance(boundary, dict) and boundary:
        return {
            str(category): [str(item) for item in items if str(item).strip()]
            for category, items in boundary.items()
            if isinstance(items, list)
        }

    skills = profile.get("skills")
    if isinstance(skills, list):
        return {"skills": [str(item) for item in skills if str(item).strip()]}
    if isinstance(skills, dict):
        return {
            str(category): [str(item) for item in items if str(item).strip()]
            for category, items in skills.items()
            if isinstance(items, list)
        }
    return {}


_ACADEMIC_TERM_ORDER = {"winter": 1, "spring": 2, "summer": 3, "fall": 4, "autumn": 4}
_SEARCH_TERM_STOPWORDS = {
    "and",
    "assistant",
    "associate",
    "entry",
    "level",
    "remote",
    "specialist",
    "technician",
    "the",
    "with",
}


def _academic_term_key(row: dict) -> tuple[int, int, str]:
    term = str(row.get("term") or "").casefold()
    year_match = re.search(r"(?:19|20)\d{2}", term)
    year = int(year_match.group()) if year_match else 0
    season = max((order for name, order in _ACADEMIC_TERM_ORDER.items() if name in term), default=0)
    title = str(row.get("course_title") or row.get("course_code") or "").casefold()
    return year, season, title


def _coursework_relevance_terms(search_config: dict | None) -> set[str]:
    config = search_config or {}
    sources: list[str] = []
    families = config.get("target_families")
    if isinstance(families, list):
        sources.extend(str(item.get("name") or "") for item in families if isinstance(item, dict))
    if not sources:
        queries = config.get("queries")
        if isinstance(queries, list):
            sources.extend(str(item.get("query") or "") for item in queries if isinstance(item, dict))
    return {
        token
        for token in re.findall(r"[a-z0-9+#]+", " ".join(sources).casefold())
        if len(token) >= 3 and token not in _SEARCH_TERM_STOPWORDS
    }


def _coursework_item(row: dict) -> str:
    title = str(row.get("course_title") or row.get("course_code") or "").strip()
    subject = str(row.get("subject_area") or "").strip()
    if title and subject:
        return f"{title} [{subject}]"
    return title or subject


def _coursework_relevance_score(row: dict, terms: set[str]) -> int:
    raw_skills = row.get("skills") or []
    if isinstance(raw_skills, str):
        raw_skill_text = raw_skills
    elif isinstance(raw_skills, list):
        raw_skill_text = " ".join(str(skill) for skill in raw_skills)
    else:
        raw_skill_text = ""
    haystack = (
        " ".join(str(row.get(key) or "") for key in ("course_title", "course_code", "subject_area", "notes"))
        + " "
        + raw_skill_text
    )
    lowered = haystack.casefold()
    return sum(1 for term in terms if term in lowered)


def _coursework_context_policy(search_config: dict | None) -> dict[str, Any]:
    raw = (search_config or {}).get("coursework_context")
    valid = raw is None or isinstance(raw, dict)
    policy = raw if isinstance(raw, dict) else {}

    def _patterns(key: str) -> list[str]:
        nonlocal valid
        value = policy.get(key)
        if value is None:
            return []
        if not isinstance(value, list):
            valid = False
            return []
        if any(not isinstance(item, str) for item in value):
            valid = False
        return [item.strip().casefold() for item in value if isinstance(item, str) and item.strip()]

    try:
        raw_max = policy.get("max_per_school", 12)
        if isinstance(raw_max, bool):
            raise ValueError
        max_per_school = int(raw_max)
    except (TypeError, ValueError):
        valid = False
        max_per_school = 12
    if not 1 <= max_per_school <= 24:
        valid = False
    return {
        "include_patterns": _patterns("include_patterns"),
        "exclude_patterns": _patterns("exclude_patterns"),
        "skill_exclude_patterns": _patterns("skill_exclude_patterns"),
        "max_per_school": max(1, min(24, max_per_school)),
        "valid": valid,
    }


def _coursework_row_is_eligible(row: dict, policy: dict[str, Any]) -> bool:
    if not policy.get("valid", False):
        return False
    status = str(row.get("status") or "").strip().casefold()
    if status not in {"completed", "complete", "passed", "accepted", "transfer credit", "transferred"}:
        return False

    credits = row.get("credits")
    try:
        numeric_credits = float(str(credits).strip())
    except (TypeError, ValueError):
        return False
    if isinstance(credits, bool) or not math.isfinite(numeric_credits) or numeric_credits <= 0:
        return False

    haystack = " ".join(
        str(row.get(key) or "")
        for key in ("course_title", "course_code", "subject_area", "notes")
    ).casefold()
    excludes = policy["exclude_patterns"]
    if any(pattern in haystack for pattern in excludes):
        return False
    includes = policy["include_patterns"]
    return not includes or any(pattern in haystack for pattern in includes)


def _select_coursework_rows(
    coursework: list[dict],
    *,
    search_config: dict | None = None,
    max_per_school: int | None = None,
) -> dict[str, list[dict]]:
    policy = _coursework_context_policy(search_config)
    limit = policy["max_per_school"] if max_per_school is None else max(1, min(24, max_per_school))
    grouped: dict[str, list[dict]] = {}
    for row in coursework:
        school = str(row.get("school") or "Unknown school").strip()
        if _coursework_item(row) and _coursework_row_is_eligible(row, policy):
            grouped.setdefault(school, []).append(row)

    relevance_terms = _coursework_relevance_terms(search_config)
    selected_by_school: dict[str, list[dict]] = {}
    for school, rows in grouped.items():
        newest = sorted(rows, key=_academic_term_key, reverse=True)
        relevant = sorted(
            (row for row in rows if _coursework_relevance_score(row, relevance_terms) > 0),
            key=lambda row: (_coursework_relevance_score(row, relevance_terms), _academic_term_key(row)),
            reverse=True,
        )
        selected: list[dict] = []
        seen: set[tuple[str, str, str]] = set()
        for row in [*relevant, *newest]:
            identity = (
                str(row.get("course_code") or "").strip().casefold(),
                str(row.get("course_title") or "").strip().casefold(),
                str(row.get("term") or "").strip().casefold(),
            )
            if identity in seen:
                continue
            seen.add(identity)
            selected.append(row)
            if len(selected) >= limit:
                break
        if selected:
            selected_by_school[school] = selected
    return selected_by_school


def _summarize_coursework(
    coursework: list[dict],
    *,
    search_config: dict | None = None,
    max_per_school: int = 12,
) -> list[str]:
    """Condense coursework into recent/search-relevant internal-only facts."""
    if not coursework:
        return []

    policy = _coursework_context_policy(search_config)
    configured_limit = policy["max_per_school"]
    limit = configured_limit if isinstance((search_config or {}).get("coursework_context"), dict) else max_per_school
    grouped = _select_coursework_rows(coursework, search_config=search_config, max_per_school=limit)
    summary: list[str] = []
    for school, rows in grouped.items():
        summary.append(f"{school}: {', '.join(_coursework_item(row) for row in rows)}")
    return summary


def _summarize_coursework_skills(
    coursework: list[dict],
    *,
    search_config: dict | None = None,
) -> list[str]:
    """Aggregate coursework skill tags into a compact internal-only summary."""
    if not coursework:
        return []

    policy = _coursework_context_policy(search_config)
    selected = _select_coursework_rows(coursework, search_config=search_config)
    grouped: dict[str, set[str]] = {}
    for school, rows in selected.items():
        for row in rows:
            raw_skills = row.get("skills") or []
            if isinstance(raw_skills, str):
                try:
                    import json

                    raw_skills = json.loads(raw_skills)
                except Exception:
                    raw_skills = [s.strip() for s in raw_skills.split(",") if s.strip()]
            if not isinstance(raw_skills, list):
                continue
            for skill in raw_skills:
                skill_text = str(skill).strip()
                if not skill_text:
                    continue
                lowered = skill_text.casefold()
                if any(pattern in lowered for pattern in policy["skill_exclude_patterns"]):
                    continue
                grouped.setdefault(school, set()).add(skill_text)

    summary: list[str] = []
    for school, skills in grouped.items():
        summary.append(f"{school}: {', '.join(sorted(skills))}")
    return summary


def load_search_config() -> dict:
    """Load search configuration from ~/.divapply/searches.yaml."""
    import yaml

    source_path = SEARCH_CONFIG_PATH if SEARCH_CONFIG_PATH.exists() else LEGACY_SEARCH_CONFIG_PATH
    if source_path.exists():
        _protect_private_user_root(source_path.parent)
    raw = _read_text_with_legacy(SEARCH_CONFIG_PATH, LEGACY_SEARCH_CONFIG_PATH)
    if raw is None:
        example = CONFIG_DIR / "searches.example.yaml"
        if example.exists():
            return normalize_search_config(yaml.safe_load(example.read_text(encoding="utf-8")) or {})
        return {}
    return normalize_search_config(yaml.safe_load(raw) or {})


def normalize_search_config(cfg: dict | None) -> dict:
    """Expand simple search config aliases into the internal filter schema."""
    cfg = dict(cfg or {})

    search_city = cfg.get("search_city") or cfg.get("city")
    if search_city and not cfg.get("locations"):
        cfg["locations"] = [{"label": str(search_city), "location": str(search_city)}]

    if cfg.get("job_boards") and not cfg.get("boards"):
        cfg["boards"] = cfg["job_boards"]
    if cfg.get("boards") and not cfg.get("sites"):
        cfg["sites"] = cfg["boards"]
    if cfg.get("sites") and not cfg.get("boards"):
        cfg["boards"] = cfg["sites"]

    if cfg.get("search_terms") and not cfg.get("queries"):
        queries = []
        for item in cfg["search_terms"]:
            if isinstance(item, dict):
                queries.append({"query": item.get("query") or item.get("term"), "tier": item.get("tier", 1)})
            else:
                queries.append({"query": str(item), "tier": 1})
        cfg["queries"] = [q for q in queries if q.get("query")]

    if cfg.get("nearby_locations") and not cfg.get("location_accept"):
        cfg["location_accept"] = cfg["nearby_locations"]
    if cfg.get("reject_locations") and not cfg.get("location_reject_non_remote"):
        cfg["location_reject_non_remote"] = cfg["reject_locations"]

    location_cfg = dict(cfg.get("location", {}) or {})
    if cfg.get("location_accept") and not location_cfg.get("accept_patterns"):
        location_cfg["accept_patterns"] = cfg["location_accept"]
    if cfg.get("location_reject_non_remote") and not location_cfg.get("reject_patterns"):
        location_cfg["reject_patterns"] = cfg["location_reject_non_remote"]
    if location_cfg:
        cfg["location"] = location_cfg

    if cfg.get("target_titles") and not cfg.get("include_titles"):
        cfg["include_titles"] = cfg["target_titles"]
    if cfg.get("avoid_titles") and not cfg.get("exclude_titles"):
        cfg["exclude_titles"] = cfg["avoid_titles"]
    if cfg.get("avoid_keywords") and not cfg.get("excluded_keywords"):
        cfg["excluded_keywords"] = cfg["avoid_keywords"]
    if cfg.get("trusted_sites") and not cfg.get("trusted_local_sites"):
        cfg["trusted_local_sites"] = cfg["trusted_sites"]

    if cfg.get("part_time_titles") and not cfg.get("customer_service_title_terms"):
        cfg["customer_service_title_terms"] = cfg["part_time_titles"]
    if "require_part_time" in cfg and "customer_service_require_part_time" not in cfg:
        cfg["customer_service_require_part_time"] = bool(cfg["require_part_time"])
    if "max_hours_per_week" in cfg and "customer_service_max_hours_per_week" not in cfg:
        cfg["customer_service_max_hours_per_week"] = cfg["max_hours_per_week"]

    return cfg


def _known_location_labels(locations: list[object]) -> set[str]:
    return {
        str(location.get("label") or location.get("location") or "").strip()
        for location in locations
        if isinstance(location, dict)
    }


def _validate_search_queries(
    queries: list[object],
    known_location_labels: set[str],
    errors: list[str],
) -> None:
    for index, query in enumerate(queries):
        if not isinstance(query, dict) or not query.get("query"):
            errors.append(f"queries[{index}] needs a query string")
    for index, query in enumerate(queries):
        if not isinstance(query, dict):
            continue
        scopes = query.get("location_labels")
        if scopes is None:
            continue
        if not isinstance(scopes, list):
            errors.append(f"queries[{index}].location_labels must be a list")
            continue
        for scope in scopes:
            scope_text = str(scope).strip()
            if scope_text not in known_location_labels:
                errors.append(f"queries[{index}].location_labels contains unknown location '{scope_text}'")


def _validate_search_locations(locations: list[object], errors: list[str]) -> None:
    for index, location in enumerate(locations):
        if not isinstance(location, dict) or not location.get("location"):
            errors.append(f"locations[{index}] needs a location string")
            continue
        patterns = location.get("match_patterns")
        if patterns is not None and (
            not isinstance(patterns, list)
            or any(not isinstance(pattern, str) or "," not in pattern for pattern in patterns)
        ):
            errors.append(f"locations[{index}].match_patterns must be state-qualified strings")


def _validate_target_families(cfg: dict, errors: list[str]) -> None:
    target_families = cfg.get("target_families", [])
    if target_families and not isinstance(target_families, list):
        errors.append("target_families must be a list")
    for index, family in enumerate(target_families if isinstance(target_families, list) else []):
        if not isinstance(family, dict):
            errors.append(f"target_families[{index}] must be a mapping")
            continue
        if not str(family.get("name") or "").strip():
            errors.append(f"target_families[{index}] needs a name")
        priority = family.get("priority")
        try:
            valid_priority = not isinstance(priority, bool) and int(str(priority)) in {1, 2, 3}
        except (TypeError, ValueError):
            valid_priority = False
        if not valid_priority:
            errors.append(f"target_families[{index}].priority must be an integer from 1 to 3")


def _bounded_integer(value: object, lower: int, upper: int) -> bool:
    if isinstance(value, bool) or not isinstance(value, (int, str)):
        return False
    try:
        return lower <= int(value) <= upper
    except ValueError:
        return False


def _validate_market_policy_entry(
    label: object,
    policy: object,
    known_location_labels: set[str],
    errors: list[str],
) -> None:
    label_text = str(label).strip()
    prefix = f"market_policies.{label_text}"
    if label_text not in known_location_labels:
        errors.append(f"market_policies contains unknown location label '{label_text}'")
    if not isinstance(policy, dict):
        errors.append(f"{prefix} must be a mapping")
        return
    schedule = str(policy.get("preferred_schedule") or "any").strip().casefold()
    if schedule not in {"any", "full_time", "part_time"}:
        errors.append(f"{prefix}.preferred_schedule is invalid")
    for key in ("require_part_time", "require_benefits"):
        if key in policy and not isinstance(policy[key], bool):
            errors.append(f"{prefix}.{key} must be boolean")
    for key in (
        "include_titles",
        "company_blacklist",
        "required_keywords",
        "excluded_keywords",
        "customer_service_title_terms",
        "trusted_local_sites",
    ):
        if key in policy and (
            not isinstance(policy[key], list)
            or any(not isinstance(item, str) for item in policy[key])
        ):
            errors.append(f"{prefix}.{key} must be a list of strings")
    application_mode = str(policy.get("application_mode") or "manual_review").strip().casefold()
    if application_mode not in {"active", "discovery_only", "manual_review"}:
        errors.append(f"{prefix}.application_mode is invalid")
    if "max_hours_per_week" in policy and not _bounded_integer(policy["max_hours_per_week"], 1, 168):
        errors.append(f"{prefix}.max_hours_per_week must be an integer from 1 to 168")


def _validate_market_policies(raw_cfg: dict, known_location_labels: set[str], errors: list[str]) -> None:
    market_policies = raw_cfg.get("market_policies")
    if market_policies is None:
        return
    if not isinstance(market_policies, dict):
        errors.append("market_policies must be a mapping")
        return
    default_market_label = str(raw_cfg.get("default_market_label") or "").strip()
    if default_market_label not in known_location_labels:
        errors.append("default_market_label must name a configured location label")
    for label, policy in market_policies.items():
        _validate_market_policy_entry(label, policy, known_location_labels, errors)


def _validate_coursework_context(raw_cfg: dict, errors: list[str]) -> None:
    coursework_context = raw_cfg.get("coursework_context")
    if coursework_context is None:
        return
    if not isinstance(coursework_context, dict):
        errors.append("coursework_context must be a mapping")
        return
    for key in ("include_patterns", "exclude_patterns", "skill_exclude_patterns"):
        value = coursework_context.get(key)
        if value is not None and (
            not isinstance(value, list) or any(not isinstance(item, str) for item in value)
        ):
            errors.append(f"coursework_context.{key} must be a list")
    if not _bounded_integer(coursework_context.get("max_per_school", 12), 1, 24):
        errors.append("coursework_context.max_per_school must be an integer from 1 to 24")


def _validate_board_fields(cfg: dict, errors: list[str], warnings: list[str]) -> None:
    sites_value = cfg.get("sites")
    boards_value = cfg.get("boards")
    boards = sites_value or boards_value or []
    if boards and not isinstance(boards, list):
        errors.append("sites/boards must be a list")
    if sites_value and boards_value and sites_value != boards_value:
        warnings.append("sites and boards differ; discovery will prefer sites")


def _validate_list_filter_fields(cfg: dict, errors: list[str]) -> None:
    filters = cfg.get("filters", {}) or {}
    list_fields = (
        "exclude_titles",
        "title_blacklist",
        "company_blacklist",
        "required_keywords",
        "excluded_keywords",
        "include_titles",
        "customer_service_title_terms",
        "trusted_local_sites",
        "location_accept",
        "location_reject_non_remote",
    )
    for key in list_fields:
        value = cfg.get(key, filters.get(key, []))
        if value and not isinstance(value, list):
            errors.append(f"{key} must be a list")


def _validate_location_filter_fields(cfg: dict, errors: list[str]) -> None:
    location_cfg = cfg.get("location", {}) or {}
    for key in ("accept_patterns", "reject_patterns"):
        value = location_cfg.get(key, [])
        if value and not isinstance(value, list):
            errors.append(f"location.{key} must be a list")


def _validate_filter_fields(cfg: dict, errors: list[str], warnings: list[str]) -> None:
    _validate_board_fields(cfg, errors, warnings)
    _validate_list_filter_fields(cfg, errors)
    _validate_location_filter_fields(cfg, errors)


def _validate_search_limits_and_location_tokens(cfg: dict, errors: list[str], warnings: list[str]) -> None:
    filters = cfg.get("filters", {}) or {}
    max_hours = cfg.get(
        "customer_service_max_hours_per_week",
        filters.get("customer_service_max_hours_per_week", 0),
    )
    if max_hours not in (None, ""):
        try:
            int(max_hours)
        except (TypeError, ValueError):
            errors.append("customer_service_max_hours_per_week must be an integer")

    location_cfg = cfg.get("location", {}) or {}
    location_lists = {
        "location_accept": cfg.get("location_accept", []) or location_cfg.get("accept_patterns", []) or [],
        "location_reject_non_remote": cfg.get("location_reject_non_remote", [])
        or location_cfg.get("reject_patterns", [])
        or [],
    }
    for key, values in location_lists.items():
        for token in values:
            token_text = str(token).strip()
            if 0 < len(token_text) <= 2:
                warnings.append(f"{key} contains short token '{token_text}'; use full city/state names when possible")


def _legacy_search_warnings(raw_cfg: dict) -> list[str]:
    aliases = {
        "job_boards": "boards",
        "search_terms": "queries",
        "nearby_locations": "locations",
        "reject_locations": "location.reject_patterns",
        "target_titles": "include_titles",
        "avoid_titles": "exclude_titles",
        "avoid_keywords": "excluded_keywords",
        "trusted_sites": "trusted_local_sites",
        "part_time_titles": "customer_service_title_terms",
    }
    warnings = [
        f"{old_key} is a legacy searches.yaml key; prefer {new_key}"
        for old_key, new_key in aliases.items()
        if old_key in raw_cfg
    ]
    if "sites" in raw_cfg and ("boards" not in raw_cfg or raw_cfg.get("sites") != raw_cfg.get("boards")):
        warnings.append("sites is a legacy searches.yaml key; prefer boards")
    return warnings


def _search_collection_context(cfg: dict, errors: list[str]) -> tuple[list[object], list[object], set[str]]:
    queries = cfg.get("queries", [])
    locations = cfg.get("locations", [])
    if not isinstance(queries, list) or not queries:
        errors.append("searches.yaml needs a non-empty queries list")
    if not isinstance(locations, list) or not locations:
        errors.append("searches.yaml needs a non-empty locations list")
    query_items = queries if isinstance(queries, list) else []
    location_items = locations if isinstance(locations, list) else []
    return query_items, location_items, _known_location_labels(location_items)


def _validate_schedule_preferences(cfg: dict, errors: list[str], warnings: list[str]) -> None:
    preferred_schedule = str(cfg.get("preferred_schedule") or "any").strip().casefold()
    if preferred_schedule not in {"any", "full_time", "part_time"}:
        errors.append("preferred_schedule must be one of: any, full_time, part_time")

    filters = cfg.get("filters", {}) or {}
    remote_pref = str(cfg.get("remote_preference") or filters.get("remote_preference") or "any").lower()
    valid_remote_preferences = {
        "any",
        "all",
        "none",
        "no_preference",
        "remote",
        "remote_only",
        "hybrid",
        "hybrid_only",
        "onsite",
        "on_site",
        "office",
    }
    if remote_pref not in valid_remote_preferences:
        warnings.append(f"remote_preference '{remote_pref}' is unknown; it will be treated as any")


def validate_search_config(cfg: dict | None = None) -> dict:
    """Validate search config shape without contacting job boards."""
    if cfg is None:
        cfg = load_search_config()
    raw_cfg = dict(cfg or {})
    cfg = normalize_search_config(raw_cfg)

    errors: list[str] = []
    warnings = _legacy_search_warnings(raw_cfg)
    query_items, location_items, known_location_labels = _search_collection_context(cfg, errors)
    _validate_search_queries(query_items, known_location_labels, errors)
    _validate_search_locations(location_items, errors)
    _validate_target_families(cfg, errors)
    _validate_schedule_preferences(cfg, errors, warnings)
    _validate_market_policies(raw_cfg, known_location_labels, errors)
    _validate_coursework_context(raw_cfg, errors)
    _validate_filter_fields(cfg, errors, warnings)
    _validate_search_limits_and_location_tokens(cfg, errors, warnings)

    return {"passed": not errors, "errors": errors, "warnings": warnings}


def load_sites_config() -> dict:
    """Load sites.yaml configuration (sites list, manual_ats, blocked, etc.)."""
    import yaml

    path = resolve_config_file("sites.yaml")
    if not path.exists():
        return {}
    stat = path.stat()
    cache_key = path.resolve()
    cached = _YAML_CACHE.get(cache_key)
    if cached and cached[0] == stat.st_mtime_ns and cached[1] == stat.st_size:
        return cached[2]
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    data = data if isinstance(data, dict) else {}
    _YAML_CACHE[cache_key] = (stat.st_mtime_ns, stat.st_size, data)
    return data


def configured_official_source_name(url: str) -> str | None:
    """Return the configured official source sharing this exact HTTPS origin."""
    target = urlparse(str(url or ""))
    if target.scheme.casefold() != "https" or not target.hostname:
        return None
    cfg = load_sites_config()
    default_verification = str(cfg.get("default_source_verification") or "unknown").strip().casefold()
    sites = cfg.get("sites")
    if not isinstance(sites, list):
        return None
    for item in sites:
        if not isinstance(item, dict):
            continue
        verification = str(item.get("source_verification") or default_verification).strip().casefold()
        source = urlparse(str(item.get("url") or ""))
        if (
            verification == "official"
            and source.scheme.casefold() == "https"
            and source.hostname
            and source.hostname.casefold() == target.hostname.casefold()
            and (source.port or 443) == (target.port or 443)
        ):
            return str(item.get("name") or target.hostname).strip() or target.hostname
    return None


def load_credentials(path: Path | None = None) -> dict:
    """Load optional login credentials from ~/.divapply/credentials.yaml.

    Profile data should stay focused on candidate facts. Login material belongs
    in this separate file or environment variables.
    """
    import yaml

    credentials_path = path or CREDENTIALS_PATH
    if not credentials_path.exists():
        return {}
    _protect_private_user_root(credentials_path.parent)
    data = yaml.safe_load(credentials_path.read_text(encoding="utf-8")) or {}
    return data if isinstance(data, dict) else {}


def get_apply_timeout() -> int | None:
    """Return the per-job apply timeout in seconds, or None when explicitly disabled."""
    value = os.environ.get("DIVAPPLY_APPLY_TIMEOUT") or os.environ.get("APPLYPILOT_APPLY_TIMEOUT")
    if value:
        if value.strip().lower() in {"0", "none", "off", "false", "no"}:
            return None
        try:
            return max(30, int(value))
        except ValueError:
            return None
    default = int(DEFAULTS["apply_timeout"])
    return default if default > 0 else None


def get_log_retention_days() -> int:
    """Return the local apply-log retention period; zero disables cleanup."""
    raw = os.environ.get("DIVAPPLY_LOG_RETENTION_DAYS", "30").strip()
    try:
        days = int(raw)
    except ValueError as exc:
        raise ValueError("DIVAPPLY_LOG_RETENTION_DAYS must be an integer from 0 to 3650") from exc
    if not 0 <= days <= 3650:
        raise ValueError("DIVAPPLY_LOG_RETENTION_DAYS must be an integer from 0 to 3650")
    return days


def gmail_mcp_enabled() -> bool:
    """Reject the retired Gmail MCP integration and otherwise remain disabled."""
    value = os.environ.get("DIVAPPLY_ENABLE_GMAIL_MCP", "")
    if value.strip().lower() in {"1", "true", "yes", "on"}:
        raise RuntimeError(
            "Gmail MCP is unavailable because its archived dependency tree has known High vulnerabilities"
        )
    return False


def is_manual_ats(url: str | None) -> bool:
    """Check if a URL routes through an ATS that requires manual application."""
    if not url:
        return False
    sites_cfg = load_sites_config()
    domains = sites_cfg.get("manual_ats", [])
    url_lower = url.lower()
    return any(domain in url_lower for domain in domains)


def load_blocked_sites() -> tuple[set[str], list[str]]:
    """Load blocked sites and URL patterns from sites.yaml."""
    cfg = load_sites_config()
    blocked = cfg.get("blocked", {})
    sites = set(blocked.get("sites", []))
    patterns = blocked.get("url_patterns", [])
    return sites, patterns


def load_blocked_sso() -> list[str]:
    """Load blocked SSO domains from sites.yaml."""
    cfg = load_sites_config()
    return cfg.get("blocked_sso", [])


def load_base_urls() -> dict[str, str | None]:
    """Load site base URLs for URL resolution from sites.yaml."""
    cfg = load_sites_config()
    return cfg.get("base_urls", {})


DEFAULTS: dict[str, Any] = {
    "min_score": 7,
    "max_apply_attempts": 3,
    "max_tailor_attempts": 5,
    "poll_interval": 60,
    "apply_timeout": 2700,
    "apply_lock_timeout": 3600,
    "viewport": "1280x900",
}


def load_env() -> None:
    """Load environment variables from ~/.divapply/.env if it exists."""
    from dotenv import load_dotenv

    source_path = ENV_PATH if ENV_PATH.exists() else LEGACY_ENV_PATH
    if source_path.exists():
        _protect_private_user_root(source_path.parent)
    if ENV_PATH.exists():
        load_dotenv(ENV_PATH, override=True)
    elif LEGACY_ENV_PATH.exists():
        load_dotenv(LEGACY_ENV_PATH, override=True)
    load_dotenv()


from divapply import runtime as _runtime  # noqa: E402

APPLY_AGENT_LABELS = _runtime.APPLY_AGENT_LABELS
APPLY_BROWSER_LABELS = _runtime.APPLY_BROWSER_LABELS
TIER_COMMANDS = _runtime.TIER_COMMANDS
TIER_LABELS = _runtime.TIER_LABELS
check_tier = _runtime.check_tier
get_apply_backend = _runtime.get_apply_backend
get_apply_backend_executable = _runtime.get_apply_backend_executable
get_apply_backend_label = _runtime.get_apply_backend_label
get_apply_browser = _runtime.get_apply_browser
get_apply_browser_label = _runtime.get_apply_browser_label
get_available_apply_backends = _runtime.get_available_apply_backends
get_chrome_path = _runtime.get_chrome_path
get_chrome_user_data = _runtime.get_chrome_user_data
get_tier = _runtime.get_tier
