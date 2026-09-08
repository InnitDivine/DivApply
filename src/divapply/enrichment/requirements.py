"""Read qualification documents actually linked by official California postings."""

from __future__ import annotations

from datetime import datetime, timezone
from io import BytesIO
import json
import re
from urllib.parse import parse_qs, urljoin, urlparse

from bs4 import BeautifulSoup
import httpx

from divapply.security import validate_external_url


def _official_url(value: str) -> str:
    url = validate_external_url(value, field="qualification source")
    host = (urlparse(url).hostname or "").casefold()
    if not any(host == domain or host.endswith("." + domain) for domain in ("calhr.ca.gov", "calcareers.ca.gov")):
        raise ValueError("Qualification source left the official state domains")
    return url


def _fetch(client: httpx.Client, url: str, *, posting_url: str = "") -> httpx.Response:
    for _ in range(6):
        if posting_url:
            url = validate_external_url(url, field="linked posting document")
            parsed, posting = urlparse(url), urlparse(posting_url)
            if (parsed.hostname, parsed.port) != (posting.hostname, posting.port):
                raise ValueError("Linked document left the employer posting origin")
        else:
            url = _official_url(url)
        response = client.get(url)
        if response.status_code in {301, 302, 303, 307, 308}:
            if not response.headers.get("location"):
                raise ValueError("Qualification redirect is missing its destination")
            target = urljoin(url, response.headers["location"])
            # Legacy CalHR cross-references still redirect to HTTP.
            if target.startswith("http://"):
                target = "https://" + target[7:]
            url = target
            continue
        response.raise_for_status()
        if len(response.content) > 2_000_000:
            raise ValueError("Qualification document exceeds 2 MB")
        return response
    raise ValueError("Too many qualification redirects")


def _normalize_label(value: str) -> str:
    return " ".join(re.sub(r"[\u200b-\u200f\ufeff]", "", value).casefold().split())


def _document_text(response: httpx.Response, *, classification: str = "") -> str:
    if response.content.startswith(b"%PDF"):
        from pypdf import PdfReader
        reader = PdfReader(BytesIO(response.content))
        if len(reader.pages) > 40:
            raise ValueError("Qualification document exceeds 40 pages")
        return "\n".join(page.extract_text() or "" for page in reader.pages)
    soup = BeautifulSoup(response.text, "html.parser")
    if classification:
        # CalHR series specifications contain separate minimums for many
        # levels. Preserve the shared rules and the exact linked class, not
        # the supervisor/manager experience requirements for other levels.
        names = {_normalize_label(cell.get_text(" ", strip=True)) for cell in soup.select("table td")}
        target = _normalize_label(classification)
        if target in names:
            minimum_level = 0
            for heading in list(soup.select("h1,h2,h3,h4")):
                if not heading.name:
                    continue  # Removed inside another classification's section.
                label = _normalize_label(heading.get_text(" ", strip=True))
                level = int(heading.name[1])
                if label in {"minimum qualifications", "minimum requirements"}:
                    minimum_level = level
                elif minimum_level and label in names and label != target:
                    for sibling in list(heading.find_next_siblings()):
                        boundaries = [f"h{rank}" for rank in range(1, level + 1)]
                        if sibling.name in boundaries or sibling.find(boundaries):
                            break
                        sibling.decompose()
                    heading.decompose()
                elif minimum_level and level <= minimum_level and label not in names and not label.startswith("all "):
                    minimum_level = 0
    for node in soup.select("script,style,nav,header,footer,noscript"):
        node.decompose()
    node = soup.select_one("main, #main-content, #content, [role=main]") or soup
    return node.get_text("\n", strip=True)


def _calhr_portal_fallback(url: str, label: str) -> httpx.Response:
    """Resolve the posting's exact CalHR class code in the new public portal.

    CalHR's legacy /state-hr-professionals/Pages/1400.aspx now redirects to
    this public route. The portal also resolves member codes (e.g. 1401)
    to their series. Verify both the class code and class name in its table.
    """
    from divapply.manual_url import render_public_page

    parsed = urlparse(_official_url(url))
    query = {key.casefold(): values for key, values in parse_qs(parsed.query).items()}
    code = (query.get("classid") or [""])[0]
    if "speccrossreference" not in parsed.path.casefold() or not re.fullmatch(r"\d{4}", code):
        raise ValueError("No exact CalHR class code for a portal lookup")
    portal = "https://eservices.calhr.ca.gov/enterprisehrblazorpublic/Public/ClassSpec/ClassSpecDetail/" + code
    page_html, final_url = render_public_page(portal, wait_text=r"minimum\s+qualifications")
    _official_url(final_url)
    soup = BeautifulSoup(page_html, "html.parser")
    matching_row = any(code in _normalize_label(row.get_text(" ", strip=True)).split() and _normalize_label(label) in _normalize_label(row.get_text(" ", strip=True))
                       for row in soup.select("tr"))
    if not label or not matching_row:
        raise ValueError("Public portal specification did not match the linked class code and name")
    return httpx.Response(200, text=page_html, request=httpx.Request("GET", final_url))


def linked_qualification_evidence(page_html: str, page_url: str) -> dict[str, str]:
    """Read linked specifications, exam requirements and duty statements."""
    host = (urlparse(page_url).hostname or "").casefold()
    state_posting = host in {"www.calcareers.ca.gov", "calcareers.ca.gov"}
    soup = BeautifulSoup(page_html, "html.parser")
    content = soup.select_one("#JobBulletin, main, #main-content, [role=main]") or soup
    links: dict[str, tuple[str, bool]] = {}
    for anchor in content.select("a[href]"):
        href = urljoin(page_url, str(anchor.get("href") or ""))
        label = anchor.get_text(" ", strip=True)
        duty = bool(re.search(r"\bduty statement\b", label, re.I))
        qualification = any(marker in href.casefold() for marker in (
            "speccrossreference", "classspecdisplay", "classspecifications/", "exambulletin.aspx",
        )) or bool(re.search(r"\b(class specification|minimum qualifications|job specification)\b", label, re.I))
        if duty or qualification:
            links[href] = (label, duty)
    if not links:
        return {"requirements_error": "The posting does not expose its linked minimum qualifications."} if state_posting else {}
    documents: list[str] = []
    qualification_documents: list[str] = []
    sources: list[dict] = []
    errors: list[tuple[str, str]] = []
    with httpx.Client(follow_redirects=False, timeout=20, headers={"User-Agent": "Mozilla/5.0"}) as client:
        for url, (label, duty) in list(links.items())[:4]:
            try:
                try:
                    response = _fetch(client, url) if state_posting else _fetch(client, url, posting_url=page_url)
                except httpx.HTTPStatusError:
                    if not state_posting or "speccrossreference" not in url.casefold():
                        raise
                    response = _calhr_portal_fallback(url, label)
                text = _document_text(response, classification=label if not duty else "")
                if len(text.strip()) < (80 if duty else 32):
                    raise ValueError("Linked document has no readable text")
                if not duty and not re.search(r"minimum\s+(?:qualifications|requirements)", text, re.I):
                    raise ValueError("Page has no minimum-qualification section")
                if len(text) > 45000:
                    raise ValueError("Qualification document is too long for a complete assessment")
                documents.append(f"SOURCE: {response.url}\nLINKED DOCUMENT: {label}\n{text}")
                if not duty:
                    qualification_documents.append(text)
                sources.append({"url": str(response.url), "label": label, "status": "read", "kind": "duties" if duty else "qualifications"})
            except Exception as exc:
                error = f"{label or 'Class specification'}: {type(exc).__name__}"
                errors.append((label, error))
                sources.append({"url": url, "label": label, "status": "unavailable", "error": error})
    # A linked exam bulletin is an acceptable fallback only if it names the
    # classification whose specification failed, not simply any readable exam.
    # Duty statements name their classification too; that is not a substitute
    # for reading the actual minimum-qualification specification or exam.
    read_text = " ".join(" ".join(doc.casefold().split()) for doc in qualification_documents)
    unresolved = [error for label, error in errors
                  if len(label.strip()) < 5 or " ".join(label.casefold().split()) not in read_text]
    if len(links) > 4:
        unresolved.append(f"{len(links) - 4} additional linked documents need review (download limit reached).")
    return {
        "requirements_description": "\n\n".join(documents),
        "requirements_sources": json.dumps(sources, ensure_ascii=True),
        "requirements_error": "; ".join(unresolved),
        "requirements_checked_at": datetime.now(timezone.utc).isoformat(),
    }
