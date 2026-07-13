"""Hybrid job fit scoring orchestration."""

from __future__ import annotations

import json
import re

from divapply.scoring.embedding import embedding_score
from divapply.scoring.keywords import score_keywords


DEFAULT_WEIGHTS = {"keyword": 0.3, "embedding": 0.3, "llm": 0.4}

_CREDENTIAL_GAP_TERMS = {
    "clearance",
    "credential",
    "certification",
    "certified",
    "degree",
    "license",
    "licensure",
}
_EXPLICIT_DISQUALIFIER_TERMS = {
    "incompatible",
    "ineligible",
    "not eligible",
    "not qualified",
    "scam",
}
_REQUIRED_GAP_TERMS = {
    "cannot substitute",
    "hard gap",
    "mandatory certification",
    "mandatory degree",
    "mandatory license",
    "minimum qualification",
    "must have",
    "non-substitutable",
    "required certification",
    "required credential",
    "required degree",
    "required license",
    "required licensure",
    "required clearance",
    "missing required",
}
_MISSING_GAP_TERMS = {
    "does not have",
    "lack of",
    "lacks",
    "missing",
    "without",
}
_NON_SUBSTITUTABLE_TERMS = {
    "cannot substitute",
    "mandatory certification",
    "mandatory degree",
    "mandatory license",
    "non-substitutable",
}
_SUBSTITUTION_TERMS = {
    "accepted alternative",
    "alternative qualification",
    "degree not required",
    "equivalent experience",
    "experience accepted",
    "experience may substitute",
    "experience can substitute",
    "or equivalent",
    "or related experience",
    "substitutable",
}
_PREFERRED_ONLY_TERMS = {
    "bonus",
    "desired",
    "nice to have",
    "nice-to-have",
    "optional",
    "plus",
    "preferred",
}
_APPLY_RECOMMENDATION_TERMS = ("apply", "strong match", "good match")
_NEGATIVE_APPLY_TERMS = ("do not apply", "skip", "only if", "unless", "not eligible")
_SCHEDULE_MISMATCH_TERMS = (
    "40 hours",
    "full time",
    "full-time",
    "hours conflict",
    "not part-time",
    "part time required",
    "part-time required",
    "schedule conflict",
    "schedule mismatch",
)
_LOW_HOUR_ROLE_TERMS = (
    "part time",
    "part-time",
    "per diem",
    "per-diem",
    "seasonal",
    "temporary",
)
_PART_TIME_TERMS = ("part time", "part-time", "parttime")
_FULL_TIME_TERMS = ("full time", "full-time", "fulltime")
_BENEFITS_TERMS = (
    "benefits eligible",
    "benefits include",
    "benefits package",
    "dental insurance",
    "health insurance",
    "medical insurance",
    "pension",
    "retirement plan",
    "vision insurance",
    "401(k)",
    "401k",
)
_NO_BENEFITS_TERMS = ("no benefits", "not benefits eligible", "without benefits")


def _clamp(value: float, low: float, high: float) -> float:
    return max(low, min(high, value))


def _has_hard_mismatch(llm_result: dict, job_description: str = "") -> bool:
    """Return True when the LLM found a non-substitutable requirement gap."""
    evidence = " ".join(
        str(llm_result.get(key, "")) for key in ("risk_flags", "missing_skills", "apply_or_skip_reason", "reasoning")
    ).casefold()
    if any(term in evidence for term in _EXPLICIT_DISQUALIFIER_TERMS):
        return True
    if any(term in evidence for term in _NON_SUBSTITUTABLE_TERMS):
        return True
    substitution_evidence = f"{evidence} {job_description.casefold()}"
    if any(term in substitution_evidence for term in _SUBSTITUTION_TERMS):
        return False

    has_required_gap = any(term in evidence for term in _REQUIRED_GAP_TERMS)
    has_preferred_only_gap = any(term in evidence for term in _PREFERRED_ONLY_TERMS) and not has_required_gap
    if has_preferred_only_gap:
        return False
    if "missing required" in evidence:
        return True

    has_credential = any(term in evidence for term in _CREDENTIAL_GAP_TERMS)
    has_missing_gap = any(term in evidence for term in _MISSING_GAP_TERMS)
    return has_credential and (has_required_gap or has_missing_gap)


def _has_positive_apply_signal(llm_result: dict, job_description: str = "") -> bool:
    """Return True when the LLM found a strong fit without hard disqualifiers."""
    if _has_hard_mismatch(llm_result, job_description):
        return False

    apply_reason = str(llm_result.get("apply_or_skip_reason", "") or "").casefold()
    reasoning = str(llm_result.get("reasoning", "") or "").casefold()
    evidence = f"{apply_reason} {reasoning}"
    if any(term in evidence for term in _NEGATIVE_APPLY_TERMS):
        return False
    return any(term in evidence for term in _APPLY_RECOMMENDATION_TERMS)


def _has_schedule_only_mismatch(llm_result: dict, job_description: str = "") -> bool:
    """Return True when the stated concern is schedule, not qualifications."""
    if _has_hard_mismatch(llm_result, job_description):
        return False
    evidence = " ".join(
        str(llm_result.get(key, "")) for key in ("risk_flags", "missing_skills", "apply_or_skip_reason", "reasoning")
    ).casefold()
    if not any(term in evidence for term in _SCHEDULE_MISMATCH_TERMS):
        return False
    return not any(term in evidence for term in _REQUIRED_GAP_TERMS)


def _posted_hours_per_week(job_description: str) -> list[float]:
    """Return explicit weekly-hour values/range endpoints from posting text."""
    values: list[float] = []
    pattern = re.compile(
        r"\b(\d{1,3}(?:\.\d+)?)\s*(?:-|–|to)?\s*(\d{1,3}(?:\.\d+)?)?\s*hours?\s*(?:per|a|/)\s*week\b",
        re.IGNORECASE,
    )
    for match in pattern.finditer(job_description):
        for raw in match.groups():
            if raw is not None:
                values.append(float(raw))
    return values


def _schedule_evidence(job_description: str) -> tuple[bool, bool]:
    text = job_description.casefold()
    part_time = any(term in text for term in _PART_TIME_TERMS)
    full_time = any(term in text for term in _FULL_TIME_TERMS) or any(
        hours >= 35 for hours in _posted_hours_per_week(job_description)
    )
    if any(term in text for term in ("not part-time", "not part time")):
        part_time = False
    if any(term in text for term in ("not full-time", "not full time")):
        full_time = False
    return part_time, full_time


def _has_benefits_evidence(job_description: str) -> bool:
    text = job_description.casefold()
    return not any(term in text for term in _NO_BENEFITS_TERMS) and any(
        term in text for term in _BENEFITS_TERMS
    )


def composite_score(
    *,
    job_description: str,
    resume_text: str,
    llm_result: dict,
    weights: dict | None = None,
    schedule_exception: bool = False,
    preferred_schedule: str = "any",
    require_part_time: bool = False,
    max_hours_per_week: int | float | None = None,
    require_benefits: bool = False,
    source_verification: str = "",
) -> dict:
    """Blend keyword, embedding, and LLM scores into a calibrated 1-10 score."""
    active_weights = {**DEFAULT_WEIGHTS, **(weights or {})}
    keyword = score_keywords(job_description, resume_text)
    keyword_modality_available = bool(keyword.get("keywords"))
    if not keyword_modality_available:
        active_weights["keyword"] = 0.0
    total = sum(max(0.0, float(v)) for v in active_weights.values()) or 1.0
    active_weights = {k: max(0.0, float(v)) / total for k, v in active_weights.items()}

    emb = embedding_score(resume_text, job_description)
    llm_score = int(_clamp(float(llm_result.get("score") or 0), 0.0, 10.0))
    llm_norm = llm_score / 10.0

    composite_norm = (
        active_weights["keyword"] * keyword["score"]
        + active_weights["embedding"] * emb
        + active_weights["llm"] * llm_norm
    )
    composite_float = round(_clamp(composite_norm * 10.0, 1.0, 10.0), 2)

    # Hard requirement gaps must not be diluted by broad keyword overlap.
    # Example: a missing required license can share many words with a resume,
    # but the candidate still does not meet the posting's minimum criteria.
    hard_mismatch_cap = llm_score <= 2 and _has_hard_mismatch(llm_result, job_description)
    if hard_mismatch_cap:
        composite_float = min(composite_float, float(max(1, llm_score)))

    positive_apply_floor = llm_score >= 7 and _has_positive_apply_signal(llm_result, job_description)
    if positive_apply_floor:
        composite_float = max(composite_float, float(min(llm_score, 7)))

    referral_schedule_exception = bool(
        schedule_exception
        and not hard_mismatch_cap
        and _has_schedule_only_mismatch(llm_result, job_description)
    )
    if referral_schedule_exception:
        composite_float = max(composite_float, 6.0)

    target_priority = str(llm_result.get("target_priority") or "").strip().casefold()
    # Missing/malformed priority is not evidence that a job belongs in the
    # primary queue. Fail closed until a valid P1/P2 classification exists.
    search_priority_cap = target_priority not in {"1", "2"}
    part_time_evidence, full_time_evidence = _schedule_evidence(job_description)
    normalized_schedule = str(preferred_schedule or "any").strip().casefold()
    schedule_preference_cap = False
    if require_part_time:
        schedule_preference_cap = not part_time_evidence or full_time_evidence
    elif normalized_schedule == "full_time":
        schedule_preference_cap = (
            not full_time_evidence
            or any(term in job_description.casefold() for term in _LOW_HOUR_ROLE_TERMS)
        )
    elif normalized_schedule == "part_time":
        schedule_preference_cap = not part_time_evidence or full_time_evidence

    if max_hours_per_week is not None:
        try:
            maximum = float(max_hours_per_week)
        except (TypeError, ValueError):
            maximum = 0.0
        posted_hours = _posted_hours_per_week(job_description)
        schedule_preference_cap = schedule_preference_cap or (
            maximum > 0 and (not posted_hours or max(posted_hours) > maximum)
        )

    if schedule_exception and not hard_mismatch_cap:
        schedule_preference_cap = False

    benefits_evidence_cap = bool(require_benefits and not _has_benefits_evidence(job_description))
    source_verification_cap = (
        str(source_verification or "").strip().casefold() == "unverified_aggregator"
    )
    if (
        search_priority_cap
        or schedule_preference_cap
        or benefits_evidence_cap
        or source_verification_cap
    ):
        composite_float = min(composite_float, 6.0)

    fit_score = int(round(composite_float))

    keyword_hits = keyword["hits"]
    keyword_misses = keyword["misses"]
    breakdown = {
        "keyword": {
            "score": keyword["score"],
            "hits": keyword_hits,
            "misses": keyword_misses,
            "required_keywords": keyword.get("required_keywords", []),
            "preferred_keywords": keyword.get("preferred_keywords", []),
            "preferred_hits": keyword.get("preferred_hits", []),
            "preferred_misses": keyword.get("preferred_misses", []),
        },
        "embedding": emb,
        "llm": {
            "score": llm_score,
            "reasoning": llm_result.get("reasoning", ""),
        },
        "weights": active_weights,
        "keyword_modality_available": keyword_modality_available,
        "composite": composite_float,
        "hard_mismatch_cap": hard_mismatch_cap,
        "positive_apply_floor": positive_apply_floor,
        "referral_schedule_exception": referral_schedule_exception,
        "search_priority_cap": search_priority_cap,
        "schedule_preference_cap": schedule_preference_cap,
        "benefits_evidence_cap": benefits_evidence_cap,
        "source_verification_cap": source_verification_cap,
        "skill_gaps": keyword_misses[:12],
    }

    return {
        "score": fit_score,
        "llm_score": llm_score,
        "keyword_score": keyword["score"],
        "embedding_score": emb,
        "composite_score": composite_float,
        "score_breakdown": json.dumps(breakdown, ensure_ascii=True),
        "keyword_hits": ", ".join(keyword_hits),
        "missing_skills": ", ".join(keyword_misses[:20]) or llm_result.get("missing_skills", ""),
    }
