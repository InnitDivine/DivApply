"""Keyword extraction and hit-rate scoring for job descriptions."""

from __future__ import annotations

import json
import os
import re
from functools import lru_cache

from divapply.llm import get_client_for_stage


_WORD_RE = re.compile(r"[a-z][a-z0-9+#.\-]{1,}", re.IGNORECASE)
_STOPWORDS = {
    "about", "above", "across", "after", "again", "against", "all", "also",
    "and", "any", "are", "around", "based", "been", "before", "being",
    "below", "between", "both", "business", "can", "candidate", "company",
    "could", "daily", "duties", "each", "employee", "employees", "equal",
    "etc", "from", "full", "have", "help", "high", "including", "into",
    "job", "jobs", "least", "level", "like", "looking", "more", "must",
    "advantage", "bonus", "certification", "certifications", "desired",
    "mandatory", "minimum", "nice",
    "need", "needs", "offer", "only", "optional", "other", "our", "plus",
    "preferred", "provide", "required", "requirements", "responsibilities", "role",
    "should", "skill", "skills", "some", "team", "than", "that", "the", "their", "them",
    "then", "this", "through", "time", "using", "will", "with", "work",
    "years", "your",
}
_REQUIRED_MARKERS = {
    "must", "required", "requirement", "requirements", "minimum",
    "mandatory", "qualification", "qualifications", "responsibilities",
    "experience", "skill", "skills",
}
_PREFERRED_MARKERS = {
    "preferred", "nice to have", "nice-to-have", "bonus", "plus",
    "desired", "optional", "advantage",
}
_SKILL_HINTS = {
    "aws", "azure", "gcp", "linux", "windows", "python", "sql", "excel",
    "powerpoint", "word", "javascript", "typescript", "react", "node",
    "kubernetes", "docker", "terraform", "salesforce", "workday",
    "greenhouse", "lever", "customer", "support", "accounting", "finance",
    "data", "analysis", "analytics", "documentation", "communication",
    "troubleshooting", "networking", "security", "compliance", "inventory",
    "scheduling", "reporting", "reconciliation", "billing", "crm",
}


def _normalize_token(token: str) -> str:
    return token.strip(".,;:()[]{}'\"").casefold()


def _line_bucket(line: str, current: str | None) -> str | None:
    """Classify a JD line as required/preferred using headings and markers."""
    lowered = line.casefold()
    has_preferred = any(marker in lowered for marker in _PREFERRED_MARKERS)
    has_required = any(marker in lowered for marker in _REQUIRED_MARKERS)
    if has_preferred:
        return "preferred"
    if has_required:
        return "required"
    return current


def _clean_phrase(phrase: str) -> str:
    parts = [_normalize_token(part) for part in phrase.split()]
    parts = [part for part in parts if part and part not in _STOPWORDS]
    return " ".join(parts).strip()


def _candidate_phrases(text: str, *, bucket: str = "required") -> list[str]:
    lowered = text.casefold()
    phrases: list[str] = []
    bucket_lines: list[str] = []

    current_bucket: str | None = None
    for line in lowered.splitlines():
        line = line.strip(" -•*\t")
        if not line:
            continue
        current_bucket = _line_bucket(line, current_bucket)
        if current_bucket != bucket:
            continue
        bucket_lines.append(line)
        if any(mark in line for mark in _REQUIRED_MARKERS | _PREFERRED_MARKERS):
            chunks = re.split(r"[,;/]| and | or ", line)
            phrases.extend(chunk.strip() for chunk in chunks)

    bucket_text = "\n".join(bucket_lines)
    if bucket == "required" and not bucket_text:
        bucket_text = lowered
    words = [_normalize_token(w) for w in _WORD_RE.findall(bucket_text)]
    words = [w for w in words if len(w) > 2 and w not in _STOPWORDS]
    for word in words:
        if word in _SKILL_HINTS or any(c in word for c in ("+", "#", ".")):
            phrases.append(word)

    for idx in range(len(words) - 1):
        phrase = f"{words[idx]} {words[idx + 1]}"
        if any(hint in phrase for hint in _SKILL_HINTS):
            phrases.append(phrase)

    seen: set[str] = set()
    ordered: list[str] = []
    for phrase in phrases:
        clean = _clean_phrase(phrase)
        if clean and clean not in seen and clean not in _STOPWORDS:
            seen.add(clean)
            ordered.append(clean)
    return ordered[:30]


def _extract_keywords_local(job_description: str) -> list[str]:
    return _candidate_phrases(job_description, bucket="required")


def _extract_preferred_keywords_local(job_description: str) -> list[str]:
    return _candidate_phrases(job_description, bucket="preferred")


def _extract_keywords_llm(job_description: str) -> list[str]:
    messages = [
        {
            "role": "system",
            "content": (
                "Extract ATS-style requirement keywords from the job description. "
                "Return JSON only: {\"keywords\":[\"...\"]}. Keep 8-25 concise terms."
            ),
        },
        {"role": "user", "content": job_description[:6000]},
    ]
    response = get_client_for_stage("score").chat(messages, temperature=0.0, max_tokens=800)
    data = json.loads(response.strip())
    keywords = data.get("keywords", []) if isinstance(data, dict) else []
    return [str(k).strip().casefold() for k in keywords if str(k).strip()][:30]


@lru_cache(maxsize=512)
def extract_requirement_keywords(job_description: str) -> tuple[str, ...]:
    """Return cached JD requirement keywords.

    Local extraction is default so scoring remains one main LLM call. Set
    DIVAPPLY_KEYWORD_EXTRACTOR=llm to use one cached LLM extraction per JD.
    """
    text = job_description or ""
    if os.environ.get("DIVAPPLY_KEYWORD_EXTRACTOR", "").casefold() == "llm":
        try:
            keywords = _extract_keywords_llm(text)
            if keywords:
                return tuple(keywords)
        except Exception:
            pass
    return tuple(_extract_keywords_local(text))


@lru_cache(maxsize=512)
def extract_preferred_keywords(job_description: str) -> tuple[str, ...]:
    """Return cached preferred/nice-to-have JD keywords."""
    return tuple(_extract_preferred_keywords_local(job_description or ""))


def score_keywords(job_description: str, resume_text: str) -> dict:
    """Score required keywords heavily and preferred keywords lightly."""
    required_keywords = list(extract_requirement_keywords(job_description))
    preferred_keywords = [
        keyword for keyword in extract_preferred_keywords(job_description)
        if keyword not in required_keywords
    ]
    resume = (resume_text or "").casefold()
    hits: list[str] = []
    misses: list[str] = []
    preferred_hits: list[str] = []
    preferred_misses: list[str] = []

    def _has_keyword(keyword: str) -> bool:
        if not keyword:
            return False
        if keyword in resume:
            return True
        parts = [part for part in keyword.split() if part not in _STOPWORDS]
        return bool(parts) and all(part in resume for part in parts)

    for keyword in required_keywords:
        if _has_keyword(keyword):
            hits.append(keyword)
        elif keyword:
            misses.append(keyword)

    for keyword in preferred_keywords:
        if _has_keyword(keyword):
            preferred_hits.append(keyword)
        elif keyword:
            preferred_misses.append(keyword)

    required_weight = 1.0
    preferred_weight = 0.25
    earned = len(hits) * required_weight + len(preferred_hits) * preferred_weight
    possible = len(required_keywords) * required_weight + len(preferred_keywords) * preferred_weight
    score = (earned / possible) if possible else 0.0
    return {
        "score": round(score, 4),
        "keywords": required_keywords + preferred_keywords,
        "required_keywords": required_keywords,
        "preferred_keywords": preferred_keywords,
        "hits": hits,
        "misses": misses,
        "preferred_hits": preferred_hits,
        "preferred_misses": preferred_misses,
    }
