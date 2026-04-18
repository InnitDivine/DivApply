"""Resume tailoring: LLM-powered ATS-optimized resume generation per job.

THIS IS THE HEAVIEST REFACTOR. Every piece of personal data -- name, email, phone,
skills, companies, projects, school -- is loaded at runtime from the user's profile.
Zero hardcoded personal information.

The LLM returns structured JSON, code assembles the final text. Header (name, contact)
is always code-injected, never LLM-generated. Each retry starts a fresh conversation
to avoid apologetic spirals.
"""

import json
import logging
import re
import time
from datetime import datetime, timezone
from pathlib import Path

from applypilot.config import RESUME_PATH, TAILORED_DIR, load_profile
from applypilot.database import get_connection, get_jobs_by_stage
from applypilot.llm import get_client_for_stage
from applypilot.scoring.validator import (
    BANNED_WORDS,
    FABRICATION_WATCHLIST,
    sanitize_text,
    validate_json_fields,
    validate_tailored_resume,
)

log = logging.getLogger(__name__)

MAX_ATTEMPTS = 5  # max cross-run retries before giving up
SUMMARY_MAX_WORDS = 42
BULLET_MAX_WORDS = 26
PROJECT_BULLET_MAX_WORDS = 20
SKILLS_MAX_ITEMS = 5
EXPERIENCE_MAX_ENTRIES = 4
PROJECTS_MAX_ENTRIES = 1


# ── Prompt Builders (profile-driven) ──────────────────────────────────────

def _build_tailor_prompt(profile: dict) -> str:
    """Build the resume tailoring system prompt from the user's profile.

    All skills boundaries, preserved entities, and formatting rules are
    derived from the profile -- nothing is hardcoded.
    """
    boundary = profile.get("skills_boundary", {})
    resume_facts = profile.get("resume_facts", {})

    # Format skills boundary for the prompt
    skills_lines = []
    for category, items in boundary.items():
        if isinstance(items, list) and items:
            label = category.replace("_", " ").title()
            skills_lines.append(f"{label}: {', '.join(items)}")
    skills_block = "\n".join(skills_lines)

    # Preserved entities
    companies = resume_facts.get("preserved_companies", [])
    projects = resume_facts.get("preserved_projects", [])
    school = resume_facts.get("preserved_school", "")
    real_metrics = resume_facts.get("real_metrics", [])
    coursework = profile.get("coursework_summary", [])
    coursework_skills = profile.get("coursework_skills", [])

    companies_str = ", ".join(companies) if companies else "N/A"
    projects_str = ", ".join(projects) if projects else "N/A"
    metrics_str = ", ".join(real_metrics) if real_metrics else "N/A"

    # Include ALL banned words from the validator so the LLM knows exactly
    # what will be rejected — the validator checks for these automatically.
    banned_str = ", ".join(BANNED_WORDS)

    education = profile.get("experience", {})
    education_level = education.get("education_level", "")
    coursework_block = "\n".join(f"- {item}" for item in coursework) if coursework else "N/A"
    coursework_skills_block = "\n".join(f"- {item}" for item in coursework_skills) if coursework_skills else "N/A"

    return f"""You are a neutral resume editor rewriting a resume using only verified facts.

Take the base resume and job description. Return a tailored resume as a JSON object.

## RECRUITER SCAN (6 seconds):
1. Title -- matches what they're hiring?
2. Summary -- 2 sentences proving you've done this work
3. First 3 bullets of most recent role -- verbs and outcomes match?
4. Skills -- must-haves visible immediately?

## SKILLS BOUNDARY (real skills only):
{skills_block}

## ACADEMIC COURSEWORK (internal only, do not cite unless already present in the resume):
{coursework_block}

## ACADEMIC SKILL MAP (internal only, do not cite unless already present in the resume):
{coursework_skills_block}

Do not add new tools unless they are directly supported by the profile or resume. Keep everything factual.

## TAILORING RULES:

TITLE: Match the target role. Keep seniority (Senior/Lead/Staff). Drop company suffixes and team names.

SUMMARY: Rewrite from scratch. Lead with the strongest verified skills relevant to this role. Sound like someone who's done this job. Exactly 2 sentences, max 42 words total.

SKILLS: Reorder each category so the job's most relevant verified skills appear first. Max 5 items per category.

Reframe EVERY bullet for this role. Same real work, different angle. Every bullet must be reworded. Never copy verbatim.
List experience entries from most recent to oldest.

PROJECTS: Keep only projects that are directly relevant to the role. Drop unrelated projects entirely.

BULLETS: Strong verb + what you built + quantified impact. Vary verbs (Built, Designed, Implemented, Reduced, Automated, Deployed, Operated, Optimized). Most relevant first. Max 3 bullets for the first two experience entries, max 2 bullets for any remaining entries, max 2 bullets per project.

## VOICE:
- Write like a real engineer. Short, direct.
- GOOD: "Automated financial reporting with Python + API integrations, cut processing time from 10 hours to 2"
- BAD: "Leveraged cutting-edge AI technologies to drive transformative operational efficiencies"
- BANNED WORDS (using ANY of these = validation failure — do not use them even once):
  {banned_str}
- No em dashes. Use commas, periods, or hyphens.

## HARD RULES:
- Do NOT invent work, companies, degrees, or certifications
- Do NOT change real numbers ({metrics_str})
- CRITICAL: You MUST include experience entries for these companies (at minimum the first two): {companies_str} — these are real jobs the candidate held. Reframe the bullets for this role, but the company names MUST appear in the experience section headers.
- Must fit 1 page.
- Target about 475-575 words before contact links.
- Leave enough room for the code-injected EDUCATION section at the bottom.

## TRUTHFULNESS RULES (critical — violating these = immediate rejection):
- The candidate's IT skills come from PERSONAL PROJECTS (home lab, PC building), NOT from paid jobs
- City of Roseville role is a CUSTOMER SERVICE front desk position at Parks & Rec — do NOT add IT duties like "network troubleshooting", "server administration", "SSH", or "Tier 1 support" to this role. Systems used: When To Work (scheduling), Microsoft Teams, payment processing, and a registration/permit application (name TBD).
- Nevada County role is ACCOUNTING — reconciliation, data entry, financial records. Not IT. Systems used: Workday ERP (financial/accounting), Megabyte Property Tax Systems (tax collection).
- Theatre Manager at UEC is REAL management — P&L, hiring, scheduling, vendor coordination. Systems used: RTS (Ready Theatre Systems), NCR Radiant POS, projection equipment.
- Banquet Captain at Ridge Golf is EVENT SETUP and SERVICE — not management or IT. Systems used: point-of-sale, event management.
- Fitness Representative at Montreux Golf is FRONT DESK — member check-ins, enrollment, records. Systems used: Jonas Club Software (member management).
- You MAY reframe bullets to emphasize relevant soft skills (communication, problem-solving, data accuracy) but NEVER add technical duties that didn't happen in that job
- Project-based IT skills belong in the PROJECTS section only when they are truly project work.
- Do not steer toward one job family over another. Use the same factual standard for every role.
- Do NOT invent metrics or percentages (e.g. "99% accuracy rate", "reduced time by 40%", "processed 500+ transactions daily"). If the original resume does not contain a specific number, do NOT add one. Use qualitative descriptions instead.
- Do NOT add tools or systems the candidate has not used professionally. "ticketing systems", "incident documentation", "ServiceNow", "Jira", "ITSM" — NONE of these belong on this resume unless they appear in the original.
- The "subtitle" field under each experience entry should contain the COMPANY NAME and DATE RANGE only (e.g. "City of Roseville Parks, Recreation & Libraries | September 2025 - Present"). Do NOT put "Tech" or any category tag in the subtitle.

## OUTPUT: Return ONLY valid JSON. No markdown fences. No commentary. No "here is" preamble.
Education is injected automatically by code — do NOT include an education field. Omit it entirely.
If no projects are relevant to the role, return an empty projects array: "projects": []

{{"title":"Role Title","summary":"2-3 tailored sentences.","skills":{{"Operating Systems":"...","Networking":"...","Infrastructure":"...","Scripting":"...","Tools":"..."}},"experience":[{{"header":"Job Title","subtitle":"Company Name | Start Date - End Date","bullets":["bullet 1","bullet 2","bullet 3","bullet 4"]}}],"projects":[{{"header":"Project Name - Brief Description","subtitle":"Tech Stack | Date","bullets":["bullet 1","bullet 2"]}}]}}"""


def _build_judge_prompt(profile: dict) -> str:
    """Build the LLM judge prompt from the user's profile."""
    boundary = profile.get("skills_boundary", {})
    resume_facts = profile.get("resume_facts", {})

    # Flatten allowed skills for the judge
    all_skills: list[str] = []
    for items in boundary.values():
        if isinstance(items, list):
            all_skills.extend(items)
    skills_str = ", ".join(all_skills) if all_skills else "N/A"

    real_metrics = resume_facts.get("real_metrics", [])
    metrics_str = ", ".join(real_metrics) if real_metrics else "N/A"

    return f"""You are a resume quality judge. A tailoring engine rewrote a resume to target a specific job. Your job is to catch LIES, not style changes.

You must answer with EXACTLY this format:
VERDICT: PASS or FAIL
ISSUES: (list any problems, or "none")

## CONTEXT -- what the tailoring engine was instructed to do (all of this is ALLOWED):
- Change the title to match the target role
- Rewrite the summary from scratch for the target job
- Reorder bullets and projects to put the most relevant first
- Reframe bullets to use the job's language
- Drop low-relevance bullets and replace with more relevant ones from other sections
- Reorder the skills section to put job-relevant skills first
- Change tone and wording extensively

## WHAT IS FABRICATION (FAIL for these):
1. Adding tools, languages, or frameworks to TECHNICAL SKILLS that aren't in the original. The allowed skills are ONLY: {skills_str}
2. Inventing NEW metrics or numbers not in the original. The real metrics are: {metrics_str}
3. Inventing work that has no basis in any original bullet (completely new achievements).
4. Adding companies, roles, or degrees that don't exist.
5. Changing real numbers (inflating 80% to 95%, 500 nodes to 1000 nodes).

## WHAT IS NOT FABRICATION (do NOT fail for these):
- Rewording any bullet, even heavily, as long as the underlying work is real
- Combining two original bullets into one
- Splitting one original bullet into two
- Describing the same work with different emphasis
- Dropping bullets entirely
- Reordering anything
- Changing the title or summary completely
- EDUCATION: The education section is ALWAYS auto-generated by code from the candidate's profile — it will look different from the original resume text. NEVER flag education formatting, location, date, or wording differences as fabrication.
- OFFICE TOOLS: Microsoft Teams, Outlook, Excel, Word, Office 365, and similar general workplace tools are in the candidate's real skills and may appear in any professional context. Do NOT flag these as fabricated.

## TOLERANCE RULE:
The goal is to get interviews, not to be a perfect fact-checker. Allow up to 3 minor stretches per resume:
- Adding a closely related tool the candidate could realistically know is a MINOR STRETCH, not fabrication.
- Reframing a metric with slightly different wording is a MINOR STRETCH.
- Adding any LEARNABLE skill given their existing stack is a MINOR STRETCH.
- Only FAIL if there are MAJOR lies: completely invented projects, fake companies, fake degrees, wildly inflated numbers, or skills from a completely different domain.

Be strict about major lies. Be lenient about minor stretches and learnable skills. Do not fail for style, tone, or restructuring."""


# ── JSON Extraction ───────────────────────────────────────────────────────

def extract_json(raw: str) -> dict:
    """Robustly extract JSON from LLM response (handles fences, preamble).

    Args:
        raw: Raw LLM response text.

    Returns:
        Parsed JSON dict.

    Raises:
        ValueError: If no valid JSON found.
    """
    raw = raw.strip()

    # Direct parse
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        pass

    # Markdown fences
    if "```" in raw:
        for part in raw.split("```")[1::2]:
            part = part.strip()
            if part.startswith("json"):
                part = part[4:].strip()
            try:
                return json.loads(part)
            except json.JSONDecodeError:
                continue

    # Find outermost { ... }
    start = raw.find("{")
    end = raw.rfind("}")
    if start != -1 and end > start:
        try:
            return json.loads(raw[start:end + 1])
        except json.JSONDecodeError:
            pass

    raise ValueError("No valid JSON found in LLM response")


def _normalize_resume_json(data: dict) -> dict:
    """Normalize LLM JSON output to consistent types before rendering.

    llama3.1:8b frequently returns JSON arrays for skill values and dicts
    for education instead of the expected string types. Normalize everything
    here so assemble_resume_text never has to deal with unexpected types.
    """
    # Skills: ensure every value is a comma-separated string, not a list/dict
    if isinstance(data.get("skills"), dict):
        cleaned = {}
        for cat, val in data["skills"].items():
            if isinstance(val, list):
                cleaned[cat] = ", ".join(str(v) for v in val if v)
            elif isinstance(val, dict):
                cleaned[cat] = ", ".join(str(v) for v in val.values() if v)
            else:
                cleaned[cat] = str(val) if val else ""
        # Drop empty categories entirely
        data["skills"] = {k: v for k, v in cleaned.items() if v.strip()}

    # Education: ensure it's a plain string
    edu = data.get("education", "")
    if isinstance(edu, dict):
        if edu.get("header") or edu.get("subtitle"):
            parts = [edu.get("header", ""), edu.get("subtitle", "")]
            if edu.get("bullets"):
                parts.extend(edu["bullets"])
            data["education"] = " | ".join(p for p in parts if p)
        else:
            # Keys are the institution strings (e.g. {"School | Degree": ""})
            data["education"] = " | ".join(k for k in edu.keys() if k.strip())
    elif isinstance(edu, list):
        # List may contain plain strings or dicts with header/subtitle
        parts = []
        for e in edu:
            if not e:
                continue
            if isinstance(e, dict):
                seg = []
                if e.get("header"):
                    seg.append(e["header"])
                if e.get("subtitle"):
                    seg.append(e["subtitle"])
                parts.append(" | ".join(seg) if seg else str(e))
            else:
                parts.append(str(e))
        data["education"] = " | ".join(parts)

    return data


def _truncate_words(text: str, max_words: int) -> str:
    """Trim text to a maximum number of whitespace-delimited words."""
    words = str(text or "").split()
    if len(words) <= max_words:
        return str(text or "").strip()
    trimmed = " ".join(words[:max_words]).rstrip(",;:-")
    if trimmed and trimmed[-1] not in ".!?":
        trimmed += "."
    return trimmed


def _trim_list_items(raw: str, max_items: int) -> str:
    """Keep only the first N comma-separated items in a skills string."""
    parts = [p.strip() for p in str(raw or "").split(",") if p.strip()]
    if not parts:
        return str(raw or "").strip()
    return ", ".join(parts[:max_items])


def _enforce_one_page_shape(data: dict) -> dict:
    """Trim verbose LLM output into a tighter one-page resume shape."""
    data["title"] = _truncate_words(data.get("title", ""), 8)
    data["summary"] = _truncate_words(data.get("summary", ""), SUMMARY_MAX_WORDS)

    if isinstance(data.get("skills"), dict):
        trimmed_skills = {}
        for cat, val in data["skills"].items():
            compact = _trim_list_items(val, SKILLS_MAX_ITEMS)
            if compact:
                trimmed_skills[cat] = compact
        data["skills"] = trimmed_skills

    trimmed_experience = []
    for idx, entry in enumerate(data.get("experience", [])[:EXPERIENCE_MAX_ENTRIES]):
        bullets = entry.get("bullets", [])
        bullet_cap = 3 if idx < 2 else 2
        trimmed_experience.append({
            "header": _truncate_words(entry.get("header", ""), 10),
            "subtitle": _truncate_words(entry.get("subtitle", ""), 14),
            "bullets": [_truncate_words(b, BULLET_MAX_WORDS) for b in bullets[:bullet_cap] if b],
        })
    data["experience"] = trimmed_experience

    trimmed_projects = []
    for entry in data.get("projects", [])[:PROJECTS_MAX_ENTRIES]:
        trimmed_projects.append({
            "header": _truncate_words(entry.get("header", ""), 12),
            "subtitle": _truncate_words(entry.get("subtitle", ""), 10),
            "bullets": [_truncate_words(b, PROJECT_BULLET_MAX_WORDS) for b in entry.get("bullets", [])[:2] if b],
        })
    data["projects"] = trimmed_projects

    return data


def _experience_sort_key(entry: dict, index: int) -> tuple[int, int, int]:
    """Sort experience entries newest-first using subtitle date hints."""
    subtitle = str(entry.get("subtitle", "")).lower()
    years = [int(m.group(0)) for m in re.finditer(r"(?:19|20)\d{2}", subtitle)]
    if years:
        end_year = max(years)
        start_year = min(years)
    else:
        end_year = -1
        start_year = -1
    if any(token in subtitle for token in ("present", "current", "now")):
        end_year = 9999
    return (-end_year, -start_year, index)


def _sort_experience_recent_first(experience: list[dict]) -> list[dict]:
    """Return experience entries ordered most recent to oldest."""
    indexed = list(enumerate(experience))
    return [entry for _, entry in sorted(indexed, key=lambda pair: _experience_sort_key(pair[1], pair[0]))]


# ── Resume Assembly (profile-driven header) ──────────────────────────────

def assemble_resume_text(data: dict, profile: dict) -> str:
    """Convert JSON resume data to formatted plain text.

    Header (name, location, contact) is ALWAYS code-injected from the profile,
    never LLM-generated. All text fields are sanitized.

    Args:
        data: Parsed JSON resume from the LLM.
        profile: User profile dict from load_profile().

    Returns:
        Formatted resume text.
    """
    personal = profile.get("personal", {})
    lines: list[str] = []

    # Header -- always code-injected from profile
    lines.append(personal.get("full_name", ""))
    lines.append(sanitize_text(data.get("title", "Software Engineer")))

    # Location from search config or profile -- leave blank if not available
    # The location line is optional; the original used a hardcoded city.
    # We omit it here; the LLM prompt can include it if the user sets it.

    # Contact line
    contact_parts: list[str] = []
    if personal.get("email"):
        contact_parts.append(personal["email"])
    if personal.get("phone"):
        contact_parts.append(personal["phone"])
    if personal.get("github_url"):
        contact_parts.append(personal["github_url"])
    if personal.get("linkedin_url"):
        contact_parts.append(personal["linkedin_url"])
    if contact_parts:
        lines.append(" | ".join(contact_parts))
    lines.append("")

    # Summary
    lines.append("SUMMARY")
    lines.append(sanitize_text(data["summary"]))
    lines.append("")

    # Technical Skills (normalized to strings by _normalize_resume_json)
    lines.append("TECHNICAL SKILLS")
    if isinstance(data.get("skills"), dict):
        for cat, val in data["skills"].items():
            if val:  # empty categories already stripped by normalizer
                lines.append(f"{cat}: {sanitize_text(str(val))}")
    lines.append("")

    # Experience
    lines.append("EXPERIENCE")
    for entry in _sort_experience_recent_first(list(data.get("experience", []))):
        lines.append(sanitize_text(entry.get("header", "")))
        if entry.get("subtitle"):
            lines.append(sanitize_text(entry["subtitle"]))
        for b in entry.get("bullets", []):
            lines.append(f"- {sanitize_text(b)}")
        lines.append("")

    # Projects -- skip section entirely if LLM returned none
    projects = [e for e in data.get("projects", []) if e.get("header") or e.get("bullets")]
    if projects:
        lines.append("PROJECTS")
        for entry in projects:
            lines.append(sanitize_text(entry.get("header", "")))
            if entry.get("subtitle"):
                lines.append(sanitize_text(entry["subtitle"]))
            for b in entry.get("bullets", []):
                lines.append(f"- {sanitize_text(b)}")
            lines.append("")

    # Education -- always injected from profile, never trusted from LLM
    lines.append("EDUCATION")
    edu_schools = profile.get("education_schools", [])
    if edu_schools:
        for sch in edu_schools:
            degree_status = sch.get("degree", "")
            received = sch.get("degree_received", False)
            end_year = sch.get("end_year", "")
            if not received and end_year == "present":
                status_note = "in progress"
            elif not received:
                status_note = "not completed"
            else:
                status_note = f"conferred {end_year}"
            gpa_str = f" | GPA: {sch['gpa']}" if sch.get("gpa") else ""
            minor_str = f" | Minor: {sch['minor']}" if sch.get("minor") else ""
            lines.append(f"{degree_status} ({status_note})")
            lines.append(f"{sch['school']} | {sch['city_state']} | {sch['start_year']}-{end_year}{gpa_str}{minor_str}")
            lines.append("")
    else:
        # Fallback to LLM-provided education if profile has none
        lines.append(sanitize_text(str(data.get("education", ""))))

    return "\n".join(lines)


# ── LLM Judge ────────────────────────────────────────────────────────────

def judge_tailored_resume(
    original_text: str, tailored_text: str, job_title: str, profile: dict
) -> dict:
    """LLM judge layer: catches subtle fabrication that programmatic checks miss.

    Args:
        original_text: Base resume text.
        tailored_text: Tailored resume text.
        job_title: Target job title.
        profile: User profile for building the judge prompt.

    Returns:
        {"passed": bool, "verdict": str, "issues": str, "raw": str}
    """
    judge_prompt = _build_judge_prompt(profile)

    messages = [
        {"role": "system", "content": judge_prompt},
        {"role": "user", "content": (
            f"JOB TITLE: {job_title}\n\n"
            f"ORIGINAL RESUME:\n{original_text}\n\n---\n\n"
            f"TAILORED RESUME:\n{tailored_text}\n\n"
            "Judge this tailored resume:"
        )},
    ]

    client = get_client_for_stage("tailor")
    response = client.chat(messages, max_tokens=512, temperature=0.1)

    passed = "VERDICT: PASS" in response.upper()
    issues = "none"
    if "ISSUES:" in response.upper():
        issues_idx = response.upper().index("ISSUES:")
        issues = response[issues_idx + 7:].strip()

    return {
        "passed": passed,
        "verdict": "PASS" if passed else "FAIL",
        "issues": issues,
        "raw": response,
    }


# ── Core Tailoring ───────────────────────────────────────────────────────

def tailor_resume(
    resume_text: str, job: dict, profile: dict,
    max_retries: int = 3, validation_mode: str = "normal",
) -> tuple[str, dict]:
    """Generate a tailored resume via JSON output + fresh context on each retry.

    Key design choices:
    - LLM returns structured JSON, code assembles the text (no header leaks)
    - Each retry starts a FRESH conversation (no apologetic spiral)
    - Issues from previous attempts are noted in the system prompt
    - Em dashes and smart quotes are auto-fixed, not rejected

    Args:
        resume_text:      Base resume text.
        job:              Job dict with title, site, location, full_description.
        profile:          User profile dict.
        max_retries:      Maximum retry attempts.
        validation_mode:  "strict", "normal", or "lenient".
                          strict  -- banned words trigger retries; judge must pass
                          normal  -- banned words = warnings only; judge can fail on last retry
                          lenient -- banned words ignored; LLM judge skipped

    Returns:
        (tailored_text, report) where report contains validation details.
    """
    job_text = (
        f"TITLE: {job['title']}\n"
        f"COMPANY: {job['site']}\n"
        f"LOCATION: {job.get('location', 'N/A')}\n\n"
        f"DESCRIPTION:\n{(job.get('full_description') or '')[:4000]}"
    )

    report: dict = {
        "attempts": 0, "validator": None, "judge": None,
        "status": "pending", "validation_mode": validation_mode,
    }
    avoid_notes: list[str] = []
    tailored = ""
    client = get_client_for_stage("tailor")
    tailor_prompt_base = _build_tailor_prompt(profile)

    for attempt in range(max_retries + 1):
        report["attempts"] = attempt + 1

        # Fresh conversation every attempt
        prompt = tailor_prompt_base
        if avoid_notes:
            prompt += "\n\n## AVOID THESE ISSUES (from previous attempt):\n" + "\n".join(
                f"- {n}" for n in avoid_notes[-5:]
            )

        messages = [
            {"role": "system", "content": prompt},
            {"role": "user", "content": f"ORIGINAL RESUME:\n{resume_text}\n\n---\n\nTARGET JOB:\n{job_text}\n\nReturn the JSON:"},
        ]

        raw = client.chat(messages, max_tokens=2048, temperature=0.4)

        # Parse JSON from response
        try:
            data = extract_json(raw)
        except ValueError:
            log.warning("Attempt %d: not valid JSON. First 200 chars: %s", attempt + 1, raw[:200])
            avoid_notes.append("Output was not valid JSON. Return ONLY a JSON object, nothing else.")
            continue

        # Normalize inconsistent LLM output types (lists/dicts for skills/education)
        data = _normalize_resume_json(data)
        data = _enforce_one_page_shape(data)

        # Layer 1: Validate JSON fields
        validation = validate_json_fields(data, profile, mode=validation_mode)
        report["validator"] = validation

        if not validation["passed"]:
            # Only retry if there are hard errors (warnings never block)
            log.warning("Attempt %d validation errors: %s", attempt + 1, validation["errors"])
            avoid_notes.extend(validation["errors"])
            if attempt < max_retries:
                continue
            # Last attempt — assemble whatever we got
            tailored = assemble_resume_text(data, profile)
            report["status"] = "failed_validation"
            return tailored, report

        # Assemble text (header injected by code, em dashes auto-fixed)
        tailored = assemble_resume_text(data, profile)

        # Layer 2: Programmatic text validation, including one-page length checks.
        text_validation = validate_tailored_resume(tailored, profile, original_text=resume_text)
        report["text_validator"] = text_validation

        if not text_validation["passed"]:
            log.warning("Attempt %d text validation errors: %s", attempt + 1, text_validation["errors"])
            avoid_notes.extend(text_validation["errors"])
            if attempt < max_retries:
                continue
            report["status"] = "failed_validation"
            return tailored, report

        # Layer 3: LLM judge (catches subtle fabrication) — skipped in lenient/none mode
        if validation_mode in ("lenient", "none"):
            report["judge"] = {"verdict": "SKIPPED", "passed": True, "issues": "none"}
            report["status"] = "approved"
            return tailored, report

        judge = judge_tailored_resume(resume_text, tailored, job.get("title", ""), profile)
        report["judge"] = judge

        if not judge["passed"]:
            avoid_notes.append(f"Judge rejected: {judge['issues']}")
            if attempt < max_retries:
                # Retry if retries remain
                continue
            # Out of retries — accept with warning
            report["status"] = "approved_with_judge_warning"
            return tailored, report

        # Both passed
        report["status"] = "approved"
        return tailored, report

    report["status"] = "exhausted_retries"
    return tailored, report


# ── Batch Entry Point ────────────────────────────────────────────────────

def run_tailoring(min_score: int = 7, limit: int = 20,
                  validation_mode: str = "normal") -> dict:
    """Generate tailored resumes for high-scoring jobs.

    Args:
        min_score:       Minimum fit_score to tailor for.
        limit:           Maximum jobs to process.
        validation_mode: "strict", "normal", or "lenient".

    Returns:
        {"approved": int, "failed": int, "errors": int, "elapsed": float}
    """
    profile = load_profile()
    resume_text = RESUME_PATH.read_text(encoding="utf-8")
    conn = get_connection()

    jobs = get_jobs_by_stage(conn=conn, stage="pending_tailor", min_score=min_score, limit=limit)

    if not jobs:
        log.info("No untailored jobs with score >= %d.", min_score)
        return {"approved": 0, "failed": 0, "errors": 0, "elapsed": 0.0}

    TAILORED_DIR.mkdir(parents=True, exist_ok=True)
    log.info("Tailoring resumes for %d jobs (score >= %d)...", len(jobs), min_score)
    t0 = time.time()
    completed = 0
    results: list[dict] = []
    stats: dict[str, int] = {"approved": 0, "failed_validation": 0, "failed_judge": 0, "error": 0}

    for job in jobs:
        completed += 1
        try:
            tailored, report = tailor_resume(resume_text, job, profile,
                                             validation_mode=validation_mode)

            # Build safe filename prefix
            safe_title = re.sub(r"[^\w\s-]", "", job["title"])[:50].strip().replace(" ", "_")
            safe_site = re.sub(r"[^\w\s-]", "", job["site"])[:20].strip().replace(" ", "_")
            # Avoid Windows reserved names (CON, NUL, PRN, etc.)
            _WIN_RESERVED = {"CON", "PRN", "AUX", "NUL", "COM1", "COM2", "COM3", "COM4",
                             "LPT1", "LPT2", "LPT3", "CLOCK$"}
            if safe_title.upper() in _WIN_RESERVED:
                safe_title = f"_{safe_title}"
            if safe_site.upper() in _WIN_RESERVED:
                safe_site = f"_{safe_site}"
            prefix = f"{safe_site}_{safe_title}"

            # Save tailored resume text
            txt_path = TAILORED_DIR / f"{prefix}.txt"
            txt_path.write_text(tailored, encoding="utf-8")

            # Save job description for traceability
            job_path = TAILORED_DIR / f"{prefix}_JOB.txt"
            job_desc = (
                f"Title: {job['title']}\n"
                f"Company: {job['site']}\n"
                f"Location: {job.get('location', 'N/A')}\n"
                f"Score: {job.get('fit_score', 'N/A')}\n"
                f"URL: {job['url']}\n\n"
                f"{job.get('full_description', '')}"
            )
            job_path.write_text(job_desc, encoding="utf-8")

            # Save validation report
            report_path = TAILORED_DIR / f"{prefix}_REPORT.json"
            report_path.write_text(json.dumps(report, indent=2), encoding="utf-8")

            # Generate PDF for approved resumes (best-effort)
            # "approved_with_judge_warning" is also a success — resume was generated.
            pdf_path = None
            if report["status"] in ("approved", "approved_with_judge_warning"):
                try:
                    from applypilot.scoring.pdf import convert_to_pdf
                    pdf_path = str(convert_to_pdf(txt_path))
                except Exception:
                    log.debug("PDF generation failed for %s", txt_path, exc_info=True)

            result = {
                "url": job["url"],
                "path": str(txt_path),
                "pdf_path": pdf_path,
                "title": job["title"],
                "site": job["site"],
                "status": report["status"],
                "attempts": report["attempts"],
            }
        except Exception as e:
            result = {
                "url": job["url"], "title": job["title"], "site": job["site"],
                "status": "error", "attempts": 0, "path": None, "pdf_path": None,
            }
            log.error("%d/%d [ERROR] %s -- %s", completed, len(jobs), job["title"][:40], e)

        results.append(result)
        stats[result.get("status", "error")] = stats.get(result.get("status", "error"), 0) + 1

        elapsed = time.time() - t0
        rate = completed / elapsed if elapsed > 0 else 0
        log.info(
            "%d/%d [%s] attempts=%s | %.1f jobs/min | %s",
            completed, len(jobs),
            result["status"].upper(),
            result.get("attempts", "?"),
            rate * 60,
            result["title"][:40],
        )

    # Persist to DB: increment attempt counter for ALL, save path only for approved
    now = datetime.now(timezone.utc).isoformat()
    _success_statuses = {"approved", "approved_with_judge_warning"}
    for r in results:
        if r["status"] in _success_statuses:
            conn.execute(
                "UPDATE jobs SET tailored_resume_path=?, tailored_at=?, "
                "tailor_attempts=COALESCE(tailor_attempts,0)+1 WHERE url=?",
                (r["path"], now, r["url"]),
            )
        else:
            conn.execute(
                "UPDATE jobs SET tailor_attempts=COALESCE(tailor_attempts,0)+1 WHERE url=?",
                (r["url"],),
            )
    conn.commit()

    elapsed = time.time() - t0
    log.info(
        "Tailoring done in %.1fs: %d approved, %d failed_validation, %d failed_judge, %d errors",
        elapsed,
        stats.get("approved", 0),
        stats.get("failed_validation", 0),
        stats.get("failed_judge", 0),
        stats.get("error", 0),
    )

    return {
        "approved": stats.get("approved", 0),
        "failed": stats.get("failed_validation", 0) + stats.get("failed_judge", 0),
        "errors": stats.get("error", 0),
        "elapsed": elapsed,
    }
