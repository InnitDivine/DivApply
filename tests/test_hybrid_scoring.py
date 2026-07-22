from __future__ import annotations

import json

import pytest

from divapply.scoring.composite import composite_score
from divapply.scoring.context import format_job_context
from divapply.scoring.embedding import embedding_score
from divapply.scoring.keywords import (
    KeywordScoringPolicy,
    extract_requirement_keywords,
    keyword_present,
    score_keywords,
)
from divapply.scoring import scorer
from divapply.scoring.scorer import _build_profile_evidence_context, _build_search_evidence_context
from divapply.search_policy import (
    job_has_schedule_exception,
    market_policy_for_job,
    resolved_application_mode,
)


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


def test_v123_keyword_present_requires_token_boundary_for_short_skills() -> None:
    assert keyword_present("ios", "Apple iOS device support")
    assert not keyword_present("ios", "Municipal operations and registrations")


def test_keyword_present_accepts_explicit_resume_evidence_equivalents() -> None:
    resume = (
        "Workstation setup, PC building, user assistance, troubleshooting, discrepancy research, "
        "project planning and coordination, time management and prioritization."
    )

    assert keyword_present("device setup", resume.casefold())
    assert keyword_present("end-user support", resume.casefold())
    assert keyword_present("problem-solving", resume.casefold())
    assert keyword_present("functional understanding of project management concepts", resume.casefold())
    assert keyword_present("time management", resume.casefold())
    assert not keyword_present("asset inventory", resume.casefold())


def test_keyword_score_weights_preferred_certifications_lightly() -> None:
    jd = "\n".join(
        [
            "Required skills: Python, SQL.",
            "Preferred certifications: AWS Certified Cloud Practitioner.",
        ]
    )
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
    jd = "\n".join(
        [
            "Preferred Qualifications:",
            "- AWS Certified Cloud Practitioner.",
            "Required Qualifications:",
            "- Python.",
            "- SQL.",
        ]
    )
    resume = "Built Python and SQL reports."

    result = score_keywords(jd, resume)

    assert any("aws" in keyword for keyword in result["preferred_keywords"])
    assert not any("aws" in keyword for keyword in result["required_keywords"])


def test_keyword_extraction_captures_admin_service_bullets_without_marker_repetition() -> None:
    jd = "\n".join(
        [
            "Required Qualifications:",
            "- Cash handling",
            "- Phone etiquette",
            "- Patient registration",
            "- Microsoft Office",
            "Preferred Qualifications:",
            "- Medical terminology",
        ]
    )

    keywords = extract_requirement_keywords(jd)
    preferred = score_keywords(jd, "cash handling phone etiquette patient registration microsoft office")

    assert "cash handling" in keywords
    assert "phone etiquette" in keywords
    assert "patient registration" in keywords
    assert "microsoft office" in keywords
    assert "medical terminology" in preferred["preferred_misses"]
    assert preferred["score"] >= 0.75


def test_v121_sutter_style_headings_produce_skill_keywords_without_degree_gap() -> None:
    jd = "\n".join(
        [
            "EDUCATION:",
            "Equivalent experience will be accepted in lieu of the required degree or diploma.",
            "Associate's in Computer Science, Information Technology, or related field",
            "SKILLS AND KNOWLEDGE:",
            "Basic knowledge in Microsoft Windows and Apple OS/iOS operating systems.",
            "Basic knowledge of active directory and associated file systems.",
            "Basic knowledge of network topologies and troubleshooting.",
            "Basic knowledge of ITIL Foundations concepts.",
            "Adept in time management within provided guidelines.",
            "Job Shift:",
            "Days",
            "Schedule:",
            "Full Time",
        ]
    )

    keywords = extract_requirement_keywords(jd)

    assert "windows" in keywords
    assert "active directory" in keywords
    assert "troubleshooting" in keywords
    assert "time management" in keywords
    assert "management" not in keywords
    assert all("degree" not in keyword for keyword in keywords)
    assert all("associate" not in keyword for keyword in keywords)
    assert "shift" not in keywords
    assert "days" not in keywords


def test_v121_government_application_metadata_never_becomes_skill_gap() -> None:
    jd = "\n".join(
        [
            "MINIMUM QUALIFICATIONS:",
            "English usage, spelling, grammar, and punctuation.",
            "An applicant with a college degree obtained outside the United States must have education records evaluated by a credential's evaluation service.",
            "DESIRABLE KNOWLEDGE:",
            "Microsoft Office",
            "NOTE:",
            "Part-time experience is converted to full-time equivalency.",
            "1. APPLICATION:",
            "Applications must be submitted by 5:00 p.m. on the final filing deadline.",
            "See Civil Service Board rule4.9C. (Download PDF reader)",
        ]
    )

    context = format_job_context({"title": "Administrative Assistant", "full_description": jd})
    result = score_keywords(context, "English grammar punctuation and Microsoft Office")
    all_keywords = [*result["required_keywords"], *result["preferred_keywords"]]

    assert "Microsoft Office".casefold() in result["preferred_keywords"]
    assert not any(
        noise in keyword
        for keyword in all_keywords
        for noise in ("note", "a.m", "p.m", "rule4.9c", "pdf reader", "credential", "filing deadline")
    )
    assert "download pdf reader" not in context.casefold()


def test_v121_government_structural_and_physical_sections_never_become_keywords() -> None:
    jd = "\n".join(
        [
            "QUALIFICATIONS",
            "Knowledge of:",
            "English usage, spelling, grammar, and punctuation.",
            "Skill in:",
            "Use of computers and Microsoft Word.",
            "Ability to:",
            "Maintain records and communicate effectively.",
            "EXPERIENCE AND EDUCATION",
            "Experience:",
            "Four years of progressively responsible clerical experience including a minimum of two years performing complex duties.",
            "Substitution:",
            "Relevant coursework may substitute for experience.",
            "SPECIAL QUALIFICATIONS",
            "Special Selection Criteria:",
            "Dictation at a speed of up to 100 net words per minute.",
            "WORKING CONDITIONS",
            "Positions in this class may be required to lift materials weighing up to 50 pounds.",
            "PROBATIONARY PERIOD",
            "Employees must complete twelve months of probation.",
            "APPLICATION AND TESTING INFORMATION",
            "Submit the online application by the filing deadline.",
        ]
    )

    keywords = extract_requirement_keywords(jd)

    assert "microsoft" in keywords
    assert "word" in keywords
    assert "records" in keywords
    assert "clerical" in keywords
    noise = (
        "knowledge of",
        "skill in",
        "ability to",
        "use of",
        "experience",
        "substitution",
        "four progressively responsible",
        "special",
        "selection criteria",
        "working conditions",
        "probationary period",
        "lift materials",
        "application testing information",
    )
    assert not any(fragment in keyword for keyword in keywords for fragment in noise)


def test_v121_context_cuts_government_application_testing_information() -> None:
    jd = "\n".join(
        [
            "Minimum Qualifications:",
            "Six months of customer relations and data entry experience.",
            "Application and Testing Information",
            "Submit the online application by 5:00 p.m.",
        ]
    )

    context = format_job_context({"title": "Election Clerk", "full_description": jd})

    assert "customer relations" in context
    assert "Application and Testing Information" not in context
    assert "5:00 p.m." not in context


def test_v121_bounded_context_never_emits_partial_description_lines() -> None:
    original_lines = [
        "Opening overview with complete duties and responsibilities.",
        *[
            f"General detail line {index} with enough content to consume the context budget."
            for index in range(20)
        ],
        "MINIMUM QUALIFICATIONS",
        "Knowledge of Microsoft Word and records management.",
        "Ability to communicate clearly with employees and the public.",
        *[
            f"Closing caveat line {index} with complete scheduling context."
            for index in range(20)
        ],
    ]
    jd = "\n".join(original_lines)

    context = format_job_context(
        {"title": "Administrative Assistant", "full_description": jd},
        description_limit=520,
    )
    description = context.split("DESCRIPTION:\n", 1)[1]

    for line in description.splitlines():
        if line and line != "...[middle omitted]...":
            assert line in original_lines


def test_v124_evidence_gap_merge_deduplicates_parenthesized_items() -> None:
    gap = "explicit inbox experience (beyond public counter support)"

    merged = scorer._merge_evidence_gaps(gap, gap)

    assert merged == gap


def test_v124_matched_specific_skill_cannot_remain_a_missing_gap() -> None:
    gaps = (
        "Apple OS/iOS support, project management concepts (only inferred, not explicit), "
        "ITIL Foundations concepts"
    )

    filtered = scorer._remove_hit_covered_gaps(gaps, "windows, project management")

    assert "project management" not in filtered.casefold()
    assert "Apple OS/iOS support" in filtered
    assert "ITIL Foundations concepts" in filtered


def test_keyword_extraction_ignores_company_copy_and_application_boilerplate() -> None:
    jd = "\n".join(
        [
            "About Attain",
            "We bring our best thinking and unique skills to advance every client.",
            "Job Responsibilities",
            "- Troubleshoot Microsoft 365 and Windows devices",
            "- Maintain asset inventory and technical documentation",
            "Qualifications",
            "- Associate degree in IT or equivalent experience",
            "Additional Information",
            "Hourly rate: $15-$20 plus benefits",
            "We are an equal opportunity and affirmative action employer.",
            "Apply for this job",
            "First Name",
            "Voluntary Self-Identification of Disability",
            "Cancer",
        ]
    )

    keywords = extract_requirement_keywords(jd)

    assert any("microsoft" in keyword for keyword in keywords)
    assert any("troubleshooting" in keyword or "troubleshoot" in keyword for keyword in keywords)
    assert not any("attain" in keyword for keyword in keywords)
    assert not any("best" in keyword for keyword in keywords)
    assert not any("hourly" in keyword for keyword in keywords)
    assert not any("disability" in keyword or "cancer" in keyword for keyword in keywords)
    assert "qualifications" not in keywords
    assert "qualifications & education" not in keywords
    assert "e.g" not in keywords


def test_keyword_extraction_ignores_state_application_and_salary_metadata() -> None:
    jd = "\n".join(
        [
            "Position Details",
            "Job Code",
            "Information Technology Specialist II",
            "Salary Information",
            "New to State candidates will be hired at the minimum salary of the classification or minimum of alternate range when applicable.",
            "# of Positions",
            "1",
            "Minimum Qualifications",
            "Two years of information technology experience.",
            "Special Requirements",
            "Must pass a background investigation.",
            "Must have experience troubleshooting Windows workstations.",
            "Please Note:",
            "A Statement of Qualifications must be submitted with the application.",
            "Do not include confidential information in application documents.",
            "You are required to complete employment history on the application form (STD 678).",
            "Incomplete resumes will not take the place of employment history in the selection process.",
            "Application Instructions",
            "Who May Apply",
            "Only qualified applicants may apply.",
            "Required Application Package Documents",
            "Complete the STD 678 State Application.",
            "A resume is optional.",
            "Include unofficial transcripts when using education to meet minimum qualifications.",
        ]
    )

    keywords = extract_requirement_keywords(jd)

    assert any("background investigation" in keyword for keyword in keywords)
    assert any("troubleshooting windows workstations" in keyword for keyword in keywords)
    assert "1" not in keywords
    noise_terms = (
        "alternate range",
        "application",
        "classification",
        "confidential information",
        "employment history",
        "incomplete resumes",
        "positions",
        "please note",
        "resume",
        "salary",
        "selection process",
        "std 678",
        "transcript",
        "who may apply",
    )
    assert not any(noise in keyword for keyword in keywords for noise in noise_terms)


def test_keyword_extraction_ignores_truncation_pay_and_location_fragments() -> None:
    jd = """Minimum Qualifications
- Bachelor's degree and two years of technical consulting experience required.
...[middle omitted]...
Pay $28.40 - $34.20 per hour
Location: Remote, U.S.
Benefits include medical and retirement.
"""

    keywords = extract_requirement_keywords(jd)

    assert not any("middle omitted" in keyword for keyword in keywords)
    assert not any("pay $" in keyword or "per hour" in keyword for keyword in keywords)
    assert not any(keyword in {"location remote", "u.s", "u.s."} for keyword in keywords)
    assert not any("benefits include" in keyword for keyword in keywords)


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


def test_format_job_context_preserves_tail_work_arrangement_caveat() -> None:
    text = format_job_context(
        {
            "title": "Support Analyst",
            "company": "Example",
            "site": "Indeed",
            "location": "Remote",
            "full_description": "Opening duties. "
            + ("general detail " * 100)
            + "First month requires onsite training in Los Angeles.",
        },
        description_limit=240,
    )

    assert "Opening duties" in text
    assert "middle omitted" in text
    assert "requires onsite training in Los Angeles" in text


def test_format_job_context_strips_application_self_id_boilerplate() -> None:
    text = format_job_context(
        {
            "title": "IT Support Specialist",
            "company": "Example Employer",
            "full_description": """Job Responsibilities
- Troubleshoot Windows devices
Qualifications
- Associate degree or equivalent experience
Equal Opportunity/Affirmative Action employer.
Apply for this job
Voluntary Self-Identification of Disability
Cancer
Veteran Status
""",
        },
        description_limit=3000,
    )

    assert "Troubleshoot Windows devices" in text
    assert "equivalent experience" in text
    assert "Self-Identification" not in text
    assert "Cancer" not in text
    assert "Veteran Status" not in text


def test_format_job_context_preserves_middle_minimum_qualifications() -> None:
    description = (
        "Role overview and technical consulting duties.\n"
        + ("opening detail " * 80)
        + "\nMinimum Qualifications\n"
        + "Bachelor's degree completed and two years of technical consulting experience required.\n"
        + ("later detail " * 80)
        + "\nApplications close Friday."
    )

    text = format_job_context(
        {"title": "Systems Analyst", "company": "Example", "full_description": description},
        description_limit=420,
    )

    assert "Role overview" in text
    assert "Minimum Qualifications" in text
    assert "two years of technical consulting experience required" in text
    assert "Applications close Friday" in text


def test_v113_job_context_preserves_experience_and_training_requirement_bodies() -> None:
    description = (
        "Role overview and database duties.\n"
        + ("opening detail " * 80)
        + "\nFor a complete list of minimum qualifications, please click HERE.\n"
        + "Experience and Training\n"
        + "Experience:\nNo professional experience is required.\nAND\n"
        + "Training:\nA Bachelor’s degree from an accredited college or university, preferably with "
        + "major course work in computer science, information systems, GIS or a related field.\n"
        + "License or Certificate:\nPossession of a valid California driver’s license by date of appointment.\n"
        + ("later detail " * 80)
        + "\nApplications close Sunday."
    )

    text = format_job_context(
        {"title": "Database Analyst I", "company": "Example City", "full_description": description},
        description_limit=1100,
    )

    assert "No professional experience is required." in text
    assert "A Bachelor’s degree" in text
    assert "valid California driver’s license" in text


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


def test_composite_renormalizes_when_keyword_modality_has_no_evidence(monkeypatch) -> None:
    monkeypatch.setattr(
        "divapply.scoring.composite.score_keywords",
        lambda *args, **kwargs: {
            "score": 0.0,
            "keywords": [],
            "hits": [],
            "misses": [],
            "required_keywords": [],
            "preferred_keywords": [],
            "preferred_hits": [],
            "preferred_misses": [],
        },
    )
    monkeypatch.setattr("divapply.scoring.composite.embedding_score", lambda *args, **kwargs: 0.5)

    result = composite_score(
        job_description="Plain-language role description without requirement headings.",
        resume_text="Relevant transferable experience.",
        llm_result={"score": 6, "target_priority": "1", "reasoning": "Moderate fit."},
    )

    breakdown = json.loads(result["score_breakdown"])
    assert breakdown["keyword_modality_available"] is False
    assert breakdown["weights"]["keyword"] == 0.0
    assert sum(breakdown["weights"].values()) == pytest.approx(1.0)
    assert result["composite_score"] == pytest.approx(5.57)


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


def test_composite_score_accepts_degree_or_equivalent_experience() -> None:
    result = composite_score(
        job_description=(
            "Part-time IT support. Associate degree in IT or equivalent experience. "
            "Troubleshoot Microsoft 365, Windows, accounts, and devices."
        ),
        resume_text=(
            "IT certificate in progress. Microsoft 365, Windows, account administration, "
            "device troubleshooting, documentation, and public-sector experience."
        ),
        llm_result={
            "score": 7,
            "target_priority": "1",
            "risk_flags": "No completed IT associate degree; equivalent experience is accepted.",
            "missing_skills": "Completed IT associate degree, but experience may substitute.",
            "apply_or_skip_reason": "Apply - the posting accepts equivalent experience.",
            "reasoning": "Strong entry-level IT fit despite the degree alternative.",
        },
        weights={"keyword": 0.45, "embedding": 0.45, "llm": 0.1},
    )

    breakdown = json.loads(result["score_breakdown"])
    assert result["score"] >= 7
    assert breakdown["hard_mismatch_cap"] is False
    assert breakdown["positive_apply_floor"] is True


def test_score_prompt_does_not_invent_paid_experience_requirement() -> None:
    assert "Do not invent a paid, professional, same-title" in scorer.SCORE_PROMPT
    assert 'Never turn "equivalent experience accepted" into "paid IT experience required"' in scorer.SCORE_PROMPT


def test_substitutable_degree_narrative_keeps_real_gaps_without_calling_degree_mandatory() -> None:
    reasoning, risks = scorer._sanitize_substitution_narrative(
        "Strong support fit, but the candidate lacks a completed IT associate degree and asset ownership.",
        "Remote role; IT degree is in progress; onboarding ownership not clear",
        "Associate degree in IT or related field; equivalent experience accepted.",
        "asset inventory",
    )

    assert "explicitly accepts equivalent experience" in reasoning
    assert "Remaining evidence gap: asset inventory" in reasoning
    assert "lacks a completed IT associate" not in reasoning
    assert "fit. The posting" in reasoning
    assert "degree" not in risks.casefold()
    assert "Remote role" in risks
    assert "onboarding ownership" in risks


def test_v120_score_job_removes_accepted_degree_gap_from_every_persisted_field(monkeypatch) -> None:
    class FakeClient:
        def chat(self, *_args, **_kwargs) -> str:
            return "\n".join(
                [
                    "FIT_SCORE: 7",
                    "TARGET_PRIORITY: 1",
                    "MATCHED_SKILLS: Windows, Active Directory, network troubleshooting",
                    "MISSING_SKILLS: Apple macOS/iOS, ITIL Foundations, degree/diploma in CS/IT or related, professional IT employment experience",
                    "KEYWORD_HITS: Windows, Active Directory, troubleshooting",
                    "RISK_FLAGS: Apple support not evidenced; professional IT employment experience absent; IT degree requirement not clearly satisfied (equivalent experience accepted but resume shows 0 paid IT experience)",
                    "APPLY_OR_SKIP_REASON: Apply - municipal ticket support aligns with the role.",
                    "SCORE_REASONING: Strong support fit. The score is capped by Apple and ITIL, and no completed IT-related degree/certification.",
                ]
            )

    monkeypatch.setattr(scorer, "get_client_for_stage", lambda _stage: FakeClient())
    result = scorer.score_job(
        resume_text=(
            "Associate of General Studies completed. Windows troubleshooting, Active Directory fundamentals, "
            "networking coursework, PC building, and three years of IT projects."
        ),
        job={
            "title": "Device Support Technician I",
            "company": "Example Health System",
            "full_description": "\n".join(
                [
                    "EDUCATION:",
                    "Equivalent experience will be accepted in lieu of the required degree or diploma.",
                    "Associate's in Computer Science, Information Technology, or related field",
                    "SKILLS AND KNOWLEDGE:",
                    "Microsoft Windows and Apple OS/iOS operating systems.",
                    "Active directory and associated file systems.",
                    "Network topologies and basic troubleshooting.",
                    "ITIL Foundations concepts.",
                ]
            ),
        },
    )

    assert "degree" not in result["missing_skills"].casefold()
    assert "associate" not in result["risk_flags"].casefold()
    assert "professional it" not in result["missing_skills"].casefold()
    assert "professional it" not in result["risk_flags"].casefold()
    assert "degree" not in result["reasoning"].casefold()
    assert "apple" in result["missing_skills"].casefold()
    assert "itil" in result["missing_skills"].casefold()
    assert result["reasoning"].casefold().count("explicitly accepts equivalent experience") == 1
    assert result["apply_or_skip_reason"].startswith("Apply -")
    assert "ticket" not in result["apply_or_skip_reason"].casefold()
    breakdown = json.loads(result["score_breakdown"])
    assert "degree" not in breakdown["llm"]["reasoning"].casefold()
    assert result["matched_skills"]


def test_v120_keeps_explicit_professional_it_experience_requirement() -> None:
    job_text = (
        "Associate degree in IT or equivalent experience. "
        "At least two years of professional IT experience required."
    )

    filtered = scorer._sanitize_substitution_gaps(
        "IT degree, professional IT experience, Apple support",
        job_text,
    )

    assert "degree" not in filtered.casefold()
    assert "professional IT experience" in filtered
    assert "Apple support" in filtered


def test_persisted_score_reasoning_is_built_only_from_bounded_evidence() -> None:
    reasoning = scorer._build_evidence_reasoning(
        {
            "score": 7,
            "keyword_hits": "support, troubleshooting, windows, device setup, microsoft 365",
            "missing_skills": "asset inventory",
        },
        "Associate degree in IT or related field; equivalent experience accepted.",
    )

    assert reasoning.startswith("Fit 7/10 based on verified candidate-to-posting evidence")
    assert "troubleshooting, windows, device setup, microsoft 365" in reasoning
    assert "support," not in reasoning
    assert "explicitly accepts equivalent experience" in reasoning
    assert "Remaining evidence gap: asset inventory" in reasoning


def test_composite_uses_posting_substitution_when_llm_reason_omits_it() -> None:
    result = composite_score(
        job_description=(
            "Associate degree in Information Technology or related field; "
            "equivalent experience accepted. Troubleshoot Windows and Microsoft 365."
        ),
        resume_text="Windows and Microsoft 365 troubleshooting plus three years of IT projects.",
        llm_result={
            "score": 7,
            "target_priority": "1",
            "risk_flags": "No completed IT associate degree.",
            "missing_skills": "Completed IT associate degree.",
            "apply_or_skip_reason": "Apply - strong entry-level support fit.",
            "reasoning": "The candidate lacks an IT degree but meets most support duties.",
        },
        weights={"keyword": 0.45, "embedding": 0.45, "llm": 0.1},
    )

    breakdown = json.loads(result["score_breakdown"])
    assert result["score"] >= 7
    assert breakdown["positive_apply_floor"] is True


def test_composite_score_preserves_positive_llm_apply_signal() -> None:
    result = composite_score(
        job_description="Part-time cashier. Customer service and accurate payments required.",
        resume_text="Municipal public counter service, payment processing, records, scheduling.",
        llm_result={
            "score": 8,
            "target_priority": "1",
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
            "target_priority": "1",
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


def test_composite_score_lifts_configured_schedule_only_referral_exception() -> None:
    result = composite_score(
        job_description=(
            "TITLE: Patient Access Representative\n"
            "COMPANY: Example Health\n"
            "SEARCH CONTEXT: Referral/priority employer schedule exception: Example Health\n"
            "DESCRIPTION:\nFull-time role. Required: customer service, patient registration, scheduling."
        ),
        resume_text=(
            "Customer service, scheduling, records, payments.\n"
            "Configured search policy marks Example Health as a schedule exception."
        ),
        llm_result={
            "score": 4,
            "risk_flags": "full-time schedule mismatch",
            "missing_skills": "none",
            "apply_or_skip_reason": "Apply because this is a configured referral exception.",
            "reasoning": "Only concern is full-time schedule against a part-time search filter.",
        },
        require_part_time=True,
        schedule_exception=True,
    )

    breakdown = json.loads(result["score_breakdown"])
    assert result["score"] >= 6
    assert breakdown["referral_schedule_exception"] is True


def test_composite_score_does_not_apply_configured_exception_to_other_employers() -> None:
    result = composite_score(
        job_description=(
            "TITLE: Front Desk Representative\n"
            "COMPANY: Local Retail Employer\n"
            "DESCRIPTION:\nFull-time role. Required: customer service, scheduling, and records."
        ),
        resume_text=(
            "Customer service, scheduling, records, payments.\n"
            "Referral/priority employer schedule exception: Example Health may be scored without the part-time-only penalty."
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


def test_composite_score_keeps_hard_gap_cap_for_configured_referral_exception() -> None:
    result = composite_score(
        job_description=(
            "COMPANY: Example Health\n"
            "SEARCH CONTEXT: Referral/priority employer schedule exception: Example Health\n"
            "DESCRIPTION:\nRequired: RN license and patient care."
        ),
        resume_text="Configured referral context does not replace qualifications.",
        llm_result={
            "score": 1,
            "risk_flags": "required license gap",
            "missing_skills": "required RN license",
            "apply_or_skip_reason": "Skip; not eligible without RN license.",
            "reasoning": "Referral does not substitute for the required RN license.",
        },
        require_part_time=True,
        schedule_exception=True,
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
            return "\n".join(
                [
                    "FIT_SCORE: 7",
                    "MATCHED_SKILLS: Python",
                    "MISSING_SKILLS: none",
                    "KEYWORD_HITS: Python",
                    "RISK_FLAGS: none",
                    "APPLY_OR_SKIP_REASON: Apply.",
                    "SCORE_REASONING: Meets core criteria.",
                ]
            )

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


def test_score_job_overrides_apply_wording_for_discovery_only(monkeypatch) -> None:
    class FakeClient:
        def chat(self, messages, **kwargs):
            return "\n".join(
                [
                    "FIT_SCORE: 8",
                    "TARGET_PRIORITY: 1",
                    "MATCHED_SKILLS: application support",
                    "MISSING_SKILLS: none",
                    "KEYWORD_HITS: support",
                    "RISK_FLAGS: none",
                    "APPLY_OR_SKIP_REASON: Apply now.",
                    "SCORE_REASONING: Strong fit.",
                ]
            )

    monkeypatch.setattr(scorer, "get_client_for_stage", lambda stage: FakeClient())

    result = scorer.score_job(
        resume_text="Application support projects.",
        job={
            "title": "Systems Analyst",
            "company": "Example",
            "location": "Sample City, ZZ",
            "full_description": "Full-time application support. Benefits include medical and retirement.",
        },
        application_mode="discovery_only",
        preferred_schedule="full_time",
        require_benefits=True,
    )

    assert result["score"] >= 7
    assert result["apply_or_skip_reason"].startswith("Discovery only")
    assert "Apply now" not in result["apply_or_skip_reason"]


def test_v124_score_job_overrides_apply_wording_for_manual_review(monkeypatch) -> None:
    class FakeClient:
        def chat(self, *_args, **_kwargs) -> str:
            return "\n".join(
                [
                    "FIT_SCORE: 7",
                    "TARGET_PRIORITY: 1",
                    "MATCHED_SKILLS: support",
                    "MISSING_SKILLS: none",
                    "KEYWORD_HITS: support",
                    "RISK_FLAGS: none",
                    "APPLY_OR_SKIP_REASON: Apply now using invented ticket experience.",
                    "SCORE_REASONING: Strong fit.",
                ]
            )

    monkeypatch.setattr(scorer, "get_client_for_stage", lambda _stage: FakeClient())
    result = scorer.score_job(
        resume_text="Verified user support.",
        job={"title": "Support Assistant", "full_description": "Required: user support."},
        application_mode="manual_review",
    )

    assert result["apply_or_skip_reason"].startswith("Manual review")
    assert "invented ticket" not in result["apply_or_skip_reason"]


def test_score_job_does_not_store_unverified_or_implied_llm_matches(monkeypatch) -> None:
    class FakeClient:
        def chat(self, messages, **kwargs):
            return "\n".join(
                [
                    "FIT_SCORE: 7",
                    "TARGET_PRIORITY: 1",
                    "MATCHED_SKILLS: VoIP not verified, ticketing implied",
                    "MISSING_SKILLS: VoIP, ticketing",
                    "KEYWORD_HITS: support",
                    "RISK_FLAGS: none",
                    "APPLY_OR_SKIP_REASON: Apply.",
                    "SCORE_REASONING: Transferable support fit.",
                ]
            )

    monkeypatch.setattr(scorer, "get_client_for_stage", lambda stage: FakeClient())

    result = scorer.score_job(
        resume_text="User support and device troubleshooting projects.",
        job={
            "title": "Support Technician",
            "company": "Example",
            "full_description": "Required: user support and device troubleshooting.",
        },
    )

    assert "not verified" not in result["matched_skills"].casefold()
    assert "implied" not in result["matched_skills"].casefold()
    assert "support" in result["matched_skills"].casefold()


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
    assert "explicit schedule exception for the current employer" in prompt


def test_profile_evidence_context_includes_verified_facts_without_secrets() -> None:
    profile = {
        "personal": {
            "city": "Exampletown",
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
            "Example University IT certification training is in progress.",
            "Password should not appear.",
        ],
        "resume_facts": {
            "preserved_projects": ["Oracle Cloud home lab"],
            "real_metrics": ["3.692 GPA"],
        },
    }

    context = _build_profile_evidence_context(profile)

    assert "Location: Exampletown, UT" in context
    assert "IT Support Analyst" not in context
    assert "help desk" not in context
    assert "Years Of Experience Total" not in context
    assert "Oracle Cloud Infrastructure" in context
    assert "Use each job title and task summary" in context
    assert "Do not invent credentials" in context
    assert "Example University" in context
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


def test_profile_evidence_context_states_highest_completed_degree_separately_from_active_programs() -> None:
    context = _build_profile_evidence_context(
        {
            "education_schools": [
                {
                    "school": "Example Community College",
                    "degree": "Associate of General Studies",
                    "major": "General Studies",
                    "degree_received": True,
                    "end_year": "2024",
                },
                {
                    "school": "Example University",
                    "degree": "Bachelor of Science",
                    "major": "Public Health",
                    "degree_received": False,
                    "end_year": "present",
                },
            ]
        }
    )

    assert "Highest completed degree: Associate of General Studies" in context
    assert "Highest completed degree: Bachelor of Science" not in context


def test_profile_evidence_context_separates_professional_and_project_it_time() -> None:
    context = _build_profile_evidence_context(
        {
            "experience": {
                "years_of_professional_it_experience": "0",
                "years_of_professional_healthcare_experience": "0",
                "years_of_it_project_experience": "3",
            }
        }
    )

    assert "Professional IT Experience: 0" in context
    assert "Professional Healthcare Experience: 0" in context
    assert "Hands-On IT Lab/Project Experience: 3" in context
    assert "Years Of Experience It" not in context


def test_profile_evidence_context_marks_legacy_it_years_as_boundary_unspecified() -> None:
    context = _build_profile_evidence_context({"experience": {"years_of_experience_it": "3"}})

    assert "IT Experience (Paid/Project Boundary Unspecified): 3" in context
    assert "Professional IT Experience: 3" not in context


def test_profile_evidence_context_does_not_call_in_progress_training_completed_certification() -> None:
    context = _build_profile_evidence_context(
        {
            "certifications": [
                {
                    "name": "Information Technology Certificate Program",
                    "issuer": "Example College",
                    "status": "In progress",
                }
            ]
        }
    )

    assert "Training (in progress): Information Technology Certificate Program | Example College" in context
    assert "Certification (completed)" not in context


def test_score_job_prompt_includes_coursework_as_internal_only(monkeypatch) -> None:
    captured: dict = {}

    class FakeClient:
        def chat(self, messages, **kwargs):
            captured["messages"] = messages
            return "\n".join(
                [
                    "FIT_SCORE: 6",
                    "MATCHED_SKILLS: Python",
                    "MISSING_SKILLS: none",
                    "KEYWORD_HITS: support",
                    "RISK_FLAGS: none",
                    "APPLY_OR_SKIP_REASON: Apply.",
                    "SCORE_REASONING: Coursework supports the support workflow.",
                ]
            )

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
            "locations": [{"location": "Exampletown, UT", "remote": False}],
        }
    )

    assert "Search schedule filter: part-time roles required" in context
    assert "Search max hours per week: 20" in context
    assert "front desk part time" in context
    assert "Exampletown, UT" in context


def test_search_evidence_context_includes_only_exact_current_job_schedule_exception() -> None:
    context = _build_search_evidence_context(
        {
            "require_part_time": True,
            "referral_employers": ["Sutter Health"],
            "priority_employers": [{"name": "Cache Employer"}],
        },
        job={"company": "Sutter Health"},
    )

    assert "Search schedule filter: part-time roles required" in context
    assert "Explicit schedule exception: current employer matched configured schedule/referral policy." in context
    assert "Cache Employer" not in context


def test_schedule_exception_requires_exact_employer_and_ignores_priority() -> None:
    config = {
        "referral_employers": ["Example Health"],
        "schedule_exception_employers": [{"name": "Exact Systems"}],
        "priority_employers": [{"name": "Priority Only"}],
    }

    assert job_has_schedule_exception(config, {"company": "Example Health"})
    assert job_has_schedule_exception(config, {"company": "exact systems"})
    assert not job_has_schedule_exception(config, {"company": "Example Health Partners"})
    assert not job_has_schedule_exception(config, {"company": "Priority Only"})
    assert not job_has_schedule_exception(config, {"company": "Unrelated"})


def test_search_evidence_context_includes_priority_policy_and_every_query() -> None:
    queries = [{"query": f"target role {index}", "tier": 1 if index < 10 else 2} for index in range(25)]

    context = _build_search_evidence_context(
        {
            "target_families": [
                {"name": "IT support", "priority": 1},
                {"name": "health information", "priority": 2},
            ],
            "queries": queries,
        }
    )

    assert (
        "Search target policy (not applicant evidence): priority 1: IT support; priority 2: health information"
        in context
    )
    assert "Tier 1 search queries:" in context
    assert "Tier 2 search queries:" in context
    assert "target role 0" in context
    assert "target role 24" in context


def test_search_evidence_context_marks_full_time_preference_and_priority_semantics() -> None:
    context = _build_search_evidence_context(
        {
            "preferred_schedule": "full_time",
            "target_families": [
                {"name": "IT support", "priority": 1},
                {"name": "health information", "priority": 2},
                {"name": "administration fallback", "priority": 3},
            ],
        }
    )

    assert "Priority semantics: 1=primary, 2=bridge, 3=fallback" in context
    assert "Search schedule preference: full-time professional roles" in context


def test_search_context_uses_job_market_policy_instead_of_global_schedule() -> None:
    search_config = {
        "preferred_schedule": "any",
        "require_part_time": False,
        "default_market_label": "Current market",
        "locations": [
            {"label": "Current market", "location": "Exampletown, YY"},
            {"label": "Future market", "location": "Sample City, ZZ"},
        ],
        "market_policies": {
            "Current market": {
                "preferred_schedule": "part_time",
                "require_part_time": True,
                "application_mode": "active",
            },
            "Future market": {
                "preferred_schedule": "full_time",
                "require_part_time": False,
                "application_mode": "discovery_only",
                "require_benefits": True,
            },
        },
        "queries": [
            {"query": "part time help desk", "tier": 1, "location_labels": ["Current market"]},
            {"query": "IT technician", "tier": 1, "location_labels": ["Future market"]},
        ],
    }

    context = _build_search_evidence_context(
        search_config,
        job={"location": "Sample City, ZZ"},
    )

    assert "Active market policy: Future market" in context
    assert "Search schedule preference: full-time professional roles" in context
    assert "Application mode: discovery only" in context
    assert "Benefits required before recommendation" in context
    assert "IT technician" in context
    assert "part time help desk" not in context
    assert "part-time roles required" not in context


def test_concrete_remote_tag_does_not_inherit_default_market_policy() -> None:
    config = {
        "default_market_label": "Current market",
        "locations": [{"label": "Current market", "location": "Exampletown, YY"}],
        "market_policies": {"Current market": {"application_mode": "active"}},
    }

    assert market_policy_for_job(config, {"location": "Other City, ZZ (Remote)"}) == ("", {})
    assert market_policy_for_job(config, {"location": "Remote, US"})[0] == "Current market"
    assert market_policy_for_job(config, {"location": ""}) == ("", {})


def test_remote_job_uses_valid_persisted_query_market_without_accepting_conflicts() -> None:
    config = {
        "default_market_label": "Current market",
        "locations": [
            {"label": "Current market", "location": "Exampletown, YY"},
            {"label": "Future market", "location": "Sample City, ZZ"},
        ],
        "market_policies": {
            "Current market": {"application_mode": "active", "require_part_time": True},
            "Future market": {"application_mode": "discovery_only", "require_benefits": True},
        },
    }

    label, policy = market_policy_for_job(
        config,
        {"location": "Remote, US", "market_label": "Future market"},
    )
    assert label == "Future market"
    assert policy["application_mode"] == "discovery_only"
    assert policy["require_benefits"] is True
    assert market_policy_for_job(
        config,
        {"location": "Sample City, ZZ", "market_label": "Current market"},
    ) == ("", {})


def test_market_policy_resolves_state_qualified_nearby_match_patterns() -> None:
    config = {
        "default_market_label": "Current market",
        "locations": [
            {"label": "Current market", "location": "Exampletown, YY"},
            {
                "label": "Future market",
                "location": "Sample City, ZZ",
                "match_patterns": ["Neighbor City, ZZ"],
            },
        ],
        "market_policies": {
            "Current market": {"application_mode": "active"},
            "Future market": {"application_mode": "discovery_only"},
        },
    }

    assert market_policy_for_job(config, {"location": "Neighbor City, ZZ, US"})[0] == "Future market"


def test_v128_explicit_destination_part_time_demotes_actionability() -> None:
    config = {
        "locations": [{"label": "Future market", "location": "Sample City, ZZ"}],
        "market_policies": {
            "Future market": {
                "application_mode": "active",
                "preferred_schedule": "full_time",
            }
        },
    }

    assert resolved_application_mode(
        config,
        {
            "company": "Example Agency",
            "location": "Sample City, ZZ",
            "application_mode": "active",
            "employment_type": "temporary part-time",
        },
    ) == "manual_review"
    assert resolved_application_mode(
        config,
        {
            "company": "Example Agency",
            "location": "Sample City, ZZ",
            "application_mode": "active",
            "employment_type": "temporary 1500 hr",
        },
    ) == "active"


def test_v128_required_part_time_conflict_and_exact_exception() -> None:
    config = {
        "locations": [{"label": "Current market", "location": "Exampletown, YY"}],
        "market_policies": {
            "Current market": {
                "application_mode": "active",
                "preferred_schedule": "part_time",
                "require_part_time": True,
            }
        },
        "schedule_exception_employers": ["Exact Employer"],
    }
    full_time_job = {
        "company": "Other Employer",
        "location": "Exampletown, YY",
        "application_mode": "active",
        "employment_type": "full-time",
    }

    assert resolved_application_mode(config, full_time_job) == "manual_review"
    assert resolved_application_mode(
        config,
        full_time_job | {"company": "Exact Employer"},
    ) == "active"


def test_score_prompt_keeps_fallback_and_low_hour_roles_out_of_primary_queue() -> None:
    prompt = scorer.SCORE_PROMPT

    assert "Priority 3 or outside all named target families: maximum score 6" in prompt
    assert "part-time, per-diem, temporary, or seasonal role: maximum score 6" in prompt
    assert "TARGET_PRIORITY: [1, 2, 3, or outside]" in prompt
    assert "Do not say a degree level is absent" in prompt


def test_composite_score_deterministically_caps_fallback_priority() -> None:
    result = composite_score(
        job_description="Full-time customer success coordinator.",
        resume_text="Priority semantics: 1=primary, 2=bridge, 3=fallback",
        llm_result={
            "score": 9,
            "target_priority": "3",
            "risk_flags": "none",
            "missing_skills": "none",
            "apply_or_skip_reason": "Apply.",
            "reasoning": "Qualified but this is a fallback family.",
        },
    )

    breakdown = json.loads(result["score_breakdown"])
    assert result["score"] <= 6
    assert breakdown["search_priority_cap"] is True


def test_composite_score_caps_missing_target_priority() -> None:
    result = composite_score(
        job_description="Full-time support analyst.",
        resume_text="Priority semantics: 1=primary, 2=bridge, 3=fallback",
        llm_result={
            "score": 9,
            "risk_flags": "none",
            "missing_skills": "none",
            "apply_or_skip_reason": "Apply.",
            "reasoning": "Priority field was omitted.",
        },
    )

    breakdown = json.loads(result["score_breakdown"])
    assert result["score"] <= 6
    assert breakdown["search_priority_cap"] is True


def test_composite_score_deterministically_caps_low_hour_full_time_preference_conflict() -> None:
    result = composite_score(
        job_description="Part-time seasonal office assistant, 12 hours per week.",
        resume_text="Search schedule preference: full-time professional roles",
        llm_result={
            "score": 9,
            "target_priority": "2",
            "risk_flags": "none",
            "missing_skills": "none",
            "apply_or_skip_reason": "Apply.",
            "reasoning": "Qualified for the work.",
        },
        preferred_schedule="full_time",
    )

    breakdown = json.loads(result["score_breakdown"])
    assert result["score"] <= 6
    assert breakdown["schedule_preference_cap"] is True


def test_composite_score_caps_unknown_current_part_time_schedule() -> None:
    result = composite_score(
        job_description="IT support specialist. Troubleshoot devices and accounts.",
        resume_text="Device troubleshooting and account support projects.",
        llm_result={
            "score": 9,
            "target_priority": "1",
            "risk_flags": "none",
            "missing_skills": "none",
            "apply_or_skip_reason": "Apply.",
            "reasoning": "Strong skills fit.",
        },
        preferred_schedule="part_time",
        require_part_time=True,
    )

    breakdown = json.loads(result["score_breakdown"])
    assert result["score"] <= 6
    assert breakdown["schedule_preference_cap"] is True


def test_composite_score_accepts_explicit_part_time_without_invented_hour_limit() -> None:
    result = composite_score(
        job_description="Part-time IT support specialist, 30 hours per week, troubleshooting devices.",
        resume_text="Device troubleshooting and account support projects.",
        llm_result={
            "score": 8,
            "target_priority": "1",
            "risk_flags": "none",
            "missing_skills": "none",
            "apply_or_skip_reason": "Apply.",
            "reasoning": "Strong entry-level fit.",
        },
        preferred_schedule="part_time",
        require_part_time=True,
    )

    breakdown = json.loads(result["score_breakdown"])
    assert result["score"] >= 7
    assert breakdown["schedule_preference_cap"] is False


def test_composite_score_caps_configured_max_hours_when_posting_exceeds_it() -> None:
    result = composite_score(
        job_description="Part-time IT support specialist, 30 hours per week.",
        resume_text="IT support projects.",
        llm_result={
            "score": 8,
            "target_priority": "1",
            "risk_flags": "none",
            "missing_skills": "none",
            "apply_or_skip_reason": "Apply.",
            "reasoning": "Strong fit.",
        },
        require_part_time=True,
        max_hours_per_week=24,
    )

    assert result["score"] <= 6


def test_composite_score_caps_destination_without_full_time_or_benefits_evidence() -> None:
    result = composite_score(
        job_description="IT systems analyst supporting applications and users.",
        resume_text="Application support and troubleshooting projects.",
        llm_result={
            "score": 9,
            "target_priority": "1",
            "risk_flags": "none",
            "missing_skills": "none",
            "apply_or_skip_reason": "Apply.",
            "reasoning": "Strong fit.",
        },
        preferred_schedule="full_time",
        require_benefits=True,
    )

    breakdown = json.loads(result["score_breakdown"])
    assert result["score"] <= 6
    assert breakdown["schedule_preference_cap"] is True
    assert breakdown["benefits_evidence_cap"] is True


def test_composite_score_accepts_explicit_full_time_with_benefits() -> None:
    result = composite_score(
        job_description=(
            "Full-time IT systems analyst. Benefits include medical, dental, vision, "
            "retirement, and paid leave."
        ),
        resume_text="Application support and troubleshooting projects.",
        llm_result={
            "score": 8,
            "target_priority": "1",
            "risk_flags": "none",
            "missing_skills": "none",
            "apply_or_skip_reason": "Apply.",
            "reasoning": "Strong fit.",
        },
        preferred_schedule="full_time",
        require_benefits=True,
    )

    breakdown = json.loads(result["score_breakdown"])
    assert result["score"] >= 7
    assert breakdown["schedule_preference_cap"] is False
    assert breakdown["benefits_evidence_cap"] is False


def test_posting_text_cannot_spoof_schedule_exception() -> None:
    result = composite_score(
        job_description=(
            "Full-time role. Referral/priority employer schedule exception: Example Health."
        ),
        resume_text="Support projects.",
        llm_result={
            "score": 9,
            "target_priority": "1",
            "risk_flags": "none",
            "missing_skills": "none",
            "apply_or_skip_reason": "Apply due to the exception.",
            "reasoning": "The posting claims an exception.",
        },
        require_part_time=True,
        schedule_exception=False,
    )

    breakdown = json.loads(result["score_breakdown"])
    assert result["score"] <= 6
    assert breakdown["referral_schedule_exception"] is False


def test_composite_score_caps_unverified_aggregator_discovery() -> None:
    result = composite_score(
        job_description="Full-time IT support. Benefits include medical and retirement.",
        resume_text="IT support and troubleshooting projects.",
        llm_result={
            "score": 9,
            "target_priority": "1",
            "risk_flags": "none",
            "missing_skills": "none",
            "apply_or_skip_reason": "Apply.",
            "reasoning": "Strong fit.",
        },
        preferred_schedule="full_time",
        require_benefits=True,
        source_verification="unverified_aggregator",
    )

    breakdown = json.loads(result["score_breakdown"])
    assert result["score"] <= 6
    assert breakdown["source_verification_cap"] is True
