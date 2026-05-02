"""DivApply configuration: paths, platform detection, user data."""

import os
import platform
import shutil
from pathlib import Path

# User data directory - all user-specific files live here.
#
# New installs default to ~/.divapply, but we still read legacy ~/.applypilot
# files so existing users can migrate without losing data.
APP_DIR = Path(os.environ.get("DIVAPPLY_DIR", os.environ.get("APPLYPILOT_DIR", Path.home() / ".divapply")))
LEGACY_APP_DIR = Path(os.environ.get("APPLYPILOT_DIR", Path.home() / ".applypilot"))

# Core paths
DB_PATH = APP_DIR / "divapply.db"
PROFILE_PATH = APP_DIR / "profile.json"
RESUME_PATH = APP_DIR / "resume.txt"
RESUME_PDF_PATH = APP_DIR / "resume.pdf"
SEARCH_CONFIG_PATH = APP_DIR / "searches.yaml"
ENV_PATH = APP_DIR / ".env"
ANSWERS_PATH = APP_DIR / "answers.yaml"
LEGACY_DB_PATH = LEGACY_APP_DIR / "applypilot.db"
LEGACY_PROFILE_PATH = LEGACY_APP_DIR / "profile.json"
LEGACY_SEARCH_CONFIG_PATH = LEGACY_APP_DIR / "searches.yaml"
LEGACY_ENV_PATH = LEGACY_APP_DIR / ".env"

# Generated output
TAILORED_DIR = APP_DIR / "tailored_resumes"
COVER_LETTER_DIR = APP_DIR / "cover_letters"
LOG_DIR = APP_DIR / "logs"

# Chrome worker isolation
CHROME_WORKER_DIR = APP_DIR / "chrome-workers"
APPLY_WORKER_DIR = APP_DIR / "apply-workers"

# Package-shipped config (YAML registries)
PACKAGE_DIR = Path(__file__).parent
CONFIG_DIR = PACKAGE_DIR / "config"


def get_chrome_path() -> str:
    """Auto-detect Chrome/Chromium executable path, cross-platform.

    Override with CHROME_PATH environment variable.
    """
    env_path = os.environ.get("CHROME_PATH")
    if env_path and Path(env_path).exists():
        return env_path

    system = platform.system()

    if system == "Windows":
        candidates = [
            Path(os.environ.get("PROGRAMFILES", r"C:\Program Files")) / "Google/Chrome/Application/chrome.exe",
            Path(os.environ.get("PROGRAMFILES(X86)", r"C:\Program Files (x86)")) / "Google/Chrome/Application/chrome.exe",
            Path(os.environ.get("LOCALAPPDATA", "")) / "Google/Chrome/Application/chrome.exe",
        ]
    elif system == "Darwin":
        candidates = [
            Path("/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"),
            Path("/Applications/Chromium.app/Contents/MacOS/Chromium"),
        ]
    else:
        candidates = []
        for name in ("google-chrome", "google-chrome-stable", "chromium-browser", "chromium"):
            found = shutil.which(name)
            if found:
                candidates.append(Path(found))

    for candidate in candidates:
        if candidate and candidate.exists():
            return str(candidate)

    for name in ("google-chrome", "google-chrome-stable", "chromium-browser", "chromium", "chrome"):
        found = shutil.which(name)
        if found:
            return found

    raise FileNotFoundError(
        "Chrome/Chromium not found. Install Chrome or set CHROME_PATH environment variable."
    )


def get_chrome_user_data() -> Path:
    """Default Chrome user data directory, cross-platform."""
    system = platform.system()
    if system == "Windows":
        return Path(os.environ.get("LOCALAPPDATA", "")) / "Google" / "Chrome" / "User Data"
    if system == "Darwin":
        return Path.home() / "Library" / "Application Support" / "Google" / "Chrome"
    return Path.home() / ".config" / "google-chrome"


def ensure_dirs() -> None:
    """Create all required directories."""
    for directory in [APP_DIR, TAILORED_DIR, COVER_LETTER_DIR, LOG_DIR, CHROME_WORKER_DIR, APPLY_WORKER_DIR]:
        directory.mkdir(parents=True, exist_ok=True)


def _read_text_with_legacy(current: Path, legacy: Path | None = None, *, encoding: str = "utf-8") -> str | None:
    """Read current user data, falling back to a legacy file."""
    if current.exists():
        return current.read_text(encoding=encoding)
    if legacy is not None and legacy.exists():
        return legacy.read_text(encoding=encoding)
    return None


def _copy_if_present(source: Path, target: Path, *, overwrite: bool = False) -> str:
    """Copy a file when available and report the action taken."""
    if not source.exists():
        return "missing"
    try:
        if source.resolve() == target.resolve():
            return "skipped"
    except Exception:
        pass
    if target.exists() and not overwrite:
        return "skipped"
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source, target)
    return "copied"


def migrate_legacy_user_data(
    *,
    source_dir: Path | None = None,
    target_dir: Path | None = None,
    overwrite: bool = False,
) -> dict[str, str]:
    """Copy legacy files into the current DivApply layout.

    This intentionally preserves the current files unless overwrite=True.
    The helper is used by the CLI migrate command and is safe to call on a
    fresh install or repeatedly during upgrade troubleshooting.
    """
    source_root = Path(source_dir or LEGACY_APP_DIR)
    target_root = Path(target_dir or APP_DIR)
    results = {
        "profile": _copy_if_present(source_root / "profile.json", target_root / "profile.json", overwrite=overwrite),
        "searches": _copy_if_present(source_root / "searches.yaml", target_root / "searches.yaml", overwrite=overwrite),
        "env": _copy_if_present(source_root / ".env", target_root / ".env", overwrite=overwrite),
        "resume_txt": _copy_if_present(source_root / "resume.txt", target_root / "resume.txt", overwrite=overwrite),
        "resume_pdf": _copy_if_present(source_root / "resume.pdf", target_root / "resume.pdf", overwrite=overwrite),
        "database": _copy_if_present(source_root / "applypilot.db", target_root / "divapply.db", overwrite=overwrite),
    }
    return results


def load_profile() -> dict:
    """Load user profile from ~/.divapply/profile.json."""
    import json

    raw = _read_text_with_legacy(PROFILE_PATH, LEGACY_PROFILE_PATH)
    if raw is None:
        raise FileNotFoundError(
            f"Profile not found at {PROFILE_PATH}. Run `divapply init` first."
        )
    profile = json.loads(raw)

    # Hidden coursework knowledge is stored in SQLite so it can inform
    # scoring/tailoring without being exposed in the generated resume text.
    try:
        from divapply.database import get_coursework, load_coursework_seed

        coursework = get_coursework()
        if not coursework:
            coursework = load_coursework_seed()
    except Exception:
        coursework = []

    profile["coursework"] = coursework
    profile["coursework_summary"] = _summarize_coursework(coursework)
    profile["coursework_skills"] = _summarize_coursework_skills(coursework)
    return profile


def _summarize_coursework(coursework: list[dict]) -> list[str]:
    """Condense coursework rows into a compact internal-only summary."""
    if not coursework:
        return []

    grouped: dict[str, list[str]] = {}
    for row in coursework:
        school = (row.get("school") or "Unknown school").strip()
        title = (row.get("course_title") or row.get("course_code") or "").strip()
        subject = (row.get("subject_area") or "").strip()
        if subject:
            item = f"{title} [{subject}]" if title else subject
        else:
            raw = (row.get("raw_text") or "").strip()
            if raw:
                first_line = raw.splitlines()[0].strip()
                item = title or (first_line[:120] + ("..." if len(first_line) > 120 else ""))
            else:
                item = title
        if not item:
            continue
        grouped.setdefault(school, [])
        if item not in grouped[school]:
            grouped[school].append(item)

    summary: list[str] = []
    for school, items in grouped.items():
        summary.append(f"{school}: {', '.join(items[:12])}")
    return summary


def _summarize_coursework_skills(coursework: list[dict]) -> list[str]:
    """Aggregate coursework skill tags into a compact internal-only summary."""
    if not coursework:
        return []

    grouped: dict[str, set[str]] = {}
    for row in coursework:
        school = (row.get("school") or "Unknown school").strip()
        raw_skills = row.get("skills") or []
        if isinstance(raw_skills, str):
            try:
                import json
                raw_skills = json.loads(raw_skills)
            except Exception:
                raw_skills = [s.strip() for s in raw_skills.split(",") if s.strip()]
        if not isinstance(raw_skills, list):
            continue
        grouped.setdefault(school, set()).update(str(skill).strip() for skill in raw_skills if str(skill).strip())

    summary: list[str] = []
    for school, skills in grouped.items():
        summary.append(f"{school}: {', '.join(sorted(skills))}")
    return summary


def load_search_config() -> dict:
    """Load search configuration from ~/.divapply/searches.yaml."""
    import yaml

    raw = _read_text_with_legacy(SEARCH_CONFIG_PATH, LEGACY_SEARCH_CONFIG_PATH)
    if raw is None:
        example = CONFIG_DIR / "searches.example.yaml"
        if example.exists():
            return yaml.safe_load(example.read_text(encoding="utf-8"))
        return {}
    return yaml.safe_load(raw)


def validate_search_config(cfg: dict | None = None) -> dict:
    """Validate search config shape without contacting job boards."""
    if cfg is None:
        cfg = load_search_config()
    cfg = cfg or {}

    errors: list[str] = []
    warnings: list[str] = []

    queries = cfg.get("queries", [])
    locations = cfg.get("locations", [])
    if not isinstance(queries, list) or not queries:
        errors.append("searches.yaml needs a non-empty queries list")
    if not isinstance(locations, list) or not locations:
        errors.append("searches.yaml needs a non-empty locations list")

    for idx, query in enumerate(queries if isinstance(queries, list) else []):
        if not isinstance(query, dict) or not query.get("query"):
            errors.append(f"queries[{idx}] needs a query string")

    for idx, location in enumerate(locations if isinstance(locations, list) else []):
        if not isinstance(location, dict) or not location.get("location"):
            errors.append(f"locations[{idx}] needs a location string")

    boards = cfg.get("sites") or cfg.get("boards") or []
    if boards and not isinstance(boards, list):
        errors.append("sites/boards must be a list")

    filters = cfg.get("filters", {}) or {}
    list_fields = (
        "exclude_titles",
        "title_blacklist",
        "company_blacklist",
        "required_keywords",
        "excluded_keywords",
    )
    for key in list_fields:
        value = cfg.get(key, filters.get(key, []))
        if value and not isinstance(value, list):
            errors.append(f"{key} must be a list")

    remote_pref = str(cfg.get("remote_preference") or filters.get("remote_preference") or "any").lower()
    if remote_pref not in {"any", "all", "none", "no_preference", "remote", "remote_only", "hybrid", "hybrid_only", "onsite", "on_site", "office"}:
        warnings.append(f"remote_preference '{remote_pref}' is unknown; it will be treated as any")

    return {"passed": not errors, "errors": errors, "warnings": warnings}


def load_sites_config() -> dict:
    """Load sites.yaml configuration (sites list, manual_ats, blocked, etc.)."""
    import yaml

    path = CONFIG_DIR / "sites.yaml"
    if not path.exists():
        return {}
    return yaml.safe_load(path.read_text(encoding="utf-8")) or {}


def is_manual_ats(url: str | None) -> bool:
    """Check if a URL routes through an ATS that requires manual application."""
    if not url:
        return False
    sites_cfg = load_sites_config()
    domains = sites_cfg.get("manual_ats", [])
    url_lower = url.lower()
    return any(domain in url_lower for domain in domains)


def load_blocked_sites() -> tuple[set[str], list[str]]:
    """Load blocked sites and URL patterns from sites.yaml."""
    cfg = load_sites_config()
    blocked = cfg.get("blocked", {})
    sites = set(blocked.get("sites", []))
    patterns = blocked.get("url_patterns", [])
    return sites, patterns


def load_blocked_sso() -> list[str]:
    """Load blocked SSO domains from sites.yaml."""
    cfg = load_sites_config()
    return cfg.get("blocked_sso", [])


def load_base_urls() -> dict[str, str | None]:
    """Load site base URLs for URL resolution from sites.yaml."""
    cfg = load_sites_config()
    return cfg.get("base_urls", {})


DEFAULTS = {
    "min_score": 7,
    "max_apply_attempts": 3,
    "max_tailor_attempts": 5,
    "poll_interval": 60,
    "apply_timeout": 300,
    "viewport": "1280x900",
}


def load_env() -> None:
    """Load environment variables from ~/.divapply/.env if it exists."""
    from dotenv import load_dotenv

    if ENV_PATH.exists():
        load_dotenv(ENV_PATH, override=True)
    elif LEGACY_ENV_PATH.exists():
        load_dotenv(LEGACY_ENV_PATH, override=True)
    load_dotenv()


TIER_LABELS = {
    1: "Discovery",
    2: "AI Scoring & Tailoring",
    3: "Full Auto-Apply",
}

TIER_COMMANDS: dict[int, list[str]] = {
    1: ["init", "run discover", "run enrich", "status", "dashboard"],
    2: ["run score", "run tailor", "run cover", "run pdf", "run"],
    3: ["apply"],
}

APPLY_AGENT_LABELS = {
    "codex": "Codex CLI",
    "claude": "Claude Code CLI",
}

APPLY_BROWSER_LABELS = {
    "firefox": "Firefox",
    "chrome": "Google Chrome",
    "msedge": "Microsoft Edge",
    "webkit": "WebKit",
}


def get_available_apply_backends() -> dict[str, str]:
    """Return detected auto-apply agent CLIs keyed by backend name."""
    backends: dict[str, str] = {}
    for name, binary in (("codex", "codex"), ("claude", "claude")):
        resolved = shutil.which(binary)
        if resolved:
            backends[name] = resolved
    return backends


def get_apply_backend(preferred: str | None = None) -> str | None:
    """Resolve which apply backend to use."""
    requested = preferred or os.environ.get("DIVAPPLY_APPLY_BACKEND") or os.environ.get("APPLYPILOT_APPLY_BACKEND")
    available = get_available_apply_backends()
    if requested:
        requested = requested.strip().lower()
        return requested if requested in available else None
    for name in ("codex", "claude"):
        if name in available:
            return name
    return None


def get_apply_backend_label(backend: str | None) -> str:
    """Return a human-readable label for the apply backend."""
    if not backend:
        return "Apply agent CLI"
    return APPLY_AGENT_LABELS.get(backend, backend)


def get_apply_browser(preferred: str | None = None) -> str:
    """Resolve which Playwright MCP browser channel to use."""
    requested = preferred or os.environ.get("DIVAPPLY_BROWSER") or os.environ.get("APPLYPILOT_BROWSER") or "firefox"
    browser = requested.strip().lower()
    return browser if browser in APPLY_BROWSER_LABELS else "firefox"


def get_apply_browser_label(browser: str | None) -> str:
    """Return a human-readable label for the apply browser."""
    if not browser:
        return "Browser"
    return APPLY_BROWSER_LABELS.get(browser, browser)


def get_tier(preferred_backend: str | None = None, preferred_browser: str | None = None) -> int:
    """Detect the current tier based on available dependencies.

    Args:
        preferred_backend: Optional backend to evaluate instead of the env/default backend.
        preferred_browser: Optional browser to evaluate instead of the env/default browser.
    """
    load_env()

    has_llm = any(os.environ.get(key) for key in ("GEMINI_API_KEY", "OPENAI_API_KEY", "LLM_URL"))
    if not has_llm:
        return 1

    has_apply_agent = get_apply_backend(preferred_backend) is not None
    browser = get_apply_browser(preferred_browser)
    has_browser = True
    if browser == "chrome":
        try:
            get_chrome_path()
        except FileNotFoundError:
            has_browser = False

    if has_apply_agent and has_browser and shutil.which("npx") is not None:
        return 3

    return 2


def check_tier(
    required: int,
    feature: str,
    preferred_backend: str | None = None,
    preferred_browser: str | None = None,
) -> None:
    """Raise SystemExit with a clear message if the current tier is too low."""
    current = get_tier(preferred_backend=preferred_backend, preferred_browser=preferred_browser)
    if current >= required:
        return

    from rich.console import Console

    console = Console(stderr=True)
    missing: list[str] = []

    if required >= 2 and not any(os.environ.get(key) for key in ("GEMINI_API_KEY", "OPENAI_API_KEY", "LLM_URL")):
        missing.append("LLM API key â€” run [bold]divapply init[/bold] or set GEMINI_API_KEY")
    if required >= 3:
        if get_apply_backend(preferred_backend) is None:
            missing.append("Apply agent CLI â€” install Codex or Claude Code for auto-apply")
        if shutil.which("npx") is None:
            missing.append("Node.js / npx â€” install Node.js 18+ for Playwright MCP")
        if get_apply_browser(preferred_browser) == "chrome":
            try:
                get_chrome_path()
            except FileNotFoundError:
                missing.append("Chrome/Chromium â€” install or set CHROME_PATH")

    console.print(
        f"\n[red]'{feature}' requires {TIER_LABELS.get(required, f'Tier {required}')} (Tier {required}).[/red]\n"
        f"Current tier: {TIER_LABELS.get(current, f'Tier {current}')} (Tier {current})."
    )
    if missing:
        console.print("\n[yellow]Missing:[/yellow]")
        for item in missing:
            console.print(f"  - {item}")
    console.print()
    raise SystemExit(1)

