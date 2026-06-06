"""Security helpers for untrusted URLs, secrets, and local artifacts."""

from __future__ import annotations

import ipaddress
import os
import re
import socket
from pathlib import Path
from urllib.parse import urljoin, urlparse


class UnsafeUrlError(ValueError):
    """Raised when a URL is not safe for outbound scraping/navigation."""


_PRIVATE_HOST_SUFFIXES = (".local", ".localhost", ".internal")
_SECRET_TOKEN_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9._~+/=-]{7,}")


def _private_networks_allowed() -> bool:
    return os.environ.get("DIVAPPLY_ALLOW_PRIVATE_URLS", "").strip().lower() in {"1", "true", "yes", "on"}


def _host_is_private(host: str) -> bool:
    normalized = host.strip("[]").casefold()
    if normalized in {"localhost", "localhost.localdomain"} or normalized.endswith(_PRIVATE_HOST_SUFFIXES):
        return True
    try:
        ip = ipaddress.ip_address(normalized)
        return (
            ip.is_private
            or ip.is_loopback
            or ip.is_link_local
            or ip.is_multicast
            or ip.is_reserved
            or ip.is_unspecified
        )
    except ValueError:
        pass

    try:
        infos = socket.getaddrinfo(normalized, None, type=socket.SOCK_STREAM)
    except socket.gaierror:
        return False

    for info in infos:
        try:
            ip = ipaddress.ip_address(info[4][0])
        except ValueError:
            continue
        if (
            ip.is_private
            or ip.is_loopback
            or ip.is_link_local
            or ip.is_multicast
            or ip.is_reserved
            or ip.is_unspecified
        ):
            return True
    return False


def validate_external_url(url: str | None, *, field: str = "url") -> str:
    """Return a normalized HTTP(S) URL safe for scraper/browser navigation."""
    value = str(url or "").strip()
    if not value:
        raise UnsafeUrlError(f"{field} is empty")
    parsed = urlparse(value)
    if parsed.scheme.casefold() not in {"http", "https"}:
        raise UnsafeUrlError(f"{field} must use http or https")
    if not parsed.hostname:
        raise UnsafeUrlError(f"{field} needs a hostname")
    if not _private_networks_allowed() and _host_is_private(parsed.hostname):
        raise UnsafeUrlError(f"{field} points to a private or local address")
    if parsed.username or parsed.password:
        raise UnsafeUrlError(f"{field} must not embed credentials")
    return value


def safe_join_external_url(base_url: str, path: str, *, field: str = "url") -> str:
    """Join a relative path to a validated external base URL without changing hosts."""
    base = validate_external_url(base_url, field=f"{field}.base_url")
    base_host = urlparse(base).hostname
    relative_path = str(path or "").strip()
    parsed_path = urlparse(relative_path)
    if parsed_path.scheme or parsed_path.netloc:
        raise UnsafeUrlError(f"{field} path must be relative")
    joined = urljoin(base.rstrip("/") + "/", relative_path.lstrip("/"))
    safe = validate_external_url(joined, field=field)
    if urlparse(safe).hostname != base_host:
        raise UnsafeUrlError(f"{field} must stay on the base host")
    return safe


def sanitize_external_url(url: str | None, *, field: str = "url") -> str | None:
    """Return a safe URL or None for optional scraped links."""
    if not url:
        return None
    try:
        return validate_external_url(url, field=field)
    except UnsafeUrlError:
        return None


def protect_file(path: Path | str) -> None:
    """Best-effort user-only permissions for sensitive local files."""
    try:
        Path(path).chmod(0o600)
    except OSError:
        pass


def collect_known_secret_values(*sources: object) -> set[str]:
    """Collect redaction candidates from nested dict/list structures and env."""
    values: set[str] = set()

    def walk(obj: object, key_hint: str = "") -> None:
        if isinstance(obj, dict):
            for key, value in obj.items():
                walk(value, str(key).casefold())
        elif isinstance(obj, (list, tuple, set)):
            for value in obj:
                walk(value, key_hint)
        elif isinstance(obj, str):
            text = obj.strip()
            if len(text) >= 8 and (
                any(token in key_hint for token in ("password", "token", "secret", "key"))
                or _SECRET_TOKEN_RE.fullmatch(text)
            ):
                values.add(text)

    for source in sources:
        walk(source)

    for key, value in os.environ.items():
        if value and len(value) >= 8 and any(token in key.casefold() for token in ("password", "token", "secret", "key")):
            values.add(value)

    return values


def redact_known_secrets(text: str, secrets: set[str]) -> str:
    """Replace known secret values and common credential patterns in logs."""
    redacted = text
    for secret in sorted(secrets, key=len, reverse=True):
        if secret:
            redacted = redacted.replace(secret, "[redacted]")
    redacted = re.sub(
        r"(?i)\b(password|passwd|api[_-]?key|token|secret)\s*[:=]\s*([^\s,;]+)",
        lambda m: f"{m.group(1)}=[redacted]",
        redacted,
    )
    redacted = re.sub(r"(?i)\bBearer\s+[A-Za-z0-9._~+/=-]+", "Bearer [redacted]", redacted)
    return redacted
