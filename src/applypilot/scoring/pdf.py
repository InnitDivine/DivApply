"""Text-to-PDF conversion for tailored resumes and cover letters.

Parses the structured text resume format, renders via an HTML/CSS template,
and exports to PDF using headless Chromium via Playwright.
"""

import logging
from pathlib import Path

from applypilot.config import TAILORED_DIR

log = logging.getLogger(__name__)


# ── Resume Parser ────────────────────────────────────────────────────────

def parse_resume(text: str) -> dict:
    """Parse a structured text resume into sections.

    Expects a format with header lines (name, title, location, contact)
    followed by ALL-CAPS section headers (SUMMARY, TECHNICAL SKILLS, etc.).

    Args:
        text: Full resume text.

    Returns:
        {"name": str, "title": str, "location": str, "contact": str, "sections": dict}
    """
    lines = [line.rstrip() for line in text.strip().split("\n")]

    # Header: first few lines before the first ALL-CAPS section header.
    # Strategy: section headers always appear AFTER at least one blank line
    # (they never appear on the very first line). This correctly handles:
    #   - Base resume: "DALTON JOSEPH DE ARRIETA" (all-caps name, line 0) → header
    #   - Tailored resume: "Dalton Joseph De Arrieta" (mixed-case, line 0) → header
    #   - Section headers: "PROFESSIONAL SUMMARY", "SUMMARY", etc. → body
    header_lines: list[str] = []
    body_start = 0
    found_blank = False
    for i, line in enumerate(lines):
        stripped = line.strip()
        if not stripped:
            found_blank = True
            continue
        # Section header: ALL-CAPS, appears after at least one blank line
        if (
            found_blank
            and stripped == stripped.upper()
            and not stripped.startswith("-")
            and len(stripped) > 3
            and not stripped.startswith("\u2022")
        ):
            body_start = i
            break
        # Everything before the first blank gap is header content
        if not found_blank:
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
            contact = " | ".join(
                h for h in header_lines[1:] if h
            )
        else:
            # Tailored-resume format: Name / Title / contact
            title = line1
            if len(header_lines) > 3:
                location = header_lines[2]
                contact = header_lines[3]
            elif len(header_lines) > 2:
                if "@" in header_lines[2] or "|" in header_lines[2]:
                    contact = header_lines[2]
                else:
                    location = header_lines[2]

    # Split body into sections by ALL-CAPS headers
    sections: dict[str, str] = {}
    current_section: str | None = None
    current_lines: list[str] = []

    for line in lines[body_start:]:
        stripped = line.strip()
        # Detect section headers (all caps, no leading dash/bullet, longer than 3 chars)
        if (
            stripped
            and stripped == stripped.upper()
            and not stripped.startswith("-")
            and len(stripped) > 3
            and not stripped.startswith("\u2022")
        ):
            if current_section:
                sections[current_section] = "\n".join(current_lines).strip()
            current_section = stripped
            current_lines = []
        else:
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

    for line in text.strip().split("\n"):
        stripped = line.strip()
        if not stripped:
            # Empty line flushes current category
            if current_cat and current_bullets:
                skills.append((current_cat, ", ".join(current_bullets)))
                current_cat = ""
                current_bullets = []
            continue

        is_bullet = stripped.startswith("- ") or stripped.startswith("\u2022 ")
        has_colon = ":" in stripped and not is_bullet

        if has_colon:
            # Format A: "Category: value"
            if current_cat and current_bullets:
                skills.append((current_cat, ", ".join(current_bullets)))
                current_cat = ""
                current_bullets = []
            cat, val = stripped.split(":", 1)
            skills.append((cat.strip(), val.strip()))
        elif is_bullet:
            # Format B bullet: collect under current category
            if current_cat:
                current_bullets.append(stripped[2:].strip())
        else:
            # Format B category header
            if current_cat and current_bullets:
                skills.append((current_cat, ", ".join(current_bullets)))
            current_cat = stripped
            current_bullets = []

    if current_cat and current_bullets:
        skills.append((current_cat, ", ".join(current_bullets)))

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
        if stripped.startswith("- ") or stripped.startswith("\u2022 "):
            if current:
                current["bullets"].append(stripped[2:].strip())
        elif current is None or (
            not stripped.startswith("-")
            and not stripped.startswith("\u2022")
            and len(current.get("bullets", [])) > 0
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


# ── HTML Template ────────────────────────────────────────────────────────

def build_html(resume: dict) -> str:
    """Build professional resume HTML from parsed data.

    Args:
        resume: Parsed resume dict from parse_resume().

    Returns:
        Complete HTML string ready for PDF rendering.
    """
    sections = resume["sections"]

    import re as _re

    def _find_key(secs: dict, *keywords: str) -> str | None:
        """Return first section key that contains any of the given keywords."""
        for k in secs:
            if any(kw in k for kw in keywords):
                return k
        return None

    # Skills — two-column grid
    skills_html = ""
    skills_key = _find_key(sections, "SKILL")
    if skills_key:
        skills = parse_skills(sections[skills_key])
        rows = ""
        for cat, val in skills:
            rows += f'<div class="skill-row"><span class="skill-cat">{cat}:</span> {val}</div>\n'
        skills_html = f'<div class="section"><div class="section-title">Technical Skills</div><div class="skills-grid">{rows}</div></div>'

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

            bullets = "".join(f"<li>{b}</li>" for b in e["bullets"])
            date_html = f'<div class="entry-date">{date}</div>' if date else ""
            sub_html = f'<div class="entry-subtitle">{company_or_date}</div>' if company_or_date else ""
            if subtitle_text:
                sub_html += f'<div class="entry-subtitle">{subtitle_text}</div>'
            items += f'''<div class="entry">
  <div class="entry-header"><div class="entry-title">{job_title}</div>{date_html}</div>
  {sub_html}
  <ul>{bullets}</ul>
</div>'''
        return f'<div class="section"><div class="section-title">{section_label}</div>{items}</div>'

    # Experience
    exp_html = ""
    exp_key = _find_key(sections, "EXPERIENCE")
    if exp_key:
        entries = parse_entries(sections[exp_key])
        exp_html = _render_entries(entries, "Experience")

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
                cert_items += f'<div class="cert-item">{line}</div>\n'
        if cert_items:
            cert_html = f'<div class="section"><div class="section-title">Certifications &amp; Licenses</div>{cert_items}</div>'

    # Education — parse into structured blocks
    edu_html = ""
    edu_key = _find_key(sections, "EDUCATION")
    if edu_key:
        edu_text = sections[edu_key].strip()
        blocks = _re.split(r'\n{2,}', edu_text)
        edu_items = ""
        for block in blocks:
            lines = [l.strip() for l in block.strip().split("\n") if l.strip()]
            if not lines:
                continue
            degree = lines[0]
            school = lines[1] if len(lines) > 1 else ""
            details = " &nbsp;·&nbsp; ".join(lines[2:]) if len(lines) > 2 else ""
            edu_items += f'''<div class="edu-entry">
  <div class="edu-degree">{degree}</div>
  <div class="edu-school">{school}</div>
  {"<div class='edu-details'>" + details + "</div>" if details else ""}
</div>'''
        edu_html = f'<div class="section"><div class="section-title">Education</div>{edu_items}</div>'

    # Summary
    summary_html = ""
    summary_key = _find_key(sections, "SUMMARY")
    if summary_key:
        summary_html = f'<div class="section"><div class="section-title">Summary</div><div class="summary">{sections[summary_key].strip()}</div></div>'

    # Contact line parsing
    contact = resume["contact"]
    contact_parts = [p.strip() for p in contact.split("|")] if contact else []
    contact_html = " &nbsp;|&nbsp; ".join(contact_parts)

    # Location line (may be empty)
    location_html = f'<div class="location">{resume["location"]}</div>' if resume["location"] else ""

    return f"""<!DOCTYPE html>
<html>
<head>
<meta charset="utf-8">
<link rel="preconnect" href="https://fonts.googleapis.com">
<link href="https://fonts.googleapis.com/css2?family=Playfair+Display:wght@700;900&family=DM+Sans:wght@300;400;500&display=swap" rel="stylesheet">
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
    font-family: 'DM Sans', 'Segoe UI', Arial, sans-serif;
    font-size: 9pt;
    line-height: 1.32;
    color: #2c2416;
    background: #fff;
}}

/* ── Header ── */
.header {{
    border-bottom: 2px solid #c17f3e;
    padding-bottom: 5px;
    margin-bottom: 6px;
}}
.header-top {{
    display: flex;
    align-items: baseline;
    justify-content: space-between;
    gap: 1rem;
}}
.name {{
    font-family: 'Playfair Display', Georgia, serif;
    font-size: 20pt;
    font-weight: 900;
    color: #2c2416;
    letter-spacing: -0.5px;
    line-height: 1;
}}
.name span {{
    color: #c17f3e;
}}
.title {{
    font-size: 9pt;
    color: #8b6f47;
    font-weight: 400;
    text-align: right;
    flex-shrink: 0;
    line-height: 1.4;
    max-width: 280px;
}}
.contact {{
    font-size: 8.2pt;
    color: #7a6a58;
    margin-top: 2px;
    display: flex;
    gap: 1.5rem;
    flex-wrap: wrap;
}}
.contact a {{
    color: #7a6a58;
    text-decoration: none;
}}

/* ── Sections ── */
.section {{
    margin-top: 6px;
}}
.section-title {{
    font-family: 'Playfair Display', Georgia, serif;
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

/* ── Summary ── */
.summary {{
    font-size: 9pt;
    color: #3a2e22;
    line-height: 1.35;
    font-weight: 300;
}}

/* ── Skills ── */
.skills-grid {{
    display: grid;
    grid-template-columns: 1fr 1fr;
    gap: 1px 12px;
}}
.skill-row {{
    font-size: 8.5pt;
    line-height: 1.25;
    color: #3a2e22;
}}
.skill-cat {{
    font-weight: 600;
    color: #4a3728;
}}

/* ── Experience entries ── */
.entry {{
    margin-bottom: 4px;
    break-inside: avoid;
    padding-left: 8px;
    border-left: 2px solid #e8dcc8;
}}
.entry-header {{
    display: flex;
    justify-content: space-between;
    align-items: baseline;
    gap: 8px;
    margin-bottom: 1px;
}}
.entry-title {{
    font-weight: 600;
    font-size: 9pt;
    color: #2c2416;
}}
.entry-date {{
    font-size: 7.8pt;
    color: #c17f3e;
    font-weight: 500;
    white-space: nowrap;
    flex-shrink: 0;
    font-family: 'DM Sans', sans-serif;
    letter-spacing: 0.03em;
}}
.entry-subtitle {{
    font-size: 8.5pt;
    color: #8b6f47;
    font-weight: 500;
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

/* ── Certifications ── */
.cert-item {{
    font-size: 8.5pt;
    line-height: 1.25;
    color: #3a2e22;
    padding-left: 8px;
    border-left: 2px solid #e8dcc8;
    margin-bottom: 3px;
}}

/* ── Education ── */
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
</style>
</head>
<body>

<div class="header">
    <div class="header-top">
        <div class="name">{resume['name'].replace('De Arrieta', '<span>De Arrieta</span>').replace('de Arrieta', '<span>de Arrieta</span>').replace('DE ARRIETA', '<span>DE ARRIETA</span>')}</div>
        <div class="title">{resume['title']}</div>
    </div>
    <div class="contact">{contact_html}</div>
</div>

{summary_html}
{skills_html}
{exp_html}
{proj_html}
{cert_html}
{edu_html}
</body>
</html>"""


# ── Cover Letter HTML Template ───────────────────────────────────────────

def build_cover_letter_html(text: str, profile: dict | None = None) -> str:
    """Build a styled cover letter HTML from plain letter text."""
    personal = (profile or {}).get("personal", {})
    name = personal.get("full_name", "")
    email = personal.get("email", "")
    phone = personal.get("phone", "")
    city = personal.get("city", "")
    state = personal.get("province_state", "")
    location = f"{city}, {state}" if city and state else city or state

    contact_parts = [p for p in [phone, email, location] if p]
    contact_line = "  &nbsp;|&nbsp;  ".join(contact_parts)

    # Split into paragraphs
    paragraphs = [p.strip() for p in text.strip().split("\n\n") if p.strip()]
    body_html = "".join(f"<p>{p.replace(chr(10), '<br>')}</p>" for p in paragraphs)

    display_name = (
        name
        .replace("De Arrieta", "<span>De Arrieta</span>")
        .replace("de Arrieta", "<span>de Arrieta</span>")
        .replace("DE ARRIETA", "<span>DE ARRIETA</span>")
    )

    from datetime import datetime
    date_str = datetime.now().strftime("%B %d, %Y")

    return f"""<!DOCTYPE html>
<html>
<head>
<meta charset="utf-8">
<link rel="preconnect" href="https://fonts.googleapis.com">
<link href="https://fonts.googleapis.com/css2?family=Playfair+Display:wght@700;900&family=DM+Sans:wght@300;400;500&display=swap" rel="stylesheet">
<style>
@page {{
    size: letter;
    margin: 0.6in 0.65in;
}}
* {{ margin: 0; padding: 0; box-sizing: border-box; }}
body {{
    font-family: 'DM Sans', 'Segoe UI', Arial, sans-serif;
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
    font-family: 'Playfair Display', Georgia, serif;
    font-size: 20pt;
    font-weight: 900;
    color: #2c2416;
    letter-spacing: -0.5px;
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


# ── PDF Renderer ─────────────────────────────────────────────────────────

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
        page.set_content(html, wait_until="networkidle")
        page.pdf(
            path=output_path,
            format="Letter",
            margin={"top": "0", "right": "0", "bottom": "0", "left": "0"},
            print_background=True,
        )
        browser.close()


# ── Public API ───────────────────────────────────────────────────────────

def convert_to_pdf(
    text_path: Path, output_path: Path | None = None, html_only: bool = False,
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
    is_cover_letter = stripped.startswith("dear ") or "_cl.txt" in text_path.name.lower() or "cover_letter" in text_path.name.lower()

    if is_cover_letter:
        if profile is None:
            try:
                from applypilot.config import load_profile
                profile = load_profile()
            except Exception:
                profile = {}
        html = build_cover_letter_html(text, profile)
    else:
        resume = parse_resume(text)
        html = build_html(resume)

    if html_only:
        out = output_path or text_path.with_suffix(".html")
        out = Path(out)
        out.write_text(html, encoding="utf-8")
        log.info("HTML generated: %s", out)
        return out

    out = output_path or text_path.with_suffix(".pdf")
    out = Path(out)
    render_pdf(html, str(out))
    log.info("PDF generated: %s", out)
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
    candidates = [
        f for f in txt_files
        if not f.name.endswith("_JOB.txt")
    ]

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
    for f in to_convert:
        try:
            convert_to_pdf(f)
            converted += 1
        except Exception as e:
            log.error("Failed to convert %s: %s", f.name, e)

    log.info("Done: %d/%d PDFs generated in %s", converted, len(to_convert), TAILORED_DIR)
    return converted
