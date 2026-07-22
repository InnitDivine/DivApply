"""Manual job URL metadata extraction."""

from __future__ import annotations

import html
import json
import re
from urllib.parse import urljoin, urlparse

import httpx
from bs4 import BeautifulSoup

from divapply.security import UnsafeUrlError, validate_external_url, validate_navigation_url


MAX_MANUAL_REDIRECTS = 5

_EMPLOYMENT_TYPE_ALIASES = {
    "fulltime": "full_time",
    "full_time": "full_time",
    "parttime": "part_time",
    "part_time": "part_time",
    "perdiem": "per_diem",
    "per_diem": "per_diem",
    "contractor": "contract",
    "contract": "contract",
    "temporary": "temporary",
    "intern": "internship",
    "internship": "internship",
    "volunteer": "volunteer",
}


def _fetch_job_page(client: httpx.Client, url: str, *, headers: dict[str, str]) -> httpx.Response:
    """Fetch a page while validating every redirect target before requesting it."""
    current_url = validate_external_url(url, field="job URL")
    for redirect_count in range(MAX_MANUAL_REDIRECTS + 1):
        response = client.get(current_url, headers=headers)
        if not bool(getattr(response, "is_redirect", False)):
            final_url = str(getattr(response, "url", current_url) or current_url)
            validate_navigation_url(final_url, field="job URL")
            if getattr(response, "status_code", None) not in {404, 410}:
                response.raise_for_status()
            return response

        if redirect_count >= MAX_MANUAL_REDIRECTS:
            raise UnsafeUrlError(f"job URL exceeded {MAX_MANUAL_REDIRECTS} redirects")
        location = getattr(response, "headers", {}).get("location")
        if not location:
            raise UnsafeUrlError("job URL redirect is missing a Location header")
        response_url = str(getattr(response, "url", current_url) or current_url)
        next_url = urljoin(response_url, str(location))
        current_url = validate_navigation_url(next_url, field="job URL redirect")

    raise UnsafeUrlError(f"job URL exceeded {MAX_MANUAL_REDIRECTS} redirects")


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


def employment_type_text(value: object) -> str:
    """Normalize schema.org employmentType scalar/list values for scoring."""
    values = value if isinstance(value, list) else [value]
    for item in values:
        token = re.sub(r"[^a-z0-9]+", "_", str(item or "").strip().casefold()).strip("_")
        if token:
            return _EMPLOYMENT_TYPE_ALIASES.get(token, token)
    return ""


def clean_job_description(text: str) -> str:
    """Convert HTML-ish job description text into readable plain text."""
    if not text:
        return ""
    if "<" in text and ">" in text:
        soup = BeautifulSoup(text, "html.parser")
        for br in soup.find_all("br"):
            br.replace_with("\n")
        for tag in soup.find_all(["p", "div", "h1", "h2", "h3", "h4", "li", "tr"]):
            tag.insert_before("\n")
            tag.insert_after("\n")
        for li in soup.find_all("li"):
            li.insert_before("- ")
        text = soup.get_text()
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    return "\n".join(lines).strip()


def extract_job_posting_schema(soup: BeautifulSoup) -> dict[str, str]:
    """Extract the strongest job metadata from JSON-LD JobPosting blocks."""
    best_result: dict[str, str] = {}
    best_description_length = 0
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
            result: dict[str, str] = {}
            description = node.get("description")
            if description:
                result["description"] = clean_job_description(html.unescape(str(description)))
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
                result["employment_type"] = employment_type_text(node["employmentType"])
            if node.get("datePosted"):
                result["date_posted"] = str(node["datePosted"])
            if node.get("validThrough"):
                result["valid_through"] = str(node["validThrough"])
            description_length = len(result.get("description", ""))
            if result and description_length >= best_description_length:
                best_result = result
                best_description_length = description_length
    return best_result


def visible_body_description(soup: BeautifulSoup) -> str:
    """Return the best visible job-description block from a pasted URL page."""
    selectors = [
        "#job-description",
        "#job_description",
        "#jobDescriptionText",
        ".job-description",
        ".job_description",
        "[class*='job-description']",
        "[class*='jobDescription']",
        "[data-testid*='description']",
        "[data-testid='job-description']",
        "[class*='job-detail']",
        "[class*='jobDetail']",
        "[class*='job-content']",
        "[class*='job-body']",
        "main article",
        "article[class*='job']",
        "main",
        "[role='main']",
    ]
    best = ""
    for selector in selectors:
        for node in soup.select(selector):
            text = clean_job_description(node.get_text("\n", strip=True))
            if len(text) > len(best):
                best = text
    if best:
        return best
    return "\n".join(line for line in soup.get_text("\n", strip=True).splitlines() if line)[:6000]


def extract_manual_job_metadata(url: str) -> dict[str, str | bool]:
    """Fetch lightweight metadata for a manually pasted job URL."""
    safe_url = validate_external_url(url, field="job URL")
    host = urlparse(safe_url).hostname or "manual"
    title_fallback = safe_url.rstrip("/").split("/")[-1].replace("-", " ").strip().title() or "Manual Job"

    with httpx.Client(follow_redirects=False, timeout=20) as client:
        response = _fetch_job_page(
            client,
            safe_url,
            headers={
                "User-Agent": (
                    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125 Safari/537.36"
                )
            },
        )

    soup = BeautifulSoup(response.text, "html.parser")
    schema_job = extract_job_posting_schema(soup)
    terminal_inactive_status = getattr(response, "status_code", None) in {404, 410}
    for hidden in soup.select(
        "[class*='d-none'], [class*='hidden'], [class*='sr-only'], "
        "[hidden], [aria-hidden='true'], [style*='display:none'], [style*='display: none'], "
        "[style*='visibility:hidden'], [style*='visibility: hidden']"
    ):
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
    visible_description = visible_body_description(soup)
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
    inactive = terminal_inactive_status or inactive_text_present

    return {
        "title": title[:180],
        "company": schema_job.get("company") or host,
        "site": host,
        "location": schema_job.get("location", ""),
        "description": description,
        "employment_type": schema_job.get("employment_type", ""),
        "job_posting_schema": bool(schema_job),
        "inactive": inactive,
    }
