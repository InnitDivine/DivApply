"""Job fit scoring: hybrid evaluation of candidate-job match quality.

Scores jobs on a 1-10 scale by blending keyword hit-rate, local hashed
embedding similarity, and the LLM evaluator. All personal data is loaded at
runtime from the user's profile and resume file.
"""

import logging
import re
import time
from datetime import datetime, timezone

from divapply.config import RESUME_PATH, load_profile, load_search_config, profile_skills
from divapply.database import get_connection, get_jobs_by_stage
from divapply.llm import get_client_for_stage
from divapply.scoring.composite import composite_score
from divapply.scoring.context import format_job_context

log = logging.getLogger(__name__)

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
- When verified profile facts and active search filters state schedule limits or preferred role type, treat those as job-fit evidence.
- Do not reward or penalize any job family, industry, employer type, or schedule type unless active search filters or verified profile facts make it relevant.
- Use general role sense only to interpret common requirements, not to invent unstated requirements.
- Transferable experience counts when duties, tools, domain knowledge, education, or coursework reasonably map to the job's work.
- When a posting says equivalent experience is accepted, evaluate verified duties and task summaries, not just exact titles.
- For entry-level, low-hour, student, customer service, cashier, front desk, office assistant, data entry, library, recreation, retail, or food service roles, do not require the same prior job title or exact industry/tool when the candidate has verified transferable public-facing service, records, payments, scheduling, data entry, or administrative experience.
- Non-substitutable requirements such as licenses, clearances, legal credentials, completed degrees, or certifications must be treated as hard gaps when the posting requires them.
- Preferred/nice-to-have certifications, tools, degrees, or licenses are not hard gaps. Treat them as small tie-breakers after required qualifications.
- Coursework and in-progress education can support skills, exposure, and student eligibility. They do not prove completed degrees, completed certificates, licensure, employment history, or professional years of experience.
- If search filters require part-time but verified search context marks a referral or priority-employer exception, do not penalize a full-time posting solely for schedule. Still penalize real conflicts and missing required qualifications.

SCORING CRITERIA:
- 9-10: Direct match. The candidate clearly meets the title, duties, and minimum qualifications.
- 7-8: Strong match. Candidate meets most qualifications; minor gaps that experience or education could bridge. For low-hour/student searches, this includes easy part-time roles that match search filters, location, and transferable customer service/admin skills.
- 5-6: Moderate match. Relevant background exists but meaningful gaps in required experience, credentials, schedule, or stated search preferences.
- 3-4: Weak match. Some transferable skills but significant gaps. Candidate could apply but is unlikely to be competitive.
- 1-2: Incompatible. Role requires specific licensure, certification, or field experience the candidate does not have and cannot substitute.

AUTOMATIC SCORE = 1 (do not evaluate further) only for clear SCAM/JUNK SIGNALS:
- Job description is vague, generic, or could apply to any industry with no specific duties
- Company name is missing, hidden, or listed only as "Confidential" or "Our Client"
- No company website, physical address, or verifiable business presence mentioned
- Promises unusually high pay for minimal qualifications (e.g. "$50-100/hr, no experience needed")
- Application asks for SSN, bank account, or payment upfront before hiring
- Job is "work from home, set your own hours, unlimited earnings" style AND also lacks concrete duties or a verifiable employer
- Recruiter-only posting where the actual employer is never named
- Job title/description is clearly a data harvesting scheme (brand ambassador, product tester, mystery shopper, chat agent, survey taker, social media evaluator, online rater) with no concrete employer, duties, or screening process
- Job redirects to a third-party site asking to "create a profile" before any interview
- Multiple identical job postings from the same "company" with different salaries
- Do not penalize legitimate remote, flexible, part-time, entry-level, customer-facing, sales, support, or field roles for category alone.

QUALIFICATION MISMATCH:
- Required license, certification, clearance, or legal credential is clearly missing and cannot be substituted
- Job explicitly requires completed education or experience that the resume does not support
- Job requires field-specific experience that is absent from the resume
- Missing preferred-only certifications or nice-to-have tools should lower confidence only slightly, not force a low score.

IMPORTANT NOTES:
- Judge based on the actual job description minimum qualifications, not job title alone.
- Do not favor or disfavor a job because it is IT, government, customer service, part-time, or any other job family unless the verified profile facts identify it as a current target.
- Do not artificially boost or suppress roles based on a presumed career path; use active search queries and filters instead.
- If the posting explicitly accepts equivalent experience or an in-progress degree, count that only when the posting says so.
- Separate "required/minimum/must have" from "preferred/nice to have/bonus/plus"; required gaps matter much more.
- For entry-level part-time roles with no hard credential/license gap, no schedule conflict, and an APPLY recommendation, avoid scoring below 6 solely because the candidate lacks exact same-title experience.
- For referral or priority-employer exceptions, score full-time roles on qualifications and location unless the profile states a hard availability conflict.
- Use only evidence from the resume, verified profile facts, profile-safe coursework summary, and the job description.

RESPOND IN EXACTLY THIS FORMAT (no other text):
FIT_SCORE: [1-10]
MATCHED_SKILLS: [comma-separated verified candidate skills that match this job]
MISSING_SKILLS: [comma-separated important requirements not supported by the resume/coursework, or "none"]
KEYWORD_HITS: [comma-separated job-description keywords that are truthfully supported]
RISK_FLAGS: [comma-separated concerns like scam, license gap, location, low detail, or "none"]
APPLY_OR_SKIP_REASON: [one short human-readable apply/skip reason]
SCORE_REASONING: [1-2 sentences explaining the score]"""


def _parse_score_response(response: str) -> dict:
    """Parse the LLM's score response into structured data.

    Args:
        response: Raw LLM response text.

    Returns:
        Structured scoring fields ready for database storage.
    """
    score = 0
    fields = {
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
            try:
                score = int(re.search(r"\d+", line).group())
                score = max(1, min(10, score))
            except (AttributeError, ValueError):
                score = 0
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


def _build_profile_evidence_context(profile: dict) -> str:
    """Build scoring-safe profile facts without credentials or EEO data."""
    lines: list[str] = []

    personal = profile.get("personal", {})
    city = personal.get("city")
    state = personal.get("province_state")
    if city or state:
        lines.append(f"Location: {', '.join(part for part in (city, state) if part)}")

    exp = profile.get("experience", {})
    for key in (
        "years_of_experience_it",
        "years_of_experience_government",
        "education_level",
        "education_detail",
    ):
        if exp.get(key):
            lines.append(f"{key.replace('_', ' ').title()}: {exp[key]}")

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

    for job in profile.get("work_history", []) or []:
        if not isinstance(job, dict):
            continue
        parts = [
            job.get("title"),
            job.get("company"),
            job.get("dates"),
            job.get("tasks") or job.get("description"),
        ]
        lines.append("Work history: " + " | ".join(str(part) for part in parts if part))

    lines.append(f"Experience inference guidance: {EXPERIENCE_INFERENCE_GUIDANCE}")

    for category, items in profile_skills(profile).items():
        if items:
            label = category.replace("_", " ").title()
            lines.append(f"{label}: {', '.join(str(item) for item in items)}")

    for school in profile.get("education_schools", []) or []:
        if not isinstance(school, dict):
            continue
        profile_status = str(school.get("status", "")).strip().lower()
        if profile_status in {"transferred", "transfer"}:
            status = "transferred"
        elif school.get("degree_received"):
            status = "completed"
        elif str(school.get("end_year", "")).lower() == "present":
            status = "in progress"
        else:
            status = "not completed"
        parts = [
            school.get("school"),
            school.get("degree"),
            school.get("major"),
            status,
            f"GPA {school.get('gpa')}" if school.get("gpa") else "",
            school.get("notes"),
        ]
        lines.append("Education: " + " | ".join(str(part) for part in parts if part))

    for cert in profile.get("certifications", []) or []:
        if not isinstance(cert, dict):
            continue
        parts = [cert.get("name"), cert.get("issuer"), cert.get("status"), f"expires {cert.get('expires')}" if cert.get("expires") else ""]
        lines.append("Certification/training: " + " | ".join(str(part) for part in parts if part))

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


def _build_search_evidence_context(search_config: dict) -> str:
    """Build scoring-safe search constraints from searches.yaml."""
    lines: list[str] = []
    if search_config.get("require_part_time") or search_config.get("customer_service_require_part_time"):
        lines.append("Search schedule filter: part-time roles required")
    max_hours = search_config.get("customer_service_max_hours_per_week") or search_config.get("max_hours_per_week")
    if max_hours:
        lines.append(f"Search max hours per week: {max_hours}")
    queries = search_config.get("queries")
    if isinstance(queries, list):
        query_terms = [str(item.get("query") or "").strip() for item in queries if isinstance(item, dict)]
        if query_terms:
            lines.append("Search queries: " + "; ".join(query_terms[:20]))
    locations = search_config.get("locations")
    if isinstance(locations, list):
        loc_terms = [str(item.get("location") or "").strip() for item in locations if isinstance(item, dict)]
        if loc_terms:
            lines.append("Search locations: " + "; ".join(loc_terms))
    exception_terms: list[str] = []
    for key in (
        "schedule_exception_employers",
        "referral_employers",
        "priority_employers",
        "employer_priority",
    ):
        value = search_config.get(key)
        if isinstance(value, list):
            for item in value:
                if isinstance(item, dict):
                    text = str(item.get("name") or item.get("employer") or "").strip()
                else:
                    text = str(item).strip()
                if text:
                    exception_terms.append(text)
        elif isinstance(value, dict):
            exception_terms.extend(str(item.get("name") or name).strip() for name, item in value.items())
        elif isinstance(value, str) and value.strip():
            exception_terms.append(value.strip())
    if exception_terms:
        unique = list(dict.fromkeys(exception_terms))
        lines.append(
            "Referral/priority employer schedule exception: "
            + "; ".join(unique[:20])
            + " may be scored without the part-time-only penalty."
        )
    return "\n".join(lines)


def score_job(
    resume_text: str,
    job: dict,
    coursework_summary: str = "",
    coursework_skills_summary: str = "",
    profile_context: str = "",
) -> dict:
    """Score a single job against the resume.

    Args:
        resume_text: The candidate's full resume text.
        job: Job dict with keys: title, site, location, full_description.

    Returns:
        Structured scoring fields.
    """
    job_text = format_job_context(job, description_limit=3000)

    coursework_block = coursework_summary.strip() or "N/A"
    coursework_skills_block = coursework_skills_summary.strip() or "N/A"
    profile_block = profile_context.strip() or "N/A"
    evidence_text = "\n\n".join(
        part for part in (resume_text, profile_block, coursework_block, coursework_skills_block)
        if part and part != "N/A"
    )
    messages = [
        {"role": "system", "content": SCORE_PROMPT},
        {"role": "user", "content": (
            f"RESUME:\n{resume_text}\n\n"
            f"VERIFIED PROFILE FACTS (safe scoring context; do not treat in-progress credentials as completed):\n{profile_block}\n\n"
            f"ACADEMIC COURSEWORK (internal only, do not cite unless already in resume):\n{coursework_block}\n\n"
            f"COURSEWORK SKILL MAP (internal only, do not cite unless already in resume):\n{coursework_skills_block}\n\n"
            f"---\n\nJOB POSTING:\n{job_text}"
        )},
    ]

    try:
        client = get_client_for_stage("score")
        response = client.chat(messages, max_tokens=4096, temperature=0.1)
        llm_result = _parse_score_response(response)
        hybrid = composite_score(
            job_description=job_text,
            resume_text=evidence_text,
            llm_result=llm_result,
        )
        return {
            **llm_result,
            **hybrid,
            "matched_skills": llm_result.get("matched_skills", ""),
            "risk_flags": llm_result.get("risk_flags", ""),
            "apply_or_skip_reason": llm_result.get("apply_or_skip_reason", ""),
            "reasoning": llm_result.get("reasoning", ""),
        }
    except Exception as e:
        log.error("LLM error scoring job '%s': %s", job.get("title", "?"), e)
        return {
            "score": 0,
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
            "reasoning": f"LLM error: {e}",
        }


def run_scoring(
    limit: int = 0,
    rescore: bool = False,
    prune_below: int = 0,
    target_url: str | None = None,
) -> dict:
    """Score unscored jobs that have full descriptions.

    Args:
        limit: Maximum number of jobs to score in this run.
        rescore: If True, re-score all jobs (not just unscored ones).
        prune_below: If > 0, delete jobs with fit_score <= this value after scoring.
        target_url: If provided, score only this job URL.

    Returns:
        {"scored": int, "errors": int, "elapsed": float, "distribution": list, "pruned": int}
    """
    profile = load_profile()
    resume_text = RESUME_PATH.read_text(encoding="utf-8")
    coursework_summary = "\n".join(profile.get("coursework_summary", []))
    coursework_skills_summary = "\n".join(profile.get("coursework_skills", []))
    search_context = _build_search_evidence_context(load_search_config())
    profile_context = "\n".join(part for part in (_build_profile_evidence_context(profile), search_context) if part)
    conn = get_connection()

    if target_url:
        jobs = conn.execute(
            "SELECT * FROM jobs WHERE url = ? AND full_description IS NOT NULL",
            (target_url,),
        ).fetchall()
    elif rescore:
        query = "SELECT * FROM jobs WHERE full_description IS NOT NULL"
        if limit > 0:
            query += " LIMIT ?"
            jobs = conn.execute(query, (limit,)).fetchall()
        else:
            jobs = conn.execute(query).fetchall()
    else:
        jobs = get_jobs_by_stage(conn=conn, stage="pending_score", limit=limit)

    if not jobs:
        log.info("No unscored jobs with descriptions found.")
        return {"scored": 0, "errors": 0, "elapsed": 0.0, "distribution": []}

    # Convert sqlite3.Row to dicts if needed
    if jobs and not isinstance(jobs[0], dict):
        columns = jobs[0].keys()
        jobs = [dict(zip(columns, row)) for row in jobs]

    log.info("Scoring %d jobs sequentially...", len(jobs))
    t0 = time.time()
    completed = 0
    errors = 0
    results: list[dict] = []

    for job in jobs:
        result = score_job(
            resume_text,
            job,
            coursework_summary,
            coursework_skills_summary,
            profile_context,
        )
        result["url"] = job["url"]
        completed += 1

        if result["score"] == 0:
            errors += 1

        results.append(result)

        log.info(
            "[%d/%d] score=%d  %s",
            completed, len(jobs), result["score"], job.get("title", "?")[:60],
        )

    # Write scores to DB
    now = datetime.now(timezone.utc).isoformat()
    for r in results:
        conn.execute(
            """
            UPDATE jobs
            SET fit_score = ?,
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
                scored_at = ?
            WHERE url = ?
            """,
            (
                r["score"],
                r.get("llm_score"),
                r.get("keyword_score"),
                r.get("embedding_score"),
                r.get("composite_score"),
                r.get("score_breakdown", ""),
                r["reasoning"],
                r.get("matched_skills", ""),
                r.get("missing_skills", ""),
                r.get("keyword_hits", ""),
                r.get("risk_flags", ""),
                r.get("apply_or_skip_reason", ""),
                now,
                r["url"],
            ),
        )
    conn.commit()

    elapsed = time.time() - t0
    log.info("Done: %d scored in %.1fs (%.1f jobs/sec)", len(results), elapsed, len(results) / elapsed if elapsed > 0 else 0)

    # Score distribution
    dist = conn.execute("""
        SELECT fit_score, COUNT(*) FROM jobs
        WHERE fit_score IS NOT NULL
        GROUP BY fit_score ORDER BY fit_score DESC
    """).fetchall()
    distribution = [(row[0], row[1]) for row in dist]

    # Auto-prune low-score jobs if requested
    pruned = 0
    if prune_below > 0:
        cursor = conn.execute(
            "DELETE FROM jobs WHERE fit_score IS NOT NULL AND fit_score > 0 AND fit_score <= ?",
            (prune_below,),
        )
        pruned = cursor.rowcount
        conn.commit()
        if pruned:
            log.info("Auto-pruned %d jobs with fit_score <= %d", pruned, prune_below)

    return {
        "scored": len(results),
        "errors": errors,
        "elapsed": elapsed,
        "distribution": distribution,
        "pruned": pruned,
    }
