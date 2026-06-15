"""DivApply HTML Dashboard Generator.

Generates a self-contained HTML dashboard with:
  - Summary stats (total, enriched, scored, high-fit)
  - Score distribution bar chart
  - Jobs-by-source breakdown
  - Filterable job cards grouped by score
  - Client-side search and score filtering
"""

from __future__ import annotations

import logging
import secrets
import threading
import urllib.parse
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from html import escape
from pathlib import Path
from typing import Any

from rich.console import Console

from divapply.config import APP_DIR
from divapply.dashboard_data import fetch_dashboard_snapshot
from divapply.database import archive_job, get_connection, record_reliability_event
from divapply.local_server import find_free_port
from divapply.security import local_request_is_same_origin, parse_local_form_length, sanitize_external_url

console = Console()
log = logging.getLogger(__name__)

SITE_COLORS = {
    "RemoteOK": "#10b981",
    "WelcomeToTheJungle": "#f59e0b",
    "Job Bank Canada": "#3b82f6",
    "CareerJet Canada": "#8b5cf6",
    "Hacker News Jobs": "#ff6600",
    "BuiltIn Remote": "#ec4899",
    "TD Bank": "#00a651",
    "CIBC": "#c41f3e",
    "RBC": "#003168",
    "indeed": "#2164f3",
    "linkedin": "#0a66c2",
    "Dice": "#eb1c26",
    "Glassdoor": "#0caa41",
}

SCORE_LABELS = {
    10: "Perfect Match",
    9: "Excellent Fit",
    8: "Strong Fit",
    7: "Good Fit",
    6: "Moderate+",
    5: "Moderate",
}


def _score_color(score: int) -> str:
    if score >= 7:
        return "#22c55e"
    if score >= 5:
        return "#fbbf24"
    return "#f87171"


def _score_label(score: int) -> str:
    return SCORE_LABELS.get(score, f"Score {score}")


def _site_color(site: str) -> str:
    return SITE_COLORS.get(site, "#94a3b8")


def _safe_href(url: str | None, *, field: str) -> str:
    return escape(sanitize_external_url(url, field=field) or "", quote=True)


def _truncate(value: str, limit: int) -> str:
    value = value.strip()
    if len(value) <= limit:
        return value
    return value[: limit - 3].rstrip() + "..."


def generate_dashboard(
    output_path: str | None = None,
    *,
    archive_endpoint: str | None = None,
    archive_token: str | None = None,
) -> str:
    """Generate an HTML dashboard of all jobs with fit scores.

    Args:
        output_path: Where to write the HTML file. Defaults to ~/.divapply/dashboard.html.

    Returns:
        Absolute path to the generated HTML file.
    """
    out = Path(output_path) if output_path else APP_DIR / "dashboard.html"

    snapshot = fetch_dashboard_snapshot(get_connection())
    total = snapshot.total
    archived = snapshot.archived
    ready = snapshot.ready
    scored = snapshot.scored
    high_fit = snapshot.high_fit
    score_dist = snapshot.score_dist
    site_stats = snapshot.site_stats
    jobs = snapshot.jobs

    # Score distribution bar chart
    score_bar_parts: list[str] = []
    max_count = max(score_dist.values()) if score_dist else 1
    for s in range(10, 0, -1):
        count = score_dist.get(s, 0)
        pct = (count / max_count * 100) if max_count else 0
        score_color = _score_color(s)
        score_bar_parts.append(f"""
        <div class="score-row" aria-label="Score {s}: {count} jobs">
          <span class="score-label">{s}</span>
          <div class="score-bar-track">
            <div class="score-bar-fill" style="width:{pct}%;background:{score_color}" aria-hidden="true"></div>
          </div>
          <span class="score-count">{count}</span>
        </div>""")
    score_bars = "".join(score_bar_parts)

    # Site stats rows
    site_row_parts: list[str] = []
    for s in site_stats:
        site = s["site"] or "?"
        color = _site_color(site)
        avg = s["avg_score"] or 0
        high_pct = s["high_fit"] / max(s["total"], 1) * 100
        mid_pct = s["mid_fit"] / max(s["total"], 1) * 100
        site_row_parts.append(f"""
        <div class="site-row">
          <div class="site-name" style="border-color:{color}">{escape(site)}</div>
          <div class="site-nums">{s['total']} jobs &middot; {s['high_fit']} strong fit &middot; avg score {avg}</div>
          <div class="bar-track" aria-label="{escape(site)}: {s['high_fit']} strong fit and {s['mid_fit']} moderate fit jobs">
            <div class="bar-fill" style="width:{high_pct}%;background:{color}" aria-hidden="true"></div>
            <div class="bar-fill" style="width:{mid_pct}%;background:{color}66" aria-hidden="true"></div>
          </div>
        </div>""")
    site_rows = "".join(site_row_parts)

    # Job cards grouped by score
    job_section_parts: list[str] = []
    current_score = None
    for j in jobs:
        score = j["fit_score"] or 0
        if score != current_score:
            if current_score is not None:
                job_section_parts.append("</div></section>")
            score_color = _score_color(score)
            score_label = _score_label(score)
            count_at_score = score_dist.get(score, 0)
            job_section_parts.append(f"""
            <section class="score-group" aria-labelledby="score-group-{score}">
            <h2 id="score-group-{score}" class="score-header" style="border-color:{score_color}">
              <span class="score-badge" style="background:{score_color}">{score}</span>
              {score_label} ({count_at_score} jobs)
            </h2>
            <div class="job-grid" role="list">""")
            current_score = score

        title = escape(j["title"] or "Untitled")
        url = _safe_href(j["url"], field="dashboard job url")
        salary = escape(j["salary"] or "")
        location = escape(j["location"] or "")
        site = escape(j["site"] or "")
        site_color = _site_color(j["site"] or "")
        apply_url = _safe_href(j["application_url"], field="dashboard apply url")
        # Parse keywords and reasoning from score_reasoning
        reasoning_raw = j["score_reasoning"] or ""
        reasoning_lines = reasoning_raw.split("\n")
        keywords = _truncate(reasoning_lines[0], 120) if reasoning_lines else ""
        reasoning = _truncate(reasoning_lines[1], 200) if len(reasoning_lines) > 1 else ""

        desc_raw = j["full_description"] or ""
        desc_preview = escape(_truncate(desc_raw, 300))
        full_desc_html = escape(j["full_description"] or "").replace("\n", "<br>")
        desc_len = len(desc_raw)
        search_index = escape(
            " ".join(
                part
                for part in (
                    j["title"] or "",
                    j["site"] or "",
                    j["location"] or "",
                    j["salary"] or "",
                    keywords,
                    reasoning,
                    _truncate(desc_raw, 300),
                )
                if part
            ).casefold(),
            quote=True,
        )
        meta_parts = []
        meta_parts.append(
            f'<span class="meta-tag site-tag" style="border-color:{site_color}">{site}</span>'
        )
        if salary:
            meta_parts.append(f'<span class="meta-tag salary">{salary}</span>')
        if location:
            meta_parts.append(f'<span class="meta-tag location">{location[:40]}</span>')
        meta_html = " ".join(meta_parts)

        apply_html = ""
        if apply_url:
            apply_html = (
                f'<a href="{apply_url}" class="apply-link" target="_blank" rel="noopener noreferrer" '
                f'aria-label="Apply to {title}">Apply</a>'
            )
        archive_html = ""
        if archive_endpoint and archive_token:
            archive_html = f"""
              <form method="post" action="{escape(archive_endpoint, quote=True)}" class="archive-form">
                <input type="hidden" name="token" value="{escape(archive_token, quote=True)}">
                <input type="hidden" name="url" value="{escape(j['url'] or '', quote=True)}">
                <button type="submit" class="archive-btn" aria-label="Archive {title}">Archive</button>
              </form>"""

        title_html = (
            f'<a href="{url}" class="job-title" target="_blank" rel="noopener noreferrer">{title}</a>'
            if url
            else f'<span class="job-title">{title}</span>'
        )

        job_section_parts.append(f"""
        <article class="job-card" data-score="{score}" data-site="{escape(j['site'] or '')}" data-location="{location.lower()}" data-search="{search_index}" role="listitem">
          <div class="card-header">
            <span class="score-pill" style="background:{_score_color(score)}" aria-label="Fit score {score}">{score}</span>
            {title_html}
          </div>
          <div class="meta-row">{meta_html}</div>
          {f'<div class="keywords-row">{escape(keywords)}</div>' if keywords else ''}
          {f'<div class="reasoning-row">{escape(reasoning)}</div>' if reasoning else ''}
          <p class="desc-preview">{desc_preview}</p>
          {"<details class='full-desc-details'><summary class='expand-btn'>Full description (" + f'{desc_len:,}' + " characters)</summary><div class='full-desc'>" + full_desc_html + "</div></details>" if j["full_description"] else ""}
          <div class="card-footer">{apply_html}{archive_html}</div>
        </article>""")

    if current_score is not None:
        job_section_parts.append("</div></section>")
    job_sections = "".join(job_section_parts)

    if not job_sections:
        job_sections = """
        <div class="empty-state" role="status">
          No active scored jobs match the dashboard criteria.
        </div>"""

    html = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>DivApply Dashboard</title>
<style>
  * {{ margin: 0; padding: 0; box-sizing: border-box; }}
  html {{ scroll-behavior: smooth; }}
  body {{ font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', system-ui, sans-serif; background: #0f172a; color: #e2e8f0; padding: 2rem; line-height: 1.5; }}
  a {{ color: inherit; }}
  a:focus-visible, button:focus-visible, input:focus-visible, summary:focus-visible {{ outline: 3px solid #f8fafc; outline-offset: 3px; }}
  .skip-link {{ position: absolute; left: 1rem; top: 1rem; z-index: 10; transform: translateY(-150%); background: #f8fafc; color: #0f172a; padding: 0.5rem 0.75rem; border-radius: 6px; font-weight: 700; }}
  .skip-link:focus {{ transform: translateY(0); }}
  .visually-hidden {{ position: absolute; width: 1px; height: 1px; padding: 0; margin: -1px; overflow: hidden; clip: rect(0, 0, 0, 0); white-space: nowrap; border: 0; }}

  h1 {{ font-size: 1.8rem; font-weight: 700; margin-bottom: 0.5rem; }}
  .subtitle {{ color: #94a3b8; margin-bottom: 2rem; }}

  /* Summary cards */
  .summary {{ display: grid; grid-template-columns: repeat(4, 1fr); gap: 1rem; margin-bottom: 2.5rem; }}
  .stat-card {{ background: #1e293b; border: 1px solid #334155; border-radius: 8px; padding: 1.25rem; min-width: 0; }}
  .stat-num {{ font-size: 2rem; font-weight: 700; }}
  .stat-label {{ color: #cbd5e1; font-size: 0.85rem; margin-top: 0.25rem; }}
  .stat-ok .stat-num {{ color: #34d399; }}
  .stat-scored .stat-num {{ color: #60a5fa; }}
  .stat-high .stat-num {{ color: #fbbf24; }}
  .stat-total .stat-num {{ color: #e2e8f0; }}

  /* Filters */
  .filters {{ background: #1e293b; border: 1px solid #334155; border-radius: 8px; padding: 1.25rem; margin-bottom: 2rem; display: flex; gap: 1rem; flex-wrap: wrap; align-items: center; }}
  .filter-label {{ color: #cbd5e1; font-size: 0.85rem; font-weight: 600; }}
  .filter-btn {{ background: #334155; border: 1px solid #475569; color: #e2e8f0; padding: 0.45rem 0.8rem; border-radius: 6px; cursor: pointer; font-size: 0.85rem; min-height: 2.75rem; transition: background 0.15s, color 0.15s; }}
  .filter-btn:hover {{ background: #475569; color: #e2e8f0; }}
  .filter-btn.active {{ background: #bfdbfe; border-color: #bfdbfe; color: #0f172a; font-weight: 700; }}
  .search-input {{ background: #334155; border: 1px solid #64748b; color: #f8fafc; padding: 0.45rem 0.8rem; border-radius: 6px; font-size: 0.9rem; width: 220px; min-height: 2.75rem; }}
  .search-input::placeholder {{ color: #cbd5e1; }}

  /* Score distribution */
  .score-section {{ display: grid; grid-template-columns: 1fr 1fr; gap: 1.5rem; margin-bottom: 2.5rem; }}
  .score-dist {{ background: #1e293b; border: 1px solid #334155; border-radius: 8px; padding: 1.5rem; }}
  .score-dist h2 {{ font-size: 1rem; margin-bottom: 1rem; color: #cbd5e1; }}
  .score-row {{ display: flex; align-items: center; gap: 0.5rem; margin-bottom: 0.4rem; }}
  .score-label {{ width: 1.5rem; text-align: right; font-size: 0.85rem; font-weight: 600; }}
  .score-bar-track {{ flex: 1; height: 14px; background: #334155; border-radius: 4px; overflow: hidden; }}
  .score-bar-fill {{ height: 100%; border-radius: 4px; transition: width 0.3s; }}
  .score-count {{ width: 2.5rem; font-size: 0.85rem; color: #cbd5e1; }}

  /* Site bars */
  .sites-section {{ background: #1e293b; border: 1px solid #334155; border-radius: 8px; padding: 1.5rem; }}
  .sites-section h2 {{ font-size: 1rem; margin-bottom: 1rem; color: #cbd5e1; }}
  .site-row {{ margin-bottom: 0.8rem; }}
  .site-name {{ color: #f8fafc; font-weight: 600; font-size: 0.9rem; border-left: 3px solid #94a3b8; padding-left: 0.5rem; }}
  .site-nums {{ color: #cbd5e1; font-size: 0.8rem; margin: 0.15rem 0; }}
  .bar-track {{ height: 8px; background: #334155; border-radius: 4px; display: flex; overflow: hidden; }}
  .bar-fill {{ height: 100%; transition: width 0.3s; }}

  /* Score group headers */
  .score-header {{ font-size: 1.2rem; font-weight: 600; margin: 2.5rem 0 1rem; padding-bottom: 0.5rem; border-bottom: 3px solid; display: flex; align-items: center; gap: 0.75rem; }}
  .score-badge {{ display: inline-flex; align-items: center; justify-content: center; width: 2rem; height: 2rem; border-radius: 8px; color: #0f172a; font-weight: 700; font-size: 1rem; }}

  /* Job grid */
  .job-grid {{ display: grid; grid-template-columns: repeat(auto-fill, minmax(min(100%, 380px), 1fr)); gap: 1rem; }}

  .job-card {{ background: #1e293b; border: 1px solid #334155; border-left: 3px solid #334155; border-radius: 8px; padding: 1rem; transition: transform 0.15s, box-shadow 0.15s; min-width: 0; content-visibility: auto; contain-intrinsic-size: auto 340px; }}
  .job-card:hover {{ transform: translateY(-2px); box-shadow: 0 4px 12px #00000044; }}
  .job-card[data-score="9"], .job-card[data-score="10"] {{ border-left-color: #10b981; }}
  .job-card[data-score="8"] {{ border-left-color: #34d399; }}
  .job-card[data-score="7"] {{ border-left-color: #60a5fa; }}
  .job-card[data-score="6"] {{ border-left-color: #f59e0b; }}
  .job-card[data-score="5"] {{ border-left-color: #f59e0b88; }}

  .card-header {{ display: flex; align-items: center; gap: 0.5rem; margin-bottom: 0.5rem; }}
  .score-pill {{ display: inline-flex; align-items: center; justify-content: center; min-width: 1.6rem; height: 1.6rem; border-radius: 6px; color: #0f172a; font-weight: 700; font-size: 0.8rem; flex-shrink: 0; }}

  .job-title {{ color: #f8fafc; text-decoration: underline; text-decoration-color: transparent; text-underline-offset: 3px; font-weight: 600; font-size: 0.95rem; overflow-wrap: anywhere; }}
  .job-title:hover {{ color: #93c5fd; text-decoration-color: currentColor; }}

  .meta-row {{ display: flex; flex-wrap: wrap; gap: 0.4rem; margin-bottom: 0.4rem; }}
  .meta-tag {{ font-size: 0.75rem; padding: 0.15rem 0.5rem; border-radius: 4px; background: #334155; color: #e2e8f0; overflow-wrap: anywhere; }}
  .meta-tag.site-tag {{ border-left: 3px solid #94a3b8; }}
  .meta-tag.salary {{ background: #064e3b; color: #6ee7b7; }}
  .meta-tag.location {{ background: #1e3a5f; color: #93c5fd; }}

  .keywords-row {{ font-size: 0.8rem; color: #34d399; margin-bottom: 0.3rem; line-height: 1.4; overflow-wrap: anywhere; }}
  .reasoning-row {{ font-size: 0.8rem; color: #cbd5e1; margin-bottom: 0.5rem; font-style: italic; line-height: 1.4; overflow-wrap: anywhere; }}

  .desc-preview {{ font-size: 0.85rem; color: #cbd5e1; line-height: 1.5; margin-bottom: 0.75rem; max-height: 3.9em; overflow: hidden; overflow-wrap: anywhere; }}

  .card-footer {{ display: flex; justify-content: flex-end; gap: 0.5rem; flex-wrap: wrap; }}
  .archive-form {{ margin-left: 0; }}
  .apply-link {{ font-size: 0.85rem; color: #bfdbfe; text-decoration: none; padding: 0.35rem 0.8rem; border: 1px solid #93c5fd; border-radius: 6px; font-weight: 700; min-height: 2.75rem; display: inline-flex; align-items: center; justify-content: center; }}
  .apply-link:hover {{ background: #60a5fa22; }}
  .archive-btn {{ font-size: 0.85rem; color: #fecaca; background: transparent; padding: 0.35rem 0.8rem; border: 1px solid #fca5a5; border-radius: 6px; font-weight: 700; min-height: 2.75rem; cursor: pointer; }}
  .archive-btn:hover {{ background: #7f1d1d55; }}

  /* Expandable full description */
  .full-desc-details {{ margin-bottom: 0.75rem; }}
  .expand-btn {{ font-size: 0.85rem; color: #bfdbfe; cursor: pointer; list-style: none; padding: 0.3rem 0; }}
  .expand-btn::-webkit-details-marker {{ display: none; }}
  .expand-btn:hover {{ color: #93c5fd; }}
  .full-desc {{ font-size: 0.8rem; color: #cbd5e1; line-height: 1.6; margin-top: 0.5rem; padding: 0.75rem; background: #0f172a; border-radius: 8px; max-height: 400px; overflow-y: auto; white-space: pre-wrap; word-break: break-word; }}

  .hidden {{ display: none !important; }}
  .job-count {{ color: #cbd5e1; font-size: 0.9rem; margin-bottom: 1rem; }}
  .empty-state {{ background: #1e293b; border: 1px solid #334155; border-radius: 8px; color: #cbd5e1; padding: 1.25rem; }}

  @media (max-width: 768px) {{
    .summary {{ grid-template-columns: repeat(2, 1fr); }}
    .score-section {{ grid-template-columns: 1fr; }}
    .job-grid {{ grid-template-columns: 1fr; }}
    body {{ padding: 1rem; }}
  }}
  @media (max-width: 560px) {{
    body {{ padding: 0.75rem; }}
    h1 {{ font-size: 1.5rem; }}
    .summary {{ grid-template-columns: 1fr; gap: 0.75rem; }}
    .filters {{ align-items: stretch; gap: 0.75rem; }}
    .filter-label {{ flex-basis: 100%; }}
    .filter-btn {{ flex: 1 1 8rem; }}
    .search-input {{ width: 100%; }}
    .score-header {{ align-items: flex-start; }}
    .card-header {{ align-items: flex-start; }}
    .card-footer {{ align-items: stretch; flex-direction: column; }}
    .apply-link, .archive-btn {{ width: 100%; }}
  }}
  @media (prefers-reduced-motion: reduce) {{
    html {{ scroll-behavior: auto; }}
    *, *::before, *::after {{ transition: none !important; }}
    .job-card:hover {{ transform: none; }}
  }}
</style>
</head>
<body>

<a class="skip-link" href="#jobs">Skip to jobs</a>
<main>
<header>
  <h1>DivApply Dashboard</h1>
  <p class="subtitle">{total} active jobs &middot; {scored} scored &middot; {high_fit} strong matches (7+) &middot; {archived} archived</p>
</header>

<section class="summary" aria-label="Pipeline summary">
  <div class="stat-card stat-total"><div class="stat-num">{total}</div><div class="stat-label">Total jobs</div></div>
  <div class="stat-card stat-ok"><div class="stat-num">{ready}</div><div class="stat-label">Ready with description and URL</div></div>
  <div class="stat-card stat-scored"><div class="stat-num">{scored}</div><div class="stat-label">Scored by LLM</div></div>
  <div class="stat-card stat-high"><div class="stat-num">{high_fit}</div><div class="stat-label">Strong fit, score 7+</div></div>
</section>

<section class="filters" aria-label="Job filters">
  <span class="filter-label" id="score-filter-label">Score:</span>
  <button type="button" class="filter-btn active" data-min-score="0" aria-pressed="true" aria-describedby="score-filter-label">All 5+</button>
  <button type="button" class="filter-btn" data-min-score="7" aria-pressed="false" aria-describedby="score-filter-label">7+ Strong</button>
  <button type="button" class="filter-btn" data-min-score="8" aria-pressed="false" aria-describedby="score-filter-label">8+ Excellent</button>
  <button type="button" class="filter-btn" data-min-score="9" aria-pressed="false" aria-describedby="score-filter-label">9+ Perfect</button>
  <label class="filter-label" for="job-search">Search:</label>
  <input id="job-search" type="search" class="search-input" placeholder="Filter by title, site..." aria-controls="jobs" autocomplete="off">
</section>

<section class="score-section" aria-label="Job analytics">
  <div class="score-dist" aria-labelledby="score-dist-heading">
    <h2 id="score-dist-heading">Score Distribution</h2>
    {score_bars}
  </div>
  <div class="sites-section" aria-labelledby="source-heading">
    <h2 id="source-heading">By Source</h2>
    {site_rows}
  </div>
</section>

<section id="jobs" aria-labelledby="jobs-heading">
<h2 id="jobs-heading" class="visually-hidden">Jobs</h2>
<div id="job-count" class="job-count" role="status" aria-live="polite"></div>

{job_sections}
</section>
</main>

<script>
let minScore = 0;
let searchText = '';
const jobCards = Array.from(document.querySelectorAll('.job-card')).map(card => {{
  return {{ card, searchText: card.dataset.search || '' }};
}});
const scoreGroups = Array.from(document.querySelectorAll('.score-group')).map(group => {{
  return {{ group, grid: group.querySelector('.job-grid') }};
}});

function filterScore(min, button) {{
  minScore = min;
  document.querySelectorAll('.filter-btn').forEach(b => {{
    b.classList.remove('active');
    b.setAttribute('aria-pressed', 'false');
  }});
  button.classList.add('active');
  button.setAttribute('aria-pressed', 'true');
  applyFilters();
}}

function filterText(text) {{
  searchText = text.toLowerCase();
  applyFilters();
}}

function applyFilters() {{
  let shown = 0;
  let total = 0;
  jobCards.forEach(item => {{
    const card = item.card;
    total++;
    const score = parseInt(card.dataset.score) || 0;
    const text = item.searchText;
    const scoreMatch = score >= (minScore || 5);
    const textMatch = !searchText || text.includes(searchText);
    if (scoreMatch && textMatch) {{
      card.classList.remove('hidden');
      shown++;
    }} else {{
      card.classList.add('hidden');
    }}
  }});
  document.getElementById('job-count').textContent = `Showing ${{shown}} of ${{total}} jobs`;

  // Hide empty score groups
  scoreGroups.forEach(item => {{
    const group = item.group;
    const grid = item.grid;
    if (grid && grid.classList.contains('job-grid')) {{
      const visible = grid.querySelectorAll('.job-card:not(.hidden)').length;
      group.style.display = visible ? '' : 'none';
    }}
  }});
}}

document.querySelectorAll('.filter-btn').forEach(button => {{
  button.addEventListener('click', () => filterScore(parseInt(button.dataset.minScore) || 0, button));
}});
document.getElementById('job-search').addEventListener('input', event => filterText(event.target.value));

applyFilters();
</script>

</body>
</html>"""

    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(html, encoding="utf-8")

    abs_path = str(out.resolve())
    console.print(f"[green]Dashboard written to {abs_path}[/green]")
    return abs_path


def open_dashboard(output_path: str | None = None) -> None:
    """Generate the dashboard and open it in the default browser.

    Args:
        output_path: Where to write the HTML file. Defaults to ~/.divapply/dashboard.html.
    """
    path = generate_dashboard(output_path)
    console.print("[dim]Opening in browser...[/dim]")
    webbrowser.open(f"file:///{path}")


def _dashboard_cache_key() -> tuple:
    """Return a compact freshness key for the live dashboard response."""
    conn = get_connection()
    data_version = conn.execute("PRAGMA data_version").fetchone()[0]
    row = conn.execute(
        """
        SELECT COUNT(*) AS rows,
               MAX(archived_at) AS archived_at,
               MAX(scored_at) AS scored_at,
               MAX(detail_scraped_at) AS detail_scraped_at,
               MAX(discovered_at) AS discovered_at,
               MAX(applied_at) AS applied_at
        FROM jobs
        """
    ).fetchone()
    return (
        data_version,
        row["rows"],
        row["archived_at"],
        row["scored_at"],
        row["detail_scraped_at"],
        row["discovered_at"],
        row["applied_at"],
    )


class _DashboardServer(ThreadingHTTPServer):
    daemon_threads = True


def _archive_dashboard_form(form: dict[str, str]) -> tuple[int, str, bool]:
    """Archive the submitted dashboard job and return status, body, redirect flag."""
    url = form.get("url")
    if not url:
        record_reliability_event(
            "dashboard_missing_archive_url",
            "Rejected dashboard archive POST without job URL",
            severity="warning",
        )
        return 400, "Missing job URL.", False

    try:
        archived = archive_job(url)
    except Exception as exc:
        log.exception("Dashboard archive failed")
        record_reliability_event(
            "dashboard_archive_failed",
            "Dashboard archive failed",
            severity="error",
            context={"url": url, "error": str(exc)},
        )
        return 500, "Archive failed.", False

    if not archived:
        record_reliability_event(
            "dashboard_archive_not_found",
            "Dashboard archive requested a missing or already archived job",
            severity="warning",
            context={"url": url},
        )
        return 404, "Job was not found or is already archived.", False

    return 303, "", True


def serve_dashboard(*, host: str = "127.0.0.1", port: int = 8776, open_browser: bool = True) -> str:
    """Serve the dashboard locally so archive buttons can update SQLite."""
    token = secrets.token_urlsafe(24)
    actual_port = find_free_port(host, port)

    class Handler(BaseHTTPRequestHandler):
        cache_lock = threading.Lock()
        response_cache: dict[str, Any] = {"key": None, "data": None}

        def log_message(self, _format: str, *_args: Any) -> None:
            return

        def _send_text(self, status: int, message: str) -> None:
            data = message.encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "text/plain; charset=utf-8")
            self.send_header("Content-Length", str(len(data)))
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.end_headers()
            self.wfile.write(data)

        def do_GET(self) -> None:  # noqa: N802
            if self.path not in ("/", "/?archived=1"):
                self.send_error(404)
                return
            try:
                key = _dashboard_cache_key()
                with self.cache_lock:
                    data = self.response_cache["data"] if self.response_cache["key"] == key else None
                    if data is None:
                        body = generate_dashboard(
                            archive_endpoint="/archive",
                            archive_token=token,
                        )
                        data = Path(body).read_bytes()
                        self.response_cache["key"] = key
                        self.response_cache["data"] = data
                self.send_response(200)
                self.send_header("Content-Type", "text/html; charset=utf-8")
                self.send_header("Content-Length", str(len(data)))
                self.send_header("Cache-Control", "no-store")
                self.send_header("Referrer-Policy", "same-origin")
                self.send_header("X-Content-Type-Options", "nosniff")
                self.end_headers()
                self.wfile.write(data)
            except Exception as exc:
                log.exception("Dashboard render failed")
                record_reliability_event(
                    "dashboard_render_failed",
                    "Dashboard render failed",
                    severity="error",
                    context={"path": self.path, "error": str(exc)},
                )
                self._send_text(500, "Dashboard render failed.")

        def do_POST(self) -> None:  # noqa: N802
            if self.path != "/archive":
                self.send_error(404)
                return
            if not local_request_is_same_origin(self.headers, host, actual_port):
                record_reliability_event(
                    "dashboard_cross_origin_post",
                    "Rejected cross-origin dashboard POST",
                    severity="warning",
                    context={"origin": self.headers.get("Origin"), "referer": self.headers.get("Referer")},
                )
                self._send_text(403, "Forbidden.")
                return
            try:
                length = parse_local_form_length(self.headers.get("Content-Length"))
                fields = urllib.parse.parse_qs(self.rfile.read(length).decode("utf-8"), keep_blank_values=True)
            except UnicodeDecodeError:
                record_reliability_event(
                    "dashboard_bad_post",
                    "Rejected non-UTF-8 dashboard POST",
                    severity="warning",
                )
                self._send_text(400, "Bad dashboard request.")
                return
            except ValueError as exc:
                status = 413 if "large" in str(exc) else 400
                record_reliability_event(
                    "dashboard_bad_post",
                    "Rejected malformed dashboard POST",
                    severity="warning",
                    context={"error": str(exc), "content_length": self.headers.get("Content-Length")},
                )
                self._send_text(status, "Bad dashboard request.")
                return
            form = {key: values[-1] for key, values in fields.items()}
            if form.get("token") != token:
                record_reliability_event(
                    "dashboard_bad_token",
                    "Rejected dashboard archive POST with invalid token",
                    severity="warning",
                )
                self._send_text(403, "Forbidden.")
                return
            status, message, should_redirect = _archive_dashboard_form(form)
            if not should_redirect:
                self._send_text(status, message)
                return
            with self.cache_lock:
                self.response_cache["key"] = None
                self.response_cache["data"] = None
            self.send_response(status)
            self.send_header("Location", "/?archived=1")
            self.end_headers()

    server = _DashboardServer((host, actual_port), Handler)
    url = f"http://{host}:{actual_port}/"
    console.print(f"[green]Dashboard:[/green] {url}")
    if open_browser:
        threading.Timer(0.2, lambda: webbrowser.open(url)).start()
    try:
        server.serve_forever()
    finally:
        server.server_close()
    return url

