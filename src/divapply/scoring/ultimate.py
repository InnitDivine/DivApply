"""Ultimate resume generator: mash top-scoring jobs into one general-purpose resume.

Pulls the N highest-scored jobs from the database, extracts their keywords
and key requirements, then generates a single ATS-optimized resume that
covers as many of those roles as possible.

Usage (via CLI):
    DivApply ultimate              # top 10 jobs, default output
    DivApply ultimate --top 20     # use top 20 jobs
    DivApply ultimate --out ~/resume_ultimate.pdf
"""

import json
import logging
import time
from pathlib import Path

from divapply.config import (
    APP_DIR, RESUME_PATH, load_profile, load_env, ensure_dirs,
)
from divapply.database import get_connection, init_db
from divapply.llm import get_client_for_stage
from divapply.scoring.tailor import (
    _build_tailor_prompt,
    extract_json,
    _normalize_resume_json,
    assemble_resume_text,
    _enforce_one_page_shape as _tailor_one_page_shape,
    _sort_experience_recent_first,
)
from divapply.scoring.validator import BANNED_WORDS

log = logging.getLogger(__name__)

def _fetch_top_jobs(n: int = 10, min_score: int = 7) -> list[dict]:
    """Pull top-scored jobs from the DB, ordered by fit_score DESC."""
    conn = get_connection()
    rows = conn.execute(
        "SELECT title, site, location, fit_score, score_reasoning, full_description "
        "FROM jobs WHERE fit_score >= ? AND full_description IS NOT NULL "
        "ORDER BY discovered_at DESC, fit_score DESC LIMIT ?",
        (min_score, n),
    ).fetchall()
    if not rows:
        return []
    columns = rows[0].keys()
    return [dict(zip(columns, row)) for row in rows]

def _build_combined_job_brief(jobs: list[dict]) -> str:
    """Condense multiple job postings into a single brief for the LLM."""
    parts: list[str] = []
    seen_titles: set[str] = set()

    for job in jobs:
        title = job["title"]
        if title in seen_titles:
            continue
        seen_titles.add(title)

        # Extract keywords from score reasoning if available
        keywords = ""
        reasoning = job.get("score_reasoning") or ""
        if reasoning:
            # First line is usually keywords
            first_line = reasoning.split("\n")[0].strip()
            if first_line and not first_line.startswith("REASONING"):
                keywords = first_line

        desc_snippet = (job.get("full_description") or "")[:800]
        parts.append(
            f"--- JOB {len(parts) + 1}: {title} ({job.get('site', '?')}) "
            f"[score={job.get('fit_score', '?')}] ---\n"
            f"Keywords: {keywords}\n"
            f"Description excerpt:\n{desc_snippet}\n"
        )

    return "\n".join(parts)

ULTIMATE_SYSTEM_PROMPT = """You are a senior technical recruiter building a GENERAL-PURPOSE resume.

You are given a base resume and excerpts from {n_jobs} real job postings that scored highest
for this candidate. Your job: produce ONE resume that maximizes interview callbacks
across ALL of these roles simultaneously.

## STRATEGY:
- Identify the common threads across all job descriptions (recurring skills, keywords, duties)
- Weight the summary and skills toward the most-repeated requirements
- Every bullet should pull double duty: relevant to at least 2-3 of the target roles
- Front-load ATS keywords from the job descriptions into the skills section
- List experience entries from most recent to oldest.
- This is a GENERAL resume, not tailored to one job. It should work dropped into any of these postings.

## CONSTRAINTS:
{tailor_rules}

## OUTPUT: Return ONLY valid JSON. No markdown fences. No commentary.
Education is injected automatically by code -- do NOT include an education field.

{{"title":"Role Title","summary":"2-3 sentences covering the broadest fit.","skills":{{"Category":"skill1, skill2, ..."}},"experience":[{{"header":"Job Title","subtitle":"Company | Dates","bullets":["..."]}}],"projects":[{{"header":"Project","subtitle":"Tech | Date","bullets":["..."]}}]}}"""

def _enforce_one_page_shape(data: dict) -> dict:
    """Enforce one-page shape by trimming text length."""
    # Example: If total word count exceeds a limit, truncate
    total_word_count = sum(len(bullet.split()) for entry in data['experience'] for bullet in entry['bullets'])
    if total_word_count > 600:  # Set a max word count for one-page resumes
        # Trim or truncate experience and project sections
        data['experience'] = data['experience'][:3]  # Keep top 3 experiences
        for entry in data['experience']:
            entry['bullets'] = entry['bullets'][:2]  # Limit to 2 bullets per experience

    # Similarly, enforce skills and project section trimming
    data['projects'] = data['projects'][:1]  # Keep only the top project

    return data

def generate_ultimate_resume(
    top_n: int = 10,
    min_score: int = 7,
    output_dir: Path | None = None,
) -> dict:
    """Generate a general-purpose resume from top-scoring jobs.

    Args:
        top_n: Number of top jobs to pull from the DB.
        min_score: Minimum fit_score to include.
        output_dir: Where to write output files. Defaults to APP_DIR.

    Returns:
        {"text_path": str, "pdf_path": str | None, "jobs_used": int, "elapsed": float}
    """
    t0 = time.time()

    load_env()
    ensure_dirs()
    init_db()

    profile = load_profile()
    resume_text = RESUME_PATH.read_text(encoding="utf-8")

    # Fetch top jobs
    jobs = _fetch_top_jobs(n=top_n, min_score=min_score)
    if not jobs:
        raise RuntimeError(
            f"No jobs with score >= {min_score} found in the database. "
            "Run `divapply run score` first."
        )

    log.info("Building ultimate resume from %d jobs (scores %d-%d)",
             len(jobs), jobs[-1]["fit_score"], jobs[0]["fit_score"])

    # Build combined job brief
    job_brief = _build_combined_job_brief(jobs)

    # Build the tailor prompt base (has all the profile rules)
    tailor_rules = _build_tailor_prompt(profile)

    # Build the system prompt
    system = ULTIMATE_SYSTEM_PROMPT.format(
        n_jobs=len(jobs),
        tailor_rules=tailor_rules,
    )

    user_msg = (
        f"BASE RESUME:\n{resume_text}\n\n"
        f"{'=' * 60}\n"
        f"TARGET JOB POSTINGS (ranked by fit score):\n\n{job_brief}\n\n"
        f"Generate the ultimate general-purpose resume JSON:"
    )

    messages = [
        {"role": "system", "content": system},
        {"role": "user", "content": user_msg},
    ]

    client = get_client_for_stage("tailor")
    raw = client.chat(messages, max_tokens=2048, temperature=0.3)

    # Parse and assemble
    data = extract_json(raw)
    data = _normalize_resume_json(data)

    # Enforce one-page layout
    data = _tailor_one_page_shape(data)

    # Sort experience by date, latest job first
    if 'experience' in data:
        data['experience'] = _sort_experience_recent_first(data['experience'])

    text = assemble_resume_text(data, profile)

    # Write outputs
    out_dir = output_dir or APP_DIR
    txt_path = out_dir / "ultimate_resume.txt"
    txt_path.write_text(text, encoding="utf-8")

    # Generate PDF
    pdf_path = None
    try:
        from divapply.scoring.pdf import convert_to_pdf
        pdf_result = convert_to_pdf(txt_path, output_path=out_dir / "ultimate_resume.pdf")
        pdf_path = str(pdf_result)
    except Exception as e:
        log.warning("PDF generation failed (install playwright?): %s", e)

    elapsed = time.time() - t0
    log.info("Ultimate resume generated in %.1fs: %s", elapsed, txt_path)

    return {
        "text_path": str(txt_path),
        "pdf_path": pdf_path,
        "jobs_used": len(jobs),
        "elapsed": elapsed,
    }

