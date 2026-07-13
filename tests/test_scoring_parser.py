from __future__ import annotations

from divapply.scoring.scorer import _parse_score_response


def test_parse_score_response_transparent_fields() -> None:
    parsed = _parse_score_response(
        "\n".join(
            [
                "FIT_SCORE: 8",
                "TARGET_PRIORITY: 2",
                "MATCHED_SKILLS: Python, SQL",
                "MISSING_SKILLS: Kubernetes",
                "KEYWORD_HITS: automation, reporting",
                "RISK_FLAGS: none",
                "APPLY_OR_SKIP_REASON: Apply, strong overlap.",
                "SCORE_REASONING: Meets most requirements with one infra gap.",
            ]
        )
    )

    assert parsed == {
        "score": 8,
        "target_priority": "2",
        "matched_skills": "Python, SQL",
        "missing_skills": "Kubernetes",
        "keyword_hits": "automation, reporting",
        "risk_flags": "none",
        "apply_or_skip_reason": "Apply, strong overlap.",
        "reasoning": "Meets most requirements with one infra gap.",
    }


def test_parse_score_response_keeps_old_format_compatible() -> None:
    parsed = _parse_score_response("SCORE: 12\nKEYWORDS: Excel\nREASONING: Good match")

    assert parsed["score"] == 10
    assert parsed["keyword_hits"] == "Excel"
    assert parsed["reasoning"] == "Good match"


def test_parse_score_response_accepts_markdown_bold_labels() -> None:
    parsed = _parse_score_response(
        "\n".join(
            [
                "**FIT_SCORE:** 8",
                "**MATCHED_SKILLS:** Python, SQL",
                "**MISSING_SKILLS:** none",
                "**KEYWORD_HITS:** reporting",
                "**RISK_FLAGS:** none",
                "**APPLY_OR_SKIP_REASON:** Apply.",
                "**SCORE_REASONING:** Strong overlap.",
            ]
        )
    )

    assert parsed["score"] == 8
    assert parsed["matched_skills"] == "Python, SQL"
    assert parsed["missing_skills"] == "none"
    assert parsed["keyword_hits"] == "reporting"
    assert parsed["risk_flags"] == "none"
    assert parsed["apply_or_skip_reason"] == "Apply."
    assert parsed["reasoning"] == "Strong overlap."


def test_parse_score_response_keeps_missing_numeric_score_at_zero() -> None:
    parsed = _parse_score_response("FIT_SCORE: unavailable\nREASONING: Model omitted a numeric score")

    assert parsed["score"] == 0


def test_parse_score_response_normalizes_outside_target_priority() -> None:
    parsed = _parse_score_response(
        "FIT_SCORE: 8\nTARGET_PRIORITY: outside named families\nSCORE_REASONING: Transferable but outside targets."
    )

    assert parsed["target_priority"] == "outside"
