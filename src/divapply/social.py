"""Social platform profile syncer â€” full browser automation.

Extracts login cookies from the user's Firefox profile, launches Playwright
Firefox with those cookies, and automates profile updates on each platform.

Supported platforms:
  - GitHub:   auto-update via REST API (needs GITHUB_TOKEN in .env)
  - LinkedIn: automates headline, about, contact info via Playwright
  - Facebook: automates bio, work, education, contact via Playwright

Does NOT modify privacy/visibility settings on any platform.
"""

import json
import logging
import os
import shutil
import sqlite3
import tempfile
import time
from dataclasses import dataclass, field
from pathlib import Path

import httpx

from divapply.config import (
    APP_DIR, RESUME_PATH, load_env, load_profile, ensure_dirs,
)
from divapply.llm import get_client

log = logging.getLogger(__name__)

SCREENSHOT_DIR = APP_DIR / "social_screenshots"


# ---------------------------------------------------------------------------
# Data structures
# ---------------------------------------------------------------------------

@dataclass
class PlatformResult:
    """Outcome of a single platform sync."""
    platform: str
    auto_updated: bool = False
    content: dict[str, str] = field(default_factory=dict)
    error: str | None = None
    sections_updated: list[str] = field(default_factory=list)
    sections_failed: list[str] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Firefox cookie extraction
# ---------------------------------------------------------------------------

def _get_firefox_profile_path() -> Path:
    """Find the user's active Firefox profile directory."""
    profiles_ini = Path(os.environ.get("APPDATA", "")) / "Mozilla" / "Firefox" / "profiles.ini"
    if not profiles_ini.exists():
        raise FileNotFoundError("Firefox profiles.ini not found â€” is Firefox installed?")

    profiles_dir = profiles_ini.parent / "Profiles"

    # Parse profiles.ini to find the default-release profile
    current_section: dict[str, str] = {}
    best: Path | None = None

    for line in profiles_ini.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line.startswith("["):
            if current_section.get("Name") == "default-release":
                rel_path = current_section.get("Path", "")
                if current_section.get("IsRelative") == "1":
                    best = profiles_ini.parent / rel_path.replace("/", os.sep)
                else:
                    best = Path(rel_path)
                break
            current_section = {}
        elif "=" in line:
            key, val = line.split("=", 1)
            current_section[key.strip()] = val.strip()

    # Check last section
    if best is None and current_section.get("Name") == "default-release":
        rel_path = current_section.get("Path", "")
        if current_section.get("IsRelative") == "1":
            best = profiles_ini.parent / rel_path.replace("/", os.sep)
        else:
            best = Path(rel_path)

    if best is None:
        # Fallback: find any profile dir with cookies.sqlite
        for d in profiles_dir.iterdir():
            if d.is_dir() and (d / "cookies.sqlite").exists():
                best = d
                break

    if best is None or not best.exists():
        raise FileNotFoundError("No Firefox profile with cookies found")

    return best


def _extract_cookies(domains: list[str]) -> list[dict]:
    """Extract cookies for specific domains from Firefox's cookies.sqlite.

    Copies the DB files first to avoid locking issues with a running Firefox.
    """
    profile_path = _get_firefox_profile_path()
    cookies_db = profile_path / "cookies.sqlite"
    if not cookies_db.exists():
        raise FileNotFoundError(f"cookies.sqlite not found in {profile_path}")

    # Copy cookie DB + WAL files to a temp location (Firefox holds locks)
    tmp_dir = Path(tempfile.mkdtemp(prefix="DivApply_cookies_"))
    try:
        for suffix in ("", "-shm", "-wal"):
            src = profile_path / f"cookies.sqlite{suffix}"
            if src.exists():
                shutil.copy2(str(src), str(tmp_dir / f"cookies.sqlite{suffix}"))

        conn = sqlite3.connect(str(tmp_dir / "cookies.sqlite"))
        conn.execute("PRAGMA journal_mode=WAL")

        # Build domain filter: match .linkedin.com, .facebook.com, etc.
        where_parts = []
        params: list[str] = []
        for domain in domains:
            where_parts.append("(host LIKE ? OR host LIKE ?)")
            params.extend([f".{domain}", f"%.{domain}"])

        query = (
            "SELECT name, value, host, path, expiry, isSecure, isHttpOnly, sameSite "
            f"FROM moz_cookies WHERE {' OR '.join(where_parts)}"
        )
        rows = conn.execute(query, params).fetchall()
        conn.close()

        # Map Firefox sameSite values to Playwright format
        samesite_map = {0: "None", 1: "Lax", 2: "Strict"}

        cookies: list[dict] = []
        now_s = time.time()
        for name, value, host, path, expiry, secure, http_only, same_site in rows:
            # Playwright requires expires as Unix seconds: -1 (session) or positive.
            # Firefox may store expiry in seconds or milliseconds depending on version.
            # Heuristic: if value > year 3000 in seconds (~32503680000), it's milliseconds.
            if expiry and expiry > 0:
                exp = float(expiry)
                if exp > 32503680000:
                    exp = exp / 1000.0  # convert ms â†’ seconds
                # Skip already-expired cookies
                if exp < now_s:
                    continue
            else:
                exp = -1.0

            cookies.append({
                "name": name,
                "value": value,
                "domain": host,
                "path": path or "/",
                "expires": exp,
                "secure": bool(secure),
                "httpOnly": bool(http_only),
                "sameSite": samesite_map.get(same_site, "Lax"),
            })

        log.info("Extracted %d cookies for %s", len(cookies), ", ".join(domains))
        return cookies

    finally:
        shutil.rmtree(str(tmp_dir), ignore_errors=True)


# ---------------------------------------------------------------------------
# LLM content generation
# ---------------------------------------------------------------------------

def _build_profile_summary(profile: dict) -> str:
    """Condense profile.json into a text brief for LLM prompts."""
    p = profile.get("personal", {})
    exp = profile.get("experience", {})
    narrative = profile.get("professional_narrative", "")
    diffs = profile.get("key_differentiators", [])
    skills = profile.get("skills_boundary", {})

    all_skills: list[str] = []
    for category_skills in skills.values():
        if isinstance(category_skills, list):
            all_skills.extend(category_skills[:5])

    return (
        f"Name: {p.get('full_name', 'N/A')}\n"
        f"Location: {p.get('city', '')}, {p.get('province_state', '')}\n"
        f"Current role: {exp.get('current_job_title', '')} at {exp.get('current_company', '')}\n"
        f"Target role: {exp.get('target_role', '')}\n"
        f"Total experience: {exp.get('years_of_experience_total', '')} years\n"
        f"IT experience: {exp.get('years_of_experience_it', '')} years\n"
        f"Education: {exp.get('education_level', '')}\n"
        f"Narrative: {narrative}\n"
        f"Key differentiators: {'; '.join(diffs[:4])}\n"
        f"Top skills: {', '.join(all_skills[:20])}\n"
        f"GitHub: {p.get('github_url', '')}\n"
        f"LinkedIn: {p.get('linkedin_url', '')}\n"
        f"Website: {p.get('website_url', '')}"
    )


_GITHUB_PROMPT = """Write a GitHub profile bio for this person.

PROFILE:
{profile_summary}

RULES:
- Max 160 characters (GitHub bio limit).
- Professional but approachable.  No emojis.
- Mention current role, strongest tech skills, and what they're building toward.
- Output ONLY the bio text, no quotes, no labels, no explanation."""

_LINKEDIN_PROMPT = """Generate LinkedIn profile content for this person.

PROFILE:
{profile_summary}

CURRENT RESUME:
{resume_excerpt}

Return ONLY valid JSON (no fences, no commentary):
{{
  "headline": "LinkedIn headline â€” max 120 chars, keyword-rich for recruiters",
  "summary": "About section â€” 3-4 short paragraphs, first person, professional. Highlight government experience, IT skills, and career direction. Include keywords recruiters search for. Under 2000 chars.",
  "skills": ["skill1", "skill2", "...up to 15 top skills ordered by relevance"]
}}"""

_FACEBOOK_PROMPT = """Write a short professional Facebook bio/intro for this person.

PROFILE:
{profile_summary}

RULES:
- 2-3 sentences, casual-professional tone.
- Mention current role, location, and what they're working toward.
- No emojis.  No hashtags.
- Output ONLY the bio text, no quotes, no labels."""


def _generate_github_bio(profile: dict) -> str:
    summary = _build_profile_summary(profile)
    prompt = _GITHUB_PROMPT.format(profile_summary=summary)
    client = get_client()
    bio = client.ask(prompt, temperature=0.4, max_tokens=256).strip()
    if bio.startswith('"') and bio.endswith('"'):
        bio = bio[1:-1]
    if len(bio) > 160:
        bio = bio[:157] + "..."
    return bio


def _generate_linkedin_content(profile: dict, resume_text: str) -> dict:
    summary = _build_profile_summary(profile)
    prompt = _LINKEDIN_PROMPT.format(
        profile_summary=summary,
        resume_excerpt=resume_text[:3000],
    )
    client = get_client()
    raw = client.ask(prompt, temperature=0.3, max_tokens=1024)

    try:
        text = raw.strip()
        if text.startswith("```"):
            text = text.split("\n", 1)[1] if "\n" in text else text[3:]
            if text.endswith("```"):
                text = text[:-3]
            text = text.strip()
        data = json.loads(text)
    except json.JSONDecodeError:
        log.warning("LinkedIn LLM returned non-JSON, using raw text")
        data = {"headline": "", "summary": raw, "skills": []}

    return {
        "headline": str(data.get("headline", ""))[:120],
        "summary": str(data.get("summary", "")),
        "skills": data.get("skills", []),
    }


def _generate_facebook_bio(profile: dict) -> str:
    summary = _build_profile_summary(profile)
    prompt = _FACEBOOK_PROMPT.format(profile_summary=summary)
    client = get_client()
    bio = client.ask(prompt, temperature=0.4, max_tokens=256).strip()
    if bio.startswith('"') and bio.endswith('"'):
        bio = bio[1:-1]
    return bio


# ---------------------------------------------------------------------------
# GitHub API update (no browser needed)
# ---------------------------------------------------------------------------

_GITHUB_API = "https://api.github.com"


def _update_github(profile: dict, bio: str) -> PlatformResult:
    """Push bio, blog, location, and name to GitHub via REST API."""
    token = os.environ.get("GITHUB_TOKEN", "")
    result = PlatformResult(platform="GitHub")

    if not token:
        result.content = {"bio": bio}
        result.error = "GITHUB_TOKEN not set â€” bio generated but not pushed"
        return result

    p = profile.get("personal", {})
    payload: dict[str, str] = {"bio": bio}

    website = p.get("website_url", "")
    if website:
        payload["blog"] = website

    city, state = p.get("city", ""), p.get("province_state", "")
    if city and state:
        payload["location"] = f"{city}, {state}"

    name = p.get("full_name", "")
    if name:
        payload["name"] = name

    try:
        resp = httpx.patch(
            f"{_GITHUB_API}/user",
            json=payload,
            headers={
                "Authorization": f"Bearer {token}",
                "Accept": "application/vnd.github+json",
                "X-GitHub-Api-Version": "2022-11-28",
            },
            timeout=15,
        )
        if resp.status_code == 200:
            result.auto_updated = True
            result.content = payload
            result.sections_updated = ["bio", "location", "blog", "name"]
        else:
            result.error = f"GitHub API {resp.status_code}: {resp.text[:200]}"
            result.content = payload
    except httpx.HTTPError as exc:
        result.error = f"GitHub API error: {exc}"
        result.content = payload

    return result


# ---------------------------------------------------------------------------
# Playwright browser helpers
# ---------------------------------------------------------------------------

def _screenshot(page, name: str) -> None:
    """Save a debug screenshot."""
    try:
        SCREENSHOT_DIR.mkdir(parents=True, exist_ok=True)
        path = SCREENSHOT_DIR / f"{name}.png"
        page.screenshot(path=str(path))
        log.info("Screenshot: %s", path)
    except Exception:
        pass


def _safe_fill(page, locator, value: str, clear_first: bool = True) -> bool:
    """Fill a text field with error handling. Returns True on success."""
    try:
        el = locator.first
        el.wait_for(state="visible", timeout=5000)
        if clear_first:
            el.click()
            el.press("Control+a")
            time.sleep(0.2)
        el.fill(value)
        return True
    except Exception as exc:
        log.debug("safe_fill failed: %s", exc)
        return False


def _safe_click(page, locator, timeout: int = 5000) -> bool:
    """Click a locator with error handling. Returns True on success."""
    try:
        el = locator.first
        el.wait_for(state="visible", timeout=timeout)
        el.click()
        return True
    except Exception as exc:
        log.debug("safe_click failed: %s", exc)
        return False


# ---------------------------------------------------------------------------
# LinkedIn automation
# ---------------------------------------------------------------------------

def _get_credentials(profile: dict, domain: str) -> tuple[str, str]:
    """Get login credentials for a domain from profile.json.

    Checks site_credentials first, then falls back to personal email + password.
    Returns (username, password) or ("", "").
    """
    creds = profile.get("site_credentials", {})
    for key, val in creds.items():
        if domain in key:
            return val.get("username", ""), val.get("password", "")
    # Fallback: personal email + password
    p = profile.get("personal", {})
    return p.get("email", ""), p.get("password", "")


def _dismiss_popups(page) -> None:
    """Close Google One Tap, cookie banners, and other overlay popups."""
    # Dismiss Google One Tap / Sign-in popup (iframe overlay)
    try:
        page.evaluate("""
            // Remove Google One Tap iframe
            document.querySelectorAll('iframe[src*="accounts.google.com"]').forEach(f => f.remove());
            // Remove any overlay/backdrop divs that block interaction
            document.querySelectorAll('[id*="credential_picker"]').forEach(e => e.remove());
        """)
    except Exception:
        pass

    # Press Escape to close any modal/popup
    try:
        page.keyboard.press("Escape")
        time.sleep(0.5)
    except Exception:
        pass

    # Close Google popup if it opened as a window
    try:
        for popup_page in page.context.pages:
            if "accounts.google.com" in popup_page.url:
                popup_page.close()
    except Exception:
        pass


def _linkedin_login(page, profile: dict) -> bool:
    """Attempt to log into LinkedIn using credentials from profile.json."""
    email, password = _get_credentials(profile, "linkedin.com")
    if not email or not password:
        log.warning("No LinkedIn credentials found in profile.json")
        return False

    log.info("Attempting LinkedIn login with %s...", email)

    # Navigate to login page
    page.goto("https://www.linkedin.com/login", wait_until="domcontentloaded", timeout=20000)
    time.sleep(2)

    # Dismiss Google One Tap and other popups that block the form
    _dismiss_popups(page)
    time.sleep(0.5)

    # Fill email
    email_field = page.locator("#username")
    if not _safe_fill(page, email_field, email):
        email_field = page.get_by_label("Email or phone")
        if not _safe_fill(page, email_field, email):
            _screenshot(page, "linkedin_login_email_fail")
            return False

    # Fill password
    pw_field = page.locator("#password")
    if not _safe_fill(page, pw_field, password):
        pw_field = page.get_by_label("Password")
        if not _safe_fill(page, pw_field, password):
            _screenshot(page, "linkedin_login_pw_fail")
            return False

    # Dismiss popups again (they can reappear after filling fields)
    _dismiss_popups(page)
    time.sleep(0.3)

    # Click Sign in
    sign_in = page.locator("button[type='submit']")
    if not _safe_click(page, sign_in, timeout=5000):
        sign_in = page.get_by_role("button", name="Sign in")
        if not _safe_click(page, sign_in, timeout=3000):
            _screenshot(page, "linkedin_login_submit_fail")
            return False

    time.sleep(5)  # Wait for redirect after login

    # Check if we landed on feed or got a challenge
    url = page.url.lower()
    if "checkpoint" in url or "challenge" in url:
        _screenshot(page, "linkedin_login_challenge")
        log.warning("LinkedIn login hit a security challenge â€” may need manual verification")
        return False

    if "feed" in url or "mynetwork" in url or "in/" in url:
        log.info("LinkedIn login successful")
        return True

    # One more check â€” are we still on login page?
    if "login" not in url:
        log.info("LinkedIn login appears successful (url: %s)", url[:80])
        return True

    _screenshot(page, "linkedin_login_unknown")
    return False


def _linkedin_check_login(page, profile: dict) -> bool:
    """Verify we're logged into LinkedIn. Attempts login if cookies fail."""
    page.goto("https://www.linkedin.com/feed/", wait_until="domcontentloaded", timeout=20000)
    time.sleep(2)
    url = page.url.lower()

    logged_in = False
    if "login" in url or "authwall" in url or "checkpoint" in url:
        logged_in = False
    else:
        try:
            page.locator("nav").first.wait_for(state="visible", timeout=5000)
            logged_in = True
        except Exception:
            logged_in = "feed" in url

    if logged_in:
        return True

    # Cookies didn't work â€” try logging in with credentials
    log.info("LinkedIn cookies didn't authenticate, attempting login...")
    return _linkedin_login(page, profile)


def _linkedin_update_headline(page, profile: dict, headline: str) -> bool:
    """Navigate to LinkedIn edit intro and update the headline."""
    linkedin_url = profile.get("personal", {}).get("linkedin_url", "")
    if not linkedin_url:
        linkedin_url = "https://www.linkedin.com/in/me"

    # Go to profile page
    page.goto(linkedin_url, wait_until="domcontentloaded", timeout=20000)
    time.sleep(2)

    # Click the edit (pencil) icon on the intro card
    # LinkedIn uses aria-label "Edit intro" on the pencil button
    edit_btn = page.get_by_role("button", name="Edit intro")
    if not _safe_click(page, edit_btn, timeout=5000):
        # Fallback: try navigating directly to the edit URL
        edit_url = linkedin_url.rstrip("/") + "/edit/intro/"
        page.goto(edit_url, wait_until="domcontentloaded", timeout=15000)
        time.sleep(2)

    # Wait for the edit modal/form to appear
    time.sleep(2)

    # Find the headline field â€” LinkedIn labels it "Headline" or has placeholder
    filled = False
    # Strategy 1: get_by_label
    for label_text in ["Headline", "Headline*"]:
        headline_field = page.get_by_label(label_text)
        if _safe_fill(page, headline_field, headline):
            filled = True
            break

    # Strategy 2: look for input near "Headline" text
    if not filled:
        try:
            inputs = page.locator("input[type='text']").all()
            for inp in inputs:
                placeholder = inp.get_attribute("placeholder") or ""
                aria = inp.get_attribute("aria-label") or ""
                if "headline" in placeholder.lower() or "headline" in aria.lower():
                    inp.click()
                    inp.press("Control+a")
                    inp.fill(headline)
                    filled = True
                    break
        except Exception:
            pass

    if not filled:
        _screenshot(page, "linkedin_headline_fail")
        return False

    # Click Save
    time.sleep(0.5)
    save_btn = page.get_by_role("button", name="Save")
    if _safe_click(page, save_btn, timeout=5000):
        time.sleep(2)
        return True

    _screenshot(page, "linkedin_headline_save_fail")
    return False


def _linkedin_update_about(page, profile: dict, summary: str) -> bool:
    """Update the LinkedIn About section."""
    linkedin_url = profile.get("personal", {}).get("linkedin_url", "")
    if not linkedin_url:
        linkedin_url = "https://www.linkedin.com/in/me"

    page.goto(linkedin_url, wait_until="domcontentloaded", timeout=20000)
    time.sleep(2)

    # Scroll down to About section
    page.evaluate("window.scrollBy(0, 500)")
    time.sleep(1)

    # Find the edit button for the About section
    # LinkedIn uses "Edit about" as aria-label
    edit_btn = page.get_by_role("button", name="Edit about")
    if not _safe_click(page, edit_btn, timeout=5000):
        # Try alternate label
        edit_btn = page.locator("[aria-label*='about' i][aria-label*='edit' i]")
        if not _safe_click(page, edit_btn, timeout=3000):
            # Try the section-level "Add a summary" link
            add_btn = page.get_by_role("button", name="Add a summary")
            if not _safe_click(page, add_btn, timeout=3000):
                _screenshot(page, "linkedin_about_edit_fail")
                return False

    time.sleep(2)

    # Find the about textarea
    filled = False

    # Strategy 1: textarea by label/role
    for selector in [
        page.get_by_label("About"),
        page.get_by_label("Summary"),
        page.locator("textarea"),
    ]:
        if _safe_fill(page, selector, summary):
            filled = True
            break

    # Strategy 2: contenteditable div (LinkedIn sometimes uses these)
    if not filled:
        try:
            editable = page.locator("[contenteditable='true']").first
            editable.wait_for(state="visible", timeout=3000)
            editable.click()
            editable.press("Control+a")
            editable.fill(summary)
            filled = True
        except Exception:
            pass

    if not filled:
        _screenshot(page, "linkedin_about_fill_fail")
        return False

    time.sleep(0.5)
    save_btn = page.get_by_role("button", name="Save")
    if _safe_click(page, save_btn, timeout=5000):
        time.sleep(2)
        return True

    _screenshot(page, "linkedin_about_save_fail")
    return False


def _linkedin_update_contact_info(page, profile: dict) -> bool:
    """Update LinkedIn contact info (website, phone, email)."""
    linkedin_url = profile.get("personal", {}).get("linkedin_url", "")
    if not linkedin_url:
        linkedin_url = "https://www.linkedin.com/in/me"

    edit_url = linkedin_url.rstrip("/") + "/edit/contact-info/"
    page.goto(edit_url, wait_until="domcontentloaded", timeout=15000)
    time.sleep(2)

    p = profile.get("personal", {})
    filled_any = False

    # Website URL
    website = p.get("website_url", "") or p.get("portfolio_url", "")
    if website:
        website_field = page.get_by_label("Website")
        if _safe_fill(page, website_field, website):
            filled_any = True
        else:
            url_inputs = page.locator("input[type='url']")
            if _safe_fill(page, url_inputs, website):
                filled_any = True

    # Phone
    phone = p.get("phone", "")
    if phone:
        phone_field = page.get_by_label("Phone")
        if _safe_fill(page, phone_field, phone):
            filled_any = True

    if not filled_any:
        _screenshot(page, "linkedin_contact_fill_fail")
        return False

    time.sleep(0.5)
    save_btn = page.get_by_role("button", name="Save")
    if _safe_click(page, save_btn, timeout=5000):
        time.sleep(2)
        return True

    _screenshot(page, "linkedin_contact_save_fail")
    return False


def _automate_linkedin(context, profile: dict, content: dict) -> PlatformResult:
    """Full LinkedIn automation: headline, about, contact info."""
    result = PlatformResult(platform="LinkedIn")
    result.content = {
        "headline": content["headline"],
        "summary": content["summary"],
        "skills": ", ".join(content.get("skills", [])),
    }

    page = context.new_page()
    page.set_default_timeout(15000)

    try:
        # Check login (attempts credential login if cookies fail)
        if not _linkedin_check_login(page, profile):
            _screenshot(page, "linkedin_not_logged_in")
            result.error = "Not logged into LinkedIn â€” cookies expired and credential login failed"
            return result

        log.info("LinkedIn: logged in, starting updates...")

        # 1. Headline
        if _linkedin_update_headline(page, profile, content["headline"]):
            result.sections_updated.append("headline")
            log.info("LinkedIn headline updated")
        else:
            result.sections_failed.append("headline")
            log.warning("LinkedIn headline update failed")

        # 2. About / Summary
        if _linkedin_update_about(page, profile, content["summary"]):
            result.sections_updated.append("about")
            log.info("LinkedIn about updated")
        else:
            result.sections_failed.append("about")
            log.warning("LinkedIn about update failed")

        # 3. Contact info
        if _linkedin_update_contact_info(page, profile):
            result.sections_updated.append("contact_info")
            log.info("LinkedIn contact info updated")
        else:
            result.sections_failed.append("contact_info")
            log.warning("LinkedIn contact info update failed")

        result.auto_updated = len(result.sections_updated) > 0

    except Exception as exc:
        result.error = str(exc)
        _screenshot(page, "linkedin_error")
        log.error("LinkedIn automation error: %s", exc)
    finally:
        page.close()

    return result


# ---------------------------------------------------------------------------
# Facebook automation
# ---------------------------------------------------------------------------

def _facebook_login(page, profile: dict) -> bool:
    """Attempt to log into Facebook using credentials from profile.json."""
    email, password = _get_credentials(profile, "facebook.com")
    if not email or not password:
        log.warning("No Facebook credentials found in profile.json")
        return False

    log.info("Attempting Facebook login with %s...", email)

    page.goto("https://www.facebook.com/login", wait_until="domcontentloaded", timeout=20000)
    time.sleep(2)

    # Fill email
    email_field = page.locator("#email")
    if not _safe_fill(page, email_field, email):
        email_field = page.get_by_label("Email address or phone number")
        if not _safe_fill(page, email_field, email):
            _screenshot(page, "facebook_login_email_fail")
            return False

    # Fill password
    pw_field = page.locator("#pass")
    if not _safe_fill(page, pw_field, password):
        pw_field = page.get_by_label("Password")
        if not _safe_fill(page, pw_field, password):
            _screenshot(page, "facebook_login_pw_fail")
            return False

    # Click Log in
    login_btn = page.get_by_role("button", name="Log in")
    if not _safe_click(page, login_btn, timeout=5000):
        login_btn = page.locator("button[name='login']")
        if not _safe_click(page, login_btn, timeout=3000):
            _screenshot(page, "facebook_login_submit_fail")
            return False

    time.sleep(5)

    url = page.url.lower()
    if "checkpoint" in url or "two_step_verification" in url:
        _screenshot(page, "facebook_login_challenge")
        log.warning("Facebook login hit a security challenge â€” may need manual verification")
        return False

    # Check we're past login
    login_form = page.locator("#email")
    try:
        login_form.wait_for(state="visible", timeout=2000)
        _screenshot(page, "facebook_login_still_on_login")
        return False  # Still on login page
    except Exception:
        log.info("Facebook login successful")
        return True


def _facebook_check_login(page, profile: dict) -> bool:
    """Verify we're logged into Facebook. Attempts login if cookies fail."""
    page.goto("https://www.facebook.com/", wait_until="domcontentloaded", timeout=20000)
    time.sleep(3)
    url = page.url.lower()

    logged_in = False
    if "login" in url or "/login" in url:
        logged_in = False
    else:
        try:
            page.locator("[aria-label='Facebook']").first.wait_for(state="visible", timeout=5000)
            logged_in = True
        except Exception:
            login_form = page.locator("form[data-testid='royal_login_form']")
            try:
                login_form.wait_for(state="visible", timeout=2000)
                logged_in = False
            except Exception:
                logged_in = True

    if logged_in:
        return True

    log.info("Facebook cookies didn't authenticate, attempting login...")
    return _facebook_login(page, profile)


def _facebook_update_bio(page, bio: str) -> bool:
    """Update the Facebook bio/intro text.

    Current Facebook UI flow: profile â†’ "Edit profile" button â†’ bio textarea
    in the edit profile dialog.
    """
    page.goto("https://www.facebook.com/me", wait_until="domcontentloaded", timeout=20000)
    time.sleep(3)

    # Step 1: Click "Edit profile" button (top of profile card)
    opened_editor = False
    for btn_text in ["Edit profile", "Edit Profile"]:
        edit_profile = page.get_by_role("button", name=btn_text)
        if _safe_click(page, edit_profile, timeout=5000):
            opened_editor = True
            break

    if not opened_editor:
        # Fallback: try link instead of button
        edit_link = page.get_by_role("link", name="Edit profile")
        if _safe_click(page, edit_link, timeout=3000):
            opened_editor = True

    if not opened_editor:
        _screenshot(page, "facebook_edit_profile_fail")
        return False

    time.sleep(3)

    # Step 2: Find bio field in the edit profile dialog/page
    # Look for "Edit" button next to bio, or the bio textarea directly
    filled = False

    # Try clicking "Edit" next to bio section if it's a sub-button
    bio_edit = page.get_by_role("button", name="Edit bio")
    if _safe_click(page, bio_edit, timeout=3000):
        time.sleep(1)

    # Find textarea â€” could be labeled "Bio", "Describe who you are", or just a textarea
    for selector in [
        page.get_by_role("textbox", name="Describe who you are"),
        page.get_by_placeholder("Describe who you are"),
        page.get_by_role("textbox", name="Bio"),
        page.get_by_label("Bio"),
        page.locator("[aria-label*='bio' i]"),
        page.locator("textarea"),
    ]:
        if _safe_fill(page, selector, bio):
            filled = True
            break

    if not filled:
        _screenshot(page, "facebook_bio_fill_fail")
        return False

    # Step 3: Save
    time.sleep(0.5)
    for btn_name in ["Save", "Save bio", "Done"]:
        save_btn = page.get_by_role("button", name=btn_name)
        if _safe_click(page, save_btn, timeout=3000):
            time.sleep(2)
            return True

    _screenshot(page, "facebook_bio_save_fail")
    return False


def _facebook_navigate_about(page, section: str = "") -> bool:
    """Navigate to a Facebook About sub-section.

    Facebook About page has tabs/links: Overview, Work and Education,
    Places Lived, Contact and Basic Info, etc.
    """
    # Go to profile first, then click About tab
    page.goto("https://www.facebook.com/me", wait_until="domcontentloaded", timeout=20000)
    time.sleep(3)

    # Click About tab
    about_link = page.get_by_role("link", name="About")
    if not _safe_click(page, about_link, timeout=5000):
        about_link = page.get_by_text("About", exact=True)
        if not _safe_click(page, about_link, timeout=3000):
            return False

    time.sleep(2)

    # Click sub-section if specified
    if section:
        sub_link = page.get_by_role("link", name=section)
        if not _safe_click(page, sub_link, timeout=5000):
            sub_link = page.get_by_text(section, exact=False)
            _safe_click(page, sub_link, timeout=3000)
        time.sleep(2)

    return True


def _facebook_update_work(page, profile: dict) -> bool:
    """Update Facebook work info from profile data."""
    if not _facebook_navigate_about(page, "Work and education"):
        _screenshot(page, "facebook_work_nav_fail")
        return False

    exp = profile.get("experience", {})
    current_title = exp.get("current_job_title", "")
    current_company = exp.get("current_company", "")

    if not current_company:
        return False

    # Look for "Add a workplace" button or "+" button near Work section
    opened = False
    for btn_text in ["Add a workplace", "Add workplace", "Add a job"]:
        add_btn = page.get_by_role("button", name=btn_text)
        if _safe_click(page, add_btn, timeout=3000):
            opened = True
            break

    if not opened:
        # Try clicking any edit/add button near "Work" text
        edit_btns = page.locator("[aria-label*='workplace' i], [aria-label*='work' i]")
        if not _safe_click(page, edit_btns, timeout=3000):
            _screenshot(page, "facebook_work_edit_fail")
            return False
        opened = True

    time.sleep(2)

    # Fill company
    filled_company = False
    for sel in [
        page.get_by_label("Company"),
        page.get_by_placeholder("Company"),
        page.get_by_label("Employer"),
    ]:
        if _safe_fill(page, sel, current_company):
            filled_company = True
            break

    if not filled_company:
        _screenshot(page, "facebook_work_company_fail")
        return False

    time.sleep(1)
    # Select from autocomplete if it appears
    try:
        suggestion = page.locator("[role='option'], [role='listbox'] li").first
        suggestion.wait_for(state="visible", timeout=3000)
        suggestion.click()
        time.sleep(0.5)
    except Exception:
        pass

    # Fill position/title
    if current_title:
        for sel in [
            page.get_by_label("Position"),
            page.get_by_placeholder("Position"),
            page.get_by_label("Title"),
        ]:
            if _safe_fill(page, sel, current_title):
                break

    # Save
    time.sleep(0.5)
    save_btn = page.get_by_role("button", name="Save")
    if _safe_click(page, save_btn, timeout=5000):
        time.sleep(2)
        return True

    _screenshot(page, "facebook_work_save_fail")
    return False


def _facebook_update_education(page, profile: dict) -> bool:
    """Update Facebook education from profile data."""
    if not _facebook_navigate_about(page, "Work and education"):
        _screenshot(page, "facebook_edu_nav_fail")
        return False

    schools = profile.get("education_schools", [])
    if not schools:
        return False

    school = schools[0]
    school_name = school.get("school", "")
    if not school_name:
        return False

    # Look for college/school add button
    opened = False
    for btn_text in ["Add a college", "Add college", "Add a high school", "Add a university"]:
        add_btn = page.get_by_role("button", name=btn_text)
        if _safe_click(page, add_btn, timeout=3000):
            opened = True
            break

    if not opened:
        _screenshot(page, "facebook_edu_edit_fail")
        return False

    time.sleep(2)

    # Fill school name
    filled = False
    for sel in [
        page.get_by_label("School"),
        page.get_by_placeholder("School"),
        page.get_by_label("College"),
    ]:
        if _safe_fill(page, sel, school_name):
            filled = True
            break

    if not filled:
        _screenshot(page, "facebook_edu_school_fail")
        return False

    time.sleep(1)
    try:
        suggestion = page.locator("[role='option'], [role='listbox'] li").first
        suggestion.wait_for(state="visible", timeout=3000)
        suggestion.click()
        time.sleep(0.5)
    except Exception:
        pass

    # Save
    time.sleep(0.5)
    save_btn = page.get_by_role("button", name="Save")
    if _safe_click(page, save_btn, timeout=5000):
        time.sleep(2)
        return True

    _screenshot(page, "facebook_edu_save_fail")
    return False


def _facebook_update_contact(page, profile: dict) -> bool:
    """Update Facebook contact info (website, email)."""
    if not _facebook_navigate_about(page, "Contact and basic info"):
        _screenshot(page, "facebook_contact_nav_fail")
        return False

    p = profile.get("personal", {})
    updated = False

    # Website
    website = p.get("website_url", "")
    if website:
        for btn_text in ["Add a website", "Add website"]:
            add_btn = page.get_by_role("button", name=btn_text)
            if _safe_click(page, add_btn, timeout=3000):
                time.sleep(1)
                for sel in [
                    page.get_by_label("Website"),
                    page.locator("input[type='url']"),
                    page.locator("input[type='text']").last,
                ]:
                    if _safe_fill(page, sel, website):
                        save_btn = page.get_by_role("button", name="Save")
                        if _safe_click(page, save_btn, timeout=3000):
                            updated = True
                        break
                break

    if not updated:
        _screenshot(page, "facebook_contact_fail")

    return updated


def _automate_facebook(context, profile: dict, bio: str) -> PlatformResult:
    """Full Facebook automation: bio, work, education, contact."""
    result = PlatformResult(platform="Facebook")
    result.content = {"bio": bio}

    page = context.new_page()
    page.set_default_timeout(15000)

    try:
        if not _facebook_check_login(page, profile):
            _screenshot(page, "facebook_not_logged_in")
            result.error = "Not logged into Facebook â€” cookies expired and credential login failed"
            return result

        log.info("Facebook: logged in, starting updates...")

        # 1. Bio
        if _facebook_update_bio(page, bio):
            result.sections_updated.append("bio")
            log.info("Facebook bio updated")
        else:
            result.sections_failed.append("bio")
            log.warning("Facebook bio update failed")

        # 2. Work
        if _facebook_update_work(page, profile):
            result.sections_updated.append("work")
            log.info("Facebook work updated")
        else:
            result.sections_failed.append("work")

        # 3. Education
        if _facebook_update_education(page, profile):
            result.sections_updated.append("education")
            log.info("Facebook education updated")
        else:
            result.sections_failed.append("education")

        # 4. Contact info
        if _facebook_update_contact(page, profile):
            result.sections_updated.append("contact")
            log.info("Facebook contact updated")
        else:
            result.sections_failed.append("contact")

        result.auto_updated = len(result.sections_updated) > 0

    except Exception as exc:
        result.error = str(exc)
        _screenshot(page, "facebook_error")
        log.error("Facebook automation error: %s", exc)
    finally:
        page.close()

    return result


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def sync_profiles(
    platforms: list[str] | None = None,
    dry_run: bool = False,
    headless: bool = False,
) -> list[PlatformResult]:
    """Sync profile data across social platforms.

    Args:
        platforms: Which platforms to sync. None = all.
                   Valid: "github", "linkedin", "facebook".
        dry_run: Generate content but don't push or automate.
        headless: Run browser in headless mode (default: visible).

    Returns:
        List of PlatformResult for each platform attempted.
    """
    load_env()
    ensure_dirs()

    profile = load_profile()
    resume_text = ""
    if RESUME_PATH.exists():
        resume_text = RESUME_PATH.read_text(encoding="utf-8")

    all_platforms = ["github", "linkedin", "facebook"]
    targets = [p.lower() for p in (platforms or all_platforms)]

    results: list[PlatformResult] = []

    # --- GitHub (API, no browser) ---
    if "github" in targets:
        log.info("Generating GitHub bio...")
        bio = _generate_github_bio(profile)
        if dry_run:
            result = PlatformResult(platform="GitHub", content={"bio": bio})
            result.error = "dry run â€” not pushed"
        else:
            result = _update_github(profile, bio)
        results.append(result)

    # --- LinkedIn & Facebook need browser ---
    needs_browser = any(t in targets for t in ("linkedin", "facebook"))

    linkedin_content = None
    facebook_bio = None

    # Generate LLM content first (before opening browser)
    if "linkedin" in targets:
        log.info("Generating LinkedIn content...")
        linkedin_content = _generate_linkedin_content(profile, resume_text)

    if "facebook" in targets:
        log.info("Generating Facebook bio...")
        facebook_bio = _generate_facebook_bio(profile)

    if needs_browser and not dry_run:
        # Extract cookies from Firefox
        domains = []
        if "linkedin" in targets:
            domains.append("linkedin.com")
        if "facebook" in targets:
            domains.append("facebook.com")

        try:
            cookies = _extract_cookies(domains)
        except Exception as exc:
            log.error("Cookie extraction failed: %s", exc)
            for t in targets:
                if t in ("linkedin", "facebook"):
                    results.append(PlatformResult(
                        platform=t.title(),
                        error=f"Cookie extraction failed: {exc}",
                    ))
            cookies = None

        if cookies is not None:
            from playwright.sync_api import sync_playwright

            with sync_playwright() as pw:
                browser = pw.firefox.launch(headless=headless)
                context = browser.new_context(
                    viewport={"width": 1280, "height": 900},
                    user_agent=(
                        "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:128.0) "
                        "Gecko/20100101 Firefox/128.0"
                    ),
                )

                # Inject cookies
                context.add_cookies(cookies)
                log.info("Injected %d cookies into browser context", len(cookies))

                # LinkedIn
                if "linkedin" in targets and linkedin_content:
                    results.append(_automate_linkedin(context, profile, linkedin_content))

                # Facebook
                if "facebook" in targets and facebook_bio:
                    results.append(_automate_facebook(context, profile, facebook_bio))

                context.close()
                browser.close()

    elif needs_browser and dry_run:
        if "linkedin" in targets and linkedin_content:
            results.append(PlatformResult(
                platform="LinkedIn",
                content={
                    "headline": linkedin_content["headline"],
                    "summary": linkedin_content["summary"],
                    "skills": ", ".join(linkedin_content.get("skills", [])),
                },
                error="dry run â€” not automated",
            ))

        if "facebook" in targets and facebook_bio:
            results.append(PlatformResult(
                platform="Facebook",
                content={"bio": facebook_bio},
                error="dry run â€” not automated",
            ))

    # Save snapshot
    out_path = APP_DIR / "social_sync.json"
    snapshot = {}
    for r in results:
        snapshot[r.platform] = {
            "auto_updated": r.auto_updated,
            "content": r.content,
            "sections_updated": r.sections_updated,
            "sections_failed": r.sections_failed,
            "error": r.error,
        }
    out_path.write_text(json.dumps(snapshot, indent=2), encoding="utf-8")
    log.info("Sync snapshot saved to %s", out_path)

    return results

