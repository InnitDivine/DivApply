"""Keyword extraction and hit-rate scoring for job descriptions."""

from __future__ import annotations

from dataclasses import dataclass
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
    "education", "e.g", "eg", "job", "jobs", "least", "level", "like", "looking", "more", "must",
    "advantage", "bonus", "certification", "certifications", "desired",
    "mandatory", "minimum", "nice",
    "need", "needs", "offer", "only", "optional", "other", "our", "plus", "qualification", "qualifications",
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
_REQUIRED_LINE_RE = re.compile(
    r"^(?:job\s+)?(?:special\s+requirements?|required(?:\s+(?:skills|qualifications|experience))?|requirements?|"
    r"minimum(?:\s+qualifications)?|mandatory|qualifications?|responsibilities|duties)\b|"
    r"\b(?:must\s+have|required\s+to|is\s+required|are\s+required|minimum\s+of)\b",
    re.IGNORECASE,
)
_PREFERRED_LINE_RE = re.compile(
    r"^(?:desirable\s+qualifications?|preferred(?:\s+(?:skills|qualifications|experience|certifications?))?|"
    r"nice[- ]to[- ]have|bonus|desired|optional|advantage)\b",
    re.IGNORECASE,
)
_REQUIREMENT_HEADING_RE = re.compile(
    r"^(?:job\s+)?(?:special\s+requirements?|required(?:\s+(?:skills|qualifications|experience))?|requirements?|"
    r"minimum(?:\s+qualifications)?|mandatory|qualifications?(?:\s*(?:&|and)\s*education)?|"
    r"responsibilities|duties|preferred(?:\s+(?:skills|qualifications|experience|certifications?))?|"
    r"desirable\s+qualifications?|nice[- ]to[- ]have|bonus|desired|optional|advantage)\s*:?[\s]*$",
    re.IGNORECASE,
)
_NON_REQUIREMENT_HEADINGS = {
    "additional information",
    "benefits",
    "classification",
    "compensation",
    "contact information",
    "department information",
    "employee benefits",
    "hourly rate",
    "job code",
    "number of positions",
    "pay range",
    "perks",
    "please note",
    "position details",
    "salary",
    "salary information",
    "what we offer",
    "working title",
}
_NON_REQUIREMENT_LINE_RE = re.compile(
    r"^(?:\.\.\.\[?middle omitted\]?\.\.\.|additional information\b|about\b|"
    r"benefits?\b|compensation\b|employment type\b|hourly rate\b|job type\b|"
    r"#\s*of positions?\b|job code\b|location\s*:|new to state candidates?\b|"
    r"number of positions?\b|pay\b|position\s*#|position details?\b|salary\b|"
    r"schedule\s*:|telework\b|work arrangement\b|work location\b|working title\b)",
    re.IGNORECASE,
)
_BOILERPLATE_BOUNDARIES = {
    "application instructions",
    "application package checklist",
    "application package documents",
    "applicants have rights under",
    "apply for this job",
    "eeo is the law",
    "equal opportunity and affirmative action",
    "equal opportunity employer",
    "how to apply",
    "public burden statement",
    "required application package documents",
    "statement of qualifications",
    "supplemental questionnaire",
    "voluntary self-identification",
    "who may apply",
}
_ADMINISTRATIVE_PHRASE_RE = re.compile(
    r"(?:"
    r"\b(?:alternate range|hourly rate|new to state candidates?|pay range|salary)\b|"
    r"\b(?:application (?:deadline|form|instructions?|materials?|package|process)|state application)\b|"
    r"\b(?:statement of qualifications?|std\s*678|transcripts?)\b|"
    r"\b(?:confidential information|employment history|filing date|how to apply|mailing address|selection process|"
    r"who may apply)\b|"
    r"\b(?:incomplete resumes?|please note)\b|"
    r"^#?\s*(?:number\s+of\s+|of\s+)?positions?\b|"
    r"^(?:classification|job code|position details?|working title)\b"
    r")",
    re.IGNORECASE,
)
_SKILL_HINTS = {
    "aws", "azure", "gcp", "linux", "windows", "python", "sql", "excel",
    "access", "administrative", "answering", "appointments", "billing", "cash",
    "cashier", "clerical", "confidentiality", "data entry", "front desk",
    "insurance", "microsoft", "office", "patient", "payments", "phone",
    "phones", "records", "registration", "typing",
    "powerpoint", "word", "javascript", "typescript", "react", "node",
    "kubernetes", "docker", "terraform", "salesforce", "workday",
    "greenhouse", "lever", "customer", "support", "accounting", "finance",
    "data", "analysis", "analytics", "documentation", "communication",
    "troubleshooting", "networking", "security", "compliance", "inventory",
    "scheduling", "reporting", "reconciliation", "billing", "crm",
}
_SKILL_PHRASES = {
    "active directory",
    "asset inventory",
    "basic networking",
    "cash handling",
    "customer service",
    "data entry",
    "device setup",
    "end-user support",
    "front desk",
    "medical terminology",
    "microsoft 365",
    "microsoft office",
    "patient registration",
    "phone etiquette",
    "problem-solving",
    "technical documentation",
    "user account management",
}
_EVIDENCE_EQUIVALENTS = {
    "device setup": ("workstation setup", "pc building", "windows installation"),
    "end-user support": ("end user support", "user assistance", "user support", "helped staff"),
    "problem-solving": ("problem solving", "troubleshooting", "resolved", "discrepancy research"),
}


@dataclass(frozen=True)
class KeywordScoringPolicy:
    """Weights and matching rules for keyword scoring."""

    required_weight: float = 1.0
    preferred_weight: float = 0.25


def _normalize_token(token: str) -> str:
    return token.strip(".,;:()[]{}'\"").casefold()


def _line_bucket(line: str, current: str | None) -> str | None:
    """Classify a JD line as required/preferred using headings and markers."""
    lowered = line.casefold().strip(" :.-")
    if lowered in _NON_REQUIREMENT_HEADINGS or _NON_REQUIREMENT_LINE_RE.search(line.strip()):
        return None
    if _PREFERRED_LINE_RE.search(lowered):
        return "preferred"
    if _REQUIRED_LINE_RE.search(lowered):
        return "required"
    return current


def _is_boilerplate_boundary(line: str) -> bool:
    lowered = line.casefold()
    return any(marker in lowered for marker in _BOILERPLATE_BOUNDARIES)


def _clean_phrase(phrase: str) -> str:
    parts = [_normalize_token(part) for part in phrase.split()]
    parts = [part for part in parts if part and part not in _STOPWORDS]
    return " ".join(parts).strip()


def _is_requirement_phrase(raw_phrase: str, clean_phrase: str) -> bool:
    """Reject metadata and application prose that cannot be a candidate skill."""
    if not re.search(r"[a-z]", clean_phrase, re.IGNORECASE):
        return False
    return _ADMINISTRATIVE_PHRASE_RE.search(f"{raw_phrase} {clean_phrase}") is None


def _strip_marker_prefix(line: str) -> str:
    return re.sub(
        r"^(required|requirements|required skills|required qualifications|minimum qualifications|"
        r"preferred|preferred qualifications|preferred skills|nice to have|nice-to-have|bonus|plus)"
        r"\s*[:\-]\s*",
        "",
        line,
    ).strip()


def _candidate_phrases(text: str, *, bucket: str = "required") -> list[str]:
    lowered = text.casefold()
    phrases: list[str] = []
    bucket_lines: list[str] = []

    current_bucket: str | None = None
    for line in lowered.splitlines():
        line = line.strip(" -•*\t")
        if not line:
            continue
        if _is_boilerplate_boundary(line):
            break
        current_bucket = _line_bucket(line, current_bucket)
        if current_bucket != bucket:
            continue
        if _REQUIREMENT_HEADING_RE.fullmatch(line.strip()):
            continue
        bucket_lines.append(line)
        markerless = _strip_marker_prefix(line)
        if markerless and markerless != line:
            phrases.extend(chunk.strip() for chunk in re.split(r"[,;/]| and | or ", markerless))
        if _REQUIRED_LINE_RE.search(line) or _PREFERRED_LINE_RE.search(line):
            chunks = re.split(r"[,;/]| and | or ", line)
            phrases.extend(chunk.strip() for chunk in chunks)
        elif 1 <= len(markerless.split()) <= 6:
            phrases.append(markerless)

    bucket_text = "\n".join(bucket_lines)
    words = [_normalize_token(w) for w in _WORD_RE.findall(bucket_text)]
    words = [w for w in words if len(w) > 2 and w not in _STOPWORDS]
    for word in words:
        if word in _SKILL_HINTS or any(c in word for c in ("+", "#", ".")):
            phrases.append(word)

    for phrase in sorted(_SKILL_PHRASES):
        if phrase in bucket_text:
            phrases.append(phrase)

    seen: set[str] = set()
    ordered: list[str] = []
    for phrase in phrases:
        clean = _clean_phrase(phrase)
        if clean and _is_requirement_phrase(phrase, clean) and clean not in seen and clean not in _STOPWORDS:
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


def keyword_present(keyword: str, text: str) -> bool:
    """Return True when a keyword or all meaningful keyword parts are present."""
    if not keyword:
        return False
    if keyword in text:
        return True
    if any(evidence in text for evidence in _EVIDENCE_EQUIVALENTS.get(keyword, ())):
        return True
    parts = [part for part in keyword.split() if part not in _STOPWORDS]
    return bool(parts) and all(part in text for part in parts)


def score_keywords(
    job_description: str,
    resume_text: str,
    *,
    policy: KeywordScoringPolicy | None = None,
) -> dict:
    """Score required keywords heavily and preferred keywords lightly."""
    policy = policy or KeywordScoringPolicy()
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

    for keyword in required_keywords:
        if keyword_present(keyword, resume):
            hits.append(keyword)
        elif keyword:
            misses.append(keyword)

    for keyword in preferred_keywords:
        if keyword_present(keyword, resume):
            preferred_hits.append(keyword)
        elif keyword:
            preferred_misses.append(keyword)

    earned = len(hits) * policy.required_weight + len(preferred_hits) * policy.preferred_weight
    possible = len(required_keywords) * policy.required_weight + len(preferred_keywords) * policy.preferred_weight
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
