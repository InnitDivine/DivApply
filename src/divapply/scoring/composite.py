"""Hybrid job fit scoring orchestration."""

from __future__ import annotations

import json

from divapply.scoring.embedding import embedding_score
from divapply.scoring.keywords import score_keywords


DEFAULT_WEIGHTS = {"keyword": 0.3, "embedding": 0.3, "llm": 0.4}


def _clamp(value: float, low: float, high: float) -> float:
    return max(low, min(high, value))


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
    fit_score = int(round(composite_float))

    keyword_hits = keyword["hits"]
    keyword_misses = keyword["misses"]
    breakdown = {
        "keyword": {
            "score": keyword["score"],
            "hits": keyword_hits,
            "misses": keyword_misses,
        },
        "embedding": emb,
        "llm": {
            "score": llm_score,
            "reasoning": llm_result.get("reasoning", ""),
        },
        "weights": active_weights,
        "composite": composite_float,
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
