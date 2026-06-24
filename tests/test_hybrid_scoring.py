from __future__ import annotations

import json

from divapply.scoring.composite import composite_score
from divapply.scoring.context import format_job_context
from divapply.scoring.embedding import embedding_score
from divapply.scoring.keywords import KeywordScoringPolicy, extract_requirement_keywords, keyword_present, score_keywords
from divapply.scoring import scorer
from divapply.scoring.scorer import _build_profile_evidence_context, _build_search_evidence_context


def test_keyword_score_reports_hits_and_misses() -> None:
    jd = "Required skills: Python, SQL, Kubernetes, documentation."
    resume = "Built Python and SQL reports with clear documentation."

    result = score_keywords(jd, resume)

    assert result["score"] > 0
    assert "python" in result["hits"]
    assert "kubernetes" in result["misses"]


def test_keyword_present_matches_meaningful_phrase_parts() -> None:
    assert keyword_present("customer support", "support specialist with customer-facing work")
    assert not keyword_present("customer support", "customer records only")


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


def test_keyword_score_accepts_custom_policy_weights() -> None:
    jd = "Required: Python. Preferred: AWS."
    resume = "Python and AWS."

    result = score_keywords(
        jd,
        resume,
        policy=KeywordScoringPolicy(required_weight=1.0, preferred_weight=0.0),
    )

    assert result["score"] == 1.0


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


def test_keyword_extraction_captures_admin_service_bullets_without_marker_repetition() -> None:
    jd = "\n".join([
        "Required Qualifications:",
        "- Cash handling",
        "- Phone etiquette",
        "- Patient registration",
        "- Microsoft Office",
        "Preferred Qualifications:",
        "- Medical terminology",
    ])

    keywords = extract_requirement_keywords(jd)
    preferred = score_keywords(jd, "cash handling phone etiquette patient registration microsoft office")

    assert "cash handling" in keywords
    assert "phone etiquette" in keywords
    assert "patient registration" in keywords
    assert "microsoft office" in keywords
    assert "medical terminology" in preferred["preferred_misses"]
    assert preferred["score"] >= 0.75


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


def test_composite_score_preserves_apply_signal_with_minor_risks() -> None:
    result = composite_score(
        job_description=(
            "Part-time front desk agent. Duties include greeting guests, reservations, "
            "payment handling, phones, records, and customer problem solving."
        ),
        resume_text="Public counter service, payment processing, scheduling, records, and customer support.",
        llm_result={
            "score": 8,
            "risk_flags": "schedule flexibility not explicitly confirmed; no exact same-title experience",
            "missing_skills": "property management system",
            "apply_or_skip_reason": "Apply - transferable front desk and payment experience align well.",
            "reasoning": "Strong fit for customer-facing front desk duties with only minor system/schedule unknowns.",
        },
        weights={"keyword": 0.45, "embedding": 0.45, "llm": 0.1},
    )

    breakdown = json.loads(result["score_breakdown"])
    assert result["score"] >= 7
    assert breakdown["positive_apply_floor"] is True


def test_composite_score_lifts_schedule_only_sutter_referral_exception() -> None:
    result = composite_score(
        job_description=(
            "TITLE: Patient Access Representative\n"
            "COMPANY: Sutter Health\n"
            "DESCRIPTION:\nFull-time role. Required: customer service, patient registration, scheduling."
        ),
        resume_text=(
            "Customer service, scheduling, records, payments.\n"
            "Referral/priority employer schedule exception: Sutter Health may be scored without the part-time-only penalty."
        ),
        llm_result={
            "score": 4,
            "risk_flags": "full-time schedule mismatch",
            "missing_skills": "none",
            "apply_or_skip_reason": "Apply because this is a Sutter Health referral exception.",
            "reasoning": "Only concern is full-time schedule against a part-time search filter.",
        },
    )

    breakdown = json.loads(result["score_breakdown"])
    assert result["score"] >= 6
    assert breakdown["referral_schedule_exception"] is True


def test_composite_score_does_not_apply_sutter_exception_to_other_employers() -> None:
    result = composite_score(
        job_description=(
            "TITLE: Front Desk Representative\n"
            "COMPANY: Local Retail Employer\n"
            "DESCRIPTION:\nFull-time role. Required: customer service, scheduling, and records."
        ),
        resume_text=(
            "Customer service, scheduling, records, payments.\n"
            "Referral/priority employer schedule exception: Sutter Health may be scored without the part-time-only penalty."
        ),
        llm_result={
            "score": 4,
            "risk_flags": "full-time schedule mismatch",
            "missing_skills": "none",
            "apply_or_skip_reason": "Only apply if the schedule works.",
            "reasoning": "Only concern is full-time schedule against a part-time search filter.",
        },
    )

    breakdown = json.loads(result["score_breakdown"])
    assert result["score"] < 6
    assert breakdown["referral_schedule_exception"] is False


def test_composite_score_keeps_hard_gap_cap_for_sutter_referral_exception() -> None:
    result = composite_score(
        job_description="COMPANY: Sutter Health\nDESCRIPTION:\nRequired: RN license and patient care.",
        resume_text="Referral/priority employer schedule exception: Sutter Health.",
        llm_result={
            "score": 1,
            "risk_flags": "required license gap",
            "missing_skills": "required RN license",
            "apply_or_skip_reason": "Skip; not eligible without RN license.",
            "reasoning": "Referral does not substitute for the required RN license.",
        },
    )

    breakdown = json.loads(result["score_breakdown"])
    assert result["score"] == 1
    assert breakdown["hard_mismatch_cap"] is True
    assert breakdown["referral_schedule_exception"] is False


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
    assert "active search filters state schedule limits" in prompt
    assert "unless active search filters or verified profile facts make it relevant" in prompt
    assert "do not require the same prior job title or exact industry/tool" in prompt
    assert "avoid scoring below 6 solely because the candidate lacks exact same-title experience" in prompt
    assert "Do not penalize legitimate remote" in prompt
    assert "Preferred/nice-to-have certifications" in prompt
    assert "required/minimum/must have" in prompt
    assert "equivalent experience is accepted" in prompt
    assert "Coursework and in-progress education can support skills" in prompt
    assert "referral or priority-employer exceptions" in prompt


def test_profile_evidence_context_includes_verified_facts_without_secrets() -> None:
    profile = {
        "personal": {
            "city": "Logan",
            "province_state": "UT",
            "password": "do-not-include",
        },
        "experience": {
            "target_role": "IT Support Analyst",
            "target_roles": {"tier1": "help desk"},
            "years_of_experience_total": "99",
            "years_of_experience_it": "3",
            "education_level": "Bachelor's Degree (in progress)",
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
    assert "IT Support Analyst" not in context
    assert "help desk" not in context
    assert "Years Of Experience Total" not in context
    assert "Oracle Cloud Infrastructure" in context
    assert "Use each job title and task summary" in context
    assert "Do not invent credentials" in context
    assert "Bridgerland Technical College" in context
    assert "do-not-include" not in context
    assert "Password should not appear" not in context


def test_profile_evidence_context_marks_in_progress_education_without_completion() -> None:
    profile = {
        "education_schools": [
            {
                "school": "Example College",
                "degree": "AAS",
                "major": "Information Technology",
                "end_year": "Present",
                "notes": "Networking and help desk coursework.",
            }
        ]
    }

    context = _build_profile_evidence_context(profile)

    assert "Example College | AAS | Information Technology | in progress" in context
    assert "Example College | AAS | Information Technology | completed" not in context


def test_score_job_prompt_includes_coursework_as_internal_only(monkeypatch) -> None:
    captured: dict = {}

    class FakeClient:
        def chat(self, messages, **kwargs):
            captured["messages"] = messages
            return "\n".join([
                "FIT_SCORE: 6",
                "MATCHED_SKILLS: Python",
                "MISSING_SKILLS: none",
                "KEYWORD_HITS: support",
                "RISK_FLAGS: none",
                "APPLY_OR_SKIP_REASON: Apply.",
                "SCORE_REASONING: Coursework supports the support workflow.",
            ])

    monkeypatch.setattr(scorer, "get_client_for_stage", lambda stage: FakeClient())

    scorer.score_job(
        resume_text="Helped users and wrote Python reports.",
        job={
            "title": "IT Support Technician",
            "company": "Example Health",
            "site": "Example ATS",
            "location": "Remote",
            "full_description": "Support users and troubleshoot access issues.",
        },
        coursework_summary="Example College: Help desk fundamentals.",
        coursework_skills_summary="Example College: Active Directory exposure.",
        profile_context="Education: Example College | AAS | Information Technology | in progress",
    )

    user_prompt = captured["messages"][1]["content"]
    assert "ACADEMIC COURSEWORK (internal only, do not cite unless already in resume)" in user_prompt
    assert "COURSEWORK SKILL MAP (internal only, do not cite unless already in resume)" in user_prompt
    assert "Active Directory exposure" in user_prompt
    assert "do not treat in-progress credentials as completed" in user_prompt


def test_search_evidence_context_includes_schedule_filters() -> None:
    context = _build_search_evidence_context(
        {
            "require_part_time": True,
            "customer_service_max_hours_per_week": 20,
            "queries": [{"query": "front desk part time", "tier": 1}],
            "locations": [{"location": "Logan, UT", "remote": False}],
        }
    )

    assert "Search schedule filter: part-time roles required" in context
    assert "Search max hours per week: 20" in context
    assert "front desk part time" in context
    assert "Logan, UT" in context


def test_search_evidence_context_includes_referral_priority_schedule_exceptions() -> None:
    context = _build_search_evidence_context(
        {
            "require_part_time": True,
            "referral_employers": ["Sutter Health"],
            "priority_employers": [{"name": "Cache Employer"}],
        }
    )

    assert "Search schedule filter: part-time roles required" in context
    assert "Referral/priority employer schedule exception: Sutter Health; Cache Employer" in context
