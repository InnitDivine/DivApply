"""Text-to-PDF conversion for tailored resumes and cover letters.

Parses the structured text resume format, renders via an HTML/CSS template,
and exports to PDF using headless Chromium via Playwright.
"""

import logging
import re
import tempfile
import unicodedata
from collections import Counter
from html import escape as _html_escape
from pathlib import Path
from typing import TypedDict

from pypdf import PdfReader

from divapply.config import TAILORED_DIR
from divapply.security import protect_file

log = logging.getLogger(__name__)

ATS_MIN_TOKEN_COVERAGE = 0.97


class ATSPDFReport(TypedDict):
    pages: int
    source_tokens: int
    extracted_tokens: int
    token_coverage: float
    sections_in_order: bool


ATS_SECTION_LABELS = {
    "SUMMARY": "SUMMARY",
    "TECHNICAL SKILLS": "TECHNICAL SKILLS",
    "CORE QUALIFICATIONS": "CORE QUALIFICATIONS",
    "EXPERIENCE": "EXPERIENCE",
    "ADDITIONAL EXPERIENCE": "ADDITIONAL EXPERIENCE",
    "PROJECTS": "PROJECTS HOME LAB",
    "CERTIFICATIONS": "CERTIFICATIONS LICENSES",
    "EDUCATION": "EDUCATION",
}

SECTION_ALIASES = {
    "SUMMARY": "SUMMARY",
    "PROFESSIONAL SUMMARY": "SUMMARY",
    "PROFILE": "SUMMARY",
    "TECHNICAL SKILLS": "TECHNICAL SKILLS",
    "SKILLS": "TECHNICAL SKILLS",
    "CORE SKILLS": "TECHNICAL SKILLS",
    "CORE QUALIFICATIONS": "CORE QUALIFICATIONS",
    "EXPERIENCE": "EXPERIENCE",
    "PROFESSIONAL EXPERIENCE": "EXPERIENCE",
    "WORK EXPERIENCE": "EXPERIENCE",
    "EMPLOYMENT": "EXPERIENCE",
    "ADDITIONAL EXPERIENCE": "ADDITIONAL EXPERIENCE",
    "OTHER EXPERIENCE": "ADDITIONAL EXPERIENCE",
    "PROJECTS": "PROJECTS",
    "PROJECT EXPERIENCE": "PROJECTS",
    "PROJECTS & HOME LAB": "PROJECTS",
    "CERTIFICATIONS": "CERTIFICATIONS",
    "CERTIFICATIONS & LICENSES": "CERTIFICATIONS",
    "LICENSES": "CERTIFICATIONS",
    "EDUCATION": "EDUCATION",
}


def _clean_heading(line: str) -> str:
    """Normalize generated section headings while leaving content untouched."""
    cleaned = line.strip().strip("#").strip()
    cleaned = re.sub(r"^[*\-_\s]+|[*\-_\s]+$", "", cleaned)
    cleaned = cleaned.rstrip(":").strip()
    cleaned = re.sub(r"\s+", " ", cleaned)
    return cleaned.upper()


def _section_heading(line: str, *, allow_styled: bool = False) -> str | None:
    """Return canonical section name for a line that looks like a resume heading."""
    stripped = line.strip()
    if not stripped or stripped.startswith(("-", "\u2022")):
        return None

    cleaned = _clean_heading(stripped)
    if cleaned in SECTION_ALIASES:
        return SECTION_ALIASES[cleaned]

    if allow_styled:
        return None

    is_plain_caps = cleaned == cleaned.upper() and len(cleaned) > 3
    if is_plain_caps and not any(ch.isdigit() for ch in cleaned) and len(cleaned.split()) <= 4:
        return cleaned
    return None


# â”€â”€ Resume Parser â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€


def parse_resume(text: str) -> dict:
    """Parse a structured text resume into sections.

    Expects a format with header lines (name, title, location, contact)
    followed by ALL-CAPS section headers (SUMMARY, TECHNICAL SKILLS, etc.).

    Args:
        text: Full resume text.

    Returns:
        {"name": str, "title": str, "location": str, "contact": str, "sections": dict}
    """
    lines = [line.rstrip() for line in text.strip().replace("\r\n", "\n").split("\n")]

    # Header: first few lines before the first ALL-CAPS section header.
    # Strategy: section headers always appear AFTER at least one blank line
    # (they never appear on the very first line). This correctly handles:
    #   - Base resume: an all-caps name on line 0 â†’ header
    #   - Tailored resume: a mixed-case name on line 0 â†’ header
    #   - Section headers: "PROFESSIONAL SUMMARY", "SUMMARY", etc. â†’ body
    header_lines: list[str] = []
    body_start = 0
    found_blank = False
    for i, line in enumerate(lines):
        stripped = line.strip()
        if not stripped:
            found_blank = True
            continue
        # Section headers may be ALL-CAPS or generated as "Summary:"/Markdown.
        if found_blank and _section_heading(stripped, allow_styled=True):
            body_start = i
            break
        # Contact/social lines may be separated by blank lines. Keep every
        # nonempty header line until the first recognized body section.
        header_lines.append(stripped)

    name = header_lines[0] if len(header_lines) > 0 else ""
    title = ""
    location = ""
    contact = ""

    if len(header_lines) > 1:
        line1 = header_lines[1]
        # Detect if line 1 is a contact/location line rather than a job title.
        # Heuristic: contains "|" with digits (phone/zip) or "@" (email).
        is_contact_line = "@" in line1 or ("|" in line1 and any(c.isdigit() for c in line1))
        if is_contact_line:
            # Base-resume format: Name / location+contact / LinkedIn / GitHub
            contact = " | ".join(h for h in header_lines[1:] if h)
        else:
            # Tailored-resume format: Name / Title / contact
            title = line1
            if len(header_lines) > 2:
                first_detail = header_lines[2]
                detail_lower = first_detail.casefold()
                looks_like_contact = (
                    "@" in first_detail
                    or "http://" in detail_lower
                    or "https://" in detail_lower
                    or "linkedin" in detail_lower
                    or "github" in detail_lower
                    or ("|" in first_detail and any(c.isdigit() for c in first_detail))
                )
                if looks_like_contact:
                    contact = " | ".join(header_lines[2:])
                else:
                    location = first_detail
                    contact = " | ".join(header_lines[3:])

    if body_start == 0:
        for i, line in enumerate(lines[1:], start=1):
            if _section_heading(line, allow_styled=True):
                body_start = i
                break

    # Split body into sections by recognized headers.
    sections: dict[str, str] = {}
    current_section: str | None = None
    current_lines: list[str] = []

    for line in lines[body_start:]:
        stripped = line.strip()
        heading = _section_heading(stripped, allow_styled=True)
        if heading:
            if current_section:
                sections[current_section] = "\n".join(current_lines).strip()
            current_section = heading
            current_lines = []
        elif current_section:
            current_lines.append(line)

    if current_section:
        sections[current_section] = "\n".join(current_lines).strip()

    return {
        "name": name,
        "title": title,
        "location": location,
        "contact": contact,
        "sections": sections,
    }


def parse_skills(text: str) -> list[tuple[str, str]]:
    """Parse skills section into (category, value) pairs.

    Handles two formats:
    - Format A (tailored resumes): "Category: value1, value2"
    - Format B (base resume): Category header line followed by bullet points

    Args:
        text: The TECHNICAL SKILLS section text.

    Returns:
        List of (category_name, skills_string) tuples.
    """
    skills: list[tuple[str, str]] = []
    current_cat = ""
    current_bullets: list[str] = []

    def _flush() -> None:
        nonlocal current_cat, current_bullets
        if current_cat:
            value = ", ".join(current_bullets).strip()
            if value:
                skills.append((current_cat, value))
            current_cat = ""
            current_bullets = []

    for line in text.strip().split("\n"):
        stripped = line.strip()
        if not stripped:
            _flush()
            continue

        is_bullet = stripped.startswith("- ") or stripped.startswith("\u2022 ")
        has_colon = ":" in stripped and not is_bullet

        if has_colon:
            # Format A: "Category: value"
            _flush()
            cat, val = stripped.split(":", 1)
            if cat.strip() and val.strip():
                skills.append((cat.strip(), val.strip()))
        elif is_bullet:
            # Format B bullet: collect under current category
            if current_cat:
                current_bullets.append(stripped[2:].strip())
            elif ":" in stripped:
                cat, val = stripped[2:].split(":", 1)
                if cat.strip() and val.strip():
                    skills.append((cat.strip(), val.strip()))
        else:
            # Format B category header
            _flush()
            current_cat = stripped
            current_bullets = []

    _flush()

    return skills


def parse_entries(text: str) -> list[dict]:
    """Parse experience/project entries from section text.

    Args:
        text: The EXPERIENCE or PROJECTS section text.

    Returns:
        List of {"title": str, "subtitle": str, "bullets": list[str]} dicts.
    """
    entries: list[dict] = []
    lines = text.strip().split("\n")
    current: dict | None = None

    for line in lines:
        stripped = line.strip()
        if not stripped:
            continue
        if line[:1].isspace() and current and current.get("bullets"):
            current["bullets"][-1] = f"{current['bullets'][-1]} {stripped}"
            continue
        is_bullet = (
            stripped.startswith("- ") or stripped.startswith("\u2022 ") or bool(re.match(r"^\d+[.)]\s+", stripped))
        )
        if is_bullet:
            bullet = re.sub(r"^(?:[-\u2022]|\d+[.)])\s+", "", stripped).strip()
            if current:
                current["bullets"].append(bullet)
            else:
                current = {"title": "Highlights", "subtitle": "", "bullets": [bullet]}
        elif current is None or (
            not stripped.startswith("-") and not stripped.startswith("\u2022") and len(current.get("bullets", [])) > 0
        ):
            # New entry
            if current:
                entries.append(current)
            current = {"title": stripped, "subtitle": "", "bullets": []}
        elif current and not current["subtitle"]:
            current["subtitle"] = stripped
        else:
            if current:
                current["bullets"].append(stripped)

    if current:
        entries.append(current)

    return entries


# â”€â”€ HTML Template â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€


def build_html(resume: dict) -> str:
    """Build professional resume HTML from parsed data.

    Args:
        resume: Parsed resume dict from parse_resume().

    Returns:
        Complete HTML string ready for PDF rendering.
    """
    sections = resume["sections"]

    import re as _re

    visible_text = " ".join(
        str(value or "")
        for value in (
            resume.get("name"),
            resume.get("title"),
            resume.get("location"),
            resume.get("contact"),
            *sections.values(),
        )
    )
    visible_word_count = len(_re.findall(r"\b[\w'-]+\b", visible_text))
    if visible_word_count < 400:
        density_class = "resume-sparse"
    elif visible_word_count > 560:
        density_class = "resume-dense"
    else:
        density_class = "resume-standard"

    def _esc(value: object) -> str:
        """Escape resume-controlled text before injecting into HTML."""
        return _html_escape(str(value or ""), quote=True)

    def _find_key(secs: dict, *keywords: str) -> str | None:
        """Return first section key that contains any of the given keywords."""
        for k in secs:
            if any(kw in k for kw in keywords):
                return k
        return None

    # Skills - one linear column so ATS readers and humans share one order.
    skills_html = ""
    skills_key = _find_key(sections, "SKILL", "QUALIFICATION")
    if skills_key:
        skills = parse_skills(sections[skills_key])
        rows = ""
        for cat, val in skills:
            rows += f'<div class="skill-row"><span class="skill-cat">{_esc(cat)}:</span> {_esc(val)}</div>\n'
        skills_label = "Core Qualifications" if "QUALIFICATION" in skills_key else "Technical Skills"
        skills_html = f'<div class="section"><div class="section-title">{skills_label}</div><div class="skills-grid">{rows}</div></div>'

    def _split_date(title: str):
        """Split 'Job Title | Company | Date' or 'Job Title\\nCompany\\nDate' into parts."""
        # Try splitting on | first
        if "|" in title:
            parts = [p.strip() for p in title.split("|")]
            return parts[0], parts[1] if len(parts) > 1 else "", parts[2] if len(parts) > 2 else ""
        return title, "", ""

    def _render_entries(entries, section_label):
        items = ""
        for e in entries:
            job_title, company_or_date, date = _split_date(e["title"])
            # If subtitle holds "Company | Date" (new format), extract date from it
            if e["subtitle"] and "|" in e["subtitle"] and not company_or_date:
                sub_parts = [p.strip() for p in e["subtitle"].split("|")]
                company_or_date = sub_parts[0]
                date = sub_parts[-1] if len(sub_parts) > 1 else date
                subtitle_text = ""
            elif not company_or_date and e["subtitle"]:
                # Subtitle holds company but no date separator
                company_or_date = e["subtitle"]
                subtitle_text = ""
            else:
                subtitle_text = e["subtitle"] if e["subtitle"] and e["subtitle"] != company_or_date else ""

            bullets = "".join(f"<li>{_esc(b)}</li>" for b in e["bullets"])
            meta_parts = [part for part in (company_or_date, subtitle_text, date) if part]
            meta_html = (
                f'<div class="entry-meta">{" | ".join(_esc(part) for part in meta_parts)}</div>'
                if meta_parts
                else ""
            )
            items += f"""<div class="entry">
  <div class="entry-title">{_esc(job_title)}</div>
  {meta_html}
  <ul>{bullets}</ul>
</div>"""
        return f'<div class="section"><div class="section-title">{section_label}</div>{items}</div>'

    # Experience
    exp_html = ""
    exp_key = _find_key(sections, "EXPERIENCE")
    if exp_key:
        entries = parse_entries(sections[exp_key])
        exp_html = _render_entries(entries, "Experience")

    additional_exp_html = ""
    additional_text = sections.get("ADDITIONAL EXPERIENCE", "").strip()
    if additional_text:
        lines = "".join(
            f'<div class="compact-exp-line">{_esc(line.strip())}</div>'
            for line in additional_text.splitlines()
            if line.strip()
        )
        additional_exp_html = (
            '<div class="section"><div class="section-title">Additional Experience</div>'
            f'<div class="compact-exp">{lines}</div></div>'
        )

    # Projects
    proj_html = ""
    proj_key = _find_key(sections, "PROJECT")
    if proj_key:
        entries = parse_entries(sections[proj_key])
        proj_html = _render_entries(entries, "Projects &amp; Home Lab")

    # Certifications
    cert_html = ""
    cert_key = _find_key(sections, "CERTIF", "LICENSE")
    if cert_key:
        cert_text = sections[cert_key].strip()
        cert_items = ""
        for line in cert_text.split("\n"):
            line = line.strip().lstrip("-").lstrip("\u2022").strip()
            if line:
                cert_items += f'<div class="cert-item">{_esc(line)}</div>\n'
        if cert_items:
            cert_html = (
                f'<div class="section"><div class="section-title">Certifications &amp; Licenses</div>{cert_items}</div>'
            )

    # Education â€” parse into structured blocks
    edu_html = ""
    edu_key = _find_key(sections, "EDUCATION")
    if edu_key:
        edu_text = sections[edu_key].strip()
        blocks = _re.split(r"\n{2,}", edu_text)
        edu_items = ""
        for block in blocks:
            edu_lines = [line.strip() for line in block.strip().split("\n") if line.strip()]
            if not edu_lines:
                continue
            degree = edu_lines[0]
            school = edu_lines[1] if len(edu_lines) > 1 else ""
            details = (
                " &nbsp;&middot;&nbsp; ".join(_esc(line) for line in edu_lines[2:])
                if len(edu_lines) > 2
                else ""
            )
            edu_items += f"""<div class="edu-entry">
  <div class="edu-degree">{_esc(degree)}</div>
  <div class="edu-school">{_esc(school)}</div>
  {"<div class='edu-details'>" + details + "</div>" if details else ""}
</div>"""
        edu_html = f'<div class="section"><div class="section-title">Education</div>{edu_items}</div>'

    # Summary
    summary_html = ""
    summary_key = _find_key(sections, "SUMMARY")
    if summary_key:
        summary_html = f'<div class="section"><div class="section-title">Summary</div><div class="summary">{_esc(sections[summary_key].strip())}</div></div>'

    # Contact line parsing
    contact = resume["contact"]
    contact_parts = [p.strip() for p in contact.split("|") if p.strip()] if contact else []
    location = str(resume.get("location") or "").strip()
    if location and all(location.casefold() != part.casefold() for part in contact_parts):
        contact_parts.insert(0, location)
    contact_parts = [_esc(part) for part in contact_parts]
    contact_html = " &nbsp;|&nbsp; ".join(contact_parts)

    display_name = _esc(resume["name"])

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<style>
@page {{
    size: letter;
    margin: 0.32in 0.42in 0.28in 0.42in;
}}
* {{
    margin: 0;
    padding: 0;
    box-sizing: border-box;
}}
body {{
    font-family: Arial, 'Segoe UI', sans-serif;
    font-size: 9pt;
    line-height: 1.32;
    color: #2c2416;
    background: #fff;
}}

/* â”€â”€ Header â”€â”€ */
.header {{
    border-bottom: 2px solid #c17f3e;
    padding-bottom: 5px;
    margin-bottom: 6px;
}}
.header-top {{
    display: block;
}}
.name {{
    font-family: Georgia, 'Times New Roman', serif;
    font-size: 20pt;
    font-weight: 900;
    color: #2c2416;
    letter-spacing: 0;
    line-height: 1;
}}
.name span {{
    color: #c17f3e;
}}
.title {{
    font-size: 9pt;
    color: #8b6f47;
    font-weight: 400;
    text-align: left;
    line-height: 1.4;
    margin-top: 2px;
}}
.contact {{
    font-size: 8.2pt;
    color: #7a6a58;
    margin-top: 2px;
    display: block;
}}
.contact a {{
    color: #7a6a58;
    text-decoration: none;
}}

/* â”€â”€ Sections â”€â”€ */
.section {{
    margin-top: 6px;
}}
.section-title {{
    font-family: Georgia, 'Times New Roman', serif;
    font-size: 8.2pt;
    font-weight: 700;
    color: #c17f3e;
    text-transform: uppercase;
    letter-spacing: 0.14em;
    border-bottom: 1px solid #e8dcc8;
    padding-bottom: 2px;
    margin-bottom: 4px;
    display: flex;
    align-items: center;
    gap: 6px;
}}
.section-title::before {{
    content: '';
    display: inline-block;
    width: 16px;
    height: 1.5px;
    background: #c17f3e;
    flex-shrink: 0;
}}

/* â”€â”€ Summary â”€â”€ */
.summary {{
    font-size: 9pt;
    color: #3a2e22;
    line-height: 1.35;
    font-weight: 300;
}}

/* â”€â”€ Skills â”€â”€ */
.skills-grid {{
    display: block;
}}
.skill-row {{
    font-size: 8.5pt;
    line-height: 1.25;
    color: #3a2e22;
    margin-bottom: 1px;
}}
.skill-cat {{
    font-weight: 600;
    color: #4a3728;
}}

/* â”€â”€ Experience entries â”€â”€ */
.entry {{
    margin-bottom: 4px;
    break-inside: avoid;
    page-break-inside: avoid;
    padding-left: 8px;
    border-left: 2px solid #e8dcc8;
}}
.entry-title {{
    font-weight: 600;
    font-size: 9pt;
    color: #2c2416;
}}
.entry-meta {{
    font-size: 8.5pt;
    color: #8b6f47;
    font-weight: 500;
    margin-bottom: 1px;
}}
.compact-exp {{
    padding-left: 8px;
    border-left: 2px solid #e8dcc8;
}}
.compact-exp-line {{
    font-size: 8.2pt;
    line-height: 1.25;
    color: #3a2e22;
    margin-bottom: 1px;
}}
ul {{
    margin-left: 11px;
    padding: 0;
}}
li {{
    font-size: 8.4pt;
    margin-bottom: 0;
    line-height: 1.25;
    color: #3a2e22;
}}
li::marker {{
    color: #c17f3e;
}}

/* â”€â”€ Certifications â”€â”€ */
.cert-item {{
    font-size: 8.5pt;
    line-height: 1.25;
    color: #3a2e22;
    padding-left: 8px;
    border-left: 2px solid #e8dcc8;
    margin-bottom: 3px;
}}

/* â”€â”€ Education â”€â”€ */
.edu-entry {{
    margin-bottom: 3px;
    padding-left: 8px;
    border-left: 2px solid #e8dcc8;
}}
.edu-degree {{
    font-weight: 600;
    font-size: 8.9pt;
    color: #2c2416;
}}
.edu-school {{
    font-size: 8.4pt;
    color: #8b6f47;
    font-weight: 500;
}}
.edu-details {{
    font-size: 8pt;
    color: #7a6a58;
    font-weight: 300;
}}

/* Sparse résumés use the available page for larger, easier-to-scan type.
   This is layout-only: no applicant text or claims are synthesized here. */
body.resume-sparse {{
    font-size: 10pt;
    line-height: 1.4;
}}
body.resume-sparse .header {{
    padding-bottom: 7px;
    margin-bottom: 8px;
}}
body.resume-sparse .title {{
    font-size: 10pt;
    line-height: 1.45;
    margin-top: 3px;
}}
body.resume-sparse .contact {{
    font-size: 9pt;
    margin-top: 3px;
}}
body.resume-sparse .section {{
    margin-top: 8px;
}}
body.resume-sparse .section-title {{
    font-size: 9pt;
    padding-bottom: 3px;
    margin-bottom: 5px;
}}
body.resume-sparse .summary {{
    font-size: 10pt;
    line-height: 1.42;
}}
body.resume-sparse .skill-row {{
    font-size: 9.4pt;
    line-height: 1.35;
    margin-bottom: 2px;
}}
body.resume-sparse .entry {{
    margin-bottom: 6px;
}}
body.resume-sparse .entry-title {{
    font-size: 9.7pt;
}}
body.resume-sparse .entry-meta {{
    font-size: 9.1pt;
    margin-bottom: 2px;
}}
body.resume-sparse .compact-exp-line,
body.resume-sparse .cert-item,
body.resume-sparse .edu-school {{
    font-size: 9.1pt;
    line-height: 1.35;
}}
body.resume-sparse li {{
    font-size: 9.2pt;
    line-height: 1.35;
    margin-bottom: 1px;
}}
body.resume-sparse .edu-degree {{
    font-size: 9.5pt;
}}
body.resume-sparse .edu-details {{
    font-size: 8.8pt;
}}

/* Long verified résumés compact spacing and type without changing content. */
body.resume-dense {{
    font-size: 8.3pt;
    line-height: 1.18;
}}
body.resume-dense .header {{
    padding-bottom: 3px;
    margin-bottom: 4px;
}}
body.resume-dense .name {{
    font-size: 19pt;
}}
body.resume-dense .title {{
    font-size: 8.5pt;
    line-height: 1.2;
    margin-top: 1px;
}}
body.resume-dense .contact {{
    font-size: 7.8pt;
    margin-top: 1px;
}}
body.resume-dense .section {{
    margin-top: 4px;
}}
body.resume-dense .section-title {{
    font-size: 7.8pt;
    padding-bottom: 1px;
    margin-bottom: 2px;
}}
body.resume-dense .summary {{
    font-size: 8.3pt;
    line-height: 1.2;
}}
body.resume-dense .skill-row {{
    font-size: 7.9pt;
    line-height: 1.14;
    margin-bottom: 0;
}}
body.resume-dense .entry {{
    margin-bottom: 2px;
}}
body.resume-dense .entry-title {{
    font-size: 8.4pt;
}}
body.resume-dense .entry-meta {{
    font-size: 7.9pt;
    margin-bottom: 0;
}}
body.resume-dense .compact-exp-line,
body.resume-dense .cert-item,
body.resume-dense .edu-school {{
    font-size: 7.8pt;
    line-height: 1.16;
}}
body.resume-dense li {{
    font-size: 7.9pt;
    line-height: 1.16;
}}
body.resume-dense .edu-entry {{
    margin-bottom: 1px;
}}
body.resume-dense .edu-degree {{
    font-size: 8.3pt;
}}
body.resume-dense .edu-details {{
    font-size: 7.6pt;
    line-height: 1.14;
}}
</style>
</head>
<body class="resume {density_class}">

<div class="header">
    <div class="header-top">
        <div class="name">{display_name}</div>
        <div class="title">{_esc(resume["title"])}</div>
    </div>
    <div class="contact">{contact_html}</div>
</div>

{summary_html}
{skills_html}
{exp_html}
{additional_exp_html}
{proj_html}
{cert_html}
{edu_html}
</body>
</html>"""


# â”€â”€ Cover Letter HTML Template â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€


def build_cover_letter_html(text: str, profile: dict | None = None) -> str:
    """Build a styled cover letter HTML from plain letter text."""

    def _esc(value: object) -> str:
        return _html_escape(str(value or ""), quote=True)

    personal = (profile or {}).get("personal", {})
    name = personal.get("full_name", "")
    email = personal.get("email", "")
    phone = personal.get("phone", "")
    city = personal.get("city", "")
    state = personal.get("province_state", "")
    location = f"{city}, {state}" if city and state else city or state

    contact_parts = [p for p in [phone, email, location] if p]
    contact_line = "  &nbsp;|&nbsp;  ".join(_esc(part) for part in contact_parts)

    # Split into paragraphs
    paragraphs = [p.strip() for p in text.strip().split("\n\n") if p.strip()]
    body_html = "".join(f"<p>{_esc(p).replace(chr(10), '<br>')}</p>" for p in paragraphs)

    display_name = _esc(name)

    from datetime import datetime

    date_str = datetime.now().strftime("%B %d, %Y")

    return f"""<!DOCTYPE html>
<html>
<head>
<meta charset="utf-8">
<style>
@page {{
    size: letter;
    margin: 0.6in 0.65in;
}}
* {{ margin: 0; padding: 0; box-sizing: border-box; }}
body {{
    font-family: Arial, 'Segoe UI', sans-serif;
    font-size: 10.5pt;
    line-height: 1.6;
    color: #2c2416;
    background: #fff;
}}
.header {{
    border-bottom: 2px solid #c17f3e;
    padding-bottom: 8px;
    margin-bottom: 24px;
    display: flex;
    justify-content: space-between;
    align-items: flex-end;
}}
.name {{
    font-family: Georgia, 'Times New Roman', serif;
    font-size: 20pt;
    font-weight: 900;
    color: #2c2416;
    letter-spacing: 0;
    line-height: 1;
}}
.name span {{ color: #c17f3e; }}
.contact {{
    font-size: 8.5pt;
    color: #7a6a58;
    text-align: right;
    line-height: 1.6;
}}
.date {{
    font-size: 9pt;
    color: #8b6f47;
    margin-bottom: 20px;
    font-weight: 300;
}}
.body p {{
    margin-bottom: 14px;
    font-weight: 300;
    color: #3a2e22;
}}
.body p:first-child {{
    margin-top: 0;
}}
</style>
</head>
<body>
<div class="header">
    <div class="name">{display_name}</div>
    <div class="contact">{contact_line}</div>
</div>
<div class="date">{date_str}</div>
<div class="body">{body_html}</div>
</body>
</html>"""


# â”€â”€ PDF Renderer â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€


def render_pdf(html: str, output_path: str) -> None:
    """Render HTML to PDF using Playwright's headless Chromium.

    Args:
        html: Complete HTML string.
        output_path: Path to write the PDF file.
    """
    from playwright.sync_api import sync_playwright

    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page()
        page.route(
            "**/*",
            lambda route: route.abort() if route.request.url.startswith(("http://", "https://")) else route.continue_(),
        )
        page.set_content(html, wait_until="domcontentloaded")
        page.pdf(
            path=output_path,
            format="Letter",
            margin={"top": "0", "right": "0", "bottom": "0", "left": "0"},
            print_background=True,
        )
        browser.close()


def _ats_tokens(text: str) -> list[str]:
    """Normalize document text into stable ATS-comparison tokens."""
    normalized = unicodedata.normalize("NFKC", str(text or "")).casefold()
    return re.findall(r"[a-z0-9]+(?:[+.#/-][a-z0-9]+)*\+?", normalized)


def _ats_token_coverage(source_tokens: list[str], extracted_tokens: list[str]) -> float:
    """Return source-token multiset coverage in extracted PDF text."""
    if not source_tokens:
        return 0.0
    source_counts = Counter(source_tokens)
    extracted_counts = Counter(extracted_tokens)
    matched = sum(min(count, extracted_counts[token]) for token, count in source_counts.items())
    return matched / len(source_tokens)


def _sections_appear_in_order(extracted_tokens: list[str], required_sections: list[str]) -> bool:
    """Verify standard section headings occur once in the intended linear order."""
    extracted = " ".join(extracted_tokens)
    cursor = -1
    for section in required_sections:
        label = ATS_SECTION_LABELS.get(str(section).strip().upper(), str(section).strip().upper())
        phrase = " ".join(_ats_tokens(label))
        if not phrase:
            continue
        position = extracted.find(phrase, cursor + 1)
        if position < 0:
            return False
        cursor = position
    return True


def validate_ats_pdf(
    source_text: str,
    pdf_path: Path,
    *,
    required_sections: list[str] | None = None,
) -> ATSPDFReport:
    """Fail closed unless a generated PDF retains a complete linear text layer."""
    try:
        reader = PdfReader(str(pdf_path))
        if reader.is_encrypted or not reader.pages:
            raise ValueError("encrypted or empty PDF")
        extracted_text = "\n".join((page.extract_text() or "") for page in reader.pages)
    except Exception as exc:
        raise RuntimeError("Generated PDF is not ATS-readable: text extraction failed") from exc

    source_tokens = _ats_tokens(source_text)
    extracted_tokens = _ats_tokens(extracted_text)
    coverage = _ats_token_coverage(source_tokens, extracted_tokens)
    sections = list(required_sections or [])
    sections_in_order = _sections_appear_in_order(extracted_tokens, sections)
    if "\ufffd" in extracted_text or coverage < ATS_MIN_TOKEN_COVERAGE or not sections_in_order:
        raise RuntimeError(
            "Generated PDF is not ATS-readable: text coverage or section order validation failed"
        )
    return {
        "pages": len(reader.pages),
        "source_tokens": len(source_tokens),
        "extracted_tokens": len(extracted_tokens),
        "token_coverage": coverage,
        "sections_in_order": sections_in_order,
    }


# â”€â”€ Public API â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€


def convert_to_pdf(
    text_path: Path,
    output_path: Path | None = None,
    html_only: bool = False,
    profile: dict | None = None,
) -> Path:
    """Convert a text resume/cover letter to PDF.

    Args:
        text_path: Path to the .txt file to convert.
        output_path: Optional override for the output path. Defaults to same
            name with .pdf extension.
        html_only: If True, output HTML instead of PDF.
        profile: Optional profile dict for cover letter header info.

    Returns:
        Path to the generated PDF (or HTML) file.
    """
    text_path = Path(text_path)
    text = text_path.read_text(encoding="utf-8")

    # Detect cover letter vs resume
    stripped = text.strip().lower()
    is_cover_letter = (
        stripped.startswith("dear ") or "_cl.txt" in text_path.name.lower() or "cover_letter" in text_path.name.lower()
    )

    if is_cover_letter:
        if profile is None:
            try:
                from divapply.config import load_profile

                profile = load_profile()
            except Exception:
                profile = {}
        html = build_cover_letter_html(text, profile)
        required_sections: list[str] = []
    else:
        resume = parse_resume(text)
        html = build_html(resume)
        required_sections = list(resume["sections"])

    if html_only:
        out = output_path or text_path.with_suffix(".html")
        out = Path(out)
        out.write_text(html, encoding="utf-8")
        protect_file(out)
        log.info("HTML generated: %s", out)
        return out

    out = output_path or text_path.with_suffix(".pdf")
    out = Path(out)
    out.parent.mkdir(parents=True, exist_ok=True)
    temporary_path: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            prefix=f".{out.stem}.ats-",
            suffix=".pdf",
            dir=out.parent,
            delete=False,
        ) as temporary:
            temporary_path = Path(temporary.name)
        render_pdf(html, str(temporary_path))
        report = validate_ats_pdf(text, temporary_path, required_sections=required_sections)
        temporary_path.replace(out)
    except Exception:
        if temporary_path is not None:
            temporary_path.unlink(missing_ok=True)
        raise
    protect_file(out)
    log.info(
        "ATS-readable PDF generated: %s (%s pages, %.1f%% source-token coverage)",
        out,
        report["pages"],
        float(report["token_coverage"]) * 100,
    )
    return out


def batch_convert(limit: int = 50) -> int:
    """Convert .txt files in TAILORED_DIR that don't have corresponding PDFs.

    Scans for .txt files (excluding _JOB.txt and _REPORT.json), checks if a
    .pdf with the same stem already exists, and converts any that are missing.

    Args:
        limit: Maximum number of files to convert.

    Returns:
        Number of PDFs generated.
    """
    if not TAILORED_DIR.exists():
        log.warning("Tailored directory does not exist: %s", TAILORED_DIR)
        return 0

    txt_files = sorted(TAILORED_DIR.glob("*.txt"))
    # Exclude _JOB.txt and _CL.txt files from resume conversion
    # (they get their own conversion calls)
    candidates = [f for f in txt_files if not f.name.endswith("_JOB.txt")]

    # Filter to those without a corresponding PDF
    to_convert: list[Path] = []
    for f in candidates:
        pdf_path = f.with_suffix(".pdf")
        if not pdf_path.exists():
            to_convert.append(f)
        if len(to_convert) >= limit:
            break

    if not to_convert:
        log.info("All text files already have PDFs.")
        return 0

    log.info("Converting %d files to PDF...", len(to_convert))
    converted = 0
    failures: list[str] = []
    for f in to_convert:
        try:
            convert_to_pdf(f)
            converted += 1
        except Exception as e:
            log.error("Failed to convert %s: %s", f.name, e)
            failures.append(f.name)

    log.info("Done: %d/%d PDFs generated in %s", converted, len(to_convert), TAILORED_DIR)
    if failures:
        raise RuntimeError(f"{len(failures)} PDF conversion(s) failed: {', '.join(failures[:5])}")
    return converted
