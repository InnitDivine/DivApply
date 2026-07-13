"""Hybrid job fit scoring orchestration."""

from __future__ import annotations

import json

from divapply.scoring.embedding import embedding_score
from divapply.scoring.keywords import score_keywords


DEFAULT_WEIGHTS = {"keyword": 0.3, "embedding": 0.3, "llm": 0.4}

_HARD_MISMATCH_TERMS = {
    "clearance",
    "credential",
    "certification",
    "certified",
    "degree",
    "incompatible",
    "license",
    "licensure",
    "missing required",
    "not qualified",
    "required license",
    "required certification",
    "required degree",
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
_REFERRAL_EXCEPTION_TERMS = (
    "employee referral",
    "employer priority",
    "priority employer",
    "priority-employer",
    "referral",
    "referred",
    "schedule exception",
)
_LOW_HOUR_ROLE_TERMS = (
    "part time",
    "part-time",
    "per diem",
    "per-diem",
    "seasonal",
    "temporary",
)


def _clamp(value: float, low: float, high: float) -> float:
    return max(low, min(high, value))


def _has_hard_mismatch(llm_result: dict) -> bool:
    """Return True when the LLM found a non-substitutable requirement gap."""
    evidence = " ".join(
        str(llm_result.get(key, "")) for key in ("risk_flags", "missing_skills", "apply_or_skip_reason", "reasoning")
    ).casefold()
    has_hard_gap = any(term in evidence for term in _HARD_MISMATCH_TERMS)
    if not has_hard_gap:
        return False

    has_required_gap = any(term in evidence for term in _REQUIRED_GAP_TERMS)
    has_preferred_only_gap = any(term in evidence for term in _PREFERRED_ONLY_TERMS) and not has_required_gap
    if has_preferred_only_gap:
        return False

    return True


def _has_positive_apply_signal(llm_result: dict) -> bool:
    """Return True when the LLM found a strong fit without hard disqualifiers."""
    if _has_hard_mismatch(llm_result):
        return False

    apply_reason = str(llm_result.get("apply_or_skip_reason", "") or "").casefold()
    reasoning = str(llm_result.get("reasoning", "") or "").casefold()
    evidence = f"{apply_reason} {reasoning}"
    if any(term in evidence for term in _NEGATIVE_APPLY_TERMS):
        return False
    return any(term in evidence for term in _APPLY_RECOMMENDATION_TERMS)


def _has_schedule_only_mismatch(llm_result: dict) -> bool:
    """Return True when the stated concern is schedule, not qualifications."""
    if _has_hard_mismatch(llm_result):
        return False
    evidence = " ".join(
        str(llm_result.get(key, "")) for key in ("risk_flags", "missing_skills", "apply_or_skip_reason", "reasoning")
    ).casefold()
    if not any(term in evidence for term in _SCHEDULE_MISMATCH_TERMS):
        return False
    return not any(term in evidence for term in _REQUIRED_GAP_TERMS)


def _has_referral_or_priority_exception(*, job_description: str, resume_text: str, llm_result: dict) -> bool:
    """Return True when search context or LLM evidence marks a referral exception."""
    job_evidence = job_description.casefold()
    llm_evidence = " ".join(
        str(llm_result.get(key, "")) for key in ("risk_flags", "missing_skills", "apply_or_skip_reason", "reasoning")
    )
    evidence = f"{job_description} {resume_text} {llm_evidence}".casefold()
    has_exception = any(term in evidence for term in _REFERRAL_EXCEPTION_TERMS)
    if not has_exception:
        return False
    return any(
        marker in job_evidence
        for marker in (
            "referral/priority employer schedule exception:",
            "priority employer:",
            "employer priority:",
        )
    )


def composite_score(
    *,
    job_description: str,
    resume_text: str,
    llm_result: dict,
    weights: dict | None = None,
) -> dict:
    """Blend keyword, embedding, and LLM scores into a calibrated 1-10 score."""
    active_weights = {**DEFAULT_WEIGHTS, **(weights or {})}
    total = sum(max(0.0, float(v)) for v in active_weights.values()) or 1.0
    active_weights = {k: max(0.0, float(v)) / total for k, v in active_weights.items()}

    keyword = score_keywords(job_description, resume_text)
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
    hard_mismatch_cap = llm_score <= 2 and _has_hard_mismatch(llm_result)
    if hard_mismatch_cap:
        composite_float = min(composite_float, float(max(1, llm_score)))

    positive_apply_floor = llm_score >= 7 and _has_positive_apply_signal(llm_result)
    if positive_apply_floor:
        composite_float = max(composite_float, float(min(llm_score, 7)))

    referral_schedule_exception = (
        not hard_mismatch_cap
        and _has_schedule_only_mismatch(llm_result)
        and _has_referral_or_priority_exception(
            job_description=job_description,
            resume_text=resume_text,
            llm_result=llm_result,
        )
    )
    if referral_schedule_exception:
        composite_float = max(composite_float, 6.0)

    target_priority = str(llm_result.get("target_priority") or "").strip().casefold()
    # Missing/malformed priority is not evidence that a job belongs in the
    # primary queue. Fail closed until a valid P1/P2 classification exists.
    search_priority_cap = target_priority not in {"1", "2"}
    schedule_preference_cap = (
        "search schedule preference: full-time professional roles" in resume_text.casefold()
        and any(term in job_description.casefold() for term in _LOW_HOUR_ROLE_TERMS)
        and not _has_referral_or_priority_exception(
            job_description=job_description,
            resume_text=resume_text,
            llm_result=llm_result,
        )
    )
    if search_priority_cap or schedule_preference_cap:
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
        "composite": composite_float,
        "hard_mismatch_cap": hard_mismatch_cap,
        "positive_apply_floor": positive_apply_floor,
        "referral_schedule_exception": referral_schedule_exception,
        "search_priority_cap": search_priority_cap,
        "schedule_preference_cap": schedule_preference_cap,
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
