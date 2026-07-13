"""Typed market, schedule, and query-scope policy shared across stages."""

from __future__ import annotations

import copy
import re
from typing import Any


def _normalized_employer(value: object) -> str:
    return " ".join(str(value or "").casefold().split())


def _configured_employer_names(value: object) -> list[str]:
    """Return employer names from supported private-config representations."""
    if isinstance(value, str):
        return [value.strip()] if value.strip() else []
    if isinstance(value, list):
        names: list[str] = []
        for item in value:
            names.extend(_configured_employer_names(item))
        return names
    if not isinstance(value, dict):
        return []

    explicit = str(
        value.get("name") or value.get("employer") or value.get("company") or ""
    ).strip()
    if explicit:
        return [explicit]

    names = []
    for key, item in value.items():
        key_text = str(key).strip()
        if not key_text:
            continue
        if isinstance(item, bool):
            if item:
                names.append(key_text)
            continue
        if isinstance(item, dict):
            nested = _configured_employer_names(item)
            names.extend(nested or [key_text])
            continue
        if item is not None:
            names.append(key_text)
    return names


def job_has_schedule_exception(search_config: dict[str, Any], job: dict[str, Any]) -> bool:
    """Return whether trusted config exactly exempts this job's employer schedule."""
    company = _normalized_employer(job.get("company"))
    if not company:
        return False
    for key in ("schedule_exception_employers", "referral_employers"):
        for configured in _configured_employer_names(search_config.get(key)):
            if _normalized_employer(configured) == company:
                return True
    return False


def scoped_query_locations(
    search_config: dict[str, Any],
    *,
    tiers: set[int] | None = None,
    location_labels: set[str] | None = None,
) -> list[dict[str, Any]]:
    """Return ordered query/location pairs honoring each query's labels."""
    queries = search_config.get("queries") or []
    locations = search_config.get("locations") or []
    if not isinstance(queries, list) or not isinstance(locations, list):
        return []

    normalized_locations = [location for location in locations if isinstance(location, dict)]
    had_configured_locations = bool(normalized_locations)
    if location_labels:
        normalized_locations = [
            location
            for location in normalized_locations
            if str(location.get("label") or location.get("location") or "").strip() in location_labels
        ]
    if location_labels and had_configured_locations and not normalized_locations:
        return []
    if not normalized_locations:
        normalized_locations = [{"location": "", "label": "", "remote": False}]

    scoped: list[dict[str, Any]] = []
    for query in queries:
        if not isinstance(query, dict) or not str(query.get("query") or "").strip():
            continue
        try:
            tier = int(query.get("tier", 0))
        except (TypeError, ValueError):
            tier = 0
        if tiers is not None and tier not in tiers:
            continue
        query_labels = {
            str(label).strip()
            for label in (query.get("location_labels") or [])
            if str(label).strip()
        }
        for location in normalized_locations:
            label = str(location.get("label") or location.get("location") or "").strip()
            if query_labels and label not in query_labels:
                continue
            scoped.append(
                {
                    "query": str(query["query"]).strip(),
                    "tier": tier,
                    "location": str(location.get("location") or "").strip(),
                    "location_label": label,
                    "remote": bool(location.get("remote", False)),
                }
            )
    return scoped


def _location_matches(configured: str, actual: str) -> bool:
    configured_text = " ".join(configured.casefold().split())
    actual_text = " ".join(actual.casefold().split())
    if not configured_text or not actual_text:
        return False
    if configured_text in actual_text:
        return True
    parts = [part.strip() for part in configured_text.split(",") if part.strip()]
    if len(parts) < 2:
        return False
    city, state = parts[0], parts[-1]
    return city in actual_text and re.search(rf"\b{re.escape(state)}\b", actual_text) is not None


def _is_broad_remote_or_unknown(location: str) -> bool:
    if not location.strip():
        return False
    lowered = location.casefold()
    if not re.search(r"\b(?:remote|wfh|work from home|anywhere|distributed)\b", lowered):
        return False
    remainder = re.sub(
        r"\b(?:remote|wfh|work from home|anywhere|distributed|nationwide|in|us|usa|united states|of|america)\b|[(),\-]",
        " ",
        lowered,
    )
    return not " ".join(remainder.split())


def _validated_persisted_market_label(
    policies: dict[str, Any],
    locations: list[Any],
    job: dict[str, Any],
) -> str:
    label = str(job.get("market_label") or "").strip()
    if label not in policies:
        return ""
    if any(
        isinstance(item, dict)
        and str(item.get("label") or item.get("location") or "").strip() == label
        for item in locations
    ):
        return label
    return ""


def _configured_market_match(
    policies: dict[str, Any],
    locations: list[Any],
    actual_location: str,
    persisted_label: str,
) -> tuple[bool, str, dict[str, Any]]:
    for location in locations:
        if not isinstance(location, dict):
            continue
        label = str(location.get("label") or location.get("location") or "").strip()
        policy = policies.get(label)
        patterns = [str(location.get("location") or "").strip()]
        configured_patterns = location.get("match_patterns")
        if isinstance(configured_patterns, list):
            patterns.extend(str(pattern).strip() for pattern in configured_patterns if str(pattern).strip())
        if not isinstance(policy, dict) or not any(
            _location_matches(pattern, actual_location) for pattern in patterns
        ):
            continue
        if persisted_label and persisted_label != label:
            return True, "", {}
        return True, label, dict(policy)
    return False, "", {}


def market_policy_for_job(search_config: dict[str, Any], job: dict[str, Any]) -> tuple[str, dict[str, Any]]:
    """Resolve one market from verified query provenance or concrete location."""
    policies = search_config.get("market_policies")
    locations = search_config.get("locations")
    if not isinstance(policies, dict) or not isinstance(locations, list):
        return "", {}

    actual_location = str(job.get("location") or "").strip()
    if not actual_location:
        return "", {}

    persisted_label = _validated_persisted_market_label(policies, locations, job)
    resolved, label, policy = _configured_market_match(policies, locations, actual_location, persisted_label)
    if resolved:
        return label, policy

    if _is_broad_remote_or_unknown(actual_location) and persisted_label:
        persisted_policy = policies.get(persisted_label)
        if isinstance(persisted_policy, dict):
            return persisted_label, dict(persisted_policy)

    default_label = str(search_config.get("default_market_label") or "").strip()
    default_policy = policies.get(default_label)
    if _is_broad_remote_or_unknown(actual_location) and isinstance(default_policy, dict):
        return default_label, dict(default_policy)
    return "", {}


def effective_search_config(search_config: dict[str, Any], job: dict[str, Any]) -> dict[str, Any]:
    """Overlay one market policy without inheriting another market's gates."""
    effective = copy.deepcopy(search_config)
    label, policy = market_policy_for_job(search_config, job)
    has_market_policies = isinstance(search_config.get("market_policies"), dict)

    if has_market_policies:
        # Every market resolution begins from a neutral policy. Unknown
        # concrete locations must not inherit a legacy/default market gate.
        effective["application_mode"] = "manual_review"
        effective["preferred_schedule"] = "any"
        effective["require_benefits"] = False
        effective["require_part_time"] = False
        effective["customer_service_require_part_time"] = False
        effective.pop("max_hours_per_week", None)
        effective.pop("customer_service_max_hours_per_week", None)
    if not policy:
        return effective

    # A market policy is an isolated policy boundary. Reset schedule/apply
    # fields before overlaying so a legacy current-market constraint cannot
    # suppress a destination-market role.
    for key in ("application_mode", "preferred_schedule", "require_benefits", "require_part_time"):
        if key in policy:
            effective[key] = policy[key]
    if "max_hours_per_week" in policy:
        effective["max_hours_per_week"] = policy["max_hours_per_week"]
        effective["customer_service_max_hours_per_week"] = policy["max_hours_per_week"]
    effective["customer_service_require_part_time"] = bool(effective["require_part_time"])
    effective["active_market_label"] = label

    queries = effective.get("queries")
    if isinstance(queries, list):
        effective["queries"] = [
            query
            for query in queries
            if isinstance(query, dict)
            and (
                not query.get("location_labels")
                or label in {str(item).strip() for item in query.get("location_labels", [])}
            )
        ]
    locations = effective.get("locations")
    if isinstance(locations, list):
        effective["locations"] = [
            location
            for location in locations
            if isinstance(location, dict)
            and str(location.get("label") or location.get("location") or "").strip() == label
        ]
    return effective
