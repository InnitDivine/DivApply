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
    "need", "needs", "offer", "only", "other", "our", "plus", "preferred",
    "provide", "required", "requirements", "responsibilities", "role",
    "should", "some", "team", "than", "that", "the", "their", "them",
    "then", "this", "through", "time", "using", "will", "with", "work",
    "years", "your",
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


def _candidate_phrases(text: str) -> list[str]:
    lowered = text.casefold()
    phrases: list[str] = []

    for line in lowered.splitlines():
        line = line.strip(" -•*\t")
        if not line:
            continue
        if any(mark in line for mark in ("required", "requirement", "qualification", "experience", "skill")):
            chunks = re.split(r"[,;/]| and | or ", line)
            phrases.extend(chunk.strip() for chunk in chunks)

    words = [_normalize_token(w) for w in _WORD_RE.findall(lowered)]
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
        clean = " ".join(_normalize_token(part) for part in phrase.split())
        clean = clean.strip()
        if clean and clean not in seen and clean not in _STOPWORDS:
            seen.add(clean)
            ordered.append(clean)
    return ordered[:30]


def _extract_keywords_local(job_description: str) -> list[str]:
    return _candidate_phrases(job_description)


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


def score_keywords(job_description: str, resume_text: str) -> dict:
    """Score requirement-keyword hit rate against the resume text."""
    keywords = list(extract_requirement_keywords(job_description))
    resume = (resume_text or "").casefold()
    hits: list[str] = []
    misses: list[str] = []
    for keyword in keywords:
        if keyword and keyword in resume:
            hits.append(keyword)
        elif keyword:
            misses.append(keyword)

    score = (len(hits) / len(keywords)) if keywords else 0.0
    return {
        "score": round(score, 4),
        "keywords": keywords,
        "hits": hits,
        "misses": misses,
    }
