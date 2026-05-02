"""Small local text-embedding helpers.

This is intentionally dependency-light: a hashed bag-of-terms vector gives a
stable semantic-ish similarity signal without calling external embedding APIs.
"""

from __future__ import annotations

import hashlib
import math
import re
from collections import Counter


_TOKEN_RE = re.compile(r"[a-z][a-z0-9+#.\-]{1,}", re.IGNORECASE)
_DIMS = 384


def _tokens(text: str) -> list[str]:
    return [token.casefold() for token in _TOKEN_RE.findall(text or "") if len(token) > 2]


def hashed_embedding(text: str, dims: int = _DIMS) -> list[float]:
    """Return a normalized hashed term-frequency vector."""
    counts = Counter(_tokens(text))
    vector = [0.0] * dims
    for token, count in counts.items():
        digest = hashlib.blake2b(token.encode("utf-8"), digest_size=8).digest()
        bucket = int.from_bytes(digest[:4], "big") % dims
        sign = 1.0 if digest[4] % 2 == 0 else -1.0
        vector[bucket] += sign * (1.0 + math.log(count))

    norm = math.sqrt(sum(v * v for v in vector))
    if not norm:
        return vector
    return [v / norm for v in vector]


def cosine(left: list[float], right: list[float]) -> float:
    """Return cosine similarity in the 0..1 range."""
    if not left or not right or len(left) != len(right):
        return 0.0
    raw = sum(a * b for a, b in zip(left, right))
    return max(0.0, min(1.0, raw))


def embedding_score(resume_text: str, job_description: str) -> float:
    """Return local embedding similarity between resume and JD."""
    return round(cosine(hashed_embedding(resume_text), hashed_embedding(job_description)), 4)
