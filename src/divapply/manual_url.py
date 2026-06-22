"""Manual job URL metadata extraction."""

from __future__ import annotations

import html
import json
from urllib.parse import urlparse

import httpx
from bs4 import BeautifulSoup

from divapply.security import validate_external_url


def flatten_json_ld_items(value: object) -> list[dict]:
    """Return every dict-like JSON-LD node from nested graph structures."""
    items: list[dict] = []
    if isinstance(value, dict):
        items.append(value)
        for graph_key in ("@graph", "graph", "itemListElement"):
            if graph_key in value:
                items.extend(flatten_json_ld_items(value[graph_key]))
    elif isinstance(value, list):
        for item in value:
            items.extend(flatten_json_ld_items(item))
    return items


def json_ld_type_matches(node: dict, expected: str) -> bool:
    raw_type = node.get("@type") or node.get("type")
    if isinstance(raw_type, str):
        return raw_type.lower() == expected.lower()
    if isinstance(raw_type, list):
        return any(str(item).lower() == expected.lower() for item in raw_type)
    return False


def job_location_text(value: object) -> str:
    """Extract a readable location from schema.org JobPosting jobLocation."""
    locations = value if isinstance(value, list) else [value]
    parts: list[str] = []
    for location in locations:
        if isinstance(location, str):
            parts.append(location)
            continue
        if not isinstance(location, dict):
            continue
        address = location.get("address")
        if isinstance(address, dict):
            city = address.get("addressLocality")
            state = address.get("addressRegion")
            country = address.get("addressCountry")
            item = ", ".join(str(part) for part in (city, state, country) if part)
            if item:
                parts.append(item)
        elif isinstance(address, str):
            parts.append(address)
        elif location.get("name"):
            parts.append(str(location["name"]))
    return "; ".join(parts)


def extract_job_posting_schema(soup: BeautifulSoup) -> dict[str, str]:
    """Extract the strongest job metadata from JSON-LD JobPosting blocks."""
    result: dict[str, str] = {}
    for tag in soup.find_all("script", attrs={"type": "application/ld+json"}):
        raw = tag.string or tag.get_text("", strip=False)
        if not raw:
            continue
        try:
            parsed = json.loads(raw)
        except json.JSONDecodeError:
            continue
        for node in flatten_json_ld_items(parsed):
            if not json_ld_type_matches(node, "JobPosting"):
                continue
            description = node.get("description")
            if description:
                result["description"] = html.unescape(str(description))
            title = node.get("title")
            if title:
                result["title"] = str(title)
            hiring_org = node.get("hiringOrganization")
            if isinstance(hiring_org, dict) and hiring_org.get("name"):
                result["company"] = str(hiring_org["name"])
            elif isinstance(hiring_org, str):
                result["company"] = hiring_org
            location = job_location_text(node.get("jobLocation"))
            if location:
                result["location"] = location
            if node.get("employmentType"):
                result["employment_type"] = str(node["employmentType"])
            if node.get("datePosted"):
                result["date_posted"] = str(node["datePosted"])
            if node.get("validThrough"):
                result["valid_through"] = str(node["validThrough"])
            return result
    return result


def extract_manual_job_metadata(url: str) -> dict[str, str | bool]:
    """Fetch lightweight metadata for a manually pasted job URL."""
    safe_url = validate_external_url(url, field="job URL")
    host = urlparse(safe_url).hostname or "manual"
    title_fallback = safe_url.rstrip("/").split("/")[-1].replace("-", " ").strip().title() or "Manual Job"

    with httpx.Client(follow_redirects=True, timeout=20) as client:
        response = client.get(
            safe_url,
            headers={
                "User-Agent": (
                    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125 Safari/537.36"
                )
            },
        )
        response.raise_for_status()

    soup = BeautifulSoup(response.text, "html.parser")
    schema_job = extract_job_posting_schema(soup)
    live_job_evidence = bool(schema_job)
    for hidden in soup.select('[class*="d-none"], [hidden], [aria-hidden="true"]'):
        hidden.decompose()
    for tag in soup(["script", "style", "noscript"]):
        tag.decompose()

    def meta_value(*names: str) -> str:
        for name in names:
            tag = soup.find("meta", attrs={"property": name}) or soup.find("meta", attrs={"name": name})
            if tag and tag.get("content"):
                return str(tag["content"]).strip()
        return ""

    h1 = soup.find("h1")
    page_title = soup.find("title")
    title = (
        schema_job.get("title")
        or meta_value("og:title", "twitter:title")
        or (h1.get_text(" ", strip=True) if h1 else "")
        or (page_title.get_text(" ", strip=True) if page_title else "")
        or title_fallback
    )
    meta_description = meta_value("description", "og:description", "twitter:description")
    text = soup.get_text("\n", strip=True)
    visible_description = "\n".join(line for line in text.splitlines() if line)[:6000]
    description = schema_job.get("description") or visible_description or meta_description

    lower_text = text.lower()
    inactive_text_present = any(
        phrase in lower_text
        for phrase in (
            "this job is inactive",
            "this opportunity has passed",
            "job is no longer available",
            "posting has expired",
            "position has been filled",
        )
    )
    live_job_evidence = live_job_evidence or any(
        phrase in lower_text
        for phrase in (
            "pay range is",
            "job description:",
            "position overview:",
            "schedule:",
        )
    )
    inactive = inactive_text_present and not live_job_evidence

    return {
        "title": title[:180],
        "company": schema_job.get("company") or ("Sutter Health" if "sutterhealth.org" in host else host),
        "site": "Sutter Health" if "sutterhealth.org" in host else host,
        "location": schema_job.get("location", ""),
        "description": description,
        "inactive": inactive,
    }
