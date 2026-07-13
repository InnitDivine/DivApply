"""Privacy helpers for safe display and export of user data."""

from __future__ import annotations

import re


def redact_error_snippet(value: str | None, *, max_length: int = 240) -> str:
    """Redact likely personal or secret data from an error snippet."""
    if not value:
        return ""

    text = str(value)
    text = re.sub(r"[\w.\-+]+@[\w.\-]+\.\w+", "[email]", text)
    text = re.sub(r"\b(?:\+?1[-.\s]?)?(?:\(?\d{3}\)?[-.\s]?)\d{3}[-.\s]?\d{4}\b", "[phone]", text)
    text = re.sub(r"(?i)(api[_-]?key|token|password|secret)\s*[=:]\s*\S+", r"\1=[redacted]", text)
    text = re.sub(r"(?i)\bbearer\s+[A-Za-z0-9._\-]+", "Bearer [redacted]", text)
    text = re.sub(r"(?i)\boauth:[A-Za-z0-9._\-]+", "oauth:[redacted]", text)
    # Long opaque strings are usually credentials, signed URLs, or session ids.
    text = re.sub(r"\b[A-Za-z0-9_\-]{32,}\b", "[redacted-key]", text)
    return text[:max_length]
