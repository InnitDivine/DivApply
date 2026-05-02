from __future__ import annotations

import json

from divapply.scoring.composite import composite_score
from divapply.scoring.embedding import embedding_score
from divapply.scoring.keywords import score_keywords


def test_keyword_score_reports_hits_and_misses() -> None:
    jd = "Required skills: Python, SQL, Kubernetes, documentation."
    resume = "Built Python and SQL reports with clear documentation."

    result = score_keywords(jd, resume)

    assert result["score"] > 0
    assert "python" in result["hits"]
    assert "kubernetes" in result["misses"]


def test_embedding_score_is_bounded() -> None:
    score = embedding_score("python sql reporting", "python sql analytics")
    assert 0.0 <= score <= 1.0


def test_composite_score_returns_breakdown_json() -> None:
    result = composite_score(
        job_description="Required: Python, SQL, Kubernetes.",
        resume_text="Python SQL reporting.",
        llm_result={"score": 7, "reasoning": "Strong data fit."},
    )

    assert 1 <= result["score"] <= 10
    assert result["llm_score"] == 7
    assert 0.0 <= result["keyword_score"] <= 1.0
    assert 0.0 <= result["embedding_score"] <= 1.0
    breakdown = json.loads(result["score_breakdown"])
    assert "keyword" in breakdown
    assert "skill_gaps" in breakdown
