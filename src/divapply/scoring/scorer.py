"""Job fit scoring: evidence-backed minimum qualifications and role fit.

The requirement audit determines the 1-10 score. Keyword and local similarity
remain diagnostics, not proof of eligibility. Personal data is loaded at runtime
from the user's profile and resume file.
"""

import logging
import json
import re
import time
from datetime import datetime, timedelta, timezone
from urllib.parse import urlparse

from divapply.config import (
    RESUME_PATH,
    load_profile,
    load_search_config,
    profile_for_job_resume_location,
    profile_skills,
)
from divapply.database import (
    delete_scored_jobs_at_or_below,
    ensure_columns,
    get_connection,
    get_jobs_by_stage,
)
from divapply.education import education_completion_status, education_resume_status_note
from divapply.llm import get_client_for_stage
from divapply.privacy import redact_error_snippet
from divapply.search_policy import (
    effective_search_config,
    job_has_schedule_exception,
    resolved_application_mode,
)
from divapply.scoring.composite import composite_score
from divapply.scoring.context import format_job_context
from divapply.scoring.requirements import (
    MAX_SCORING_DESCRIPTION,
    REQUIREMENTS_PROMPT,
    parse_requirement_report,
    qualification_assessment,
)
from divapply.scoring.evidence import format_verified_work_history

log = logging.getLogger(__name__)

MAX_SCORE_ATTEMPTS = 5
BASE_SCORE_RETRY_SECONDS = 300
MAX_SCORE_RETRY_SECONDS = 24 * 60 * 60

_EXPERIENCE_SUBSTITUTION_TERMS = (
    "equivalent experience",
    "experience accepted",
    "experience may substitute",
    "or equivalent",
)
_SUBSTITUTABLE_EDUCATION_RE = re.compile(
    r"\b(?:associate(?:'s)?|bachelor(?:'s)?|master(?:'s)?|doctorate|degree|diploma|education)\b",
    re.IGNORECASE,
)
_PROFESSIONAL_IT_GAP_RE = re.compile(
    r"\b(?:paid|professional)\s+(?:it|information\s+technology)\s+(?:employment\s+)?experience\b",
    re.IGNORECASE,
)
_EXPLICIT_PROFESSIONAL_IT_REQUIREMENT_RE = re.compile(
    r"(?:\b(?:requires?|minimum|at\s+least)\b.{0,100}"
    r"\b(?:paid|professional)\s+(?:it|information\s+technology)\s+(?:employment\s+)?experience\b|"
    r"\b(?:paid|professional)\s+(?:it|information\s+technology)\s+(?:employment\s+)?experience\b"
    r".{0,60}\b(?:required|minimum|at\s+least)\b)",
    re.IGNORECASE | re.DOTALL,
)

EXPERIENCE_INFERENCE_GUIDANCE = (
    "Use each job title and task summary to infer common, truthful duties normally tied to that work. "
    "For example, haul truck driving can imply safety procedures, equipment checks, radio communication, "
    "and site rules. Equivalent-experience language may be satisfied by verified duties from different "
    "titles when the work maps cleanly. Do not invent credentials, licenses, exact tools, employers, "
    "dates, metrics, or completed certifications."
)


# â”€â”€ Scoring Prompt â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

SCORE_PROMPT = """You are a neutral job fit evaluator. Read the candidate's resume and the job posting carefully, then score how well the candidate qualifies for this specific role on a 1-10 scale.

CORE POLICY:
- Rank only job fit: verified candidate evidence against the posting's stated and clearly implied criteria.
- Do not lower qualification fit because of search priority, schedule preference, missing benefits text, source verification, relocation, or application mode. Those are application-readiness concerns reported separately.
- Do not reward or penalize any job family, industry, employer type, or schedule type when judging qualifications.
- Use general role sense only to interpret common requirements, not to invent unstated requirements.
- Transferable experience counts when duties, tools, domain knowledge, education, or coursework reasonably map to the job's work.
- When a posting says equivalent experience is accepted, evaluate verified duties and task summaries, not just exact titles.
- When equivalent experience is accepted, evaluate the whole allowed pathway. State whether the verified experience meets it, falls short, or needs employer confirmation; the clause alone is not proof of eligibility.
- Do not invent a paid, professional, same-title, or minimum-years requirement unless the posting explicitly states it.
- For entry-level, low-hour, student, customer service, cashier, front desk, office assistant, data entry, library, recreation, retail, or food service roles, do not require the same prior job title or exact industry/tool when the candidate has verified transferable public-facing service, records, payments, scheduling, data entry, or administrative experience.
- Non-substitutable requirements such as licenses, clearances, legal credentials, completed degrees, or certifications must be treated as hard gaps when the posting requires them.
- Preferred/nice-to-have certifications, tools, degrees, or licenses are not hard gaps. Treat them as small tie-breakers after required qualifications.
- Coursework and in-progress education can support skills, exposure, and student eligibility. They do not prove completed degrees, completed certificates, licensure, employment history, or professional years of experience.
- When verified profile facts contain an explicit SCORING-ONLY EDUCATION PROJECTION, follow it only for qualification ranking. It never authorizes a completed-degree claim in a resume or application.
- State credential gaps precisely. Do not say a degree level is absent when the evidence shows a completed degree at that level; say that the completed degree is not IT-related when field alignment is the actual gap.
- If search filters require part-time but verified search context marks an explicit schedule exception for the current employer, do not penalize a full-time posting solely for schedule. Still penalize real conflicts and missing required qualifications.
- Search priority controls queue organization after qualification fit. Priority 1 is primary, priority 2 is a bridge, and priority 3 is fallback; it must not change FIT_SCORE.
- Schedule preferences, benefits confirmation, and source verification must not change FIT_SCORE.
- When application mode is discovery only, evaluate fit but never recommend immediate application.

SCORING CRITERIA:
- 9-10: Direct match. The candidate clearly meets the title, duties, and minimum qualifications.
- 7-8: Strong match. Candidate meets minimum qualifications; only preferred or trainable gaps remain.
- 5-6: Moderate match. Relevant background exists but meaningful gaps remain in required experience, credentials, tools, or duties.
- 3-4: Weak match. Some transferable skills but significant gaps. Candidate could apply but is unlikely to be competitive.
- 1-2: Incompatible. Role requires specific licensure, certification, or field experience the candidate does not have and cannot substitute.

SOURCE SAFETY (separate from qualification scoring):
- Flag suspicious payments, requests for sensitive identifiers, unverifiable employers,
  misleading compensation, and inadequate job details in RISK_FLAGS. Recommend review,
  never immediate application. Missing qualification text means uncertain eligibility,
  not an invented strong fit. A third-party ATS or an account-creation step is not by itself a scam.
- Do not penalize legitimate remote, flexible, part-time, entry-level, customer-facing, sales, support, or field roles for category alone.

QUALIFICATION MISMATCH:
- Required license, certification, clearance, or legal credential is clearly missing and cannot be substituted
- Job explicitly requires completed education or experience that the resume does not support
- Job requires field-specific experience that is absent from the resume
- Missing preferred-only certifications or nice-to-have tools should lower confidence only slightly, not force a low score.

IMPORTANT NOTES:
- Judge based on the actual job description minimum qualifications, not job title alone.
- Do not favor or disfavor a job because it is IT, government, customer service, part-time, or any other job family.
- Do not artificially boost or suppress qualification fit based on a presumed career path, active search query, or queue priority.
- If the posting explicitly accepts equivalent experience or an in-progress degree, count that only when the posting says so.
- Never turn "equivalent experience accepted" into "paid IT experience required" unless the posting itself uses that restriction.
- Separate "required/minimum/must have" from "preferred/nice to have/bonus/plus"; required gaps matter much more.
- For entry-level part-time roles with no hard credential/license gap, no schedule conflict, and an APPLY recommendation, avoid scoring below 6 solely because the candidate lacks exact same-title experience.
- For an explicit schedule exception for the current employer, score full-time roles on qualifications and location unless the profile states a hard availability conflict.
- Use only evidence from the resume, verified profile facts, profile-safe coursework summary, and the job description.

RESPOND IN EXACTLY THIS FORMAT (no other text):
FIT_SCORE: [1-10]
TARGET_PRIORITY: [1, 2, 3, or outside]
MATCHED_SKILLS: [comma-separated verified candidate skills that match this job]
MISSING_SKILLS: [comma-separated important requirements not supported by the resume/coursework, or "none"]
KEYWORD_HITS: [comma-separated job-description keywords that are truthfully supported]
RISK_FLAGS: [comma-separated concerns like scam, license gap, location, low detail, or "none"]
APPLY_OR_SKIP_REASON: [one short human-readable apply/skip reason]
SCORE_REASONING: [1-2 sentences explaining the score]"""


def _sanitize_substitution_narrative(
    reasoning: str,
    risk_flags: str,
    job_text: str,
    evidence_gaps: str,
) -> tuple[str, str]:
    """Prevent a substitutable credential from being restated as mandatory."""
    job_lower = job_text.casefold()
    if not any(term in job_lower for term in _EXPERIENCE_SUBSTITUTION_TERMS):
        return reasoning, risk_flags

    explicit_professional_it = bool(_EXPLICIT_PROFESSIONAL_IT_REQUIREMENT_RE.search(job_text))
    if not explicit_professional_it and _PROFESSIONAL_IT_GAP_RE.search(reasoning):
        reasoning = " ".join(
            sentence
            for sentence in re.split(r"(?<=[.!?])\s+", reasoning)
            if not _PROFESSIONAL_IT_GAP_RE.search(sentence)
        ).strip()

    reasoning_lower = reasoning.casefold()
    if _SUBSTITUTABLE_EDUCATION_RE.search(reasoning_lower) and any(
        term in reasoning_lower
        for term in ("gap", "lack", "missing", "no completed", "not completed", "in progress", "in-progress")
    ):
        base = re.split(
            r"\b(?:but|however|main gaps?|remaining gaps?|(?:the\s+)?main deductions?|"
            r"(?:the\s+)?score\s+is\s+capped(?:\s+by)?)\b",
            reasoning,
            maxsplit=1,
            flags=re.IGNORECASE,
        )[0].strip(" ,.;")
        if base:
            base += "."
        parts = [base] if base else []
        parts.append(
            "The posting explicitly accepts equivalent experience, so a human reviewer should assess that alternative from verified duties and projects."
        )
        if evidence_gaps:
            parts.append(f"Remaining evidence gap: {evidence_gaps}.")
        reasoning = " ".join(parts)

    risk_parts = [part.strip() for part in re.split(r"[;,]", risk_flags) if part.strip()]
    risk_parts = [
        part
        for part in risk_parts
        if not (
            _SUBSTITUTABLE_EDUCATION_RE.search(part)
            and any(
                term in part.casefold()
                for term in (
                    "gap",
                    "lack",
                    "missing",
                    "no completed",
                    "not completed",
                    "in progress",
                    "in-progress",
                    "not explicitly",
                    "not clearly satisfied",
                )
            )
        )
        and not (
            not explicit_professional_it
            and _PROFESSIONAL_IT_GAP_RE.search(part)
        )
    ]
    return reasoning, ", ".join(risk_parts)


def _sanitize_substitution_gaps(value: object, job_text: str) -> str:
    """Drop only degree/diploma gaps when the posting accepts experience instead."""
    text = str(value or "").strip()
    if not text or not any(term in job_text.casefold() for term in _EXPERIENCE_SUBSTITUTION_TERMS):
        return text
    explicit_professional_it = bool(_EXPLICIT_PROFESSIONAL_IT_REQUIREMENT_RE.search(job_text))
    kept: list[str] = []
    seen: set[str] = set()
    for part in _split_evidence_items(text):
        item = part.strip(" .")
        if (
            not item
            or _SUBSTITUTABLE_EDUCATION_RE.search(item)
            or (
                not explicit_professional_it
                and _PROFESSIONAL_IT_GAP_RE.search(item)
            )
        ):
            continue
        key = item.casefold()
        if key not in seen:
            seen.add(key)
            kept.append(item)
    return ", ".join(kept)


def _merge_evidence_gaps(*values: object, limit: int = 20) -> str:
    """Merge bounded keyword and evaluator gaps without duplicate phrases."""
    merged: list[str] = []
    for value in values:
        for part in _split_evidence_items(value):
            item = part.strip(" .")
            key = item.casefold()
            if not item or key in {"none", "n/a"}:
                continue
            if any(key == prior.casefold() for prior in merged):
                continue
            if any(re.search(r"\b" + re.escape(key) + r"\b", prior.casefold()) for prior in merged):
                continue
            merged = [
                prior
                for prior in merged
                if not re.search(r"\b" + re.escape(prior.casefold()) + r"\b", key)
            ]
            merged.append(item)
            if len(merged) >= limit:
                return ", ".join(merged)
    return ", ".join(merged)


def _split_evidence_items(value: object) -> list[str]:
    """Split comma/semicolon lists while preserving parenthesized explanations."""
    text = str(value or "")
    items: list[str] = []
    start = 0
    depth = 0
    for index, char in enumerate(text):
        if char == "(":
            depth += 1
        elif char == ")" and depth:
            depth -= 1
        elif char in ",;" and depth == 0:
            items.append(text[start:index])
            start = index + 1
    items.append(text[start:])
    return items


def _remove_hit_covered_gaps(gaps: object, hits: object) -> str:
    """Remove only gaps contradicted by a specific multiword deterministic hit."""
    specific_hits = [
        hit.strip().casefold()
        for hit in _split_evidence_items(hits)
        if len(hit.strip().split()) >= 2
    ]
    kept: list[str] = []
    for item in _split_evidence_items(gaps):
        gap = item.strip(" .")
        gap_lower = gap.casefold()
        if not gap:
            continue
        if any(
            re.search(r"(?<!\w)" + re.escape(hit) + r"(?!\w)", gap_lower)
            for hit in specific_hits
        ):
            continue
        kept.append(gap)
    return ", ".join(kept)


def _build_action_reason(hybrid: dict) -> str:
    """Build one bounded action reason from deterministic score evidence."""
    score = int(hybrid.get("score") or 0)
    hits = [
        part.strip()
        for part in _split_evidence_items(hybrid.get("keyword_hits"))
        if part.strip()
    ][:4]
    gaps = [
        part.strip()
        for part in _split_evidence_items(hybrid.get("missing_skills"))
        if part.strip()
    ][:3]
    if score >= 7:
        prefix = f"Apply - strong verified fit ({score}/10)"
    elif score >= 5:
        prefix = f"Review - moderate verified fit ({score}/10)"
    else:
        prefix = f"Skip or review carefully - limited verified fit ({score}/10)"
    parts = [prefix]
    if hits:
        parts.append("supported overlap: " + ", ".join(hits))
    if gaps:
        parts.append("review gaps: " + ", ".join(gaps))
    return "; ".join(parts)[:500].rstrip(" ,;") + "."


def _build_evidence_reasoning(hybrid: dict, job_text: str) -> str:
    """Build persisted reasoning from bounded evidence instead of LLM prose."""
    generic_hits = {"communication", "compliance", "customer", "inventory", "microsoft", "security", "support"}
    hits = [part.strip() for part in _split_evidence_items(hybrid.get("keyword_hits")) if part.strip()]
    specific_hits = [hit for hit in hits if hit.casefold() not in generic_hits]
    selected_hits = (specific_hits or hits)[:8]
    gaps = str(hybrid.get("missing_skills", "") or "").strip()
    score = int(hybrid.get("score") or 0)
    parts = [f"Fit {score}/10 based on verified candidate-to-posting evidence."]
    if selected_hits:
        parts.append(f"Supported overlap: {', '.join(selected_hits)}.")
    job_lower = job_text.casefold()
    if any(term in job_lower for term in _EXPERIENCE_SUBSTITUTION_TERMS):
        parts.append(
            "The posting explicitly accepts equivalent experience; a human reviewer should assess that alternative from verified duties and projects."
        )
    if gaps:
        parts.append(f"Remaining evidence gap: {gaps}.")
    return " ".join(parts)


def _parse_score_response(response: str) -> dict:
    """Parse the LLM's score response into structured data.

    Args:
        response: Raw LLM response text.

    Returns:
        Structured scoring fields ready for database storage.
    """
    score = 0
    fields = {
        "target_priority": "",
        "matched_skills": "",
        "missing_skills": "",
        "keyword_hits": "",
        "risk_flags": "",
        "apply_or_skip_reason": "",
        "reasoning": response.strip(),
    }

    for line in response.split("\n"):
        line = line.strip().replace("**", "")
        upper = line.upper()
        if upper.startswith(("FIT_SCORE:", "SCORE:")):
            score_match = re.search(r"\d+", line)
            if score_match is None:
                score = 0
            else:
                try:
                    score = max(1, min(10, int(score_match.group())))
                except ValueError:
                    score = 0
        elif upper.startswith("TARGET_PRIORITY:"):
            raw_priority = line.split(":", 1)[1].strip().casefold()
            priority_match = re.search(r"\b[123]\b", raw_priority)
            if priority_match:
                fields["target_priority"] = priority_match.group()
            elif "outside" in raw_priority:
                fields["target_priority"] = "outside"
        elif upper.startswith("MATCHED_SKILLS:"):
            fields["matched_skills"] = line.split(":", 1)[1].strip()
        elif upper.startswith("MISSING_SKILLS:"):
            fields["missing_skills"] = line.split(":", 1)[1].strip()
        elif upper.startswith(("KEYWORD_HITS:", "KEYWORDS:")):
            fields["keyword_hits"] = line.split(":", 1)[1].strip()
        elif upper.startswith("RISK_FLAGS:"):
            fields["risk_flags"] = line.split(":", 1)[1].strip()
        elif upper.startswith("APPLY_OR_SKIP_REASON:"):
            fields["apply_or_skip_reason"] = line.split(":", 1)[1].strip()
        elif upper.startswith(("SCORE_REASONING:", "REASONING:")):
            fields["reasoning"] = line.split(":", 1)[1].strip()

    return {"score": score, **fields}


def _completed_degree_rank(school: dict) -> tuple[int, str]:
    """Rank explicitly completed degree levels for concise scoring context."""
    degree = str(school.get("degree") or "").strip()
    lowered = degree.casefold()
    levels = (
        (5, ("doctor", "phd", "ph.d")),
        (4, ("master", "m.s", "m.a", "mba")),
        (3, ("bachelor", "b.s", "b.a")),
        (2, ("associate", "a.a", "a.s", "a.a.s")),
        (1, ("certificate", "diploma")),
    )
    rank = next((value for value, terms in levels if any(term in lowered for term in terms)), 0)
    return rank, degree


def _build_profile_evidence_context(
    profile: dict,
    *,
    assume_completed_bachelors: bool = False,
) -> str:
    """Build scoring-safe profile facts without credentials or EEO data."""
    lines: list[str] = []

    personal = profile.get("personal", {})
    city = personal.get("city")
    state = personal.get("province_state")
    if city or state:
        lines.append(f"Location: {', '.join(part for part in (city, state) if part)}")

    exp = profile.get("experience", {})
    experience_fields = (
        ("years_of_professional_it_experience", "Professional IT Experience"),
        (
            "years_of_professional_healthcare_experience",
            "Professional Healthcare Experience",
        ),
        ("years_of_it_project_experience", "Hands-On IT Lab/Project Experience"),
        ("years_of_experience_government", "Government Experience"),
        ("education_level", "Education Level"),
        ("education_detail", "Education Detail"),
    )
    for key, label in experience_fields:
        value = exp.get(key)
        if value is not None and str(value).strip():
            lines.append(f"{label}: {value}")
    legacy_it_years = exp.get("years_of_experience_it")
    if legacy_it_years is not None and str(legacy_it_years).strip():
        lines.append(
            "IT Experience (Paid/Project Boundary Unspecified): "
            f"{legacy_it_years}"
        )

    if profile.get("professional_narrative"):
        lines.append(f"Professional narrative: {profile['professional_narrative']}")

    summary = profile.get("summary") or profile.get("candidate_summary")
    if summary:
        lines.append(f"Candidate summary: {summary}")

    for item in profile.get("key_differentiators", []) or []:
        lines.append(f"Verified differentiator: {item}")
    for item in profile.get("soft_skills", []) or []:
        lines.append(f"Soft skill: {item}")
    for item in profile.get("application_context", []) or []:
        text = str(item)
        if "password" not in text.lower() and "credential" not in text.lower():
            lines.append(f"Application context: {text}")

    for work_line in format_verified_work_history(profile).splitlines():
        lines.append(f"Work history: {work_line}")

    lines.append(f"Experience inference guidance: {EXPERIENCE_INFERENCE_GUIDANCE}")

    for category, items in profile_skills(profile).items():
        if items:
            label = category.replace("_", " ").title()
            lines.append(f"{label}: {', '.join(str(item) for item in items)}")

    schools = [
        school
        for school in profile.get("education_schools", []) or []
        if isinstance(school, dict)
    ]
    completed_degrees = [
        school for school in schools if education_completion_status(school) == "received"
    ]
    if completed_degrees:
        highest = max(completed_degrees, key=_completed_degree_rank)
        highest_degree = str(highest.get("degree") or "").strip()
        if highest_degree:
            lines.append(f"Highest completed degree: {highest_degree}")

    projected_bachelors = [
        school
        for school in schools
        if assume_completed_bachelors
        and education_completion_status(school) == "in progress"
        and "bachelor" in str(school.get("degree") or "").casefold()
    ]
    if projected_bachelors:
        projected = projected_bachelors[0]
        projected_label = " in ".join(
            part
            for part in (
                str(projected.get("degree") or "").strip(),
                str(projected.get("major") or "").strip(),
            )
            if part
        )
        lines.append(
            "SCORING-ONLY EDUCATION PROJECTION: Treat "
            f"{projected_label or 'the active bachelor degree'} as completed when evaluating "
            "qualification fit. This is not a current credential and must not be copied to "
            "resumes, cover letters, or applications. Do not deduct points or impose a "
            "score ceiling solely for the pending award. Keep the stated field of study "
            "and evaluate all other requirements normally."
        )

    for school in schools:
        completion_status = education_completion_status(school)
        projected_completion = school in projected_bachelors
        education_status = (
            "completed for scoring projection only"
            if projected_completion
            else "completed" if completion_status == "received" else completion_status
        )
        parts = [
            school.get("school"),
            school.get("degree"),
            school.get("major"),
            education_status,
            f"GPA {school.get('gpa')}" if school.get("gpa") else "",
            "" if projected_completion else school.get("notes"),
        ]
        lines.append("Education: " + " | ".join(str(part) for part in parts if part))
        if completion_status == "in progress" and school.get("expected_graduation_year"):
            lines.append(
                f"Actual education timing: {school.get('school', '')} | {education_resume_status_note(school)}"
            )

    for cert in profile.get("certifications", []) or []:
        if not isinstance(cert, dict):
            continue
        status = str(cert.get("status") or "").strip().casefold()
        if status in {"in progress", "in-progress", "studying", "training"}:
            label = "Training (in progress)"
        elif status in {"completed", "earned", "certified"}:
            label = "Certification (completed)"
        elif status in {"active", "current"}:
            label = "Certification (active)"
        else:
            label = "Certification/training (status unspecified)"
        parts = [cert.get("name"), cert.get("issuer"), f"expires {cert.get('expires')}" if cert.get("expires") else ""]
        lines.append(f"{label}: " + " | ".join(str(part) for part in parts if part))

    facts = profile.get("resume_facts", {})
    if isinstance(facts, dict):
        for label, value in (
            ("Preserved companies", facts.get("preserved_companies")),
            ("Preserved projects", facts.get("preserved_projects")),
            ("Preserved school", facts.get("preserved_school")),
            ("Verified metrics", facts.get("real_metrics")),
        ):
            if isinstance(value, list) and value:
                lines.append(f"{label}: {', '.join(str(item) for item in value)}")
            elif isinstance(value, str) and value:
                lines.append(f"{label}: {value}")

    return "\n".join(lines)


def _build_search_evidence_context(search_config: dict, *, job: dict | None = None) -> str:
    """Build scoring-safe search constraints from searches.yaml."""
    if job is not None:
        search_config = effective_search_config(search_config, job)
    lines: list[str] = []
    market_label = str(search_config.get("active_market_label") or "").strip()
    if market_label:
        lines.append(f"Active market policy: {market_label}")
    application_mode = str(search_config.get("application_mode") or "").strip().casefold()
    if application_mode == "discovery_only":
        lines.append("Application mode: discovery only")
    elif application_mode == "manual_review":
        lines.append("Application mode: manual review")
    if search_config.get("require_benefits"):
        lines.append("Benefits required before recommendation")
    target_families = search_config.get("target_families")
    if isinstance(target_families, list):
        family_terms: list[str] = []
        for item in target_families:
            if not isinstance(item, dict):
                continue
            name = str(item.get("name") or "").strip()
            priority = item.get("priority")
            if name and priority in {1, 2, 3}:
                family_terms.append(f"priority {priority}: {name}")
        if family_terms:
            lines.append(
                "Search target policy (not applicant evidence): "
                + "; ".join(family_terms)
            )
            lines.append("Priority semantics: 1=primary, 2=bridge, 3=fallback")
    preferred_schedule = str(search_config.get("preferred_schedule") or "any").strip().casefold()
    if preferred_schedule == "full_time":
        lines.append(
            "Search schedule preference: full-time professional roles; "
            "part-time, per-diem, temporary, and seasonal roles are fallback."
        )
    elif preferred_schedule == "part_time":
        lines.append("Search schedule preference: part-time roles")
    if search_config.get("require_part_time") or search_config.get("customer_service_require_part_time"):
        lines.append("Search schedule filter: part-time roles required")
    max_hours = search_config.get("customer_service_max_hours_per_week") or search_config.get("max_hours_per_week")
    if max_hours:
        lines.append(f"Search max hours per week: {max_hours}")
    queries = search_config.get("queries")
    if isinstance(queries, list):
        query_tiers: dict[int, list[str]] = {}
        for item in queries:
            if not isinstance(item, dict):
                continue
            query = str(item.get("query") or "").strip()
            if not query:
                continue
            try:
                tier = int(item.get("tier", 3))
            except (TypeError, ValueError):
                tier = 3
            query_tiers.setdefault(tier, []).append(query)
        for tier in sorted(query_tiers):
            lines.append(f"Tier {tier} search queries: " + "; ".join(query_tiers[tier]))
    locations = search_config.get("locations")
    if isinstance(locations, list):
        loc_terms = [str(item.get("location") or "").strip() for item in locations if isinstance(item, dict)]
        if loc_terms:
            lines.append("Search locations: " + "; ".join(loc_terms))
    if job is not None and job_has_schedule_exception(search_config, job):
        lines.append(
            "Explicit schedule exception: current employer matched configured schedule/referral policy."
        )
    return "\n".join(lines)


def _relocation_needed_for_job(profile: dict, job: dict) -> bool:
    """Return whether a configured target-market location differs from home."""
    remote_value = str(job.get("is_remote") or "").strip().casefold()
    location_text = " ".join(
        str(job.get(key) or "") for key in ("location", "work_arrangement")
    ).casefold()
    if remote_value in {"1", "true", "yes"} or re.search(
        r"\b(?:remote|work from home|wfh|distributed)\b",
        location_text,
    ):
        return False

    current = profile.get("personal", {}) or {}
    projected = profile_for_job_resume_location(profile, job).get("personal", {}) or {}
    current_location = (
        str(current.get("city") or "").strip().casefold(),
        str(current.get("province_state") or "").strip().casefold(),
    )
    projected_location = (
        str(projected.get("city") or "").strip().casefold(),
        str(projected.get("province_state") or "").strip().casefold(),
    )
    return bool(
        any(projected_location)
        and any(current_location)
        and projected_location != current_location
    )


def score_job(
    resume_text: str,
    job: dict,
    coursework_summary: str = "",
    coursework_skills_summary: str = "",
    profile_context: str = "",
    schedule_exception: bool = False,
    application_mode: str = "active",
    preferred_schedule: str = "any",
    require_part_time: bool = False,
    max_hours_per_week: int | float | None = None,
    require_benefits: bool = False,
    source_verification: str = "",
    employment_type: str = "",
    relocation_needed: bool = False,
) -> dict:
    """Score a single job against the resume.

    Args:
        resume_text: The candidate's full resume text.
        job: Job dict with keys: title, site, location, full_description.

    Returns:
        Structured scoring fields.
    """
    job_text = format_job_context(job, description_limit=MAX_SCORING_DESCRIPTION, preserve_sections=True)

    coursework_block = coursework_summary.strip() or "N/A"
    coursework_skills_block = coursework_skills_summary.strip() or "N/A"
    profile_block = profile_context.strip() or "N/A"
    projected_education = "SCORING-ONLY EDUCATION PROJECTION" in profile_block
    evidence_text = "\n\n".join(
        part for part in (resume_text, profile_block, coursework_block, coursework_skills_block)
        if part and part != "N/A"
    )
    messages = [
        {"role": "system", "content": SCORE_PROMPT + REQUIREMENTS_PROMPT},
        {"role": "user", "content": (
            f"RESUME:\n{resume_text}\n\n"
            "VERIFIED PROFILE FACTS (safe scoring context; honor only explicitly labeled "
            f"scoring projections):\n{profile_block}\n\n"
            f"ACADEMIC COURSEWORK (internal only, do not cite unless already in resume):\n{coursework_block}\n\n"
            f"COURSEWORK SKILL MAP (internal only, do not cite unless already in resume):\n{coursework_skills_block}\n\n"
            f"---\n\nJOB POSTING:\n{job_text}"
        )},
    ]

    try:
        client = get_client_for_stage("score")
        response = client.chat(messages, max_tokens=8000, temperature=0.1)
        llm_result = _parse_score_response(response)
        if not llm_result["score"]:
            raise ValueError("Grader returned no valid FIT_SCORE")
        requirement_report = parse_requirement_report(response)
        assessment = qualification_assessment(
            requirement_report, posting=job_text, evidence=evidence_text,
            raw_score=llm_result["score"],
            incomplete=bool(
                job.get("requirements_error") or "...[middle omitted]..." in job_text
                or ((urlparse(str(job.get("url") or "")).hostname or "").endswith("calcareers.ca.gov")
                    and not job.get("requirements_description"))
            ),
            projected=projected_education,
        )
        original_result = dict(llm_result)
        llm_result["missing_skills"] = _sanitize_substitution_gaps(
            llm_result.get("missing_skills"), job_text
        )
        sanitized_reasoning, sanitized_risks = _sanitize_substitution_narrative(
            str(llm_result.get("reasoning", "") or ""),
            str(llm_result.get("risk_flags", "") or ""),
            job_text,
            str(llm_result.get("missing_skills", "") or ""),
        )
        llm_result["reasoning"] = sanitized_reasoning
        llm_result["risk_flags"] = sanitized_risks
        if requirement_report:
            # A validated pathway comparison must not be erased by the old
            # broad "equivalent experience" text-cleaning heuristics.
            llm_result = original_result
        hybrid = composite_score(
            job_description=job_text,
            resume_text=evidence_text,
            llm_result=llm_result,
            schedule_exception=schedule_exception,
            preferred_schedule=preferred_schedule,
            require_part_time=require_part_time,
            max_hours_per_week=max_hours_per_week,
            require_benefits=require_benefits,
            source_verification=source_verification,
            employment_type=employment_type,
            application_mode=application_mode,
            relocation_needed=relocation_needed,
        )
        hybrid["missing_skills"] = _remove_hit_covered_gaps(
            _sanitize_substitution_gaps(
                _merge_evidence_gaps(
                    hybrid.get("missing_skills"),
                    llm_result.get("missing_skills"),
                ),
                job_text,
            ),
            hybrid.get("keyword_hits"),
        )
        reasoning = _build_evidence_reasoning(hybrid, job_text)
        # The semantic requirement audit determines qualification. Word overlap
        # remains inspectable diagnostics, not proof of minimum eligibility.
        hybrid["score"] = hybrid["qualification_score"] = assessment["score"]
        if projected_education:
            readiness_flags = json.loads(hybrid["readiness_flags"])
            if "degree_completion_pending" not in readiness_flags:
                readiness_flags.append("degree_completion_pending")
            hybrid["readiness_flags"] = json.dumps(readiness_flags, ensure_ascii=True)
            if hybrid["application_readiness"] == "ready":
                hybrid["application_readiness"] = "review"
        breakdown = json.loads(hybrid["score_breakdown"])
        breakdown.update({
            "similarity_composite": hybrid["composite_score"],
            "qualification_score": assessment["score"],
            "eligibility_status": assessment["eligibility_status"],
            "assessment_incomplete": assessment["assessment_incomplete"],
            "posting_source_url": job.get("detail_source_url"),
            "posting_fetched_at": job.get("detail_scraped_at"),
            "application_readiness": hybrid["application_readiness"],
            "readiness_flags": json.loads(hybrid["readiness_flags"]),
        })
        hybrid["composite_score"] = float(assessment["score"])
        hybrid["score_breakdown"] = json.dumps(breakdown, ensure_ascii=True)
        if requirement_report:
            hybrid["missing_skills"] = assessment["qualification_gaps"] or llm_result.get("missing_skills", "")
            reasoning = llm_result.get("reasoning", "")
        reasoning = f"Qualification {assessment['score']}/10; eligibility: {assessment['eligibility_status']}. " + reasoning
        risk_flags = str(llm_result.get("risk_flags", "") or "")
        action_reason = _build_action_reason(hybrid)
        if projected_education:
            action_reason = action_reason.replace("verified fit", "projected fit")
        normalized_mode = str(application_mode or "active").strip().casefold()
        if normalized_mode == "discovery_only":
            action_reason = (
                "Discovery only - do not apply until this market is activated and "
                "relocation timing is confirmed."
            )
        elif normalized_mode == "manual_review":
            action_reason = (
                "Manual review - verify market, schedule, source, and eligibility before applying."
            )
        return {
            **llm_result,
            **hybrid,
            **{key: value for key, value in assessment.items() if key not in {"score", "qualification_gaps"}},
            "matched_skills": llm_result.get("matched_skills", "") if requirement_report else hybrid.get("keyword_hits", ""),
            "risk_flags": risk_flags,
            "apply_or_skip_reason": action_reason,
            "reasoning": reasoning,
            "scoring_source_url": job.get("detail_source_url"),
        }
    except Exception as e:
        safe_error = redact_error_snippet(str(e), max_length=500) or type(e).__name__
        log.error("LLM error scoring job '%s': %s", job.get("title", "?"), safe_error)
        return {
            "score": 0,
            "qualification_score": 0,
            "application_readiness": "scoring_error",
            "readiness_flags": '["scoring_error"]',
            "llm_score": 0,
            "keyword_score": 0.0,
            "embedding_score": 0.0,
            "composite_score": 0.0,
            "score_breakdown": "",
            "matched_skills": "",
            "missing_skills": "",
            "keyword_hits": "",
            "risk_flags": "llm_error",
            "apply_or_skip_reason": "Skip until scoring succeeds.",
            "reasoning": f"LLM error: {safe_error}",
            "error": safe_error,
        }


def _score_retry_time(attempt: int, *, now: datetime) -> str:
    delay_seconds = min(
        BASE_SCORE_RETRY_SECONDS * (2 ** max(0, attempt - 1)),
        MAX_SCORE_RETRY_SECONDS,
    )
    return (now + timedelta(seconds=delay_seconds)).isoformat()


def _load_score_candidates(
    conn,
    *,
    target_url: str | None,
    rescore: bool,
    limit: int,
) -> list[dict]:
    if target_url:
        rows = conn.execute(
            "SELECT * FROM jobs WHERE url = ? "
            "AND archived_at IS NULL",
            (target_url,),
        ).fetchall()
    elif rescore:
        query = "SELECT * FROM jobs WHERE archived_at IS NULL AND COALESCE(availability_state, '') != 'closed'"
        if limit > 0:
            query += " LIMIT ?"
            rows = conn.execute(query, (limit,)).fetchall()
        else:
            rows = conn.execute(query).fetchall()
    else:
        rows = get_jobs_by_stage(conn=conn, stage="pending_score", limit=limit)

    if rows and not isinstance(rows[0], dict):
        columns = rows[0].keys()
        return [dict(zip(columns, row)) for row in rows]
    return rows


def _score_candidate(
    job: dict,
    *,
    resume_text: str,
    coursework_summary: str,
    coursework_skills_summary: str,
    search_config: dict,
    profile: dict,
    profile_evidence_context: str,
) -> dict:
    effective_config = effective_search_config(search_config, job)
    application_mode = resolved_application_mode(search_config, job)
    search_context = _build_search_evidence_context(search_config, job=job)
    profile_context = "\n".join(
        part for part in (profile_evidence_context, search_context) if part
    )
    result = score_job(
        resume_text,
        job,
        coursework_summary,
        coursework_skills_summary,
        profile_context,
        schedule_exception=job_has_schedule_exception(effective_config, job),
        application_mode=application_mode,
        preferred_schedule=str(effective_config.get("preferred_schedule") or "any"),
        require_part_time=bool(
            effective_config.get("require_part_time")
            or effective_config.get("customer_service_require_part_time")
        ),
        max_hours_per_week=(
            effective_config.get("max_hours_per_week")
            or effective_config.get("customer_service_max_hours_per_week")
        ),
        require_benefits=bool(effective_config.get("require_benefits")),
        source_verification=str(job.get("source_verification") or ""),
        employment_type=str(job.get("employment_type") or ""),
        relocation_needed=_relocation_needed_for_job(profile, job),
    )
    result["url"] = job["url"]
    result["prior_score_attempts"] = int(job.get("score_attempts") or 0)
    result["resolved_application_mode"] = application_mode
    return result


def _persist_score_results(conn, results: list[dict], *, now: str) -> None:
    # Some callers provide an existing database connection directly. Migrate
    # that connection before persisting the readiness fields so upgrades also
    # work outside the normal get_connection() path.
    ensure_columns(conn)
    for result in results:
        if result.get("error"):
            attempt = min(MAX_SCORE_ATTEMPTS, int(result.get("prior_score_attempts") or 0) + 1)
            conn.execute(
                """
                UPDATE jobs
                SET score_error = ?, score_attempts = ?, score_retry_at = ?,
                    fit_score = NULL, qualification_score = NULL, scoring_version = NULL,
                    application_mode = COALESCE(?, application_mode)
                WHERE url = ? AND archived_at IS NULL
                """,
                (
                    result["error"],
                    attempt,
                    _score_retry_time(attempt, now=datetime.fromisoformat(now)),
                    result.get("resolved_application_mode"),
                    result["url"],
                ),
            )
            continue
        conn.execute(
            """
            UPDATE jobs
            SET fit_score = ?,
                qualification_score = ?,
                application_readiness = ?,
                readiness_flags = ?,
                llm_score = ?,
                keyword_score = ?,
                embedding_score = ?,
                composite_score = ?,
                score_breakdown = ?,
                score_reasoning = ?,
                matched_skills = ?,
                missing_skills = ?,
                keyword_hits = ?,
                risk_flags = ?,
                apply_or_skip_reason = ?,
                scored_at = ?,
                score_error = NULL,
                score_attempts = 0,
                score_retry_at = NULL,
                application_mode = COALESCE(?, application_mode)
            WHERE url = ? AND archived_at IS NULL
            """,
            (
                result["score"],
                result.get("qualification_score", result["score"]),
                result.get("application_readiness", "review"),
                result.get("readiness_flags", "[]"),
                result.get("llm_score"),
                result.get("keyword_score"),
                result.get("embedding_score"),
                result.get("composite_score"),
                result.get("score_breakdown", ""),
                result["reasoning"],
                result.get("matched_skills", ""),
                result.get("missing_skills", ""),
                result.get("keyword_hits", ""),
                result.get("risk_flags", ""),
                result.get("apply_or_skip_reason", ""),
                now,
                result.get("resolved_application_mode"),
                result["url"],
            ),
        )
        if result.get("scoring_version"):
            conn.execute(
                "UPDATE jobs SET eligibility_status=?, requirements_assessment=?, "
                "scoring_version=?, scoring_input_hash=?, scoring_source_url=? WHERE url=? AND archived_at IS NULL",
                (result.get("eligibility_status"), result.get("requirements_assessment"),
                 result["scoring_version"], result.get("scoring_input_hash"), result.get("scoring_source_url"), result["url"]),
            )
    conn.commit()


def _score_distribution(conn) -> list[tuple[int, int]]:
    rows = conn.execute("""
        SELECT fit_score, COUNT(*) FROM jobs
        WHERE fit_score IS NOT NULL AND archived_at IS NULL
        GROUP BY fit_score ORDER BY fit_score DESC
    """).fetchall()
    return [(row[0], row[1]) for row in rows]


def _prune_scored_jobs(conn, prune_below: int) -> int:
    if prune_below <= 0:
        return 0
    pruned = delete_scored_jobs_at_or_below(prune_below, conn=conn, positive_only=True)
    if pruned:
        log.info("Auto-pruned %d jobs with fit_score <= %d", pruned, prune_below)
    return pruned


def run_scoring(
    limit: int = 0,
    rescore: bool = False,
    prune_below: int = 0,
    target_url: str | None = None,
    refresh: bool = True,
) -> dict:
    """Score unscored jobs that have full descriptions.

    Args:
        limit: Maximum number of jobs to score in this run.
        rescore: If True, re-read and score saved jobs (not just unscored ones).
        prune_below: If > 0, delete jobs with fit_score <= this value after scoring.
        target_url: If provided, score only this job URL.
        refresh: Internal optimization for a caller that just refreshed the page.

    Returns:
        {"scored": int, "errors": int, "elapsed": float, "distribution": list, "pruned": int}
    """
    profile = load_profile()
    resume_text = RESUME_PATH.read_text(encoding="utf-8")
    coursework_summary = "\n".join(profile.get("coursework_summary", []))
    coursework_skills_summary = "\n".join(profile.get("coursework_skills", []))
    search_config = load_search_config()
    scoring_assumptions = search_config.get("scoring_assumptions") or {}
    profile_evidence_context = _build_profile_evidence_context(
        profile,
        assume_completed_bachelors=bool(
            isinstance(scoring_assumptions, dict)
            and scoring_assumptions.get("assume_completed_bachelors")
        ),
    )
    conn = get_connection()
    jobs = _load_score_candidates(conn, target_url=target_url, rescore=rescore, limit=limit)

    if not jobs:
        log.info("No unscored jobs with descriptions found.")
        return {"scored": 0, "errors": 0, "elapsed": 0.0, "distribution": []}

    log.info("Reading employer postings and scoring %d jobs sequentially...", len(jobs))
    t0 = time.time()
    completed = 0
    errors = 0
    results: list[dict] = []

    for job in jobs:
        from divapply.job_health import refresh_job

        try:
            if refresh or not job.get("detail_source_url"):
                job = refresh_job(job, conn)
            if job.get("availability_state") == "closed":
                log.info("Skipping closed employer posting: %s", job.get("title", "?"))
                continue
        except Exception as exc:
            error = redact_error_snippet(str(exc), max_length=400) or type(exc).__name__
            log.warning("Employer page not scored: %s | %s", job.get("title", "?"), error)
            _persist_score_results(conn, [{"url": job["url"], "error": error,
                "prior_score_attempts": job.get("score_attempts", 0)}], now=datetime.now(timezone.utc).isoformat())
            conn.execute("UPDATE jobs SET detail_error=? WHERE url=? AND archived_at IS NULL", (error, job["url"]))
            conn.commit()
            errors += 1
            continue
        result = _score_candidate(
            job,
            resume_text=resume_text,
            coursework_summary=coursework_summary,
            coursework_skills_summary=coursework_skills_summary,
            search_config=search_config,
            profile=profile,
            profile_evidence_context=profile_evidence_context,
        )
        _persist_score_results(conn, [result], now=datetime.now(timezone.utc).isoformat())
        completed += 1

        if result.get("error"):
            errors += 1

        results.append(result)

        log.info(
            "[%d/%d] score=%s  %s",
            completed,
            len(jobs),
            "retry" if result.get("error") else result["score"],
            job.get("title", "?")[:60],
        )

    elapsed = time.time() - t0
    scored_count = sum(not result.get("error") for result in results)
    log.info(
        "Done: %d scored, %d retryable errors in %.1fs (%.1f jobs/sec)",
        scored_count,
        errors,
        elapsed,
        scored_count / elapsed if elapsed > 0 else 0,
    )

    distribution = _score_distribution(conn)
    pruned = _prune_scored_jobs(conn, prune_below)

    return {
        "scored": scored_count,
        "errors": errors,
        "elapsed": elapsed,
        "distribution": distribution,
        "pruned": pruned,
    }
