"""Parse user-supplied batches of external job links.

This module deliberately stops at parsing and validation.  It does not fetch
pages, mutate the database, generate application documents, or launch a
browser.  The CLI can therefore inspect the complete parse result before it
authorizes any later stage of the application workflow.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Literal
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from divapply.security import UnsafeUrlError, validate_external_url


LinkBatchStatus = Literal["accepted", "duplicate_input", "invalid_url"]

_TRACKING_QUERY_KEYS = frozenset({"fbclid", "gclid", "mc_cid", "mc_eid", "msclkid"})
_CanonicalUrlIdentity = tuple[str, str, int | None, str, str, str]


@dataclass(frozen=True, slots=True)
class LinkBatchRecord:
    """The outcome for one non-blank, non-comment input line."""

    line_number: int
    input_value: str
    status: LinkBatchStatus
    url: str | None = None
    canonical_url: str | None = None
    duplicate_of_line: int | None = None
    error: str | None = None


@dataclass(frozen=True, slots=True)
class LinkBatchParseResult:
    """Structured, order-preserving result returned by the batch parser."""

    records: tuple[LinkBatchRecord, ...]
    total_lines: int
    ignored_lines: int
    source: Path | None = None

    @property
    def entries(self) -> tuple[LinkBatchRecord, ...]:
        """Return validated, de-duplicated links in their input order."""
        return tuple(record for record in self.records if record.status == "accepted")

    @property
    def duplicates(self) -> tuple[LinkBatchRecord, ...]:
        """Return links already represented by an earlier input line."""
        return tuple(record for record in self.records if record.status == "duplicate_input")

    @property
    def invalid(self) -> tuple[LinkBatchRecord, ...]:
        """Return lines rejected by strict external-URL validation."""
        return tuple(record for record in self.records if record.status == "invalid_url")


def _canonical_url_identity(url: str) -> _CanonicalUrlIdentity:
    """Return a strict URL identity with known tracking parameters removed."""
    try:
        parsed = urlsplit(url)
        scheme = parsed.scheme.casefold()
        host = (parsed.hostname or "").rstrip(".").casefold().encode("idna").decode("ascii")
        port = parsed.port
    except (UnicodeError, ValueError) as exc:
        raise UnsafeUrlError("job URL contains an invalid hostname or port") from exc

    if port == (443 if scheme == "https" else 80):
        port = None
    path = (parsed.path or "/").rstrip("/") or "/"
    query_pairs = [
        (key, value)
        for key, value in parse_qsl(parsed.query, keep_blank_values=True)
        if not key.casefold().startswith("utm_") and key.casefold() not in _TRACKING_QUERY_KEYS
    ]
    query = urlencode(sorted(query_pairs))
    return scheme, host, port, path, query, parsed.fragment


def _identity_url(identity: _CanonicalUrlIdentity) -> str:
    scheme, host, port, path, query, fragment = identity
    display_host = f"[{host}]" if ":" in host else host
    netloc = f"{display_host}:{port}" if port is not None else display_host
    return urlunsplit((scheme, netloc, path, query, fragment))


def canonicalize_job_url(url: str) -> str:
    """Validate a job URL and return its deterministic de-duplication form."""
    safe_url = validate_external_url(url, field="job URL")
    return _identity_url(_canonical_url_identity(safe_url))


def parse_link_batch_lines(lines: Iterable[str], *, source: Path | None = None) -> LinkBatchParseResult:
    """Parse one external job URL per line without performing any side effects.

    Blank lines and lines whose first non-whitespace character is ``#`` are
    ignored.  Inline ``#`` characters are retained because URL fragments can
    carry a job or application identifier.
    """
    records: list[LinkBatchRecord] = []
    seen: dict[str, LinkBatchRecord] = {}
    total_lines = 0
    ignored_lines = 0

    for line_number, raw_line in enumerate(lines, start=1):
        total_lines = line_number
        if line_number == 1:
            raw_line = raw_line.removeprefix("\ufeff")
        value = raw_line.strip()
        if not value or value.startswith("#"):
            ignored_lines += 1
            continue

        try:
            safe_url = validate_external_url(value, field=f"job URL on line {line_number}")
            canonical_url = _identity_url(_canonical_url_identity(safe_url))
        except UnsafeUrlError as exc:
            records.append(
                LinkBatchRecord(
                    line_number=line_number,
                    input_value=value,
                    status="invalid_url",
                    error=str(exc),
                )
            )
            continue

        first = seen.get(canonical_url)
        if first is not None:
            records.append(
                LinkBatchRecord(
                    line_number=line_number,
                    input_value=value,
                    status="duplicate_input",
                    url=safe_url,
                    canonical_url=canonical_url,
                    duplicate_of_line=first.line_number,
                )
            )
            continue

        record = LinkBatchRecord(
            line_number=line_number,
            input_value=value,
            status="accepted",
            url=safe_url,
            canonical_url=canonical_url,
        )
        seen[canonical_url] = record
        records.append(record)

    return LinkBatchParseResult(
        records=tuple(records),
        total_lines=total_lines,
        ignored_lines=ignored_lines,
        source=source,
    )


def parse_link_batch_text(text: str) -> LinkBatchParseResult:
    """Parse a UTF-8-compatible string containing one job URL per line."""
    return parse_link_batch_lines(text.splitlines())


def parse_link_batch_file(path: str | Path) -> LinkBatchParseResult:
    """Read and parse a UTF-8 or UTF-8-BOM job-link file."""
    source = Path(path)
    text = source.read_text(encoding="utf-8-sig")
    return parse_link_batch_lines(text.splitlines(), source=source)
