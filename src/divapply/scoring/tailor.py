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

from divapply.artifacts import tailored_artifact_paths
from divapply.config import (
    RESUME_PATH,
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
from divapply.scoring.evidence import format_verified_work_history
from divapply.scoring.validator import (
    ALLOWED_SKILLS_SECTION_TITLES,
    BANNED_WORDS,
    candidate_evidence_supports,
    prune_unsupported_tailored_skills,
    sanitize_text,
    validate_json_fields,
    validate_tailored_resume,
)
from divapply.security import protect_file

log = logging.getLogger(__name__)

MAX_ATTEMPTS = 5  # max cross-run retries before giving up
SUMMARY_MAX_WORDS = 42
BULLET_MAX_WORDS = 26
PROJECT_BULLET_MAX_WORDS = 20
SKILLS_MAX_ITEMS = 5
EXPERIENCE_MAX_ENTRIES = 4
PROJECTS_MAX_ENTRIES = 1
COMPLETED_COURSEWORK_MAX_ITEMS = 6
CURRENT_COURSEWORK_MAX_ITEMS = 3


def _delete_temp_artifacts(*paths: Path) -> None:
    """Delete intermediate generated files after durable PDFs are available."""
    root = TAILORED_DIR.resolve()
    for path in paths:
        try:
            resolved = path.resolve()
            if not resolved.is_relative_to(root):
                log.warning("Refusing to delete artifact outside tailored directory: %s", path)
                continue
            if path.suffix not in {".txt", ".json"}:
                log.warning("Refusing to delete unexpected temporary artifact type: %s", path)
                continue
            if path.exists() or path.is_symlink():
                path.unlink()
        except OSError:
            log.warning("Could not delete temporary generated artifact: %s", path)


def _delete_unpersisted_artifacts(*paths: Path) -> None:
    """Remove text/report/PDF outputs created after a concurrent archive."""
    root = TAILORED_DIR.resolve()
    for path in paths:
        try:
            if not path.resolve().is_relative_to(root):
                log.warning("Refusing to delete output outside tailored directory: %s", path)
                continue
            if path.suffix.casefold() not in {".txt", ".json", ".pdf"}:
                continue
            if path.exists() or path.is_symlink():
                path.unlink()
        except OSError:
            log.warning("Could not delete unpersisted tailored artifact: %s", path)


# â”€â”€ Prompt Builders (profile-driven) â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€


def _build_tailor_prompt(profile: dict) -> str:
    """Build the resume tailoring system prompt from the user's profile.

    All skills boundaries, preserved entities, and formatting rules are
    derived from the profile -- nothing is hardcoded.
    """
    resume_facts = profile.get("resume_facts", {})

    # Format skills boundary for the prompt
    skills_lines = []
    for category, items in profile_skills(profile).items():
        if items:
            label = category.replace("_", " ").title()
            skills_lines.append(f"{label}: {', '.join(items)}")
    skills_block = "\n".join(skills_lines)

    # Preserved entities
    companies = resume_facts.get("preserved_companies", [])
    real_metrics = resume_facts.get("real_metrics", [])
    coursework = profile.get("coursework_summary", [])
    coursework_skills = profile.get("coursework_skills", [])
    work_history = format_verified_work_history(profile)

    companies_str = ", ".join(companies) if companies else "N/A"
    metrics_str = ", ".join(real_metrics) if real_metrics else "N/A"

    # Include ALL banned words from the validator so the LLM knows exactly
    # what will be rejected â€” the validator checks for these automatically.
    banned_str = ", ".join(BANNED_WORDS)

    coursework_block = "\n".join(f"- {item}" for item in coursework) if coursework else "N/A"
    coursework_skills_block = "\n".join(f"- {item}" for item in coursework_skills) if coursework_skills else "N/A"
    work_history_block = work_history or "N/A"
    truth_items: list[str] = []
    for key in ("truthfulness_rules", "application_context", "answer_context"):
        value = profile.get(key)
        if isinstance(value, list):
            truth_items.extend(str(item).strip() for item in value if str(item).strip())
        elif isinstance(value, str) and value.strip():
            truth_items.append(value.strip())
    truth_block = "\n".join(f"- {item}" for item in truth_items) if truth_items else "N/A"

    return f"""You are a neutral resume editor rewriting a resume using only verified facts.

Take the base resume and job description. Return a tailored resume as a JSON object.

## RECRUITER SCAN (6 seconds):
1. Title -- matches what they're hiring?
2. Summary -- 2 sentences connecting verified evidence to this work
3. First 3 bullets of most recent role -- verbs and outcomes match?
4. Skills -- must-haves visible immediately?

## SKILLS BOUNDARY (real skills only):
{skills_block}

## ACADEMIC COURSEWORK (internal evidence only):
{coursework_block}

## ACADEMIC SKILL MAP (can inform skills, not paid work):
{coursework_skills_block}

## VERIFIED WORK HISTORY (exact candidate-owned evidence):
{work_history_block}

Coursework may support the skills section when it is relevant, but do not present coursework exposure as job experience.
Do not add new tools unless they are directly supported by the profile, resume, or academic skill map. Keep everything factual.

## TAILORING RULES:

TITLE: Match the target role. Keep seniority (Senior/Lead/Staff). Drop company suffixes and team names.

SUMMARY: Rewrite from scratch. Position the candidate for the target role using verified evidence. Do not imply they previously held the target role unless the source facts say so. Exactly 2 sentences, max 42 words total.

SKILLS: Reorder each category so the job's most relevant verified skills appear first. Max 5 items per category. Return skills_section_title as TECHNICAL SKILLS for IT/engineering roles or CORE QUALIFICATIONS for customer service, government, administrative, and health-operations roles. Use role-relevant category names; do not force operating-system/network/cloud categories into non-IT résumés.
Copy every skill item exactly from SKILLS BOUNDARY or ACADEMIC SKILL MAP. Never derive, paraphrase, broaden, or import a skill phrase from the job posting.
When using CORE QUALIFICATIONS, include only qualifications directly relevant to the posting. Omit low-relevance technical exposure categories even when those skills are supported.

Reframe EVERY bullet for this role. Same real work, different angle. Every bullet must be reworded. Never copy verbatim.
List experience entries from most recent to oldest.

PROJECTS: Keep only projects that are directly relevant to the role. Drop unrelated projects entirely.
For a CORE QUALIFICATIONS résumé, return an empty projects array unless a project proves an essential technical requirement in the posting.
For desktop, equipment, deployment, or hardware-support roles, prefer a verified PC-building/hardware project over a cloud lab. For server, Linux, cloud, or network roles, prefer the verified home lab.

BULLETS: Strong verb + verified action + outcome or purpose. Use a metric only when the source resume or verified profile supplies it. Vary accurate verbs and put the most relevant evidence first. Max 3 bullets for the first two experience entries, max 2 bullets for any remaining entries, max 2 bullets per project.
Keep compound verbs in the same tense. Write "Provision and administer" for ongoing work or "Provisioned and administered" for completed work, never "Provisioned and administer."

## VOICE:
- Write like a real engineer. Short, direct.
- GOOD: "Automated recurring reports with Python and API integrations, reducing manual processing"
- BAD: "Leveraged cutting-edge AI technologies to drive transformative operational efficiencies"
- BANNED WORDS (using ANY of these = validation failure â€” do not use them even once):
  {banned_str}
- No em dashes. Use commas, periods, or hyphens.

## HARD RULES:
- Do NOT invent work, companies, degrees, or certifications
- Do NOT change real numbers ({metrics_str})
- CRITICAL: You MUST include experience entries for these companies (at minimum the first two): {companies_str} â€” these are real jobs the candidate held. Reframe the bullets for this role, but the company names MUST appear in the experience section headers.
- Must fit 1 page.
- Target about 475-575 words before contact links.
- Leave enough room for the code-injected EDUCATION section at the bottom.

## TRUTHFULNESS RULES (critical â€” violating these = immediate rejection):
- Use only facts from the original resume, profile, and hidden coursework summaries.
- Never move a skill from coursework or personal projects into paid work history unless the source resume/profile says it happened in that job.
- You MAY reframe bullets to emphasize relevant transferable skills, but NEVER add duties that did not happen in that role.
- Do NOT claim phone, email, or chat support experience unless that communication channel is explicit in the source resume or verified profile.
- Do NOT relabel residents, members, visitors, or public-counter customers as software clients, software users, or government users. Do not claim customer follow-up unless the source facts explicitly contain follow-up work.
- If verified professional IT experience is zero, anchor hands-on IT claims to the lab, project, or coursework that proves them. Describe paid municipal/county/front-desk work separately as transferable evidence; never say hands-on IT work occurred in those paid settings unless the source explicitly does.
- Do not steer toward one job family over another. Use the same factual standard for every role.
- Do NOT invent metrics or percentages (e.g. "99% accuracy rate", "reduced time by 40%", "processed 500+ transactions daily"). If the original resume does not contain a specific number, do NOT add one. Use qualitative descriptions instead.
- Do NOT add tools, systems, certifications, licenses, degrees, employers, or coursework the candidate has not actually used or completed.
- The "subtitle" field under each experience entry should contain the company name and date range only. Do NOT put category tags in the subtitle.

## IT SUPPORT / DEVICE SUPPORT GUIDANCE:
- Strong, truthful reframes: customer troubleshooting, intake/triage, documentation, device setup, account/help requests, inventory, escalation, scheduling, remote communication, and policy-following when those map to real work.
- For device support roles, emphasize verified troubleshooting and service workflow. Do not invent enterprise systems such as Active Directory, Azure AD, Intune, SCCM, Jamf, ServiceNow, Jira, Zendesk, imaging, MDM, VPN, or ticket queues unless they appear in the profile, resume, or academic skill map.
- If a tool appears only in coursework, it can appear in skills as academic exposure, but do not claim it was used in a paid job bullet.
- If the job asks for a missing tool, describe the transferable task without naming the tool.

## PROFILE-SPECIFIC FACT GUARDS:
{truth_block}

## OUTPUT: Return ONLY valid JSON. No markdown fences. No commentary. No "here is" preamble.
Education is injected automatically by code â€” do NOT include an education field. Omit it entirely.
If no projects are relevant to the role, return an empty projects array: "projects": []

{{"title":"Role Title","summary":"2 tailored sentences.","skills_section_title":"TECHNICAL SKILLS or CORE QUALIFICATIONS","skills":{{"Role-Relevant Category":"verified skill, verified skill"}},"experience":[{{"header":"Job Title","subtitle":"Company Name | Start Date - End Date","bullets":["bullet 1","bullet 2","bullet 3"]}}],"projects":[{{"header":"Project Name - Brief Description","subtitle":"Tech Stack | Date","bullets":["bullet 1","bullet 2"]}}]}}"""


def _build_judge_prompt(profile: dict) -> str:
    """Build the LLM judge prompt from the user's profile."""
    resume_facts = profile.get("resume_facts", {})

    # Flatten allowed skills for the judge
    skills_evidence_lines: list[str] = []
    for category, items in profile_skills(profile).items():
        if items:
            skills_evidence_lines.append(f"- {category.replace('_', ' ').title()}: {', '.join(items)}")
    skills_evidence = "\n".join(skills_evidence_lines) or "- N/A"

    real_metrics = resume_facts.get("real_metrics", [])
    metrics_str = ", ".join(real_metrics) if real_metrics else "N/A"
    work_history_evidence = format_verified_work_history(profile) or "N/A"

    education_lines: list[str] = []
    for school in profile.get("education_schools", []) or []:
        if not isinstance(school, dict):
            continue
        labeled_fields = (
            ("School", school.get("school", "")),
            ("Location", school.get("city_state", "")),
            ("Degree", school.get("degree", "")),
            ("Major", school.get("major", "")),
            ("Minor", school.get("minor", "")),
            ("Start", school.get("start_year", "")),
            ("End", school.get("end_year", "")),
            ("GPA", school.get("gpa", "")),
            ("GPA as of", school.get("gpa_as_of", "")),
            ("Earned credits", school.get("units", "")),
            ("Status", school.get("status", "")),
        )
        education_lines.append(
            " | ".join(f"{label}: {value}" for label, value in labeled_fields if str(value or "").strip())
        )
    education_evidence = "\n".join(f"- {line}" for line in education_lines) or "- N/A"

    return f"""You are a final factuality and coherence judge. A tailoring engine rewrote a resume to target a specific job. Your job is to catch lies, unsupported claims, contradictions, and incoherent output.

You must answer with EXACTLY this format:
VERDICT: PASS or FAIL
ISSUES: (list any problems, or "none")

VERDICT DECISION: FAIL only when ISSUES names at least one concrete claim and explains why it is absent from the supplied evidence. If your analysis says a phrase is broadly supported, may be acceptable, or has no definitive fabrication, you MUST return PASS.

## CONTEXT -- what the tailoring engine was instructed to do (all of this is ALLOWED):
- Change the title to match the target role
- Rewrite the summary from scratch for the target job
- Reorder bullets and projects to put the most relevant first
- Reframe bullets to use the job's language
- Drop low-relevance bullets and replace with more relevant ones from other sections
- Reorder the skills section to put job-relevant skills first
- Change tone and wording extensively

## AUTHORITATIVE CURRENT EDUCATION (profile/transcript; newer than base résumé):
{education_evidence}

## AUTHORITATIVE ALLOWED SKILLS (profile; exact listed phrases are supported):
{skills_evidence}

## AUTHORITATIVE VERIFIED WORK HISTORY (exact listed role facts are supported):
{work_history_evidence}

## WHAT IS FABRICATION (FAIL for these):
1. Adding tools, languages, or frameworks that are absent from both the original and AUTHORITATIVE ALLOWED SKILLS above. Any exact listed profile skill is supported and must not be failed merely because the base résumé omits it.
2. Inventing NEW metrics or numbers not in the original. The real metrics are: {metrics_str}
3. Inventing work that has no basis in any original bullet (completely new achievements).
4. Adding companies, roles, or degrees that don't exist.
5. Changing real numbers (inflating 80% to 95%, 500 nodes to 1000 nodes).
6. Adding coursework, credentials, certifications, licenses, clearances, or degrees that are not present in the profile/resume.
7. Moving project-only skills into paid work history unless the original resume supports that job context.
8. Claiming direct professional experience where only coursework, personal projects, or transferable experience exists.
9. For IT support/device support, inventing enterprise tools or systems such as Active Directory, Azure AD, Intune, SCCM, Jamf, ServiceNow, Jira, Zendesk, imaging, MDM, VPN, or ticket queues when they are not supported.

## WHAT IS NOT FABRICATION (do NOT fail for these):
- Rewording any bullet, even heavily, as long as the underlying work is real
- Combining two original bullets into one
- Splitting one original bullet into two
- Describing the same work with different emphasis
- Dropping bullets entirely
- Reordering anything
- Changing the title or summary completely
- A target-role headline is positioning, not a claim that the candidate previously held that job. Never fail solely because the headline matches the target title.
- A skill listed in the original/profile skills section is supported even when no paid-work bullet repeats it. Never demand paid use of a lab/coursework/fundamentals skill.
- Omitting original skills, bullets, projects, metrics, or details is allowed and is not a factuality/coherence failure.
- Using coursework-supported skills in the skills section when the profile/coursework evidence supports them
- EDUCATION: The education section is ALWAYS auto-generated by code from the current candidate profile and canonical transcript records. It may be newer and more precise than the original resume text. NEVER flag its school location, dates, GPA, credits, major/minor wording, degree status, or formatting when supported by that profile.
- OFFICE TOOLS: Microsoft Teams, Outlook, Excel, Word, Office 365, and similar general workplace tools are in the candidate's real skills and may appear in any professional context. Do NOT flag these as fabricated.

## COHERENCE CHECKS (FAIL for these):
- Repeated or contradictory sections
- Summary says a skill or credential absent from the original resume, profile skills, coursework, projects, and tailored skills section
- Bullets imply a different job, company, degree, or certification than the source
- Keyword stuffing that makes the resume read as false or incoherent

Strict rule: no minor stretches. If a fact is not supported by the original resume/profile, fail. The explicit allowed transformations above take precedence over general coherence concerns. Do not fail for omission, style, tone, targeting, or restructuring."""


# â”€â”€ JSON Extraction â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€


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
            return json.loads(raw[start : end + 1])
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
        trimmed_experience.append(
            {
                "header": _truncate_words(entry.get("header", ""), 10),
                "subtitle": _truncate_words(entry.get("subtitle", ""), 14),
                "bullets": [_truncate_words(b, BULLET_MAX_WORDS) for b in bullets[:bullet_cap] if b],
            }
        )
    data["experience"] = trimmed_experience

    trimmed_projects = []
    skills_section_title = str(data.get("skills_section_title", "TECHNICAL SKILLS")).strip().upper()
    if skills_section_title != "CORE QUALIFICATIONS":
        for entry in data.get("projects", [])[:PROJECTS_MAX_ENTRIES]:
            trimmed_projects.append(
                {
                    "header": _truncate_words(entry.get("header", ""), 12),
                    "subtitle": _truncate_words(entry.get("subtitle", ""), 10),
                    "bullets": [
                        _truncate_words(b, PROJECT_BULLET_MAX_WORDS) for b in entry.get("bullets", [])[:2] if b
                    ],
                }
            )
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


def _format_job_trace(job: dict) -> str:
    """Return saved job context with employer and source kept separate."""
    return (
        f"Title: {job['title']}\n"
        f"Company: {job.get('company') or 'N/A'}\n"
        f"Source: {job.get('site') or 'N/A'}\n"
        f"Location: {job.get('location', 'N/A')}\n"
        f"Score: {job.get('fit_score', 'N/A')}\n"
        f"URL: {job['url']}\n\n"
        f"{job.get('full_description', '')}"
    )


# â”€â”€ Resume Assembly (profile-driven header) â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€


def _structured_coursework(value: object, *, limit: int) -> list[str]:
    """Return bounded, deduplicated coursework explicitly supplied by the profile."""
    if not isinstance(value, list):
        return []

    items: list[str] = []
    seen: set[str] = set()
    for raw in value:
        if not isinstance(raw, str):
            continue
        item = sanitize_text(raw).strip()
        key = item.casefold()
        if not item or key in seen:
            continue
        seen.add(key)
        items.append(item)
        if len(items) >= limit:
            break
    return items


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

    # Preserve current verified city/state for recruiter and ATS context without
    # exposing a street address or substituting a planned destination.
    city = str(personal.get("city") or "").strip()
    state = str(personal.get("province_state") or "").strip()
    location = ", ".join(part for part in (city, state) if part)
    if location:
        lines.append(location)

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
    skills_section_title = str(data.get("skills_section_title", "TECHNICAL SKILLS")).strip().upper()
    if skills_section_title not in ALLOWED_SKILLS_SECTION_TITLES:
        skills_section_title = "TECHNICAL SKILLS"
    lines.append(skills_section_title)
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
            degree_status = str(sch.get("degree", "")).strip()
            major = str(sch.get("major", "")).strip()
            received = sch.get("degree_received", False)
            end_year = sch.get("end_year", "")
            status = str(sch.get("status", "")).strip().lower()
            expected_year = str(sch.get("expected_graduation_year", "")).strip()
            active_program = bool(
                not received
                and status not in {"transferred", "transfer"}
                and (
                    status in {"in progress", "in-progress", "current", "enrolled"}
                    or str(end_year).casefold() == "present"
                    or expected_year
                )
            )
            if status in {"transferred", "transfer"}:
                status_note = "transferred"
                degree_status = f"{major or degree_status} coursework"
            elif active_program:
                status_note = f"in progress; expected {expected_year}" if expected_year else "in progress"
            elif not received:
                status_note = "not completed"
            else:
                status_note = f"conferred {end_year}"
            if major and status not in {"transferred", "transfer"} and major.casefold() not in degree_status.casefold():
                degree_status = f"{degree_status} in {major}"
            try:
                gpa_eligible = float(str(sch.get("gpa", ""))) >= 3.5
            except ValueError:
                gpa_eligible = False
            show_gpa = sch.get("show_gpa", gpa_eligible)
            gpa_as_of = str(sch.get("gpa_as_of", "")).strip()
            if gpa_as_of:
                try:
                    parsed_gpa_date = datetime.strptime(gpa_as_of, "%Y-%m-%d")
                    gpa_as_of = f"{parsed_gpa_date.strftime('%B')} {parsed_gpa_date.day}, {parsed_gpa_date.year}"
                except ValueError:
                    pass
            gpa_note = f" (as of {gpa_as_of})" if gpa_as_of else ""
            gpa_str = f" | GPA: {sch['gpa']}{gpa_note}" if show_gpa and sch.get("gpa") else ""
            credits_str = (
                f" | Earned credits: {sch['units']}"
                if active_program and sch.get("units") and sch.get("units_scope") == "total"
                else ""
            )
            show_minor = bool(sch.get("show_minor", active_program))
            minor_str = f" | Minor: {sch['minor']}" if show_minor and sch.get("minor") else ""
            lines.append(f"{degree_status} ({status_note})")
            lines.append(
                f"{sch['school']} | {sch['city_state']} | "
                f"{sch['start_year']}-{end_year}{gpa_str}{credits_str}{minor_str}"
            )
            completed_coursework = _structured_coursework(
                sch.get("completed_coursework"), limit=COMPLETED_COURSEWORK_MAX_ITEMS
            )
            current_coursework = _structured_coursework(
                sch.get("current_coursework"), limit=CURRENT_COURSEWORK_MAX_ITEMS
            )
            if completed_coursework:
                lines.append(f"Relevant completed coursework: {'; '.join(completed_coursework)}")
            if current_coursework:
                lines.append(f"Current coursework: {'; '.join(current_coursework)}")
            lines.append("")
    else:
        lines.append("Not provided")

    return "\n".join(lines)


# â”€â”€ LLM Judge â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€


def judge_tailored_resume(original_text: str, tailored_text: str, job_title: str, profile: dict) -> dict:
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
        {
            "role": "user",
            "content": (
                f"JOB TITLE: {job_title}\n\n"
                f"ORIGINAL RESUME:\n{original_text}\n\n---\n\n"
                f"TAILORED RESUME:\n{tailored_text}\n\n"
                "Judge this tailored resume:"
            ),
        },
    ]

    client = get_client_for_stage("judge")
    response = client.chat(messages, max_tokens=512, temperature=0.1)

    passed = "VERDICT: PASS" in response.upper()
    issues = "none"
    if "ISSUES:" in response.upper():
        issues_idx = response.upper().index("ISSUES:")
        issues = response[issues_idx + 7 :].strip()

    return {
        "passed": passed,
        "verdict": "PASS" if passed else "FAIL",
        "issues": issues,
        "raw": response,
    }


def _judge_rejection_contradicts_candidate_evidence(
    judge: dict,
    profile: dict,
    original_text: str,
) -> bool:
    """Detect a narrow absence-only judge failure contradicted by exact evidence."""
    if judge.get("passed"):
        return False
    issues = str(judge.get("issues") or "")
    lowered = issues.casefold()
    absence_markers = (
        "not supported",
        "unsupported",
        "absent from",
        "not present",
        "only supports",
        "does not list",
        "neither is supported",
    )
    context_markers = (
        "paid work",
        "paid-work",
        "professional experience",
        "work history",
        "job bullet",
        "employer",
        "company",
        "moves ",
        "moved ",
        "attribut",
    )
    if not any(marker in lowered for marker in absence_markers):
        return False
    if any(marker in lowered for marker in context_markers):
        return False
    quoted = [
        left or right
        for left, right in re.findall(r'[“"]([^”"]+)[”"]|[‘]([^’]+)[’]', issues)
        if left or right
    ]
    canonical_resume = assemble_resume_text(
        {
            "title": "",
            "summary": "",
            "skills_section_title": "TECHNICAL SKILLS",
            "skills": {},
            "experience": [],
            "projects": [],
        },
        profile,
    )
    canonical_evidence = " ".join(canonical_resume.casefold().split())

    def supported(phrase: str) -> bool:
        normalized = " ".join(phrase.casefold().split()).strip(" .:-")
        return candidate_evidence_supports(phrase, profile, original_text) or normalized in canonical_evidence

    return bool(quoted) and all(supported(phrase) for phrase in quoted)


# â”€â”€ Core Tailoring â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€


def tailor_resume(
    resume_text: str,
    job: dict,
    profile: dict,
    max_retries: int = 3,
    validation_mode: str = "normal",
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
        validation_mode:  "strict", "normal", "lenient", or "none".
                          strict  -- banned words trigger retries; judge must pass
                          normal  -- banned words = warnings only; judge can fail on last retry
                          lenient -- banned words ignored; LLM judge skipped

    Returns:
        (tailored_text, report) where report contains validation details.
    """
    gap_targets = ""
    if job.get("score_breakdown"):
        try:
            breakdown = json.loads(job["score_breakdown"])
            gaps = breakdown.get("skill_gaps") or breakdown.get("keyword", {}).get("misses") or []
            gaps = [str(gap) for gap in gaps if str(gap).strip()][:10]
            if gaps:
                gap_targets = "\n\nSCORING GAPS TO ADDRESS ONLY IF TRUTHFULLY SUPPORTED BY THE RESUME:\n" + ", ".join(
                    gaps
                )
        except (TypeError, json.JSONDecodeError):
            gap_targets = ""

    job_text = format_job_context(job, description_limit=4000, extra=gap_targets)

    report: dict = {
        "attempts": 0,
        "validator": None,
        "judge": None,
        "status": "pending",
        "validation_mode": validation_mode,
    }
    avoid_notes: list[str] = []
    tailored = ""
    client = get_client_for_stage("tailor")
    tailor_prompt_base = _build_tailor_prompt(profile)

    for attempt in range(max_retries + 1):
        report["attempts"] = attempt + 1
        report["validator"] = None
        report["text_validator"] = None
        report["judge"] = None

        # Fresh conversation every attempt
        prompt = tailor_prompt_base
        if avoid_notes:
            prompt += "\n\n## AVOID THESE ISSUES (from previous attempt):\n" + "\n".join(
                f"- {n}" for n in avoid_notes[-5:]
            )

        messages = [
            {"role": "system", "content": prompt},
            {
                "role": "user",
                "content": f"ORIGINAL RESUME:\n{resume_text}\n\n---\n\nTARGET JOB:\n{job_text}\n\nReturn the JSON:",
            },
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
        data["skills"] = prune_unsupported_tailored_skills(
            data.get("skills"),
            profile,
            original_text=resume_text,
        )

        # Layer 1: Validate JSON fields
        validation = validate_json_fields(
            data,
            profile,
            mode=validation_mode,
            original_text=resume_text,
        )
        report["validator"] = validation

        if not validation["passed"]:
            # Only retry if there are hard errors (warnings never block)
            log.warning("Attempt %d validation errors: %s", attempt + 1, validation["errors"])
            avoid_notes.extend(validation["errors"])
            if attempt < max_retries:
                continue
            # Last attempt â€” assemble whatever we got
            tailored = assemble_resume_text(data, profile)
            report["status"] = "failed_validation"
            return tailored, report

        # Assemble text (header injected by code, em dashes auto-fixed)
        tailored = assemble_resume_text(data, profile)

        # Layer 2: Programmatic text validation, including one-page length checks.
        text_validation = validate_tailored_resume(tailored, profile, original_text=resume_text, mode=validation_mode)
        report["text_validator"] = text_validation

        if not text_validation["passed"]:
            log.warning("Attempt %d text validation errors: %s", attempt + 1, text_validation["errors"])
            avoid_notes.extend(text_validation["errors"])
            if attempt < max_retries:
                continue
            report["status"] = "failed_validation"
            return tailored, report

        # Layer 3: LLM judge (catches subtle fabrication) â€” skipped in lenient/none mode
        if validation_mode in ("lenient", "none"):
            report["judge"] = {"verdict": "SKIPPED", "passed": True, "issues": "none"}
            report["status"] = "approved"
            return tailored, report

        judge = judge_tailored_resume(resume_text, tailored, job.get("title", ""), profile)
        if _judge_rejection_contradicts_candidate_evidence(judge, profile, resume_text):
            original_issues = str(judge.get("issues") or "")
            log.warning("Judge absence claim contradicted exact candidate evidence; applying deterministic pass")
            judge = {
                **judge,
                "passed": True,
                "verdict": "PASS",
                "issues": "none",
                "evidence_override": original_issues,
            }
        report["judge"] = judge

        if not judge["passed"]:
            avoid_notes.append(f"Judge rejected: {judge['issues']}")
            if attempt < max_retries:
                # Retry if retries remain
                continue
            # Strict mode is a release gate; normal mode retains historical
            # warning-success behavior for explicitly less strict workflows.
            report["status"] = "failed_judge" if validation_mode == "strict" else "approved_with_judge_warning"
            return tailored, report

        # Both passed
        report["status"] = "approved"
        return tailored, report

    report["status"] = "exhausted_retries"
    return tailored, report


# â”€â”€ Batch Entry Point â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€


def run_tailoring(
    min_score: int = 7,
    limit: int = 20,
    validation_mode: str = "normal",
    target_url: str | None = None,
) -> dict:
    """Generate tailored resumes for high-scoring jobs.

    Args:
        min_score:       Minimum fit_score to tailor for.
        limit:           Maximum jobs to process.
        validation_mode: "strict", "normal", or "lenient".
        target_url: If provided, tailor only this job URL.

    Returns:
        {"approved": int, "failed": int, "errors": int, "elapsed": float}
    """
    profile = load_profile()
    resume_text = RESUME_PATH.read_text(encoding="utf-8")
    conn = get_connection()

    if target_url:
        jobs = conn.execute(
            """
            SELECT * FROM jobs
            WHERE url = ? AND fit_score >= ? AND {meaningful_full_description}
              AND {actionable_job}
              AND archived_at IS NULL
              AND tailored_resume_path IS NULL
              AND COALESCE(tailor_attempts, 0) < ?
            """.format(
                meaningful_full_description=MEANINGFUL_FULL_DESCRIPTION_SQL,
                actionable_job=ACTIONABLE_JOB_SQL,
            ),
            (target_url, min_score, MAX_ATTEMPTS),
        ).fetchall()
        if jobs and not isinstance(jobs[0], dict):
            columns = jobs[0].keys()
            jobs = [dict(zip(columns, row)) for row in jobs]
    else:
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
            job_profile = profile_for_job_resume_location(profile, job)
            tailored, report = tailor_resume(
                resume_text,
                job,
                job_profile,
                validation_mode=validation_mode,
            )

            txt_path, job_path, report_path = tailored_artifact_paths(TAILORED_DIR, job)
            txt_path.write_text(tailored, encoding="utf-8")
            protect_file(txt_path)

            # Save job description for traceability
            job_path.write_text(_format_job_trace(job), encoding="utf-8")
            protect_file(job_path)

            # Save validation report
            report_path.write_text(json.dumps(report, indent=2), encoding="utf-8")
            protect_file(report_path)

            # Generate PDF for approved resumes (best-effort)
            # "approved_with_judge_warning" is also a success â€” resume was generated.
            pdf_path = None
            artifact_path = None
            if report["status"] in ("approved", "approved_with_judge_warning"):
                artifact_path = str(txt_path)
                try:
                    from divapply.scoring.pdf import convert_to_pdf

                    pdf_path = str(convert_to_pdf(txt_path))
                    artifact_path = pdf_path
                    _delete_temp_artifacts(txt_path, job_path, report_path)
                except Exception:
                    log.debug("PDF generation failed for %s", txt_path, exc_info=True)
            else:
                # Strict failures are private review artifacts, not application
                # artifacts. Keep the text, trace, and report for human review,
                # but never persist their path to the job row.
                if validation_mode != "strict":
                    _delete_temp_artifacts(txt_path, job_path, report_path)

            result = {
                "url": job["url"],
                "path": artifact_path,
                "pdf_path": pdf_path,
                "cleanup_paths": [str(txt_path), str(job_path), str(report_path)] + ([pdf_path] if pdf_path else []),
                "title": job["title"],
                "site": job["site"],
                "status": report["status"],
                "attempts": report["attempts"],
            }
        except Exception as e:
            result = {
                "url": job["url"],
                "title": job["title"],
                "site": job["site"],
                "status": "error",
                "attempts": 0,
                "path": None,
                "pdf_path": None,
            }
            log.error("%d/%d [ERROR] %s -- %s", completed, len(jobs), job["title"][:40], e)

        results.append(result)
        stats[result.get("status", "error")] = stats.get(result.get("status", "error"), 0) + 1

        elapsed = time.time() - t0
        rate = completed / elapsed if elapsed > 0 else 0
        log.info(
            "%d/%d [%s] attempts=%s | %.1f jobs/min | %s",
            completed,
            len(jobs),
            result["status"].upper(),
            result.get("attempts", "?"),
            rate * 60,
            result["title"][:40],
        )

    # Persist to DB: increment attempt counter for ALL, save path only for approved
    now = datetime.now(timezone.utc).isoformat()
    _success_statuses = {"approved", "approved_with_judge_warning"}
    saved_approved = 0
    for r in results:
        if r["status"] in _success_statuses and r.get("path"):
            cursor = conn.execute(
                "UPDATE jobs SET tailored_resume_path=?, tailored_at=?, "
                "tailor_attempts=COALESCE(tailor_attempts,0)+1 "
                "WHERE url=? AND archived_at IS NULL",
                (r["path"], now, r["url"]),
            )
            if cursor.rowcount > 0:
                saved_approved += 1
            else:
                _delete_unpersisted_artifacts(*(Path(path) for path in r.get("cleanup_paths", []) if path))
        else:
            conn.execute(
                "UPDATE jobs SET tailor_attempts=COALESCE(tailor_attempts,0)+1 WHERE url=? AND archived_at IS NULL",
                (r["url"],),
            )
    conn.commit()

    elapsed = time.time() - t0
    approved_count = saved_approved
    log.info(
        "Tailoring done in %.1fs: %d approved, %d failed_validation, %d failed_judge, %d errors",
        elapsed,
        approved_count,
        stats.get("failed_validation", 0),
        stats.get("failed_judge", 0),
        stats.get("error", 0),
    )

    return {
        "approved": approved_count,
        "failed": stats.get("failed_validation", 0) + stats.get("failed_judge", 0),
        "errors": stats.get("error", 0),
        "elapsed": elapsed,
    }
