"""Job fit scoring: LLM-powered evaluation of candidate-job match quality.

Scores jobs on a 1-10 scale by comparing the user's resume against each
job description. All personal data is loaded at runtime from the user's
profile and resume file.
"""

import json
import logging
import re
import time
from datetime import datetime, timezone

from divapply.config import RESUME_PATH, load_profile
from divapply.database import get_connection, get_jobs_by_stage
from divapply.llm import get_client_for_stage

log = logging.getLogger(__name__)


# â”€â”€ Scoring Prompt â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

SCORE_PROMPT = """You are a neutral job fit evaluator. Read the candidate's resume and the job posting carefully, then score how well the candidate qualifies for this specific role on a 1-10 scale.

SCORING CRITERIA:
- 9-10: Direct match. The candidate clearly meets the title, duties, and minimum qualifications.
- 7-8: Strong match. Candidate meets most qualifications; minor gaps that experience or education could bridge.
- 5-6: Moderate match. Relevant background exists but meaningful gaps in required experience or credentials.
- 3-4: Weak match. Some transferable skills but significant gaps. Candidate could apply but is unlikely to be competitive.
- 1-2: Incompatible. Role requires specific licensure, certification, or field experience the candidate does not have and cannot substitute.

AUTOMATIC SCORE = 1 (do not evaluate further) if ANY of these are true â€” SCAM/JUNK SIGNALS:
- Job description is vague, generic, or could apply to any industry with no specific duties
- Company name is missing, hidden, or listed only as "Confidential" or "Our Client"
- No company website, physical address, or verifiable business presence mentioned
- Promises unusually high pay for minimal qualifications (e.g. "$50-100/hr, no experience needed")
- Application asks for SSN, bank account, or payment upfront before hiring
- Job is "work from home, set your own hours, unlimited earnings" style
- Recruiter-only posting where the actual employer is never named
- Job title/description is clearly a data harvesting scheme (brand ambassador, product tester, mystery shopper, chat agent, survey taker, social media evaluator, online rater)
- Job redirects to a third-party site asking to "create a profile" before any interview
- Multiple identical job postings from the same "company" with different salaries

QUALIFICATION MISMATCH:
- Required license, certification, clearance, or legal credential is clearly missing and cannot be substituted
- Job explicitly requires completed education or experience that the resume does not support
- Job requires field-specific experience that is absent from the resume

IMPORTANT NOTES:
- Judge based on the actual job description minimum qualifications, not job title alone.
- Do not favor or disfavor a job because it is IT, government, customer service, part-time, or any other job family.
- Do not artificially boost or suppress roles based on a presumed career path.
- If the posting explicitly accepts equivalent experience or an in-progress degree, count that only when the posting says so.
- Use only evidence from the resume and the job description.

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
        line = line.strip()
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


def score_job(
    resume_text: str,
    job: dict,
    coursework_summary: str = "",
    coursework_skills_summary: str = "",
) -> dict:
    """Score a single job against the resume.

    Args:
        resume_text: The candidate's full resume text.
        job: Job dict with keys: title, site, location, full_description.

    Returns:
        Structured scoring fields.
    """
    job_text = (
        f"TITLE: {job['title']}\n"
        f"COMPANY: {job['site']}\n"
        f"LOCATION: {job.get('location', 'N/A')}\n\n"
        f"DESCRIPTION:\n{(job.get('full_description') or '')[:3000]}"
    )

    coursework_block = coursework_summary.strip() or "N/A"
    coursework_skills_block = coursework_skills_summary.strip() or "N/A"
    messages = [
        {"role": "system", "content": SCORE_PROMPT},
        {"role": "user", "content": (
            f"RESUME:\n{resume_text}\n\n"
            f"ACADEMIC COURSEWORK (internal only, do not cite unless already in resume):\n{coursework_block}\n\n"
            f"COURSEWORK SKILL MAP (internal only, do not cite unless already in resume):\n{coursework_skills_block}\n\n"
            f"---\n\nJOB POSTING:\n{job_text}"
        )},
    ]

    try:
        client = get_client_for_stage("score")
        response = client.chat(messages, max_tokens=4096, temperature=0.1)
        return _parse_score_response(response)
    except Exception as e:
        log.error("LLM error scoring job '%s': %s", job.get("title", "?"), e)
        return {
            "score": 0,
            "matched_skills": "",
            "missing_skills": "",
            "keyword_hits": "",
            "risk_flags": "llm_error",
            "apply_or_skip_reason": "Skip until scoring succeeds.",
            "reasoning": f"LLM error: {e}",
        }


def run_scoring(limit: int = 0, rescore: bool = False, prune_below: int = 0) -> dict:
    """Score unscored jobs that have full descriptions.

    Args:
        limit: Maximum number of jobs to score in this run.
        rescore: If True, re-score all jobs (not just unscored ones).
        prune_below: If > 0, delete jobs with fit_score <= this value after scoring.

    Returns:
        {"scored": int, "errors": int, "elapsed": float, "distribution": list, "pruned": int}
    """
    profile = load_profile()
    resume_text = RESUME_PATH.read_text(encoding="utf-8")
    coursework_summary = "\n".join(profile.get("coursework_summary", []))
    coursework_skills_summary = "\n".join(profile.get("coursework_skills", []))
    conn = get_connection()

    if rescore:
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
        result = score_job(resume_text, job, coursework_summary, coursework_skills_summary)
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

