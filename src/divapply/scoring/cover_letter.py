"""Cover letter generation: LLM-powered, profile-driven, with validation.

Generates concise, engineering-voice cover letters tailored to specific job
postings. All personal data (name, skills, achievements) comes from the user's
profile at runtime. No hardcoded personal information.
"""

import logging
import re
import time
from datetime import datetime, timezone
from pathlib import Path

from divapply.artifacts import cover_letter_artifact_path
from divapply.config import (
    COVER_LETTER_DIR,
    TAILORED_DIR,
    load_profile,
    profile_for_job_resume_location,
    profile_skills,
)
from divapply.database import (
    ACTIONABLE_JOB_SQL,
    MEANINGFUL_FULL_DESCRIPTION_SQL,
    get_connection,
    get_jobs_by_stage,
)
from divapply.llm import get_client_for_stage
from divapply.scoring.context import format_job_context
from divapply.scoring.validator import (
    BANNED_WORDS,
    LLM_LEAK_PHRASES,
    sanitize_text,
    validate_cover_letter,
)
from divapply.security import _is_link_or_reparse, protect_file

log = logging.getLogger(__name__)

MAX_ATTEMPTS = 5  # max cross-run retries before giving up
MAX_TAILORED_ARTIFACT_BYTES = 10 * 1024 * 1024
MAX_TAILORED_PDF_PAGES = 4


def _recorded_missing_skills(job: dict) -> list[str]:
    """Return bounded persisted evidence gaps for document-generation guards."""
    raw = job.get("missing_skills")
    if isinstance(raw, list):
        items = raw
    else:
        items = re.split(r"[,;|\n]", str(raw or ""))
    return [" ".join(str(item).split()) for item in items if str(item).strip()][:12]


class CoverLetterValidationError(RuntimeError):
    """Raised when every generated draft fails the selected validator mode."""

    def __init__(self, errors: list[str]):
        self.errors = list(errors)
        super().__init__("Cover letter validation failed after all retries: " + "; ".join(errors))


def _delete_temp_artifact(path) -> None:
    """Delete an intermediate generated text file after PDF creation."""
    try:
        resolved = path.resolve()
        root = COVER_LETTER_DIR.resolve()
        if not resolved.is_relative_to(root):
            log.warning("Refusing to delete artifact outside cover letter directory: %s", path)
            return
        if path.suffix != ".txt" or not path.name.endswith("_CL.txt"):
            log.warning("Refusing to delete unexpected cover letter artifact: %s", path)
            return
        if path.exists() or path.is_symlink():
            path.unlink()
    except OSError:
        log.warning("Could not delete temporary generated artifact: %s", path)


def _delete_unpersisted_artifact(path_value: str | None) -> None:
    """Remove an output created after its job was concurrently archived."""
    if not path_value:
        return
    path = Path(path_value)
    try:
        if not path.resolve().is_relative_to(COVER_LETTER_DIR.resolve()):
            log.warning("Refusing to delete output outside cover letter directory: %s", path)
            return
        if path.suffix.casefold() not in {".txt", ".pdf"}:
            return
        if path.exists() or path.is_symlink():
            path.unlink()
    except OSError:
        log.warning("Could not delete unpersisted cover artifact: %s", path)


# â”€â”€ Prompt Builder (profile-driven) â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€


def _drop_mixed_paid_setting_sentences(text: str) -> str:
    """Remove sentences that ambiguously combine City and County evidence."""
    cleaned_blocks: list[str] = []
    removed = 0
    for block in re.split(r"\n{2,}", text.strip()):
        kept: list[str] = []
        for sentence in re.split(r"(?<=[.!?])\s+", block.strip()):
            lowered = sentence.casefold()
            has_city_setting = bool(re.search(r"\b(?:city|municipal|front[ -]desk)\b", lowered))
            has_county_setting = bool(re.search(r"\bcounty\b", lowered))
            if has_city_setting and has_county_setting:
                removed += 1
                continue
            if sentence.strip():
                kept.append(sentence.strip())
        if kept:
            cleaned_blocks.append(" ".join(kept))
    if removed:
        log.debug("Removed %d ambiguous mixed-paid-setting sentence(s) before validation.", removed)
    return "\n\n".join(cleaned_blocks)


def _repair_unanchored_zero_it_closing(text: str, job: dict, profile: dict) -> str:
    """Replace employer-specific closing overclaims with a truthful next-step statement."""
    professional_it_years = str(
        (profile.get("experience") or {}).get("years_of_professional_it_experience", "")
    ).strip().casefold()
    company = str(job.get("company") or job.get("site") or "").strip()
    if professional_it_years not in {"0", "0.0", "none"} or not company:
        return text
    pattern = re.compile(
        rf"(?P<prefix>\b{re.escape(company)}(?:'s|’s)?\b[^.!?]*?)\s+"
        r"(?:fits|matches|aligns with)\s+(?=[^.!?]*(?:\bi\b|\bmy\b))[^.!?]*[.!?]",
        re.IGNORECASE,
    )
    return pattern.sub(
        lambda match: (
            match.group("prefix").rstrip()
            + " is a practical next step for my home-lab and training foundation."
        ),
        text,
    )


def _drop_ambiguous_zero_it_bridge_sentences(text: str, profile: dict) -> str:
    """Remove vague pronoun bridges from mixed evidence to hands-on IT duties."""
    professional_it_years = str(
        (profile.get("experience") or {}).get("years_of_professional_it_experience", "")
    ).strip().casefold()
    if professional_it_years not in {"0", "0.0", "none"}:
        return text
    blocks: list[str] = []
    for block in re.split(r"\n{2,}", text.strip()):
        kept: list[str] = []
        for sentence in re.split(r"(?<=[.!?])\s+", block.strip()):
            lowered = sentence.casefold()
            bridge = re.search(
                r"\b(?:(?:those|these|both) (?:settings|contexts|roles|experiences)|(?:that|this) mix)\b",
                lowered,
            )
            it_duty = re.search(
                r"\b(?:it support|windows|hardware|network(?:ing| troubleshooting)?|device support|"
                r"ticket resolution|troubleshoot\w*)\b",
                lowered,
            )
            if bridge and it_duty:
                continue
            if sentence.strip():
                kept.append(sentence.strip())
        if kept:
            blocks.append(" ".join(kept))
    return "\n\n".join(blocks)


def _build_cover_letter_prompt(profile: dict) -> str:
    """Build the cover letter system prompt from the user's profile.

    All personal data, skills, and sign-off name come from the profile.
    """
    personal = profile.get("personal", {})
    resume_facts = profile.get("resume_facts", {})

    # Preferred name for the sign-off (falls back to full name)
    sign_off_name = personal.get("preferred_name") or personal.get("full_name", "")

    # Flatten all allowed skills
    all_skills: list[str] = []
    for items in profile_skills(profile).values():
        all_skills.extend(items)
    skills_str = ", ".join(all_skills) if all_skills else "the tools listed in the resume"

    # Real metrics from resume_facts
    real_metrics = resume_facts.get("real_metrics", [])
    coursework = profile.get("coursework_summary", [])
    coursework_skills = profile.get("coursework_skills", [])

    # Build achievement examples for the prompt
    metrics_hint = ""
    if real_metrics:
        metrics_hint = f"\nReal metrics to use: {', '.join(real_metrics)}"

    coursework_hint = ""
    if coursework:
        coursework_hint = (
            "\nAcademic coursework (internal only, do not cite unless already on the resume):\n"
            + "\n".join(f"- {item}" for item in coursework[:12])
        )

    coursework_skills_hint = ""
    if coursework_skills:
        coursework_skills_hint = (
            "\nAcademic skill map (internal only, do not cite unless already on the resume):\n"
            + "\n".join(f"- {item}" for item in coursework_skills[:12])
        )

    # Build the full banned list from the validator so the prompt stays in sync
    # with what will actually be rejected â€” the validator checks all of these.
    all_banned = ", ".join(f'"{w}"' for w in BANNED_WORDS)
    leak_banned = ", ".join(f'"{p}"' for p in LLM_LEAK_PHRASES)

    return f"""Write a cover letter for {sign_off_name}. The goal is to get an interview.

STRUCTURE: 3 short paragraphs. Under 250 words. Every sentence must earn its place.
- Output exactly three body paragraphs separated by blank lines, plus the salutation and sign-off as their own blocks.

PARAGRAPH 1 (2-3 sentences): Open with the strongest verified fact from the candidate's background that directly matches the job. Use the same rule for every role.

PARAGRAPH 2 (3-4 sentences): Pick 2 achievements from the resume that are MOST relevant to THIS job. Use numbers when available. Frame as solving their problem, not listing your accomplishments.{metrics_hint}
{coursework_hint}
{coursework_skills_hint}

PARAGRAPH 3 (1-2 sentences): Reference one specific thing about the company or role from the job description. Then close: "Happy to walk through any of this in more detail." or "Let's discuss." Nothing else.
- Name the exact target job title once in the letter.

JOB DESCRIPTION ACCURACY:
- Use the job description as evidence, not decoration. Mention a company, duty, requirement, or team detail only if it appears in TARGET JOB.
- If VERIFIED EXTRA CONTEXT is present, you may use it briefly, but do not quote or invent referral details beyond that text.
- Never mention logins, passwords, tokens, private credentials, or application-site automation.

EXPERIENCE AND AVAILABILITY BOUNDARY:
- Transferable experience is not the same as prior target-role employment. Name the real setting and say how its duties map.
- Do not relabel front-desk work as IT support, healthcare work, field support, ticket handling, onboarding/offboarding, or user-access administration unless the source resume explicitly says that happened there.
- Municipal public-facing service is not patient-facing healthcare service. Never merge those contexts.
- Residents, members, visitors, and public-counter customers are not software clients. Do not call that verified work "client-facing" unless the source résumé explicitly does.
- Do not claim phone, call, email, chat, training, or follow-up experience unless that channel/duty is explicit in the source résumé. A missing target duty may be framed only as a transferable next step, never as work already done.
- Do not say the candidate has solved "the same problems from both sides". Name the distinct public-service and project evidence without equating their contexts.
- Home-lab and project work may prove practical exposure, but never call it paid or professional IT employment.
- Copy education, certificate-program, and training names exactly from candidate evidence. Never turn the target job title into the name of training, coursework, a program, or a credential.
- Use project-specific facts only when the project anchor and those tools/duties appear together in RESUME. The general allowed-skills list is not evidence that a tool belonged to a named project. Never merge separate projects.
- Keep device, computer, and network experience from home-lab projects separate from paid municipal or accounting roles.
- In every sentence, name the setting that proves an IT skill. Do not join Windows, Microsoft 365, end-user, or technical-question claims to municipal, county, front-desk, or generic customer-service experience.
- Never say a list of IT skills was used "across" paid/public-sector and lab/project settings. Attribute paid-work evidence and home-lab/training evidence in separate clauses or sentences.
- When professional IT experience is zero, never put a paid/public-sector setting and a home-lab/project setting in the same sentence as an IT skill. Use separate sentences so each skill has one unambiguous evidence source.
- When professional IT experience is zero, name the lab, project, coursework, or training before the first hands-on IT skill in every candidate-experience sentence.
- Never use "those settings", "these roles", "that mix", or a similar pronoun bridge to map multiple paid/project contexts to IT duties.
- A company or client-sector list is company context, not candidate experience. Never imply the candidate worked in every sector the target employer serves; state only candidate sectors directly supported by RESUME.
- Keep each paid employer or paid-work setting in its own sentence. Never combine duties from municipal/city and county roles under one shared verb or requirement list.
- Do not say the candidate is already doing the target job, works in the same professional environment, or has target-industry tenure when only transferable duties map.
- When professional IT experience is zero, never say the candidate has already done IT work "in the field"; identify home-lab/project and transferable paid-work contexts separately.
- When professional IT experience is zero, do not claim a general "background in end-user support". Name public-service issue routing and home-lab troubleshooting as separate evidence.
- Do not promise relocation, commute, immediate on-site presence, or schedule availability unless the verified profile explicitly confirms it. State that the candidate can discuss the requirement instead.

BANNED WORDS AND PHRASES (automated validator rejects ANY of these â€” do not use even once):
{all_banned}

ALSO BANNED (meta-commentary the validator catches):
{leak_banned}

BANNED PUNCTUATION: No em dashes (â€”) or en dashes (â€“). Use commas or periods.

VOICE:
- Write like a real professional emailing someone they respect. Not formal, not casual. Just direct.
- Avoid stock cover-letter openings like "I am writing to express my interest" or "I am excited to apply."
- NEVER narrate or explain what you're doing. BAD: "This demonstrates my commitment to X." GOOD: Just state the fact.
- NEVER hedge. BAD: "might address some of your challenges." GOOD: "solves the same problem."
- Prefer concrete facts over generalities. If a sentence does not add useful information, cut it.
- Only mention projects or tools that are directly relevant to the job.

FABRICATION = INSTANT REJECTION:
The candidate's real tools are ONLY: {skills_str}.
Do NOT mention ANY tool not in this list. If the job asks for tools not listed, talk about the work, not the tools.

Sign off: just "{sign_off_name}"

Output ONLY the letter text. No subject lines. No "Here is the cover letter:" preamble. No notes after the sign-off.
Start DIRECTLY with "Dear Hiring Manager," and end with the name. Do not repeat the candidate's name immediately after the salutation."""


# â”€â”€ Helpers â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€


def _strip_preamble(text: str) -> str:
    """Remove LLM preamble before 'Dear Hiring Manager,' if present.

    Gemini and other models sometimes output "Here is the cover letter:" or
    similar meta-commentary before the actual letter text. Strip everything
    before the first occurrence of "Dear" so the validator's start-check passes.
    """
    lowered = text.lower()
    dear_idx = lowered.find("dear hiring manager")
    if dear_idx == -1:
        dear_idx = lowered.find("dear")
    if dear_idx > 0:
        return text[dear_idx:]
    return text


def _ensure_exact_target_title_once(text: str, job: dict) -> str:
    """Insert or deduplicate the exact title without changing candidate claims."""
    title = " ".join(str(job.get("title") or "").split())
    if not title:
        return text
    pattern = re.compile(
        r"(?<!\w)" + r"\s+".join(re.escape(part) for part in title.split()) + r"(?!\w)",
        re.IGNORECASE,
    )
    matches = list(pattern.finditer(text))
    if matches:
        repaired = text
        for match in reversed(matches[1:]):
            repaired = repaired[: match.start()] + "the role" + repaired[match.end() :]
        return repaired

    blocks = [block.strip() for block in re.split(r"\n{2,}", text.strip()) if block.strip()]
    if len(blocks) < 3:
        return text
    blocks[1] = f"I am applying for the {title} position. {blocks[1]}"
    return "\n\n".join(blocks)


def _read_tailored_resume_text(job: dict) -> str:
    """Read only the exact persisted, owned tailored-resume artifact."""
    raw_path = str(job.get("tailored_resume_path") or "").strip()
    if not raw_path:
        raise ValueError("Tailored resume artifact is required for cover generation.")
    path = Path(raw_path).expanduser()
    if _is_link_or_reparse(path):
        raise ValueError("Tailored resume artifact must not be a link or reparse point.")
    if not path.is_file():
        raise FileNotFoundError("Tailored resume artifact is missing.")
    resolved = path.resolve(strict=True)
    if not resolved.is_relative_to(TAILORED_DIR.resolve()):
        raise ValueError("Tailored resume artifact is outside the owned output directory.")
    if resolved.stat().st_size > MAX_TAILORED_ARTIFACT_BYTES:
        raise ValueError("Tailored resume artifact exceeds the safe size limit.")

    suffix = resolved.suffix.casefold()
    if suffix == ".txt":
        text = resolved.read_text(encoding="utf-8")
    elif suffix == ".pdf":
        from pypdf import PdfReader

        reader = PdfReader(str(resolved))
        if len(reader.pages) > MAX_TAILORED_PDF_PAGES:
            raise ValueError("Tailored resume PDF exceeds the safe page limit.")
        text = "\n".join(page.extract_text() or "" for page in reader.pages)
    else:
        raise ValueError("Tailored resume artifact must be TXT or PDF.")
    text = text.strip()
    if not text:
        raise ValueError("Tailored resume artifact contains no extractable text.")
    return text


# â”€â”€ Core Generation â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€


def generate_cover_letter(
    resume_text: str,
    job: dict,
    profile: dict,
    max_retries: int = 3,
    validation_mode: str = "normal",
) -> str:
    """Generate a cover letter with fresh context on each retry + auto-sanitize.

    Same design as tailor_resume: fresh conversation per attempt, issues noted
    in the prompt, no conversation history stacking.

    Args:
        resume_text:      The candidate's resume text (base or tailored).
        job:              Job dict with title, site, location, full_description.
        profile:          User profile dict.
        max_retries:      Maximum retry attempts.
        validation_mode:  "strict", "normal", or "lenient".

    Returns:
        Validated cover letter text.

    Raises:
        CoverLetterValidationError: Every generated draft failed validation.
    """
    job_text = format_job_context(job, description_limit=3000)
    missing_skills = _recorded_missing_skills(job)
    gap_block = ", ".join(missing_skills) if missing_skills else "none recorded"

    avoid_notes: list[str] = []
    letter = ""
    rejected_draft = ""
    last_errors: list[str] = []
    client = get_client_for_stage("cover")
    cl_prompt_base = _build_cover_letter_prompt(profile)

    for attempt in range(max_retries + 1):
        # Fresh conversation every attempt
        prompt = cl_prompt_base
        if avoid_notes:
            prompt += "\n\n## AVOID THESE ISSUES:\n" + "\n".join(f"- {n}" for n in avoid_notes[-5:])
        if any("hands-on it claim" in note.casefold() for note in avoid_notes):
            title = str(job.get("title") or "the target")
            company = str(job.get("company") or job.get("site") or "The employer")
            prompt += (
                "\n- Use this safe opening pattern exactly, filling only verified skills: "
                f'"For the {title} role, my home-lab work provides hands-on practice with [verified skills]." '
                "Delete any candidate IT sentence where the lab/project/training anchor comes after the skill. "
                "Use this safe closing pattern: "
                f'"{company}\'s [verified job detail] is a practical next step for my home-lab and training '
                'foundation. Happy to walk through any of this in more detail."'
            )

        if rejected_draft:
            draft_request = (
                "REJECTED DRAFT:\n"
                f"{rejected_draft}\n\n"
                "Revise the rejected draft to fix every validation error above. Preserve only supported facts. "
                "Keep each named paid employer or paid-work setting in a separate sentence, and return only "
                "the corrected cover letter."
            )
        else:
            draft_request = "Write the cover letter:"

        messages = [
            {"role": "system", "content": prompt},
            {
                "role": "user",
                "content": (
                    f"RESUME:\n{resume_text}\n\n---\n\nTARGET JOB:\n{job_text}\n\n"
                    "RECORDED CANDIDATE EVIDENCE GAPS (never claim these as performed skills, including "
                    f"synonyms or transferable labels): {gap_block}\n\n{draft_request}"
                ),
            },
        ]

        letter = client.chat(messages, max_tokens=1024, temperature=0.0 if avoid_notes else 0.2)
        letter = sanitize_text(letter)  # auto-fix em dashes, smart quotes
        letter = _strip_preamble(letter)  # remove any "Here is the letter:" prefix
        letter = _drop_mixed_paid_setting_sentences(letter)
        letter = _repair_unanchored_zero_it_closing(letter, job, profile)
        letter = _drop_ambiguous_zero_it_bridge_sentences(letter, profile)
        letter = _ensure_exact_target_title_once(letter, job)

        validation = validate_cover_letter(
            letter,
            mode=validation_mode,
            profile=profile,
            resume_text=resume_text,
            job=job,
        )
        if validation["passed"]:
            return letter

        last_errors = list(validation["errors"])
        rejected_draft = letter
        avoid_notes.extend(last_errors)
        # Warnings never block â€” only hard errors trigger a retry
        log.debug(
            "Cover letter attempt %d/%d failed: %s",
            attempt + 1,
            max_retries + 1,
            validation["errors"],
        )

    raise CoverLetterValidationError(last_errors or ["Unknown validation failure."])


# â”€â”€ Batch Entry Point â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€


def run_cover_letters(
    min_score: int = 7,
    limit: int = 0,
    validation_mode: str = "normal",
    target_url: str | None = None,
) -> dict:
    """Generate cover letters for high-scoring jobs that have tailored resumes.

    Args:
        min_score:       Minimum fit_score threshold.
        limit:           Maximum jobs to process.
        validation_mode: "strict", "normal", or "lenient".
        target_url: If provided, generate a cover letter only for this job URL.

    Returns:
        {"generated": int, "errors": int, "elapsed": float}
    """
    profile = load_profile()
    conn = get_connection()

    # Fetch jobs that have tailored resumes but no cover letter yet
    if target_url:
        jobs = conn.execute(
            "SELECT * FROM jobs "
            "WHERE url = ? AND fit_score >= ? AND tailored_resume_path IS NOT NULL "
            "AND archived_at IS NULL "
            f"AND {ACTIONABLE_JOB_SQL} "
            f"AND {MEANINGFUL_FULL_DESCRIPTION_SQL} "
            "AND (cover_letter_path IS NULL OR cover_letter_path = '') "
            "AND COALESCE(cover_attempts, 0) < ?",
            (target_url, min_score, MAX_ATTEMPTS),
        ).fetchall()
    else:
        jobs = get_jobs_by_stage(
            conn=conn,
            stage="pending_cover",
            min_score=min_score,
            limit=limit,
        )

    if not jobs:
        log.info("No jobs needing cover letters (score >= %d).", min_score)
        return {"generated": 0, "errors": 0, "elapsed": 0.0}

    # Convert rows to dicts
    if jobs and not isinstance(jobs[0], dict):
        if hasattr(jobs[0], "keys"):
            columns = jobs[0].keys()
            jobs = [dict(zip(columns, row)) for row in jobs]
        else:
            log.error("Unexpected row type: %s â€” cannot process", type(jobs[0]))
            return {"generated": 0, "errors": len(jobs), "elapsed": 0.0}

    COVER_LETTER_DIR.mkdir(parents=True, exist_ok=True)
    log.info(
        "Generating cover letters for %d jobs (score >= %d)...",
        len(jobs),
        min_score,
    )
    t0 = time.time()
    completed = 0
    results: list[dict] = []
    error_count = 0

    for job in jobs:
        completed += 1
        try:
            job_profile = profile_for_job_resume_location(profile, job)
            resume_text = _read_tailored_resume_text(job)
            letter = generate_cover_letter(resume_text, job, job_profile, validation_mode=validation_mode)

            cl_path = cover_letter_artifact_path(COVER_LETTER_DIR, job)
            cl_path.write_text(letter, encoding="utf-8")
            protect_file(cl_path)

            # Generate PDF, retaining the validated protected text as a
            # truthful fallback when the local browser/runtime is unavailable.
            artifact_path = str(cl_path)
            pdf_path = None
            try:
                from divapply.scoring.pdf import convert_to_pdf

                pdf_path = str(convert_to_pdf(cl_path, profile=job_profile))
                artifact_path = pdf_path
                _delete_temp_artifact(cl_path)
            except Exception:
                log.debug("PDF generation failed for %s", cl_path, exc_info=True)

            result = {
                "url": job["url"],
                "path": artifact_path,
                "pdf_path": pdf_path,
                "title": job["title"],
                "site": job["site"],
            }
            results.append(result)

            elapsed = time.time() - t0
            rate = completed / elapsed if elapsed > 0 else 0
            log.info(
                "%d/%d [OK] | %.1f jobs/min | %s",
                completed,
                len(jobs),
                rate * 60,
                result["title"][:40],
            )
        except Exception as e:
            result = {
                "url": job["url"],
                "title": job["title"],
                "site": job["site"],
                "path": None,
                "pdf_path": None,
                "error": str(e),
            }
            error_count += 1
            results.append(result)
            log.error("%d/%d [ERROR] %s -- %s", completed, len(jobs), job["title"][:40], e)

    # Persist to DB: increment attempt counter for ALL, save path only for successes
    now = datetime.now(timezone.utc).isoformat()
    saved = 0
    for r in results:
        if r.get("path"):
            cursor = conn.execute(
                "UPDATE jobs SET cover_letter_path=?, cover_letter_at=?, "
                "cover_attempts=COALESCE(cover_attempts,0)+1 "
                "WHERE url=? AND archived_at IS NULL",
                (r["path"], now, r["url"]),
            )
            if cursor.rowcount > 0:
                saved += 1
            else:
                _delete_unpersisted_artifact(r.get("path"))
        else:
            conn.execute(
                "UPDATE jobs SET cover_attempts=COALESCE(cover_attempts,0)+1 WHERE url=? AND archived_at IS NULL",
                (r["url"],),
            )
    conn.commit()

    elapsed = time.time() - t0
    log.info("Cover letters done in %.1fs: %d generated, %d errors", elapsed, saved, error_count)

    return {
        "generated": saved,
        "errors": error_count,
        "elapsed": elapsed,
    }
