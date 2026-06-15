"""DivApply first-time setup wizard.

Interactive flow that creates ~/.divapply/ with:
  - resume.txt (and optionally resume.pdf)
  - profile.json
  - searches.yaml
  - .env (LLM API key)
"""

from __future__ import annotations

import json
import re
import shutil
from pathlib import Path

from rich.console import Console
from rich.panel import Panel
from rich.prompt import Confirm, Prompt

from divapply.config import (
    APP_DIR,
    ENV_PATH,
    PROFILE_PATH,
    RESUME_PATH,
    RESUME_PDF_PATH,
    SEARCH_CONFIG_PATH,
    ensure_dirs,
)
from divapply.security import protect_file, write_private_text

console = Console()


SECTION_HEADING_RE = re.compile(r"^[A-Z][A-Z0-9 &/+.,'-]{2,}$")
EMAIL_RE = re.compile(r"[\w.+-]+@[\w.-]+\.[A-Za-z]{2,}")
PHONE_RE = re.compile(r"(?:\+?1[\s.-]?)?(?:\(?\d{3}\)?[\s.-]?)\d{3}[\s.-]?\d{4}")
URL_RE = re.compile(r"https?://[^\s)>\]]+|(?:www\.)[^\s)>\]]+")


def _split_csv(value: str) -> list[str]:
    """Split comma/newline profile fields into a clean list."""
    return [s.strip() for s in re.split(r",|\n", value or "") if s.strip()]


def _read_resume_text() -> str:
    """Read resume text copied during setup, with a best-effort PDF fallback."""
    if RESUME_PATH.exists():
        return RESUME_PATH.read_text(encoding="utf-8", errors="ignore")

    if not RESUME_PDF_PATH.exists():
        return ""

    try:
        from pypdf import PdfReader
    except Exception:
        return ""

    try:
        reader = PdfReader(str(RESUME_PDF_PATH))
        return "\n".join(page.extract_text() or "" for page in reader.pages)
    except Exception:
        return ""


def _extract_section_lines(text: str, headings: set[str], *, max_lines: int = 12) -> list[str]:
    """Return lines under the first matching resume section heading."""
    lines = [line.strip(" \t-*•") for line in text.splitlines()]
    capture = False
    found: list[str] = []
    normalized_headings = {heading.lower() for heading in headings}

    for line in lines:
        if not line:
            if capture and found:
                break
            continue
        normalized = line.rstrip(":").lower()
        if normalized in normalized_headings:
            capture = True
            continue
        if capture and SECTION_HEADING_RE.match(line) and len(line.split()) <= 5:
            break
        if capture:
            found.append(line)
            if len(found) >= max_lines:
                break
    return found


def _infer_profile_defaults(resume_text: str) -> dict[str, str]:
    """Infer conservative setup defaults from resume text."""
    lines = [line.strip() for line in resume_text.splitlines() if line.strip()]
    text = "\n".join(lines)

    defaults: dict[str, str] = {
        "full_name": "",
        "email": "",
        "phone": "",
        "linkedin_url": "",
        "github_url": "",
        "website_url": "",
        "skills": "",
        "preserved_companies": "",
        "preserved_projects": "",
        "preserved_school": "",
        "real_metrics": "",
        "education_level": "",
        "current_job_title": "",
    }

    if lines:
        first = lines[0]
        if 1 < len(first.split()) <= 5 and not EMAIL_RE.search(first) and not PHONE_RE.search(first):
            defaults["full_name"] = first

    email = EMAIL_RE.search(text)
    if email:
        defaults["email"] = email.group(0)

    phone = PHONE_RE.search(text)
    if phone:
        defaults["phone"] = phone.group(0)

    urls = [url.rstrip(".,") for url in URL_RE.findall(text)]
    for url in urls:
        lower = url.lower()
        if "linkedin.com" in lower and not defaults["linkedin_url"]:
            defaults["linkedin_url"] = url
        elif "github.com" in lower and not defaults["github_url"]:
            defaults["github_url"] = url
        elif not defaults["website_url"]:
            defaults["website_url"] = url

    skill_lines = _extract_section_lines(text, {"skills", "technical skills", "core skills", "key skills"})
    if skill_lines:
        skills: list[str] = []
        for line in skill_lines:
            cleaned = re.sub(r"^[A-Za-z &/+.-]{2,30}:\s*", "", line)
            skills.extend(_split_csv(cleaned))
        defaults["skills"] = ", ".join(dict.fromkeys(skills[:30]))

    experience_lines = _extract_section_lines(text, {"experience", "work experience", "professional experience"})
    if experience_lines:
        defaults["current_job_title"] = experience_lines[0].split("|", 1)[0].strip()
        companies = []
        for line in experience_lines[:8]:
            parts = [part.strip() for part in re.split(r"\s+[|–-]\s+", line) if part.strip()]
            if len(parts) >= 2 and not re.search(r"\d{4}|present|current", parts[1], re.I):
                companies.append(parts[1])
        defaults["preserved_companies"] = ", ".join(dict.fromkeys(companies[:8]))

    education_lines = _extract_section_lines(text, {"education"}, max_lines=8)
    if education_lines:
        defaults["preserved_school"] = ", ".join(education_lines[:3])
        education_text = " ".join(education_lines)
        degree_match = re.search(
            r"(Bachelor(?:'s)?|Associate(?:'s)?|Master(?:'s)?|PhD|Certificate)[^,;\n]*",
            education_text,
            re.I,
        )
        if degree_match:
            defaults["education_level"] = degree_match.group(0).strip()

    metric_matches = re.findall(r"\b(?:\d+(?:\.\d+)?%|\d+\s*(?:WPM|KPH|GPA)|GPA\s*\d+(?:\.\d+)?)\b", text, re.I)
    defaults["real_metrics"] = ", ".join(dict.fromkeys(metric_matches[:8]))
    return defaults


# ---------------------------------------------------------------------------
# Resume
# ---------------------------------------------------------------------------

def _setup_resume() -> None:
    """Prompt for resume file and copy into APP_DIR."""
    console.print(Panel("[bold]Step 1: Resume[/bold]\nPoint to your master resume file (.txt or .pdf)."))

    while True:
        path_str = Prompt.ask("Resume file path")
        src = Path(path_str.strip().strip('"').strip("'")).expanduser().resolve()

        if not src.exists():
            console.print(f"[red]File not found:[/red] {src}")
            continue

        suffix = src.suffix.lower()
        if suffix not in (".txt", ".pdf"):
            console.print("[red]Unsupported format.[/red] Provide a .txt or .pdf file.")
            continue

        if suffix == ".txt":
            shutil.copy2(src, RESUME_PATH)
            protect_file(RESUME_PATH)
            console.print(f"[green]Copied to {RESUME_PATH}[/green]")
        elif suffix == ".pdf":
            shutil.copy2(src, RESUME_PDF_PATH)
            protect_file(RESUME_PDF_PATH)
            console.print(f"[green]Copied to {RESUME_PDF_PATH}[/green]")

            # Also ask for a plain-text version for LLM consumption
            txt_path_str = Prompt.ask(
                "Plain-text version of your resume (.txt)",
                default="",
            )
            if txt_path_str.strip():
                txt_src = Path(txt_path_str.strip().strip('"').strip("'")).expanduser().resolve()
                if txt_src.exists():
                    shutil.copy2(txt_src, RESUME_PATH)
                    protect_file(RESUME_PATH)
                    console.print(f"[green]Copied to {RESUME_PATH}[/green]")
                else:
                    console.print("[yellow]File not found, skipping plain-text copy.[/yellow]")
        break


# ---------------------------------------------------------------------------
# Profile
# ---------------------------------------------------------------------------

def _setup_profile() -> dict:
    """Walk through profile questions and return a nested profile dict."""
    console.print(Panel("[bold]Step 2: Profile[/bold]\nTell DivApply about yourself. This powers scoring, tailoring, and auto-fill."))

    defaults = _infer_profile_defaults(_read_resume_text())
    profile: dict = {}

    # -- Personal --
    console.print("\n[bold cyan]Personal Information[/bold cyan]")
    full_name = Prompt.ask("Full name", default=defaults["full_name"])
    profile["personal"] = {
        "full_name": full_name,
        "preferred_name": Prompt.ask("Preferred/nickname (leave blank to use first name)", default=""),
        "email": Prompt.ask("Email address", default=defaults["email"]),
        "phone": Prompt.ask("Phone number", default=defaults["phone"]),
        "city": Prompt.ask("City"),
        "province_state": Prompt.ask("Province/State (e.g. Ontario, California)", default=""),
        "country": Prompt.ask("Country"),
        "postal_code": Prompt.ask("Postal/ZIP code", default=""),
        "address": Prompt.ask("Street address (optional, used for form auto-fill)", default=""),
        "linkedin_url": Prompt.ask("LinkedIn URL", default=defaults["linkedin_url"]),
        "github_url": Prompt.ask("GitHub URL (optional)", default=defaults["github_url"]),
        "portfolio_url": Prompt.ask("Portfolio URL (optional)", default=""),
        "website_url": Prompt.ask("Personal website URL (optional)", default=defaults["website_url"]),
    }

    # -- Work Authorization --
    console.print("\n[bold cyan]Work Authorization[/bold cyan]")
    profile["work_authorization"] = {
        "legally_authorized_to_work": Confirm.ask("Are you legally authorized to work in your target country?"),
        "require_sponsorship": Confirm.ask("Will you now or in the future need sponsorship?"),
        "work_permit_type": Prompt.ask("Work permit type (e.g. Citizen, PR, Open Work Permit â€” leave blank if N/A)", default=""),
    }

    # -- Compensation --
    console.print("\n[bold cyan]Compensation[/bold cyan]")
    salary = Prompt.ask("Expected annual salary (number)", default="")
    salary_currency = Prompt.ask("Currency", default="USD")
    salary_range = Prompt.ask("Acceptable range (e.g. 80000-120000)", default="")
    range_parts = salary_range.split("-") if "-" in salary_range else [salary, salary]
    profile["compensation"] = {
        "salary_expectation": salary,
        "salary_currency": salary_currency,
        "salary_range_min": range_parts[0].strip(),
        "salary_range_max": range_parts[1].strip() if len(range_parts) > 1 else range_parts[0].strip(),
    }

    # -- Profile Summary --
    console.print("\n[bold cyan]Profile Summary[/bold cyan]")
    profile["experience"] = {
        "education_level": Prompt.ask("Highest education", default=defaults["education_level"]),
        "current_job_title": Prompt.ask("Current/most recent job title", default=defaults["current_job_title"]),
    }

    # -- Simplified Skills --
    console.print("\n[bold cyan]Verified Skills[/bold cyan]")
    skills = Prompt.ask("Core skills to preserve/use for matching (comma-separated)", default=defaults["skills"])
    profile["skills"] = _split_csv(skills)

    # -- Resume Facts (preserved truths for tailoring) --
    console.print("\n[bold cyan]Resume Facts[/bold cyan]")
    console.print("[dim]These are preserved exactly during resume tailoring â€” the AI will never change them.[/dim]")
    companies = Prompt.ask("Companies to always keep (comma-separated)", default=defaults["preserved_companies"])
    projects = Prompt.ask("Projects to always keep (comma-separated)", default=defaults["preserved_projects"])
    school = Prompt.ask("School name(s) to preserve", default=defaults["preserved_school"])
    metrics = Prompt.ask("Real metrics to preserve (e.g. '99.9% uptime, 50k users')", default=defaults["real_metrics"])
    profile["resume_facts"] = {
        "preserved_companies": _split_csv(companies),
        "preserved_projects": _split_csv(projects),
        "preserved_school": school.strip(),
        "real_metrics": _split_csv(metrics),
    }

    # -- EEO Voluntary (defaults) --
    profile["eeo_voluntary"] = {
        "gender": "Decline to self-identify",
        "race_ethnicity": "Decline to self-identify",
        "veteran_status": "Decline to self-identify",
        "disability_status": "Decline to self-identify",
    }

    # Save
    PROFILE_PATH.write_text(json.dumps(profile, indent=2, ensure_ascii=False), encoding="utf-8")
    protect_file(PROFILE_PATH)
    console.print(f"\n[green]Profile saved to {PROFILE_PATH}[/green]")
    return profile


# ---------------------------------------------------------------------------
# Search config
# ---------------------------------------------------------------------------

def _setup_searches() -> None:
    """Generate a searches.yaml from user input."""
    console.print(Panel("[bold]Step 3: Job Search Config[/bold]\nDefine what you're looking for."))

    location = Prompt.ask("Target location (e.g. 'Remote', 'Canada', 'New York, NY')", default="Remote")
    distance_str = Prompt.ask("Search radius in miles (0 for remote-only)", default="0")
    try:
        distance = int(distance_str)
    except ValueError:
        distance = 0

    roles_raw = Prompt.ask(
        "Target job titles (comma-separated, e.g. 'Backend Engineer, Full Stack Developer')"
    )
    roles = [r.strip() for r in roles_raw.split(",") if r.strip()]

    if not roles:
        console.print("[yellow]No roles provided. Using a default set.[/yellow]")
        roles = ["Software Engineer"]

    # Build YAML content
    lines = [
        "# DivApply search configuration",
        "# Edit this file to refine your job search queries.",
        "",
        "defaults:",
        f'  location: "{location}"',
        f"  distance: {distance}",
        "  hours_old: 72",
        "  results_per_site: 50",
        "",
        "locations:",
        f'  - location: "{location}"',
        f"    remote: {str(distance == 0).lower()}",
        "",
        "queries:",
    ]
    for i, role in enumerate(roles):
        lines.append(f'  - query: "{role}"')
        lines.append(f"    tier: {min(i + 1, 3)}")

    SEARCH_CONFIG_PATH.write_text("\n".join(lines) + "\n", encoding="utf-8")
    protect_file(SEARCH_CONFIG_PATH)
    console.print(f"[green]Search config saved to {SEARCH_CONFIG_PATH}[/green]")


# ---------------------------------------------------------------------------
# AI Features
# ---------------------------------------------------------------------------

def _setup_ai_features() -> None:
    """Ask about AI scoring/tailoring â€” optional LLM configuration."""
    console.print(Panel(
        "[bold]Step 4: AI Features (optional)[/bold]\n"
        "An LLM powers job scoring, resume tailoring, and cover letters.\n"
        "Without this, you can still discover and enrich jobs."
    ))

    if not Confirm.ask("Enable AI scoring and resume tailoring?", default=True):
        console.print("[dim]Discovery-only mode. You can configure AI later with [bold]divapply init[/bold].[/dim]")
        return

    console.print("Supported providers: [bold]Gemini[/bold] (recommended, free tier), OpenAI, local (Ollama/llama.cpp)")
    provider = Prompt.ask(
        "Provider",
        choices=["gemini", "openai", "local"],
        default="gemini",
    )

    env_lines = ["# DivApply configuration", ""]

    if provider == "gemini":
        api_key = Prompt.ask("Gemini API key (from aistudio.google.com)")
        model = Prompt.ask("Model", default="gemini-2.0-flash")
        env_lines.append(f"GEMINI_API_KEY={api_key}")
        env_lines.append(f"LLM_MODEL={model}")
    elif provider == "openai":
        api_key = Prompt.ask("OpenAI API key")
        model = Prompt.ask("Model", default="gpt-4o-mini")
        env_lines.append(f"OPENAI_API_KEY={api_key}")
        env_lines.append(f"LLM_MODEL={model}")
    elif provider == "local":
        url = Prompt.ask("Local LLM endpoint URL", default="http://localhost:8080/v1")
        model = Prompt.ask("Model name", default="local-model")
        env_lines.append(f"LLM_URL={url}")
        env_lines.append(f"LLM_MODEL={model}")

    env_lines.append("")
    write_private_text(ENV_PATH, "\n".join(env_lines))
    console.print(f"[green]AI configuration saved to {ENV_PATH}[/green]")


# ---------------------------------------------------------------------------
# Auto-Apply
# ---------------------------------------------------------------------------

def _setup_auto_apply() -> None:
    """Configure autonomous job application (requires an apply agent CLI)."""
    console.print(Panel(
        "[bold]Step 5: Auto-Apply (optional)[/bold]\n"
        "DivApply can autonomously fill and submit job applications\n"
        "using Codex or Claude Code as the browser agent."
    ))

    if not Confirm.ask("Enable autonomous job applications?", default=True):
        console.print("[dim]You can apply manually using the tailored resumes DivApply generates.[/dim]")
        return

    # Check for an apply agent CLI
    from divapply.config import get_apply_backend, get_apply_backend_label
    backend = get_apply_backend()
    if backend:
        console.print(f"[green]{get_apply_backend_label(backend)} detected.[/green]")
    else:
        console.print(
            "[yellow]No supported apply agent CLI found on PATH.[/yellow]\n"
            "Install Codex or Claude Code.\n"
            "Auto-apply won't work until one of them is installed."
        )

    # Optional: CapSolver for CAPTCHAs
    console.print("\n[dim]Some job sites use CAPTCHAs. CapSolver can handle them automatically.[/dim]")
    if Confirm.ask("Configure CapSolver API key? (optional)", default=False):
        capsolver_key = Prompt.ask("CapSolver API key")
        # Append to existing .env or create
        if ENV_PATH.exists():
            existing = ENV_PATH.read_text(encoding="utf-8")
            if "CAPSOLVER_API_KEY" not in existing:
                write_private_text(
                    ENV_PATH,
                    existing.rstrip() + f"\nCAPSOLVER_API_KEY={capsolver_key}\n",
                )
        else:
            write_private_text(ENV_PATH, f"# DivApply configuration\nCAPSOLVER_API_KEY={capsolver_key}\n")
        console.print("[green]CapSolver key saved.[/green]")
    else:
        console.print("[dim]Skipped. Add CAPSOLVER_API_KEY to .env later if needed.[/dim]")


# ---------------------------------------------------------------------------
# Main entry
# ---------------------------------------------------------------------------

def run_wizard() -> None:
    """Run the full interactive setup wizard."""
    console.print()
    console.print(
        Panel.fit(
            "[bold green]DivApply Setup Wizard[/bold green]\n\n"
            "This will create your configuration at:\n"
            f"  [cyan]{APP_DIR}[/cyan]\n\n"
            "You can re-run this anytime with [bold]divapply init[/bold].",
            border_style="green",
        )
    )

    ensure_dirs()
    console.print(f"[dim]Created {APP_DIR}[/dim]\n")

    # Step 1: Resume
    _setup_resume()
    console.print()

    # Step 2: Profile
    _setup_profile()
    console.print()

    # Step 3: Search config
    _setup_searches()
    console.print()

    # Step 4: AI features (optional LLM)
    _setup_ai_features()
    console.print()

    # Step 5: Auto-apply (apply agent detection)
    _setup_auto_apply()
    console.print()

    # Done â€” show tier status
    from divapply.config import get_tier, TIER_LABELS, TIER_COMMANDS

    tier = get_tier()

    tier_lines: list[str] = []
    for t in range(1, 4):
        label = TIER_LABELS[t]
        cmds = ", ".join(f"[bold]{c}[/bold]" for c in TIER_COMMANDS[t])
        if t <= tier:
            tier_lines.append(f"  [green]âœ“ Tier {t} â€” {label}[/green]  ({cmds})")
        elif t == tier + 1:
            tier_lines.append(f"  [yellow]â†’ Tier {t} â€” {label}[/yellow]  ({cmds})")
        else:
            tier_lines.append(f"  [dim]âœ— Tier {t} â€” {label}  ({cmds})[/dim]")

    unlock_hint = ""
    if tier == 1:
        unlock_hint = "\n[dim]To unlock Tier 2: configure an LLM API key (re-run [bold]divapply init[/bold]).[/dim]"
    elif tier == 2:
        unlock_hint = "\n[dim]To unlock Tier 3: install Codex or Claude Code + Chrome.[/dim]"

    console.print(
        Panel.fit(
            "[bold green]Setup complete![/bold green]\n\n"
            f"[bold]Your tier: Tier {tier} â€” {TIER_LABELS[tier]}[/bold]\n\n"
            + "\n".join(tier_lines)
            + unlock_hint,
            border_style="green",
        )
    )

