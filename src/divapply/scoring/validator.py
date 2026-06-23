"""Resume and cover letter validation: banned words, fabrication detection, structural checks.

All validation is profile-driven -- no hardcoded personal data. The validator receives
a profile dict (from divapply.config.load_profile()) and validates against the user's
actual skills, companies, projects, and school.

Validation modes
----------------
strict  -- banned words = hard errors that trigger retries (original behavior)
normal  -- banned words = warnings only; fabrication/structure = errors (default)
lenient -- banned words ignored; only fabrication and required structure checked
none    -- validation skipped entirely; use only for debugging
"""

import re
import logging

from divapply.config import profile_skills

log = logging.getLogger(__name__)


# â”€â”€ Universal Constants (not personal data) â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

BANNED_WORDS: list[str] = [
    "passionate", "dedicated", "committed to",
    "utilizing", "utilize", "harnessing",
    "spearheaded", "spearhead", "orchestrated", "championed", "pioneered",
    "robust", "scalable solutions", "cutting-edge", "state-of-the-art", "best-in-class",
    "proven track record", "track record of success", "demonstrated ability",
    "strong communicator", "team player", "fast learner", "self-starter", "go-getter",
    "synergy", "cross-functional collaboration", "holistic",
    "transformative", "innovative solutions", "paradigm", "ecosystem",
    "proactive", "detail-oriented", "highly motivated",
    "seamless", "full lifecycle",
    "deep understanding", "extensive experience", "comprehensive knowledge",
    "thrives in", "excels at", "adept at", "well-versed in",
    "i am confident", "i believe", "i am excited",
    "plays a critical role", "instrumental in", "integral part of",
    "strong track record", "eager to", "eager",
    # Cover-letter-specific additions
    "this demonstrates", "this reflects", "i have experience with",
    "furthermore", "additionally", "moreover",
]

LLM_LEAK_PHRASES: list[str] = [
    "i am sorry", "i apologize", "i will try", "let me try",
    "i am at a loss", "i am truly sorry", "apologies for",
    "i keep fabricating", "i will have to admit", "one final attempt",
    "one last time", "if it fails again", "persistent errors",
    "i am having difficulty", "i made an error", "my mistake",
    "here is the corrected", "here is the revised", "here is the updated",
    "here is my", "below is the", "as requested",
    "note:", "disclaimer:", "important:",
    "i have rewritten", "i have removed", "i have fixed",
    "i have replaced", "i have updated", "i have corrected",
    "per your feedback", "based on your feedback", "as per the instructions",
    "the following resume", "the resume below",
    "the following cover letter", "the letter below",
]

# Known fabrication markers: completely unrelated tools/languages.
# Reasonable stretches (K8s, Terraform, Redis, Kafka etc.) are ALLOWED.
FABRICATION_WATCHLIST: set[str] = {
    # Languages with zero relation to the candidate's stack
    "c#", "c++", "golang", "rust", "ruby",
    "kotlin", "swift", "scala", "matlab",
    # Frameworks for wrong languages
    "spring", "django", "rails", "angular", "vue", "svelte",
    # Hard lies: certifications can't be stretched
    "certif", "certified", "pmp", "scrum master", "aws certified",
}

COVER_LETTER_TOOL_TERMS: set[str] = FABRICATION_WATCHLIST | {
    "aws", "azure", "gcp", "google cloud",
    "docker", "kubernetes", "terraform", "ansible",
    "react", "node", "node.js", "typescript", "javascript",
    "java", "golang", "ruby", "php",
    "salesforce", "tableau", "power bi", "servicenow",
    "quickbooks", "workday", "oracle", "sap",
    "certification", "licensed", "license",
}

COVER_LETTER_CREDENTIAL_TERMS: set[str] = {
    "api key",
    "apikey",
    "credential",
    "credentials",
    "login",
    "password",
    "passcode",
    "secret",
    "token",
}

GENERIC_COVER_LETTER_PHRASES: list[str] = [
    "i am writing to express my interest",
    "i am thrilled to apply",
    "i am excited to apply",
    "i would be honored",
    "perfect fit",
    "unique blend",
    "dynamic team",
    "esteemed organization",
    "bring value to your organization",
    "thank you for your time and consideration",
]

REQUIRED_SECTIONS: set[str] = {"SUMMARY", "TECHNICAL SKILLS", "EXPERIENCE", "PROJECTS", "EDUCATION"}


# â”€â”€ Helpers â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

def _build_skills_set(profile: dict) -> set[str]:
    """Build the set of allowed skills from the profile's skills_boundary."""
    allowed: set[str] = set()
    for category in profile_skills(profile).values():
        allowed.update(s.lower().strip() for s in category)
    return allowed


def _normalized_skill_aliases(profile: dict) -> set[str]:
    """Return lower-case skill aliases allowed in generated documents."""
    aliases = _build_skills_set(profile)
    expanded = set(aliases)
    for skill in aliases:
        expanded.add(skill.replace(".", ""))
        if skill == "node.js":
            expanded.add("node")
        if skill == "javascript":
            expanded.add("js")
    return expanded


def _split_skill_tokens(raw: str) -> list[str]:
    """Split a profile/coursework skill summary into comparable skill tokens."""
    if ":" in raw:
        raw = raw.split(":", 1)[1]
    parts = re.split(r"[,;/|]", raw)
    return [part.strip().lower() for part in parts if part.strip()]


def _build_coursework_skills_set(profile: dict) -> set[str]:
    """Return skills supported by coursework summaries, not paid work."""
    skills: set[str] = set()
    for item in profile.get("coursework_skills", []) or []:
        if isinstance(item, str):
            skills.update(_split_skill_tokens(item))
        elif isinstance(item, dict):
            for value in item.values():
                if isinstance(value, str):
                    skills.update(_split_skill_tokens(value))
                elif isinstance(value, list):
                    skills.update(str(skill).strip().lower() for skill in value if str(skill).strip())
    for row in profile.get("coursework", []) or []:
        raw_skills = row.get("skills") if isinstance(row, dict) else None
        if isinstance(raw_skills, list):
            skills.update(str(skill).strip().lower() for skill in raw_skills if str(skill).strip())
        elif isinstance(raw_skills, str):
            skills.update(_split_skill_tokens(raw_skills))
    return {skill for skill in skills if len(skill) > 1}


def _profile_evidence_text(profile: dict, original_text: str = "") -> str:
    """Flatten verified facts into a lower-case evidence string."""
    chunks: list[str] = [original_text]
    chunks.extend(skill for skills in profile_skills(profile).values() for skill in skills)
    chunks.extend(profile.get("coursework_summary", []) or [])
    chunks.extend(profile.get("coursework_skills", []) or [])
    resume_facts = profile.get("resume_facts", {}) or {}
    for value in resume_facts.values():
        if isinstance(value, list):
            chunks.extend(str(item) for item in value)
        elif value:
            chunks.append(str(value))
    for cert in profile.get("certifications", []) or []:
        chunks.append(str(cert))
    for school in profile.get("education_schools", []) or []:
        if isinstance(school, dict):
            chunks.extend(str(value) for value in school.values() if value)
    return " ".join(chunks).lower()


def _add_unsupported_metric_findings(text: str, profile: dict, errors: list[str]) -> None:
    """Reject generated numeric outcome claims not present in verified metrics."""
    resume_facts = profile.get("resume_facts", {}) or {}
    allowed_metrics = " ".join(str(metric).lower() for metric in resume_facts.get("real_metrics", []) or [])
    metric_patterns = (
        r"\b\d+(?:\.\d+)?\s?%",
        r"\b\d+(?:\.\d+)?\s?(?:x|times)\b",
        r"\b\d+(?:\.\d+)?\s?(?:hours?|hrs?|minutes?|mins?|transactions?|tickets?|calls?|users?|devices?|systems?)\b",
    )
    for pattern in metric_patterns:
        for match in re.finditer(pattern, text, flags=re.IGNORECASE):
            metric = match.group(0).lower()
            if metric not in allowed_metrics:
                errors.append(f"Unsupported metric: '{match.group(0)}'")


def _add_unsupported_credential_findings(text: str, evidence_text: str, errors: list[str]) -> None:
    """Reject generated credential/degree claims that are absent from verified facts."""
    patterns = (
        r"\b(?:certified|certification|certificate|license|licensed|clearance)\b",
        r"\b(?:associate|bachelor|master|phd|doctorate|degree)\b",
        r"\b(?:aws certified|pmp|scrum master|comptia|a\+|network\+|security\+)\b",
    )
    for pattern in patterns:
        for match in re.finditer(pattern, text, flags=re.IGNORECASE):
            claim = match.group(0).lower()
            if claim not in evidence_text:
                errors.append(f"Unsupported credential or degree claim: '{match.group(0)}'")


def _add_coursework_as_work_findings(
    experience_entries: list[dict],
    profile: dict,
    original_text: str,
    errors: list[str],
) -> None:
    """Reject coursework-only skills when they are claimed inside paid work."""
    coursework_skills = _build_coursework_skills_set(profile)
    if not coursework_skills:
        return
    paid_work_evidence = (original_text + " " + " ".join(_build_skills_set(profile))).lower()
    coursework_only = {skill for skill in coursework_skills if skill not in paid_work_evidence}
    if not coursework_only:
        return
    for entry in experience_entries:
        header = str(entry.get("header", "")).lower()
        subtitle = str(entry.get("subtitle", "")).lower()
        context = f"{header} {subtitle}"
        if "course" in context or "project" in context or "school" in context:
            continue
        for bullet in entry.get("bullets", []) or []:
            bullet_lower = str(bullet).lower()
            for skill in sorted(coursework_only):
                if re.search(r"\b" + re.escape(skill) + r"\b", bullet_lower):
                    errors.append(f"Coursework-only skill used as paid work: '{skill}'")


def _section_text(text: str, section: str, next_sections: tuple[str, ...]) -> str:
    """Return text between an uppercase resume section and the next section."""
    pattern = r"(?im)^" + re.escape(section) + r"\s*$"
    match = re.search(pattern, text)
    if not match:
        return ""
    start = match.end()
    end = len(text)
    for next_section in next_sections:
        next_match = re.search(r"(?im)^" + re.escape(next_section) + r"\s*$", text[start:])
        if next_match:
            end = min(end, start + next_match.start())
    return text[start:end]


def sanitize_text(text: str) -> str:
    """Auto-fix common LLM output issues instead of rejecting."""
    text = text.replace(" \u2014 ", ", ").replace("\u2014", ", ")   # em dash -> comma
    text = text.replace("\u2013", "-")    # en dash -> hyphen
    text = text.replace("\u201c", '"').replace("\u201d", '"')   # smart double quotes
    text = text.replace("\u2018", "'").replace("\u2019", "'")   # smart single quotes
    return text.strip()


def _add_banned_word_findings(text: str, mode: str, errors: list[str], warnings: list[str]) -> None:
    """Append banned-word findings using the configured validation mode."""
    if mode == "lenient":
        return
    found = [word for word in BANNED_WORDS if re.search(r"\b" + re.escape(word) + r"\b", text)]
    if not found:
        return
    msg = f"Banned words: {', '.join(found[:5])}"
    if mode == "strict":
        errors.append(msg)
    else:
        warnings.append(msg)


def _add_llm_leak_findings(text: str, errors: list[str]) -> None:
    """Append an error when model self-talk leaked into generated content."""
    found = [phrase for phrase in LLM_LEAK_PHRASES if phrase in text]
    if found:
        errors.append(f"LLM self-talk: '{found[0]}'")


def _term_in_text(term: str, text: str) -> bool:
    """Match a skill/tool term as a phrase without substring false positives."""
    return bool(re.search(r"(?<![\w+#.])" + re.escape(term) + r"(?![\w+#.])", text))


def _add_cover_letter_tool_findings(
    text_lower: str,
    profile: dict | None,
    resume_text: str,
    job: dict | None,
    errors: list[str],
) -> None:
    """Reject unsupported tools, credentials, and job-only tool claims."""
    for term in COVER_LETTER_CREDENTIAL_TERMS:
        if _term_in_text(term, text_lower):
            errors.append(f"Private credential mentioned: '{term}'")
            return

    profile = profile or {}
    allowed = _normalized_skill_aliases(profile)
    evidence = (resume_text or "").lower()
    if profile:
        for term in COVER_LETTER_TOOL_TERMS:
            if term in allowed:
                continue
            if _term_in_text(term, text_lower) and not _term_in_text(term, evidence):
                errors.append(f"Unsupported tool or credential mentioned: '{term}'")
                return

    if not job:
        return

    job_text = " ".join(
        str(job.get(key) or "")
        for key in ("title", "company", "site", "location", "full_description", "description")
    ).lower()
    for term in COVER_LETTER_TOOL_TERMS:
        if term in allowed or _term_in_text(term, evidence):
            continue
        if _term_in_text(term, job_text) and _term_in_text(term, text_lower):
            errors.append(f"Job-only tool or credential claimed: '{term}'")
            return


def _add_cover_letter_job_specificity_findings(
    text_lower: str,
    job: dict | None,
    warnings: list[str],
) -> None:
    """Warn when the letter does not anchor itself to the target posting."""
    if not job:
        return
    anchors = [
        str(job.get("company") or "").strip().lower(),
        str(job.get("title") or "").strip().lower(),
    ]
    description = str(job.get("full_description") or job.get("description") or "").lower()
    for candidate in re.findall(r"\b[a-z][a-z0-9+#.]{3,}\b", description):
        if candidate not in {"required", "preferred", "responsibilities", "experience", "ability"}:
            anchors.append(candidate)
        if len(anchors) >= 8:
            break
    if not any(anchor and anchor in text_lower for anchor in anchors):
        warnings.append("Cover letter does not reference the target role, company, or job description.")


# â”€â”€ JSON Field Validation â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

def validate_json_fields(data: dict, profile: dict, mode: str = "normal") -> dict:
    """Validate individual JSON fields from an LLM-generated tailored resume.

    Args:
        data:    Parsed JSON from the LLM (title, summary, skills, experience, projects, education).
        profile: User profile dict from load_profile().
        mode:    Validation strictness â€” "strict", "normal", "lenient", or "none".
                 strict  â†’ banned words are errors (trigger retries)
                 normal  â†’ banned words are warnings (no retry)
                 lenient â†’ banned words ignored entirely
                 none    â†’ skip validation entirely

    Returns:
        {"passed": bool, "errors": list[str], "warnings": list[str]}
    """
    errors: list[str] = []
    warnings: list[str] = []

    # none mode: accept whatever the LLM returned, no checks at all
    if mode == "none":
        return {"passed": True, "errors": [], "warnings": []}

    # Required keys â€” always checked regardless of mode
    # education is injected by code (not LLM), projects can be empty []
    for key in ("title", "summary", "skills", "experience"):
        if key not in data or not data[key]:
            errors.append(f"Missing required field: {key}")
    # projects must exist but can be empty list
    if "projects" not in data:
        errors.append("Missing required field: projects")
    if data.get("education"):
        errors.append("Education must be injected from profile, not LLM output")
    if errors:
        return {"passed": False, "errors": errors, "warnings": warnings}

    # Collect all text for bulk checks
    all_text_parts: list[str] = [data["summary"]]

    # Skills: check for fabrication (always enforced)
    if isinstance(data["skills"], dict):
        skills_text = " ".join(str(v) for v in data["skills"].values()).lower()
        evidence_text = _profile_evidence_text(profile)
        for fake in FABRICATION_WATCHLIST:
            if len(fake) <= 2:
                continue
            if fake in skills_text and fake not in evidence_text:
                errors.append(f"Fabricated skill: '{fake}'")

    # Experience: check preserved companies (first 2 are required, rest are warnings)
    resume_facts = profile.get("resume_facts", {})
    preserved_companies = resume_facts.get("preserved_companies", [])

    if isinstance(data["experience"], list):
        for i, company in enumerate(preserved_companies):
            has_company = any(
                company.lower() in (
                    str(e.get("header", "")) + " " + str(e.get("subtitle", ""))
                ).lower()
                for e in data["experience"]
            )
            if not has_company:
                if i < 2:  # First 2 companies are required (most recent)
                    errors.append(f"Company '{company}' missing from experience")
                else:
                    warnings.append(f"Company '{company}' not in experience (may have been dropped for relevance)")
        for entry in data["experience"]:
            for b in entry.get("bullets", []):
                all_text_parts.append(b)
        _add_coursework_as_work_findings(data["experience"], profile, "", errors)

    # Projects: collect bullets
    if isinstance(data["projects"], list):
        for entry in data["projects"]:
            for b in entry.get("bullets", []):
                all_text_parts.append(b)

    # Education is now injected by code from profile, not LLM-generated.
    # Skip validation of education in LLM output since it's always correct.

    # Bulk text checks
    all_text = " ".join(all_text_parts).lower()
    evidence_text = _profile_evidence_text(profile)
    _add_unsupported_metric_findings(all_text, profile, errors)
    _add_unsupported_credential_findings(all_text, evidence_text, errors)

    # LLM self-talk is always an error regardless of mode (indicates broken output)
    _add_llm_leak_findings(all_text, errors)

    # Banned filler words â€” severity depends on mode
    _add_banned_word_findings(all_text, mode, errors, warnings)

    return {"passed": len(errors) == 0, "errors": errors, "warnings": warnings}


# â”€â”€ Full Resume Text Validation â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

def validate_tailored_resume(
    text: str,
    profile: dict,
    original_text: str = "",
    mode: str = "normal",
) -> dict:
    """Programmatic validation of a tailored resume against the user's profile.

    Args:
        text: The tailored resume text to validate.
        profile: User profile dict from load_profile().
        original_text: The original base resume text (for fabrication comparison).
        mode: Validation strictness (matches validate_json_fields):
              strict  -> banned words = errors (trigger retries)
              normal  -> banned words = warnings (no retry)
              lenient -> banned words ignored entirely
              none    -> skip validation entirely

    Returns:
        {"passed": bool, "errors": list[str], "warnings": list[str]}
    """
    if mode == "none":
        return {"passed": True, "errors": [], "warnings": []}

    errors: list[str] = []
    warnings: list[str] = []
    text_lower = text.lower()

    personal = profile.get("personal", {})
    resume_facts = profile.get("resume_facts", {})

    # 1. Check required sections exist (flexible matching). PROJECTS is
    # optional: the tailor prompt explicitly allows an empty projects list,
    # in which case assemble_resume_text drops the section entirely.
    section_variants: dict[str, list[str]] = {
        "SUMMARY": ["summary", "professional summary", "profile"],
        "TECHNICAL SKILLS": ["technical skills", "skills", "tech stack", "core skills", "technologies"],
        "EXPERIENCE": ["experience", "work experience", "professional experience"],
        "EDUCATION": ["education", "academic background"],
    }
    for section, variants in section_variants.items():
        if not any(v in text_lower for v in variants):
            errors.append(f"Missing required section: {section} (or variant)")

    # 2. Check name preserved (warn, don't error -- we can inject it)
    full_name = personal.get("full_name", "")
    if full_name and full_name.lower() not in text_lower:
        warnings.append(f"Name '{full_name}' missing -- will be injected")

    # 3. Check companies preserved (first 2 required, rest are warnings)
    for i, company in enumerate(resume_facts.get("preserved_companies", [])):
        if company.lower() not in text_lower:
            if i < 2:
                errors.append(f"Company '{company}' missing -- cannot remove real experience")
            else:
                warnings.append(f"Company '{company}' not in resume (may have been dropped for relevance)")

    # 4. Check projects preserved
    for project in resume_facts.get("preserved_projects", []):
        if project.lower() not in text_lower:
            warnings.append(f"Project '{project}' not found -- may have been renamed")

    # 5. Education injected by code â€” skip school check on LLM text

    # 6. Check contact info preserved (warn, don't error -- we can inject)
    email = personal.get("email", "")
    phone = personal.get("phone", "")
    if email and email.lower() not in text_lower:
        warnings.append("Email missing -- will be injected")
    if phone and phone not in text:
        warnings.append("Phone missing -- will be injected")

    # 7. Scan TECHNICAL SKILLS section for fabricated tools
    skills_start = text_lower.find("technical skills")
    skills_end = text_lower.find("experience", skills_start) if skills_start != -1 else -1
    if skills_start != -1 and skills_end != -1:
        skills_block = text_lower[skills_start:skills_end]
        evidence_text = _profile_evidence_text(profile, original_text)
        for fake in FABRICATION_WATCHLIST:
            if len(fake) <= 2:
                continue
            if fake in skills_block and fake not in evidence_text:
                errors.append(f"FABRICATED SKILL in Technical Skills: '{fake}'")

    # 8. Scan full document for fabrication watchlist items not in original
    if original_text:
        original_lower = original_text.lower()
        for fake in FABRICATION_WATCHLIST:
            if len(fake) <= 2:
                continue
            if fake in text_lower and fake not in original_lower:
                warnings.append(f"New tool/skill appeared: '{fake}' (not in original)")

    # 8b. Coursework-only skills may appear in skills, but not as paid-work duties.
    experience_block = _section_text(text, "EXPERIENCE", ("PROJECTS", "EDUCATION"))
    experience_entry = {"header": "EXPERIENCE", "subtitle": "", "bullets": experience_block.splitlines()}
    _add_coursework_as_work_findings([experience_entry], profile, original_text, errors)

    # 8c. Numeric outcomes and credential/degree claims must be supported.
    evidence_text = _profile_evidence_text(profile, original_text)
    _add_unsupported_metric_findings(text, profile, errors)
    non_education_text = text.replace(_section_text(text, "EDUCATION", ()), "")
    _add_unsupported_credential_findings(non_education_text.lower(), evidence_text, errors)

    # 9. Em dashes (should be auto-fixed by sanitize_text, but safety net)
    if "\u2014" in text or "\u2013" in text:
        errors.append("Contains em dash or en dash.")

    # 10. Banned words (word-boundary matching). Severity respects the
    # caller's validation mode so "normal"/"lenient" don't force retries
    # over filler-word complaints.
    _add_banned_word_findings(text_lower, mode, errors, warnings)

    # 11. LLM self-talk leak detection
    _add_llm_leak_findings(text_lower, errors)

    # 12. Duplicate section detection
    for section_name in ["summary", "experience", "education", "projects"]:
        count = text_lower.count(f"\n{section_name}\n") + text_lower.count(f"\n{section_name} \n")
        if text_lower.startswith(f"{section_name}\n"):
            count += 1
        if count > 1:
            errors.append(f"Section '{section_name}' appears {count} times.")

    # 13. One-page length guardrail
    body_lines = [
        line.strip() for line in text.splitlines()
        if line.strip()
        and "@" not in line
        and "linkedin.com" not in line.lower()
        and "github.com" not in line.lower()
    ]
    words = sum(len(line.split()) for line in body_lines)
    if words > 650:
        errors.append(f"Resume too long ({words} words). Target a one-page resume.")
    elif words > 575:
        warnings.append(f"Resume is getting long ({words} words). May spill onto a second page.")

    return {
        "passed": len(errors) == 0,
        "errors": errors,
        "warnings": warnings,
    }


# â”€â”€ Cover Letter Validation â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

def validate_cover_letter(
    text: str,
    mode: str = "normal",
    *,
    profile: dict | None = None,
    resume_text: str = "",
    job: dict | None = None,
) -> dict:
    """Programmatic validation of a cover letter.

    Args:
        text: The cover letter text to validate.
        mode: Validation strictness â€” "strict", "normal", "lenient", or "none".
              strict  â†’ banned words are errors (trigger retries); word limit enforced
              normal  â†’ banned words are warnings; word limit is soft (+25 words)
              lenient â†’ banned words ignored; word count not checked
              none    â†’ skip validation entirely
        profile: Optional profile dict used to catch unsupported tool mentions.
        resume_text: Optional resume text used as additional factual evidence.
        job: Optional job dict used for target-specific warnings and job-only tools.

    Returns:
        {"passed": bool, "errors": list[str], "warnings": list[str]}
    """
    errors: list[str] = []
    warnings: list[str] = []

    # none mode: accept everything
    if mode == "none":
        return {"passed": True, "errors": [], "warnings": []}

    text_lower = text.lower()

    # 1. Em dashes â€” always an error (sanitize_text should have caught these)
    if "\u2014" in text or "\u2013" in text:
        errors.append("Contains em dash or en dash.")

    # 2. Banned words â€” severity depends on mode
    _add_banned_word_findings(text_lower, mode, errors, warnings)

    generic = [phrase for phrase in GENERIC_COVER_LETTER_PHRASES if phrase in text_lower]
    if generic:
        msg = f"Generic cover-letter phrase: '{generic[0]}'"
        if mode != "lenient":
            errors.append(msg)

    # 3. Word count
    words = len(text.split())
    if mode == "strict" and words > 250:
        errors.append(f"Too long ({words} words). Max 250.")
    elif mode == "normal" and words > 275:
        errors.append(f"Too long ({words} words). Max 275.")
    # lenient: no word count check

    # 4. LLM self-talk â€” always an error regardless of mode
    _add_llm_leak_findings(text_lower, errors)

    # 4b. Unsupported tools and credentials are hard errors when profile/job
    # evidence is available.
    _add_cover_letter_tool_findings(text_lower, profile, resume_text, job, errors)
    _add_cover_letter_job_specificity_findings(text_lower, job, warnings)

    # 5. Must start with "Dear" â€” always checked (preamble should have been stripped)
    stripped = text.strip()
    if not stripped.lower().startswith("dear"):
        errors.append("Must start with 'Dear Hiring Manager,'")

    return {"passed": len(errors) == 0, "errors": errors, "warnings": warnings}

