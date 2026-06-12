from __future__ import annotations

import json

from divapply.scoring.composite import composite_score
from divapply.scoring.context import format_job_context
from divapply.scoring.embedding import embedding_score
from divapply.scoring.keywords import score_keywords
from divapply.scoring import scorer
from divapply.scoring.scorer import _build_profile_evidence_context


def test_keyword_score_reports_hits_and_misses() -> None:
    jd = "Required skills: Python, SQL, Kubernetes, documentation."
    resume = "Built Python and SQL reports with clear documentation."

    result = score_keywords(jd, resume)

    assert result["score"] > 0
    assert "python" in result["hits"]
    assert "kubernetes" in result["misses"]


def test_keyword_score_weights_preferred_certifications_lightly() -> None:
    jd = "\n".join([
        "Required skills: Python, SQL.",
        "Preferred certifications: AWS Certified Cloud Practitioner.",
    ])
    resume = "Built Python and SQL reports."

    result = score_keywords(jd, resume)

    assert any("aws" in keyword for keyword in result["preferred_keywords"])
    assert not any("aws" in keyword for keyword in result["required_keywords"])
    assert result["score"] >= 0.7


def test_keyword_score_keeps_preferred_qualifications_out_of_required_bucket() -> None:
    jd = "\n".join([
        "Preferred Qualifications:",
        "- AWS Certified Cloud Practitioner.",
        "Required Qualifications:",
        "- Python.",
        "- SQL.",
    ])
    resume = "Built Python and SQL reports."

    result = score_keywords(jd, resume)

    assert any("aws" in keyword for keyword in result["preferred_keywords"])
    assert not any("aws" in keyword for keyword in result["required_keywords"])


def test_embedding_score_is_bounded() -> None:
    score = embedding_score("python sql reporting", "python sql analytics")
    assert 0.0 <= score <= 1.0


def test_format_job_context_keeps_company_and_source_separate() -> None:
    text = format_job_context(
        {
            "title": "Support Analyst",
            "company": "Real Employer",
            "site": "Indeed",
            "location": "Remote",
            "full_description": "Required: Python support.",
        }
    )

    assert "COMPANY: Real Employer" in text
    assert "SOURCE: Indeed" in text


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


def test_composite_score_caps_non_substitutable_requirement_gap() -> None:
    result = composite_score(
        job_description="Required: Python, SQL, documentation, CPA license.",
        resume_text="Python SQL documentation reporting analytics.",
        llm_result={
            "score": 1,
            "risk_flags": "required license gap",
            "missing_skills": "CPA license",
            "reasoning": "Posting requires a CPA license not supported by the resume.",
        },
    )

    breakdown = json.loads(result["score_breakdown"])
    assert result["score"] == 1
    assert breakdown["hard_mismatch_cap"] is True


def test_composite_score_caps_plain_missing_license_gap_when_llm_rejects() -> None:
    result = composite_score(
        job_description="Required: Python, SQL, CPA license.",
        resume_text="Python SQL reporting analytics.",
        llm_result={
            "score": 1,
            "risk_flags": "missing CPA license",
            "missing_skills": "CPA license",
            "reasoning": "Missing CPA license.",
        },
    )

    breakdown = json.loads(result["score_breakdown"])
    assert result["score"] == 1
    assert breakdown["hard_mismatch_cap"] is True


def test_composite_score_does_not_cap_preferred_only_certificate_gap() -> None:
    result = composite_score(
        job_description="Required: Python, SQL. Preferred: AWS certification.",
        resume_text="Python SQL reporting analytics.",
        llm_result={
            "score": 2,
            "risk_flags": "preferred certification missing",
            "missing_skills": "preferred AWS certification",
            "reasoning": "Candidate meets required criteria but lacks a preferred certification.",
        },
    )

    breakdown = json.loads(result["score_breakdown"])
    assert breakdown["hard_mismatch_cap"] is False


def test_composite_score_preserves_positive_llm_apply_signal() -> None:
    result = composite_score(
        job_description="Part-time cashier. Customer service and accurate payments required.",
        resume_text="Municipal public counter service, payment processing, records, scheduling.",
        llm_result={
            "score": 8,
            "risk_flags": "none",
            "apply_or_skip_reason": "Apply - strong match for customer service and payments.",
            "reasoning": "Strong match for entry-level part-time cashier work.",
        },
        weights={"keyword": 0.45, "embedding": 0.45, "llm": 0.1},
    )

    breakdown = json.loads(result["score_breakdown"])
    assert result["score"] >= 7
    assert breakdown["positive_apply_floor"] is True
    assert result["score"] > 2


def test_score_job_prompt_uses_company_separate_from_source(monkeypatch) -> None:
    captured: dict = {}

    class FakeClient:
        def chat(self, messages, **kwargs):
            captured["messages"] = messages
            return "\n".join([
                "FIT_SCORE: 7",
                "MATCHED_SKILLS: Python",
                "MISSING_SKILLS: none",
                "KEYWORD_HITS: Python",
                "RISK_FLAGS: none",
                "APPLY_OR_SKIP_REASON: Apply.",
                "SCORE_REASONING: Meets core criteria.",
            ])

    monkeypatch.setattr(scorer, "get_client_for_stage", lambda stage: FakeClient())

    scorer.score_job(
        resume_text="Python support work.",
        job={
            "title": "Support Analyst",
            "company": "Real Employer",
            "site": "Indeed",
            "location": "Remote",
            "full_description": "Required: Python support.",
        },
    )

    user_prompt = captured["messages"][1]["content"]
    assert "COMPANY: Real Employer" in user_prompt
    assert "SOURCE: Indeed" in user_prompt


def test_score_prompt_does_not_penalize_job_category_alone() -> None:
    prompt = scorer.SCORE_PROMPT

    assert "Rank only job fit" in prompt
    assert "current search target, availability, schedule limits" in prompt
    assert "unless the profile's current search target or availability makes it relevant" in prompt
    assert "do not require the same prior job title or exact industry/tool" in prompt
    assert "avoid scoring below 6 solely because the candidate lacks exact same-title experience" in prompt
    assert "Do not penalize legitimate remote" in prompt
    assert "Preferred/nice-to-have certifications" in prompt
    assert "required/minimum/must have" in prompt


def test_profile_evidence_context_includes_verified_facts_without_secrets() -> None:
    profile = {
        "personal": {
            "city": "Logan",
            "province_state": "UT",
            "password": "do-not-include",
        },
        "experience": {
            "target_role": "IT Support Analyst",
            "years_of_experience_it": "3",
            "education_level": "Bachelor's Degree (in progress)",
        },
        "availability": {
            "available_for_full_time": "No while in school",
            "available_for_part_time": "Yes, 5-15 hours per week",
        },
        "skills_boundary": {
            "infrastructure": ["Oracle Cloud Infrastructure", "Nginx"],
            "networking": ["DNS", "SSH"],
        },
        "application_context": [
            "Bridgerland Technical College IT certification training is in progress.",
            "Password should not appear.",
        ],
        "resume_facts": {
            "preserved_projects": ["Oracle Cloud home lab"],
            "real_metrics": ["3.692 GPA"],
        },
    }

    context = _build_profile_evidence_context(profile)

    assert "Location: Logan, UT" in context
    assert "IT Support Analyst" in context
    assert "Available For Full Time: No while in school" in context
    assert "Available For Part Time: Yes, 5-15 hours per week" in context
    assert "Oracle Cloud Infrastructure" in context
    assert "Bridgerland Technical College" in context
    assert "do-not-include" not in context
    assert "Password should not appear" not in context
