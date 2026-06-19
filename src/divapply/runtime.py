"""Runtime capability detection for browsers, apply backends, and tiers."""

from __future__ import annotations

import os
import platform
import shutil
import tomllib
from pathlib import Path


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
    "chromium": "Chromium",
    "firefox": "Firefox",
    "chrome": "Google Chrome",
    "msedge": "Microsoft Edge",
    "webkit": "WebKit",
}


def _existing_file(path: str | None) -> str | None:
    if not path:
        return None
    candidate = Path(path).expanduser()
    return str(candidate) if candidate.is_file() else None


def _codex_cli_from_config() -> str | None:
    config_path = Path(os.environ.get("CODEX_HOME", Path.home() / ".codex")) / "config.toml"
    if not config_path.is_file():
        return None
    try:
        data = tomllib.loads(config_path.read_text(encoding="utf-8"))
    except (OSError, tomllib.TOMLDecodeError):
        return None

    servers = data.get("mcp_servers", {})
    if not isinstance(servers, dict):
        return None
    node_repl = servers.get("node_repl", {})
    if not isinstance(node_repl, dict):
        return None
    env = node_repl.get("env", {})
    if not isinstance(env, dict):
        return None
    return _existing_file(env.get("CODEX_CLI_PATH"))


def get_apply_backend_executable(backend: str) -> str | None:
    """Return the executable path used to launch an apply backend."""
    normalized = backend.strip().lower()
    if normalized == "codex":
        for value in (
            os.environ.get("DIVAPPLY_CODEX_PATH"),
            os.environ.get("CODEX_CLI_PATH"),
            _codex_cli_from_config(),
            shutil.which("codex"),
        ):
            resolved = _existing_file(value)
            if resolved:
                return resolved
        return None
    if normalized == "claude":
        return shutil.which("claude")
    return None


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


def get_available_apply_backends() -> dict[str, str]:
    """Return detected auto-apply agent CLIs keyed by backend name."""
    backends: dict[str, str] = {}
    for name in ("codex", "claude"):
        resolved = get_apply_backend_executable(name)
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
    requested = preferred or os.environ.get("DIVAPPLY_BROWSER") or os.environ.get("APPLYPILOT_BROWSER") or "chromium"
    browser = requested.strip().lower()
    return browser if browser in APPLY_BROWSER_LABELS else "chromium"


def get_apply_browser_label(browser: str | None) -> str:
    """Return a human-readable label for the apply browser."""
    if not browser:
        return "Browser"
    return APPLY_BROWSER_LABELS.get(browser, browser)


def get_tier(preferred_backend: str | None = None, preferred_browser: str | None = None) -> int:
    """Detect the current tier based on available dependencies."""
    from divapply.config import load_env

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
        missing.append("LLM API key - run [bold]divapply init[/bold] or set GEMINI_API_KEY")
    if required >= 3:
        if get_apply_backend(preferred_backend) is None:
            missing.append("Apply agent CLI - install Codex or Claude Code for auto-apply")
        if shutil.which("npx") is None:
            missing.append("Node.js / npx - install Node.js 18+ for Playwright MCP")
        if get_apply_browser(preferred_browser) == "chrome":
            try:
                get_chrome_path()
            except FileNotFoundError:
                missing.append("Chrome/Chromium - install or set CHROME_PATH")

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
