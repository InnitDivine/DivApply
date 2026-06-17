"""Local browser editor for simple DivApply user settings."""

from __future__ import annotations

import html
import json
import secrets
import threading
import urllib.parse
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

import yaml

from divapply.config import PROFILE_PATH, SEARCH_CONFIG_PATH
from divapply.local_server import bind_local_server
from divapply.security import (
    local_request_is_same_origin,
    parse_local_form_length,
    write_private_text,
)


def _read_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


def _read_yaml(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    return data if isinstance(data, dict) else {}


def _to_float(value: Any, default: float) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _to_int(value: Any, default: int) -> int:
    try:
        return int(float(value))
    except (TypeError, ValueError):
        return default


def _money(value: float) -> str:
    return f"{value:,.0f}"


def _list_to_text(values: Any) -> str:
    if not isinstance(values, list):
        return ""
    lines: list[str] = []
    for value in values:
        if isinstance(value, dict):
            query = str(value.get("query") or value.get("term") or "").strip()
            tier = value.get("tier")
            if query:
                lines.append(f"{query} | {tier or 1}")
        else:
            text = str(value).strip()
            if text:
                lines.append(text)
    return "\n".join(lines)


def _locations_to_text(values: Any) -> str:
    if not isinstance(values, list):
        return ""
    lines: list[str] = []
    for value in values:
        if isinstance(value, dict):
            location = str(value.get("location") or "").strip()
            if not location:
                continue
            remote = bool(value.get("remote", False))
            lines.append(f"{location} | {'remote' if remote else 'onsite'}")
        else:
            text = str(value).strip()
            if text:
                lines.append(f"{text} | onsite")
    return "\n".join(lines)


def _text_to_locations(value: str | None) -> list[dict[str, Any]]:
    locations: list[dict[str, Any]] = []
    for line in _text_to_list(value):
        if "|" in line:
            location, mode = [part.strip() for part in line.split("|", 1)]
            remote = mode.lower() in {"remote", "true", "yes", "1"}
        else:
            location = line
            remote = False
        if location:
            locations.append({"location": location, "remote": remote})
    return locations


def _text_to_list(value: str | None) -> list[str]:
    if not value:
        return []
    return [line.strip() for line in value.splitlines() if line.strip()]


def _text_to_queries(value: str | None) -> list[dict[str, Any]]:
    queries: list[dict[str, Any]] = []
    for line in _text_to_list(value):
        if "|" in line:
            query, tier_raw = [part.strip() for part in line.split("|", 1)]
            tier = _to_int(tier_raw, 1)
        else:
            query = line
            tier = 1
        if query:
            queries.append({"query": query, "tier": max(1, min(3, tier))})
    return queries


def _work_history_to_text(values: Any) -> str:
    if not isinstance(values, list):
        return ""
    lines: list[str] = []
    for value in values:
        if not isinstance(value, dict):
            continue
        title = str(value.get("title") or "").strip()
        company = str(value.get("company") or "").strip()
        dates = str(value.get("dates") or "").strip()
        tasks = str(value.get("tasks") or "").strip()
        if title or company or dates or tasks:
            lines.append(" | ".join([title, company, dates, tasks]))
    return "\n".join(lines)


def _text_to_work_history(value: str | None) -> list[dict[str, str]]:
    jobs: list[dict[str, str]] = []
    for line in _text_to_list(value):
        parts = [part.strip() for part in line.split("|", 3)]
        parts += [""] * (4 - len(parts))
        title, company, dates, tasks = parts
        if title or company:
            jobs.append({"title": title, "company": company, "dates": dates, "tasks": tasks})
    return jobs


def _education_to_text(values: Any) -> str:
    if not isinstance(values, list):
        return ""
    lines: list[str] = []
    for value in values:
        if not isinstance(value, dict):
            continue
        school = str(value.get("school") or "").strip()
        degree = str(value.get("degree") or "").strip()
        major = str(value.get("major") or "").strip()
        dates = " to ".join(
            part for part in (str(value.get("start_year") or "").strip(), str(value.get("end_year") or "").strip()) if part
        )
        gpa = str(value.get("gpa") or "").strip()
        notes = str(value.get("notes") or "").strip()
        if school or degree or major:
            lines.append(" | ".join([school, degree, major, dates, gpa, notes]))
    return "\n".join(lines)


def _text_to_education(value: str | None) -> list[dict[str, Any]]:
    schools: list[dict[str, Any]] = []
    for line in _text_to_list(value):
        parts = [part.strip() for part in line.split("|", 5)]
        parts += [""] * (6 - len(parts))
        school, degree, major, dates, gpa, notes = parts
        if not (school or degree or major):
            continue
        start_year = ""
        end_year = ""
        if " to " in dates:
            start_year, end_year = [part.strip() for part in dates.split(" to ", 1)]
        elif "-" in dates:
            start_year, end_year = [part.strip() for part in dates.split("-", 1)]
        elif dates:
            start_year = dates
        schools.append(
            {
                "school": school,
                "degree": degree,
                "major": major,
                "gpa": gpa,
                "start_year": start_year,
                "end_year": end_year,
                "notes": notes,
            }
        )
    return schools


def _certifications_to_text(values: Any) -> str:
    if not isinstance(values, list):
        return ""
    lines: list[str] = []
    for value in values:
        if not isinstance(value, dict):
            continue
        name = str(value.get("name") or "").strip()
        issuer = str(value.get("issuer") or "").strip()
        status = str(value.get("status") or "").strip()
        expires = str(value.get("expires") or "").strip()
        if name:
            lines.append(" | ".join([name, issuer, status, expires]))
    return "\n".join(lines)


def _text_to_certifications(value: str | None) -> list[dict[str, str]]:
    certifications: list[dict[str, str]] = []
    for line in _text_to_list(value):
        parts = [part.strip() for part in line.split("|", 3)]
        parts += [""] * (4 - len(parts))
        name, issuer, status, expires = parts
        if not name:
            continue
        cert: dict[str, str] = {"name": name}
        if issuer:
            cert["issuer"] = issuer
        if status:
            cert["status"] = status
        if expires:
            cert["expires"] = expires
        certifications.append(cert)
    return certifications


def _references_to_text(values: Any) -> str:
    if not isinstance(values, list):
        return ""
    lines: list[str] = []
    for value in values:
        if not isinstance(value, dict):
            continue
        name = str(value.get("name") or "").strip()
        title = str(value.get("title") or "").strip()
        phone = str(value.get("phone") or "").strip()
        email = str(value.get("email") or "").strip()
        address = str(value.get("address") or "").strip()
        if name:
            lines.append(" | ".join([name, title, phone, email, address]))
    return "\n".join(lines)


def _text_to_references(value: str | None) -> list[dict[str, str]]:
    references: list[dict[str, str]] = []
    for line in _text_to_list(value):
        parts = [part.strip() for part in line.split("|", 4)]
        parts += [""] * (5 - len(parts))
        name, title, phone, email, address = parts
        if not name:
            continue
        reference = {"name": name}
        if title:
            reference["title"] = title
        if phone:
            reference["phone"] = phone
        if email:
            reference["email"] = email
        if address:
            reference["address"] = address
        references.append(reference)
    return references


def _merge_records(
    existing: Any,
    edited: list[dict[str, Any]],
    key_fields: tuple[str, ...],
) -> list[dict[str, Any]]:
    """Overlay editor rows onto existing profile records without dropping extra facts."""
    if not isinstance(existing, list):
        existing = []

    def key_for(record: dict[str, Any]) -> tuple[str, ...]:
        return tuple(str(record.get(field) or "").strip().casefold() for field in key_fields)

    existing_by_key = {
        key_for(record): dict(record)
        for record in existing
        if isinstance(record, dict) and any(key_for(record))
    }

    merged: list[dict[str, Any]] = []
    used_keys: set[tuple[str, ...]] = set()
    for record in edited:
        key = key_for(record)
        base = existing_by_key.get(key, {}).copy()
        base.update(record)
        merged.append(base)
        used_keys.add(key)

    # Preserve records that the editor cannot represent cleanly, such as
    # imported records missing a display key. User-visible keyed records are
    # removed when their line is removed from the editor.
    for record in existing:
        if not isinstance(record, dict):
            continue
        key = key_for(record)
        if not any(key) and key not in used_keys:
            merged.append(dict(record))
    return merged


def _split_name(personal: dict[str, Any]) -> tuple[str, str, str]:
    first = str(personal.get("first_name") or "").strip()
    middle = str(personal.get("middle_name") or "").strip()
    last = str(personal.get("last_name") or "").strip()
    if first or middle or last:
        return first, middle, last
    full_name = str(personal.get("full_name") or "").strip()
    parts = full_name.split()
    if not parts:
        return "", "", ""
    if len(parts) == 1:
        return parts[0], "", ""
    if len(parts) == 2:
        return parts[0], "", parts[1]
    return parts[0], " ".join(parts[1:-1]), parts[-1]


def _full_name(first: str, middle: str, last: str) -> str:
    return " ".join(part for part in (first.strip(), middle.strip(), last.strip()) if part)


def _schedule_hours(schedule_type: str) -> int:
    if schedule_type == "full_time":
        return 40
    return 20


def _annual_from_hourly(hourly: float, schedule_type: str) -> float:
    return hourly * _schedule_hours(schedule_type) * 52


def _option(value: str, current: str, label: str) -> str:
    selected = " selected" if value == current else ""
    return f'<option value="{_esc(value)}"{selected}>{_esc(label)}</option>'


def _profile_values(profile: dict[str, Any], search_cfg: dict[str, Any]) -> dict[str, Any]:
    compensation = profile.get("compensation", {}) if isinstance(profile.get("compensation"), dict) else {}
    personal = profile.get("personal", {}) if isinstance(profile.get("personal"), dict) else {}

    hourly = _to_float(compensation.get("target_hourly_rate"), 15.0)
    schedule_type = "part_time" if search_cfg.get("require_part_time", True) else "either"
    if schedule_type not in {"part_time", "full_time", "either"}:
        schedule_type = "part_time"
    first_name, middle_name, last_name = _split_name(personal)
    defaults = search_cfg.get("defaults", {}) if isinstance(search_cfg.get("defaults"), dict) else {}
    location_cfg = search_cfg.get("location", {}) if isinstance(search_cfg.get("location"), dict) else {}

    first_location = ""
    locations = search_cfg.get("locations")
    if isinstance(locations, list) and locations and isinstance(locations[0], dict):
        first_location = str(locations[0].get("location") or "")

    return {
        "first_name": first_name,
        "middle_name": middle_name,
        "last_name": last_name,
        "preferred_name": personal.get("preferred_name", ""),
        "email": personal.get("email", ""),
        "phone": personal.get("phone", ""),
        "address": personal.get("address", ""),
        "city": personal.get("city", ""),
        "province_state": personal.get("province_state", ""),
        "postal_code": personal.get("postal_code", ""),
        "country": personal.get("country", "United States"),
        "linkedin_url": personal.get("linkedin_url", ""),
        "github_url": personal.get("github_url", ""),
        "website_url": personal.get("website_url", ""),
        "search_city": search_cfg.get("search_city") or first_location or personal.get("city") or "Logan, UT",
        "skills": _list_to_text(profile.get("skills")),
        "work_history": _work_history_to_text(profile.get("work_history")),
        "education": _education_to_text(profile.get("education_schools")),
        "certifications": _certifications_to_text(profile.get("certifications")),
        "references": _references_to_text(profile.get("references")),
        "projects": _list_to_text((profile.get("resume_facts") or {}).get("preserved_projects") if isinstance(profile.get("resume_facts"), dict) else []),
        "real_metrics": _list_to_text((profile.get("resume_facts") or {}).get("real_metrics") if isinstance(profile.get("resume_facts"), dict) else []),
        "schedule_type": schedule_type,
        "hourly": hourly,
        "salary_part_time": _annual_from_hourly(hourly, "part_time"),
        "salary_full_time": _annual_from_hourly(hourly, "full_time"),
        "locations": _locations_to_text(search_cfg.get("locations")),
        "accept_patterns": _list_to_text(location_cfg.get("accept_patterns") or search_cfg.get("location_accept") or search_cfg.get("nearby_locations")),
        "reject_patterns": _list_to_text(location_cfg.get("reject_patterns") or search_cfg.get("location_reject_non_remote") or search_cfg.get("reject_locations")),
        "queries": _list_to_text(search_cfg.get("queries") or search_cfg.get("search_terms")),
        "boards": _list_to_text(search_cfg.get("boards") or search_cfg.get("sites") or search_cfg.get("job_boards")),
        "exclude_titles": _list_to_text(search_cfg.get("exclude_titles") or search_cfg.get("avoid_titles")),
        "include_titles": _list_to_text(search_cfg.get("include_titles") or search_cfg.get("target_titles")),
        "results_per_site": _to_int(defaults.get("results_per_site"), 50),
        "hours_old": _to_int(defaults.get("hours_old"), 168),
    }


def _esc(value: Any) -> str:
    return html.escape(str(value or ""), quote=True)


def render_editor(profile: dict[str, Any], search_cfg: dict[str, Any], *, token: str, saved: bool = False) -> str:
    """Render the local settings editor HTML."""
    values = _profile_values(profile, search_cfg)
    saved_banner = (
        '<div class="notice" role="status">Saved. DivApply will use these settings on the next run.</div>'
        if saved else ""
    )
    hourly = values["hourly"]
    schedule_options = "".join([
        _option("part_time", values["schedule_type"], "Part-time"),
        _option("full_time", values["schedule_type"], "Full-time"),
        _option("either", values["schedule_type"], "Either"),
    ])
    return f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>DivApply Settings</title>
  <style>
    :root {{
      color-scheme: light;
      --bg: #f7f8fa;
      --panel: #ffffff;
      --text: #172033;
      --muted: #637083;
      --border: #d8dee8;
      --accent: #0f766e;
      --accent-dark: #0b5f59;
      --focus: #2563eb;
    }}
    * {{ box-sizing: border-box; }}
    body {{
      margin: 0;
      font: 15px/1.5 system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
      background: var(--bg);
      color: var(--text);
    }}
    .skip-link {{
      position: absolute;
      left: 18px;
      top: 12px;
      transform: translateY(-180%);
      background: var(--text);
      color: #fff;
      padding: 8px 10px;
      border-radius: 6px;
      font-weight: 700;
      z-index: 10;
    }}
    .skip-link:focus-visible {{ transform: translateY(0); }}
    main {{
      max-width: 980px;
      margin: 0 auto;
      padding: 28px 18px 42px;
    }}
    header {{
      display: flex;
      align-items: end;
      justify-content: space-between;
      gap: 18px;
      margin-bottom: 18px;
    }}
    h1 {{
      margin: 0;
      font-size: 28px;
      letter-spacing: 0;
    }}
    .subtle {{ color: var(--muted); margin: 4px 0 0; }}
    form {{
      display: grid;
      grid-template-columns: 1fr 1fr;
      gap: 16px;
    }}
    section {{
      background: var(--panel);
      border: 1px solid var(--border);
      border-radius: 8px;
      padding: 18px;
    }}
    section.wide {{ grid-column: 1 / -1; }}
    h2 {{ margin: 0 0 14px; font-size: 17px; }}
    label {{
      display: block;
      font-weight: 650;
      margin: 14px 0 6px;
    }}
    input:not([type="hidden"]), textarea, select {{
      width: 100%;
      border: 1px solid var(--border);
      border-radius: 6px;
      padding: 10px 11px;
      font: inherit;
      color: var(--text);
      background: #fff;
      min-height: 44px;
    }}
    textarea {{ min-height: 92px; resize: vertical; }}
    textarea.tall {{ min-height: 180px; }}
    textarea.huge {{ min-height: 240px; }}
    input[type="range"] {{
      width: 100%;
      accent-color: var(--accent);
      min-height: 44px;
    }}
    input:focus, textarea:focus, select:focus, button:focus {{
      outline: 3px solid color-mix(in srgb, var(--focus) 25%, transparent);
      outline-offset: 2px;
      border-color: var(--focus);
    }}
    .slider-row {{
      display: grid;
      grid-template-columns: 1fr auto;
      gap: 12px;
      align-items: center;
    }}
    .compact-grid {{
      display: grid;
      grid-template-columns: repeat(2, minmax(0, 1fr));
      gap: 0 12px;
    }}
    .compact-grid .wide-field {{ grid-column: 1 / -1; }}
    .value-pill {{
      min-width: 84px;
      text-align: right;
      font-weight: 700;
      font-variant-numeric: tabular-nums;
    }}
    .actions {{
      grid-column: 1 / -1;
      display: flex;
      justify-content: flex-end;
      gap: 10px;
    }}
    button {{
      border: 0;
      border-radius: 7px;
      padding: 11px 16px;
      background: var(--accent);
      color: white;
      font: inherit;
      font-weight: 700;
      cursor: pointer;
      min-height: 44px;
    }}
    button:hover {{ background: var(--accent-dark); }}
    .notice {{
      border: 1px solid #86efac;
      background: #f0fdf4;
      color: #166534;
      border-radius: 8px;
      padding: 10px 12px;
      margin-bottom: 16px;
      font-weight: 650;
    }}
    .hint {{ color: var(--muted); font-size: 13px; margin: 5px 0 0; }}
    @media (max-width: 720px) {{
      header {{ display: block; }}
      form, .compact-grid {{ grid-template-columns: 1fr; }}
      section.wide {{ grid-column: auto; }}
      .compact-grid .wide-field {{ grid-column: auto; }}
      .actions {{ justify-content: stretch; }}
      button {{ width: 100%; }}
    }}
</style>
</head>
<body>
  <a class="skip-link" href="#settings-form">Skip to settings form</a>
  <main>
    <header>
      <div>
        <h1>DivApply Settings</h1>
        <p class="subtle">Edit the simple facts DivApply uses for search, scoring, and apply prompts.</p>
      </div>
    </header>
    {saved_banner}
    <form id="settings-form" method="post" action="/save" aria-label="DivApply settings">
      <input type="hidden" name="token" value="{_esc(token)}">
      <section class="wide">
        <h2>Personal</h2>
        <div class="compact-grid">
          <div>
            <label for="first_name">First name</label>
            <input id="first_name" name="first_name" type="text" autocomplete="given-name" value="{_esc(values['first_name'])}">
          </div>
          <div>
            <label for="middle_name">Middle name</label>
            <input id="middle_name" name="middle_name" type="text" autocomplete="additional-name" value="{_esc(values['middle_name'])}">
          </div>
          <div>
            <label for="last_name">Last name</label>
            <input id="last_name" name="last_name" type="text" autocomplete="family-name" value="{_esc(values['last_name'])}">
          </div>
          <div>
            <label for="preferred_name">Preferred name</label>
            <input id="preferred_name" name="preferred_name" type="text" autocomplete="nickname" value="{_esc(values['preferred_name'])}">
          </div>
          <div>
            <label for="email">Email</label>
            <input id="email" name="email" type="email" autocomplete="email" value="{_esc(values['email'])}">
          </div>
          <div>
            <label for="phone">Phone</label>
            <input id="phone" name="phone" type="tel" autocomplete="tel" value="{_esc(values['phone'])}">
          </div>
          <div class="wide-field">
            <label for="address">Address</label>
            <input id="address" name="address" type="text" autocomplete="street-address" value="{_esc(values['address'])}">
          </div>
          <div>
            <label for="city">City</label>
            <input id="city" name="city" type="text" autocomplete="address-level2" value="{_esc(values['city'])}">
          </div>
          <div>
            <label for="province_state">State</label>
            <input id="province_state" name="province_state" type="text" autocomplete="address-level1" value="{_esc(values['province_state'])}">
          </div>
          <div>
            <label for="postal_code">Postal code</label>
            <input id="postal_code" name="postal_code" type="text" autocomplete="postal-code" value="{_esc(values['postal_code'])}">
          </div>
          <div>
            <label for="country">Country</label>
            <input id="country" name="country" type="text" autocomplete="country-name" value="{_esc(values['country'])}">
          </div>
          <div class="wide-field">
            <label for="linkedin_url">LinkedIn</label>
            <input id="linkedin_url" name="linkedin_url" type="url" autocomplete="url" value="{_esc(values['linkedin_url'])}">
          </div>
          <div class="wide-field">
            <label for="github_url">GitHub</label>
            <input id="github_url" name="github_url" type="url" autocomplete="url" value="{_esc(values['github_url'])}">
          </div>
          <div class="wide-field">
            <label for="website_url">Website</label>
            <input id="website_url" name="website_url" type="url" autocomplete="url" value="{_esc(values['website_url'])}">
          </div>
        </div>
      </section>

      <section>
        <h2>Goal</h2>
        <label for="schedule_type">Work type</label>
        <select id="schedule_type" name="schedule_type">
          {schedule_options}
        </select>

        <label for="target_hourly_rate">Hourly pay target</label>
        <input id="target_hourly_rate" name="target_hourly_rate" type="text" inputmode="decimal" value="{hourly:g}">
        <p class="hint">DivApply converts this to a rough salary target when scoring jobs.</p>

        <p class="hint">Search intent lives in the query list below. Profile facts stay limited to who you are and what you can truthfully claim.</p>
      </section>

      <section>
        <h2>Experience</h2>
        <label for="skills">Skills</label>
        <textarea class="tall" id="skills" name="skills">{_esc(values['skills'])}</textarea>
        <p class="hint">One skill per line. Keep this factual and simple.</p>

        <label for="certifications">Certifications</label>
        <textarea id="certifications" name="certifications">{_esc(values['certifications'])}</textarea>
        <p class="hint">One per line: name | issuer | status | expires.</p>

        <label for="boards">Job boards</label>
        <textarea id="boards" name="boards">{_esc(values['boards'])}</textarea>
        <p class="hint">One board per line, for example: indeed, linkedin, glassdoor.</p>
      </section>

      <section class="wide">
        <h2>Past Jobs</h2>
        <label for="work_history">Work history</label>
        <textarea class="huge" id="work_history" name="work_history">{_esc(values['work_history'])}</textarea>
        <p class="hint">One job per line: title | company | dates | short task summary. DivApply can infer normal duties from the title and tasks, but it will not invent credentials, employers, dates, or metrics.</p>
      </section>

      <section class="wide">
        <h2>Education</h2>
        <label for="education">Schools</label>
        <textarea class="tall" id="education" name="education">{_esc(values['education'])}</textarea>
        <p class="hint">One school per line: school | degree | major | start to end | GPA | notes.</p>
      </section>

      <section>
        <h2>Projects</h2>
        <label for="projects">Real projects</label>
        <textarea class="tall" id="projects" name="projects">{_esc(values['projects'])}</textarea>
        <p class="hint">One real project per line. These can be used in resumes and cover letters.</p>
      </section>

      <section>
        <h2>Metrics</h2>
        <label for="real_metrics">Real metrics and facts</label>
        <textarea class="tall" id="real_metrics" name="real_metrics">{_esc(values['real_metrics'])}</textarea>
        <p class="hint">One truthful number or fact per line, such as GPA, typing speed, or verified outcomes.</p>
      </section>

      <section class="wide">
        <h2>References</h2>
        <label for="references">Professional references</label>
        <textarea class="tall" id="references" name="references">{_esc(values['references'])}</textarea>
        <p class="hint">One reference per line: name | title | phone | email | state or address.</p>
      </section>

      <section class="wide">
        <h2>Locations</h2>
        <label for="locations">Search these locations</label>
        <textarea id="locations" name="locations">{_esc(values['locations'])}</textarea>
        <p class="hint">One per line. Use "Logan, UT | onsite" or "Remote | remote".</p>
      </section>

      <section>
        <h2>Accept Location Text</h2>
        <label for="accept_patterns">Accept postings that mention</label>
        <textarea class="tall" id="accept_patterns" name="accept_patterns">{_esc(values['accept_patterns'])}</textarea>
        <p class="hint">One city, county, state, region, or remote phrase per line.</p>
      </section>

      <section>
        <h2>Reject Location Text</h2>
        <label for="reject_patterns">Reject postings that mention</label>
        <textarea class="tall" id="reject_patterns" name="reject_patterns">{_esc(values['reject_patterns'])}</textarea>
        <p class="hint">Useful for nearby cities, states, or countries you do not want.</p>
      </section>

      <section class="wide">
        <h2>Queries</h2>
        <label for="queries">Search for these jobs</label>
        <textarea class="tall" id="queries" name="queries">{_esc(values['queries'])}</textarea>
        <p class="hint">One search per line. Optional priority: "front desk | 1". Tiers are 1 high, 2 normal, 3 broad.</p>
      </section>

      <section>
        <h2>Skip Titles</h2>
        <label for="exclude_titles">Skip jobs with these title words</label>
        <textarea class="tall" id="exclude_titles" name="exclude_titles">{_esc(values['exclude_titles'])}</textarea>
      </section>

      <section>
        <h2>Must Match Titles</h2>
        <label for="include_titles">Optional strict title filter</label>
        <textarea class="tall" id="include_titles" name="include_titles">{_esc(values['include_titles'])}</textarea>
        <p class="hint">Leave blank for ApplyPilot-style broad search. Add terms only when you want strict filtering.</p>
      </section>

      <section>
        <h2>Defaults</h2>
        <label for="results_per_site">Results per board</label>
        <input id="results_per_site" name="results_per_site" type="text" value="{_esc(values['results_per_site'])}">
        <label for="hours_old">Posted within hours</label>
        <input id="hours_old" name="hours_old" type="text" value="{_esc(values['hours_old'])}">
      </section>

      <div class="actions">
        <button type="submit">Save Settings</button>
      </div>
    </form>
  </main>
</body>
</html>"""


def save_editor_settings(form: dict[str, str]) -> None:
    """Persist editor form values into profile.json and searches.yaml."""
    profile = _read_json(PROFILE_PATH)
    search_cfg = _read_yaml(SEARCH_CONFIG_PATH)

    hourly = max(0.0, _to_float(form.get("target_hourly_rate"), 15.0))
    schedule_type = form.get("schedule_type", "part_time")
    if schedule_type not in {"part_time", "full_time", "either"}:
        schedule_type = "part_time"
    hours = _schedule_hours(schedule_type)
    annual = _annual_from_hourly(hourly, schedule_type)

    personal = dict(profile.get("personal", {}) or {})
    for key in (
        "first_name",
        "middle_name",
        "last_name",
        "preferred_name",
        "email",
        "phone",
        "address",
        "city",
        "province_state",
        "postal_code",
        "country",
        "linkedin_url",
        "github_url",
        "website_url",
    ):
        if key in form:
            personal[key] = form[key].strip()
    personal["full_name"] = _full_name(
        str(personal.get("first_name") or ""),
        str(personal.get("middle_name") or ""),
        str(personal.get("last_name") or ""),
    )
    profile["personal"] = personal

    compensation = dict(profile.get("compensation", {}) or {})
    compensation["target_hourly_rate"] = f"{hourly:g}"
    compensation.pop("target_hours_per_week", None)
    compensation.pop("projected_weekly_income", None)
    compensation.pop("projected_annual_income", None)
    if schedule_type == "either":
        compensation["salary_expectation"] = str(round(_annual_from_hourly(hourly, "full_time")))
        compensation["salary_range_min"] = str(round(_annual_from_hourly(hourly, "part_time")))
        compensation["salary_range_max"] = str(round(_annual_from_hourly(hourly, "full_time")))
    else:
        annual_salary = str(round(annual))
        compensation["salary_expectation"] = annual_salary
        compensation["salary_range_min"] = annual_salary
        compensation["salary_range_max"] = annual_salary
    if schedule_type == "either":
        salary_note = (
            f"part-time about ${_money(_annual_from_hourly(hourly, 'part_time'))}/year "
            f"or full-time about ${_money(_annual_from_hourly(hourly, 'full_time'))}/year"
        )
    else:
        salary_note = f"about ${_money(annual)}/year"
    compensation["hourly_expectation"] = (
        f"Target ${hourly:g}/hr ({salary_note} based on "
        f"{hours} hours per week). "
        "Use the employer's posted range when available."
    )
    profile["compensation"] = compensation

    profile.pop("job_search", None)
    if "skills" in form:
        profile["skills"] = _text_to_list(form.get("skills"))
    if "work_history" in form:
        work_history = _text_to_work_history(form.get("work_history"))
        work_history = _merge_records(profile.get("work_history"), work_history, ("title", "company"))
        profile["work_history"] = work_history
        resume_facts = dict(profile.get("resume_facts", {}) or {})
        resume_facts["preserved_companies"] = [
            str(job.get("company") or "").strip() for job in work_history if str(job.get("company") or "").strip()
        ]
        profile["resume_facts"] = resume_facts
    if "education" in form:
        education = _text_to_education(form.get("education"))
        education = _merge_records(profile.get("education_schools"), education, ("school",))
        profile["education_schools"] = education
        resume_facts = dict(profile.get("resume_facts", {}) or {})
        resume_facts["preserved_school"] = " | ".join(
            str(school.get("school") or "").strip()
            for school in education
            if str(school.get("school") or "").strip()
        )
        profile["resume_facts"] = resume_facts
    if "certifications" in form:
        certifications = _text_to_certifications(form.get("certifications"))
        profile["certifications"] = _merge_records(profile.get("certifications"), certifications, ("name",))
    if "references" in form:
        references = _text_to_references(form.get("references"))
        profile["references"] = _merge_records(profile.get("references"), references, ("name",))
    if "projects" in form or "real_metrics" in form:
        resume_facts = dict(profile.get("resume_facts", {}) or {})
        if "projects" in form:
            resume_facts["preserved_projects"] = _text_to_list(form.get("projects"))
        if "real_metrics" in form:
            resume_facts["real_metrics"] = _text_to_list(form.get("real_metrics"))
        profile["resume_facts"] = resume_facts

    profile.pop("availability", None)

    locations = _text_to_locations(form.get("locations"))
    if locations:
        search_cfg["locations"] = locations

    boards = _text_to_list(form.get("boards"))
    if boards:
        search_cfg["boards"] = boards

    search_cfg["queries"] = _text_to_queries(form.get("queries"))
    exclude_titles = _text_to_list(form.get("exclude_titles"))
    if exclude_titles:
        search_cfg["exclude_titles"] = exclude_titles
    else:
        search_cfg.pop("exclude_titles", None)
        search_cfg.pop("avoid_titles", None)

    include_titles = _text_to_list(form.get("include_titles"))
    if include_titles:
        search_cfg["include_titles"] = include_titles
    else:
        search_cfg.pop("include_titles", None)
        search_cfg.pop("target_titles", None)

    accept_patterns = _text_to_list(form.get("accept_patterns"))
    reject_patterns = _text_to_list(form.get("reject_patterns"))
    if accept_patterns or reject_patterns:
        location_cfg = dict(search_cfg.get("location", {}) or {})
        if accept_patterns:
            location_cfg["accept_patterns"] = accept_patterns
        else:
            location_cfg.pop("accept_patterns", None)
        if reject_patterns:
            location_cfg["reject_patterns"] = reject_patterns
        else:
            location_cfg.pop("reject_patterns", None)
        if location_cfg:
            search_cfg["location"] = location_cfg
    else:
        search_cfg.pop("location", None)

    defaults = dict(search_cfg.get("defaults", {}) or {})
    defaults["results_per_site"] = max(1, _to_int(form.get("results_per_site"), 50))
    defaults["hours_old"] = max(1, _to_int(form.get("hours_old"), 168))
    search_cfg["defaults"] = defaults

    search_cfg["require_part_time"] = schedule_type == "part_time"
    search_cfg.pop("search_terms", None)
    search_cfg.pop("nearby_locations", None)
    search_cfg.pop("reject_locations", None)
    search_cfg.pop("search_city", None)
    search_cfg.pop("sites", None)
    search_cfg.pop("customer_service_title_terms", None)
    search_cfg.pop("customer_service_require_part_time", None)
    search_cfg.pop("customer_service_max_hours_per_week", None)

    write_private_text(PROFILE_PATH, json.dumps(profile, indent=2, ensure_ascii=False) + "\n")
    write_private_text(SEARCH_CONFIG_PATH, yaml.safe_dump(search_cfg, sort_keys=False, allow_unicode=True))


def run_editor(*, host: str = "127.0.0.1", port: int = 8765, open_browser: bool = True) -> str:
    """Start the local editor server and block until interrupted."""
    token = secrets.token_urlsafe(24)
    saved = False

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, _format: str, *_args: Any) -> None:
            return

        def do_GET(self) -> None:  # noqa: N802
            nonlocal saved
            if self.path not in ("/", "/?saved=1"):
                self.send_error(404)
                return
            profile = _read_json(PROFILE_PATH)
            search_cfg = _read_yaml(SEARCH_CONFIG_PATH)
            body = render_editor(profile, search_cfg, token=token, saved=saved or self.path.endswith("saved=1"))
            saved = False
            data = body.encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(data)))
            self.send_header("Cache-Control", "no-store")
            self.send_header("Referrer-Policy", "same-origin")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.end_headers()
            self.wfile.write(data)

        def do_POST(self) -> None:  # noqa: N802
            nonlocal saved
            if self.path != "/save":
                self.send_error(404)
                return
            if not local_request_is_same_origin(self.headers, host, actual_port):
                self.send_error(403)
                return
            try:
                length = parse_local_form_length(self.headers.get("Content-Length"))
                fields = urllib.parse.parse_qs(self.rfile.read(length).decode("utf-8"), keep_blank_values=True)
            except UnicodeDecodeError:
                self.send_error(400)
                return
            except ValueError as exc:
                self.send_error(413 if "large" in str(exc) else 400)
                return
            form = {key: values[-1] for key, values in fields.items()}
            if form.get("token") != token:
                self.send_error(403)
                return
            save_editor_settings(form)
            saved = True
            self.send_response(303)
            self.send_header("Location", "/?saved=1")
            self.end_headers()

    server, actual_port = bind_local_server(ThreadingHTTPServer, Handler, host, port)
    url = f"http://{host}:{actual_port}/"
    if open_browser:
        threading.Timer(0.2, lambda: webbrowser.open(url)).start()
    try:
        server.serve_forever()
    finally:
        server.server_close()
    return url
