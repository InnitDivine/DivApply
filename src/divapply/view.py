"""DivApply HTML Dashboard Generator.

Generates a self-contained HTML dashboard with:
  - Summary stats (total, enriched, scored, high-fit)
  - Score distribution bar chart
  - Jobs-by-source breakdown
  - Filterable job cards grouped by score
  - Client-side search and score filtering
"""

from __future__ import annotations

import webbrowser
from html import escape
from pathlib import Path

from rich.console import Console

from divapply.config import APP_DIR
from divapply.database import get_connection
from divapply.security import sanitize_external_url

console = Console()

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


def generate_dashboard(output_path: str | None = None) -> str:
    """Generate an HTML dashboard of all jobs with fit scores.

    Args:
        output_path: Where to write the HTML file. Defaults to ~/.divapply/dashboard.html.

    Returns:
        Absolute path to the generated HTML file.
    """
    out = Path(output_path) if output_path else APP_DIR / "dashboard.html"

    conn = get_connection()

    # Stats
    total = conn.execute("SELECT COUNT(*) FROM jobs").fetchone()[0]
    ready = conn.execute(
        "SELECT COUNT(*) FROM jobs "
        "WHERE full_description IS NOT NULL AND COALESCE(application_url, '') != ''"
    ).fetchone()[0]
    scored = conn.execute(
        "SELECT COUNT(*) FROM jobs WHERE fit_score IS NOT NULL"
    ).fetchone()[0]
    high_fit = conn.execute(
        "SELECT COUNT(*) FROM jobs WHERE fit_score >= 7"
    ).fetchone()[0]

    # Score distribution
    score_dist: dict[int, int] = {}
    if scored:
        rows = conn.execute(
            "SELECT fit_score, COUNT(*) FROM jobs "
            "WHERE fit_score IS NOT NULL "
            "GROUP BY fit_score ORDER BY fit_score DESC"
        ).fetchall()
        for r in rows:
            score_dist[r[0]] = r[1]

    # Site stats
    site_stats = conn.execute("""
        SELECT site,
               COUNT(*) as total,
               SUM(CASE WHEN fit_score >= 7 THEN 1 ELSE 0 END) as high_fit,
               SUM(CASE WHEN fit_score BETWEEN 5 AND 6 THEN 1 ELSE 0 END) as mid_fit,
               SUM(CASE WHEN fit_score < 5 AND fit_score IS NOT NULL THEN 1 ELSE 0 END) as low_fit,
               SUM(CASE WHEN fit_score IS NULL THEN 1 ELSE 0 END) as unscored,
               ROUND(AVG(fit_score), 1) as avg_score
        FROM jobs GROUP BY site ORDER BY high_fit DESC, total DESC
    """).fetchall()

    # All scored jobs (5+), ordered by score desc
    jobs = conn.execute("""
        SELECT url, title, salary, description, location, site, strategy,
               full_description, application_url, detail_error,
               fit_score, score_reasoning
        FROM jobs
        WHERE fit_score >= 5
        ORDER BY fit_score DESC, site, title
    """).fetchall()

    # Score distribution bar chart
    score_bars = ""
    max_count = max(score_dist.values()) if score_dist else 1
    for s in range(10, 0, -1):
        count = score_dist.get(s, 0)
        pct = (count / max_count * 100) if max_count else 0
        score_color = _score_color(s)
        score_bars += f"""
        <div class="score-row" aria-label="Score {s}: {count} jobs">
          <span class="score-label">{s}</span>
          <div class="score-bar-track">
            <div class="score-bar-fill" style="width:{pct}%;background:{score_color}" aria-hidden="true"></div>
          </div>
          <span class="score-count">{count}</span>
        </div>"""

    # Site stats rows
    site_rows = ""
    for s in site_stats:
        site = s["site"] or "?"
        color = _site_color(site)
        avg = s["avg_score"] or 0
        high_pct = s["high_fit"] / max(s["total"], 1) * 100
        mid_pct = s["mid_fit"] / max(s["total"], 1) * 100
        site_rows += f"""
        <div class="site-row">
          <div class="site-name" style="border-color:{color}">{escape(site)}</div>
          <div class="site-nums">{s['total']} jobs &middot; {s['high_fit']} strong fit &middot; avg score {avg}</div>
          <div class="bar-track" aria-label="{escape(site)}: {s['high_fit']} strong fit and {s['mid_fit']} moderate fit jobs">
            <div class="bar-fill" style="width:{high_pct}%;background:{color}" aria-hidden="true"></div>
            <div class="bar-fill" style="width:{mid_pct}%;background:{color}66" aria-hidden="true"></div>
          </div>
        </div>"""

    # Job cards grouped by score
    job_sections = ""
    current_score = None
    for j in jobs:
        score = j["fit_score"] or 0
        if score != current_score:
            if current_score is not None:
                job_sections += "</div>"
            score_color = _score_color(score)
            score_label = _score_label(score)
            count_at_score = score_dist.get(score, 0)
            job_sections += f"""
            <h2 class="score-header" style="border-color:{score_color}">
              <span class="score-badge" style="background:{score_color}">{score}</span>
              {score_label} ({count_at_score} jobs)
            </h2>
            <div class="job-grid">"""
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

        title_html = (
            f'<a href="{url}" class="job-title" target="_blank" rel="noopener noreferrer">{title}</a>'
            if url
            else f'<span class="job-title">{title}</span>'
        )

        job_sections += f"""
        <article class="job-card" data-score="{score}" data-site="{escape(j['site'] or '')}" data-location="{location.lower()}">
          <div class="card-header">
            <span class="score-pill" style="background:{_score_color(score)}" aria-label="Fit score {score}">{score}</span>
            {title_html}
          </div>
          <div class="meta-row">{meta_html}</div>
          {f'<div class="keywords-row">{escape(keywords)}</div>' if keywords else ''}
          {f'<div class="reasoning-row">{escape(reasoning)}</div>' if reasoning else ''}
          <p class="desc-preview">{desc_preview}</p>
          {"<details class='full-desc-details'><summary class='expand-btn'>Full description (" + f'{desc_len:,}' + " characters)</summary><div class='full-desc'>" + full_desc_html + "</div></details>" if j["full_description"] else ""}
          <div class="card-footer">{apply_html}</div>
        </article>"""

    if current_score is not None:
        job_sections += "</div>"

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
  .filter-btn {{ background: #334155; border: 1px solid #475569; color: #e2e8f0; padding: 0.45rem 0.8rem; border-radius: 6px; cursor: pointer; font-size: 0.85rem; transition: background 0.15s, color 0.15s; }}
  .filter-btn:hover {{ background: #475569; color: #e2e8f0; }}
  .filter-btn.active {{ background: #bfdbfe; border-color: #bfdbfe; color: #0f172a; font-weight: 700; }}
  .search-input {{ background: #334155; border: 1px solid #64748b; color: #f8fafc; padding: 0.45rem 0.8rem; border-radius: 6px; font-size: 0.9rem; width: 220px; min-height: 2.4rem; }}
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

  .job-card {{ background: #1e293b; border: 1px solid #334155; border-left: 3px solid #334155; border-radius: 8px; padding: 1rem; transition: transform 0.15s, box-shadow 0.15s; min-width: 0; }}
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

  .card-footer {{ display: flex; justify-content: flex-end; }}
  .apply-link {{ font-size: 0.85rem; color: #bfdbfe; text-decoration: none; padding: 0.35rem 0.8rem; border: 1px solid #93c5fd; border-radius: 6px; font-weight: 700; min-height: 2.3rem; display: inline-flex; align-items: center; }}
  .apply-link:hover {{ background: #60a5fa22; }}

  /* Expandable full description */
  .full-desc-details {{ margin-bottom: 0.75rem; }}
  .expand-btn {{ font-size: 0.85rem; color: #bfdbfe; cursor: pointer; list-style: none; padding: 0.3rem 0; }}
  .expand-btn::-webkit-details-marker {{ display: none; }}
  .expand-btn:hover {{ color: #93c5fd; }}
  .full-desc {{ font-size: 0.8rem; color: #cbd5e1; line-height: 1.6; margin-top: 0.5rem; padding: 0.75rem; background: #0f172a; border-radius: 8px; max-height: 400px; overflow-y: auto; white-space: pre-wrap; word-break: break-word; }}

  .hidden {{ display: none !important; }}
  .job-count {{ color: #cbd5e1; font-size: 0.9rem; margin-bottom: 1rem; }}

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
  <p class="subtitle">{total} jobs &middot; {scored} scored &middot; {high_fit} strong matches (7+)</p>
</header>

<section class="summary" aria-label="Pipeline summary">
  <div class="stat-card stat-total"><div class="stat-num">{total}</div><div class="stat-label">Total jobs</div></div>
  <div class="stat-card stat-ok"><div class="stat-num">{ready}</div><div class="stat-label">Ready with description and URL</div></div>
  <div class="stat-card stat-scored"><div class="stat-num">{scored}</div><div class="stat-label">Scored by LLM</div></div>
  <div class="stat-card stat-high"><div class="stat-num">{high_fit}</div><div class="stat-label">Strong fit, score 7+</div></div>
</section>

<section class="filters" aria-label="Job filters">
  <span class="filter-label" id="score-filter-label">Score:</span>
  <button type="button" class="filter-btn active" aria-pressed="true" aria-describedby="score-filter-label" onclick="filterScore(0, this)">All 5+</button>
  <button type="button" class="filter-btn" aria-pressed="false" aria-describedby="score-filter-label" onclick="filterScore(7, this)">7+ Strong</button>
  <button type="button" class="filter-btn" aria-pressed="false" aria-describedby="score-filter-label" onclick="filterScore(8, this)">8+ Excellent</button>
  <button type="button" class="filter-btn" aria-pressed="false" aria-describedby="score-filter-label" onclick="filterScore(9, this)">9+ Perfect</button>
  <label class="filter-label" for="job-search">Search:</label>
  <input id="job-search" type="search" class="search-input" placeholder="Filter by title, site..." aria-controls="jobs" oninput="filterText(this.value)">
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
  document.querySelectorAll('.job-card').forEach(card => {{
    total++;
    const score = parseInt(card.dataset.score) || 0;
    const text = card.textContent.toLowerCase();
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
  document.querySelectorAll('.score-header').forEach(header => {{
    const grid = header.nextElementSibling;
    if (grid && grid.classList.contains('job-grid')) {{
      const visible = grid.querySelectorAll('.job-card:not(.hidden)').length;
      header.style.display = visible ? '' : 'none';
      grid.style.display = visible ? '' : 'none';
    }}
  }});
}}

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

