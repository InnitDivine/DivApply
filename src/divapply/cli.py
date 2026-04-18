"""DivApply CLI â€” the main entry point."""

from __future__ import annotations

import csv
import json
import logging
from typing import Optional
from pathlib import Path

import typer
from rich.console import Console
from rich.table import Table

from divapply import __version__

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s",
    datefmt="%H:%M:%S",
)

app = typer.Typer(
    name="divapply",
    help="DivApply, an AI-powered end-to-end job application pipeline.",
    no_args_is_help=True,
)
console = Console()
log = logging.getLogger(__name__)

# Valid pipeline stages (in execution order)
VALID_STAGES = ("discover", "enrich", "score", "tailor", "cover", "pdf")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _bootstrap() -> None:
    """Common setup: load env, create dirs, init DB."""
    from divapply.config import load_env, ensure_dirs
    from divapply.database import init_db

    load_env()
    ensure_dirs()
    init_db()


def _version_callback(value: bool) -> None:
    if value:
        console.print(f"[bold]DivApply[/bold] {__version__}")
        raise typer.Exit()


# ---------------------------------------------------------------------------
# Commands
# ---------------------------------------------------------------------------

@app.callback()
def main(
    version: bool = typer.Option(
        False, "--version", "-V",
        help="Show version and exit.",
        callback=_version_callback,
        is_eager=True,
    ),
) -> None:
    """DivApply â€” AI-powered end-to-end job application pipeline."""


@app.command()
def init() -> None:
    """Run the first-time setup wizard (profile, resume, search config)."""
    from divapply.wizard.init import run_wizard

    run_wizard()


@app.command("import-coursework")
def import_coursework(
    path: Path = typer.Argument(..., exists=True, readable=True, resolve_path=True, help="Transcript or coursework file to import."),
) -> None:
    """Import coursework knowledge into the hidden SQLite coursework table."""
    _bootstrap()

    from divapply.database import replace_coursework

    entries: list[dict] = []
    suffix = path.suffix.lower()

    if suffix in {".json", ".csv"}:
        text = path.read_text(encoding="utf-8", errors="ignore")

    if suffix == ".json":
        payload = json.loads(text)
        if isinstance(payload, dict):
            payload = payload.get("coursework") or payload.get("courses") or payload.get("entries") or [payload]
        if isinstance(payload, list):
            for item in payload:
                if isinstance(item, dict):
                    entries.append({
                        "school": item.get("school") or item.get("institution"),
                        "course_code": item.get("course_code") or item.get("code"),
                        "course_title": item.get("course_title") or item.get("title") or item.get("name"),
                        "subject_area": item.get("subject_area") or item.get("subject") or item.get("category"),
                        "term": item.get("term") or item.get("semester") or item.get("session"),
                        "credits": item.get("credits") or item.get("units"),
                        "grade": item.get("grade"),
                        "source": item.get("source") or path.name,
                        "notes": item.get("notes"),
                        "raw_text": item.get("raw_text") or item.get("text") or json.dumps(item, ensure_ascii=True),
                    })
        else:
            entries.append({"source": path.name, "raw_text": text})
    elif suffix == ".csv":
        reader = csv.DictReader(text.splitlines())
        for row in reader:
            entries.append({
                "school": row.get("school") or row.get("institution"),
                "course_code": row.get("course_code") or row.get("code"),
                "course_title": row.get("course_title") or row.get("title") or row.get("name"),
                "subject_area": row.get("subject_area") or row.get("subject") or row.get("category"),
                "term": row.get("term") or row.get("semester") or row.get("session"),
                "credits": row.get("credits") or row.get("units"),
                "grade": row.get("grade"),
                "source": path.name,
                "notes": row.get("notes"),
                "raw_text": json.dumps(row, ensure_ascii=True),
            })
    elif suffix == ".pdf":
        try:
            from pypdf import PdfReader
        except Exception as exc:
            console.print(
                "[red]PDF import needs the optional 'pypdf' package.[/red]\n"
                "Install it or convert the transcript to JSON, CSV, or plain text first."
            )
            raise typer.Exit(code=1) from exc

        reader = PdfReader(str(path))
        raw_text = "\n".join(page.extract_text() or "" for page in reader.pages).strip()
        entries.append({"source": path.name, "raw_text": raw_text, "notes": "Imported from PDF transcript"})
    else:
        text = path.read_text(encoding="utf-8", errors="ignore")
        entries.append({"source": path.name, "raw_text": text, "notes": "Imported plain text transcript"})

    inserted = replace_coursework(entries)
    console.print(f"[green]Imported coursework entries:[/green] {inserted}")


@app.command()
def run(
    stages: Optional[list[str]] = typer.Argument(
        None,
        help=(
            "Pipeline stages to run. "
            f"Valid: {', '.join(VALID_STAGES)}, all. "
            "Defaults to 'all' if omitted."
        ),
    ),
    min_score: int = typer.Option(7, "--min-score", help="Minimum fit score for tailor/cover stages."),
    prune_score: int = typer.Option(0, "--prune-score", help="Auto-delete jobs scoring at or below this after scoring (0 = off)."),
    workers: int = typer.Option(1, "--workers", "-w", help="Parallel threads for discovery/enrichment stages."),
    stream: bool = typer.Option(False, "--stream", help="Run stages concurrently (streaming mode)."),
    dry_run: bool = typer.Option(False, "--dry-run", help="Preview stages without executing."),
    validation: str = typer.Option(
        "normal",
        "--validation",
        help=(
            "Validation strictness for tailor/cover stages. "
            "strict: banned words = errors, judge must pass. "
            "normal: banned words = warnings only (default). "
            "lenient: banned words ignored, LLM judge skipped. "
            "none: skip all validation entirely, accept whatever the LLM returns."
        ),
    ),
) -> None:
    """Run pipeline stages: discover, enrich, score, tailor, cover, pdf."""
    _bootstrap()

    from divapply.pipeline import run_pipeline

    stage_list = stages if stages else ["all"]

    # Validate stage names
    for s in stage_list:
        if s != "all" and s not in VALID_STAGES:
            console.print(
                f"[red]Unknown stage:[/red] '{s}'. "
                f"Valid stages: {', '.join(VALID_STAGES)}, all"
            )
            raise typer.Exit(code=1)

    # Gate AI stages behind Tier 2
    llm_stages = {"score", "tailor", "cover"}
    if any(s in stage_list for s in llm_stages) or "all" in stage_list:
        from divapply.config import check_tier
        check_tier(2, "AI scoring/tailoring")

    # Validate the --validation flag value
    valid_modes = ("strict", "normal", "lenient", "none")
    if validation not in valid_modes:
        console.print(
            f"[red]Invalid --validation value:[/red] '{validation}'. "
            f"Choose from: {', '.join(valid_modes)}"
        )
        raise typer.Exit(code=1)

    result = run_pipeline(
        stages=stage_list,
        min_score=min_score,
        dry_run=dry_run,
        stream=stream,
        workers=workers,
        validation_mode=validation,
        prune_below=prune_score,
    )

    if result.get("errors"):
        raise typer.Exit(code=1)


@app.command()
def apply(
    limit: Optional[int] = typer.Option(None, "--limit", "-l", help="Max applications to submit."),
    workers: int = typer.Option(1, "--workers", "-w", help="Number of parallel browser workers."),
    min_score: int = typer.Option(7, "--min-score", help="Minimum fit score for job selection."),
    model: Optional[str] = typer.Option(None, "--model", "-m", help="Apply agent model name."),
    backend: Optional[str] = typer.Option(None, "--backend", "-b", help="Apply agent backend: codex or claude."),
    browser: str = typer.Option("firefox", "--browser", help="Playwright browser: firefox, chrome, msedge, webkit."),
    continuous: bool = typer.Option(False, "--continuous", "-c", help="Run forever, polling for new jobs."),
    dry_run: bool = typer.Option(False, "--dry-run", help="Preview actions without submitting."),
    headless: bool = typer.Option(False, "--headless", help="Run browsers in headless mode."),
    url: Optional[str] = typer.Option(None, "--url", help="Apply to a specific job URL."),
    gen: bool = typer.Option(False, "--gen", help="Generate prompt file for manual debugging instead of running."),
    mark_applied: Optional[str] = typer.Option(None, "--mark-applied", help="Manually mark a job URL as applied."),
    mark_failed: Optional[str] = typer.Option(None, "--mark-failed", help="Manually mark a job URL as failed (provide URL)."),
    fail_reason: Optional[str] = typer.Option(None, "--fail-reason", help="Reason for --mark-failed."),
    reset_failed: bool = typer.Option(False, "--reset-failed", help="Reset all failed jobs for retry."),
) -> None:
    """Launch auto-apply to submit job applications."""
    _bootstrap()

    from divapply.config import (
        PROFILE_PATH as _profile_path,
        check_tier,
        get_apply_backend,
        get_apply_backend_label,
        get_apply_browser,
        get_apply_browser_label,
        get_chrome_path,
    )
    from divapply.database import get_connection

    # --- Utility modes (no browser agent needed) ---

    if mark_applied:
        from divapply.apply.launcher import mark_job
        mark_job(mark_applied, "applied")
        console.print(f"[green]Marked as applied:[/green] {mark_applied}")
        return

    if mark_failed:
        from divapply.apply.launcher import mark_job
        mark_job(mark_failed, "failed", reason=fail_reason)
        console.print(f"[yellow]Marked as failed:[/yellow] {mark_failed} ({fail_reason or 'manual'})")
        return

    if reset_failed:
        from divapply.apply.launcher import reset_failed as do_reset
        count = do_reset()
        console.print(f"[green]Reset {count} failed job(s) for retry.[/green]")
        return

    # --- Full apply mode ---

    # Check 1: Tier 3 required (apply agent CLI + Chrome)
    resolved_browser = get_apply_browser(browser)
    resolved_model = (
        model
        or os.environ.get("LLM_MODEL_APPLY")
        or os.environ.get("LLM_MODEL")
        or "gpt-5.4-mini"
    )
    check_tier(3, "auto-apply")
    resolved_backend = get_apply_backend(backend)
    if resolved_backend is None:
        console.print(
            "[red]No supported apply backend found.[/red]\n"
            "Install Codex or Claude Code, or pass [bold]--backend[/bold] with an installed option."
        )
        raise typer.Exit(code=1)
    if resolved_browser == "chrome":
        try:
            get_chrome_path()
        except FileNotFoundError:
            console.print("[red]Chrome/Chromium not found.[/red]\nInstall Chrome or set CHROME_PATH.")
            raise typer.Exit(code=1)

    # Check 2: Profile exists
    if not _profile_path.exists():
        console.print(
            "[red]Profile not found.[/red]\n"
            "Run [bold]divapply init[/bold] to create your profile first."
        )
        raise typer.Exit(code=1)

    # Check 3: Tailored resumes exist (skip for --gen with --url)
    if not (gen and url):
        conn = get_connection()
        ready = conn.execute(
            "SELECT COUNT(*) FROM jobs WHERE tailored_resume_path IS NOT NULL AND applied_at IS NULL"
        ).fetchone()[0]
        if ready == 0:
            console.print(
                "[red]No tailored resumes ready.[/red]\n"
                "Run [bold]divapply run score tailor[/bold] first to prepare applications."
            )
            raise typer.Exit(code=1)

    if gen:
        from divapply.apply.launcher import gen_prompt, get_manual_command
        target = url or ""
        if not target:
            console.print("[red]--gen requires --url to specify which job.[/red]")
            raise typer.Exit(code=1)
        prompt_file = gen_prompt(
            target,
            min_score=min_score,
            model=resolved_model,
            backend=resolved_backend,
            browser=resolved_browser,
        )
        if not prompt_file:
            console.print("[red]No matching job found for that URL.[/red]")
            raise typer.Exit(code=1)
        mcp_path = _profile_path.parent / ".mcp-apply-0.json"
        console.print(f"[green]Wrote prompt to:[/green] {prompt_file}")
        console.print(f"\n[bold]Run manually:[/bold]")
        console.print(f"  {get_manual_command(resolved_backend, resolved_model, prompt_file, mcp_path)}")
        return

    from divapply.apply.launcher import main as apply_main

    effective_limit = limit if limit is not None else (0 if continuous else 1)

    console.print("\n[bold blue]Launching Auto-Apply[/bold blue]")
    console.print(f"  Limit:    {'unlimited' if continuous else effective_limit}")
    console.print(f"  Workers:  {workers}")
    console.print(f"  Backend:  {get_apply_backend_label(resolved_backend)}")
    console.print(f"  Browser:  {get_apply_browser_label(resolved_browser)}")
    console.print(f"  Model:    {resolved_model}")
    console.print(f"  Headless: {headless}")
    console.print(f"  Dry run:  {dry_run}")
    if url:
        console.print(f"  Target:   {url}")
    console.print()

    apply_main(
        limit=effective_limit,
        target_url=url,
        min_score=min_score,
        headless=headless,
        model=resolved_model,
        backend=resolved_backend,
        browser=resolved_browser,
        dry_run=dry_run,
        continuous=continuous,
        workers=workers,
    )


@app.command()
def status() -> None:
    """Show pipeline statistics from the database."""
    _bootstrap()

    from divapply.database import get_stats

    stats = get_stats()

    console.print("\n[bold]DivApply Pipeline Status[/bold]\n")

    # Summary table
    summary = Table(title="Pipeline Overview", show_header=True, header_style="bold cyan")
    summary.add_column("Metric", style="bold")
    summary.add_column("Count", justify="right")

    summary.add_row("Total jobs discovered", str(stats["total"]))
    summary.add_row("With full description", str(stats["with_description"]))
    summary.add_row("Pending enrichment", str(stats["pending_detail"]))
    summary.add_row("Enrichment errors", str(stats["detail_errors"]))
    summary.add_row("Scored by LLM", str(stats["scored"]))
    summary.add_row("Pending scoring", str(stats["unscored"]))
    summary.add_row("Tailored resumes", str(stats["tailored"]))
    summary.add_row("Pending tailoring (7+)", str(stats["untailored_eligible"]))
    summary.add_row("Cover letters", str(stats["with_cover_letter"]))
    summary.add_row("Ready to apply", str(stats["ready_to_apply"]))
    summary.add_row("Applied", str(stats["applied"]))
    summary.add_row("Apply errors", str(stats["apply_errors"]))

    console.print(summary)

    # Score distribution
    if stats["score_distribution"]:
        dist_table = Table(title="\nScore Distribution", show_header=True, header_style="bold yellow")
        dist_table.add_column("Score", justify="center")
        dist_table.add_column("Count", justify="right")
        dist_table.add_column("Bar")

        max_count = max(count for _, count in stats["score_distribution"]) or 1
        for score, count in stats["score_distribution"]:
            bar_len = int(count / max_count * 30)
            if score >= 7:
                color = "green"
            elif score >= 5:
                color = "yellow"
            else:
                color = "red"
            bar = f"[{color}]{'=' * bar_len}[/{color}]"
            dist_table.add_row(str(score), str(count), bar)

        console.print(dist_table)

    # By site
    if stats["by_site"]:
        site_table = Table(title="\nJobs by Source", show_header=True, header_style="bold magenta")
        site_table.add_column("Site")
        site_table.add_column("Count", justify="right")

        for site, count in stats["by_site"]:
            site_table.add_row(site or "Unknown", str(count))

        console.print(site_table)

    console.print()


@app.command()
def dashboard() -> None:
    """Generate and open the HTML dashboard in your browser."""
    _bootstrap()

    from divapply.view import open_dashboard

    open_dashboard()


@app.command()
def doctor() -> None:
    """Check your setup and diagnose missing requirements."""
    import shutil
    from divapply.config import (
        load_env, PROFILE_PATH, RESUME_PATH, RESUME_PDF_PATH,
        SEARCH_CONFIG_PATH, ENV_PATH, get_chrome_path,
    )

    load_env()

    ok_mark = "[green]OK[/green]"
    fail_mark = "[red]MISSING[/red]"
    warn_mark = "[yellow]WARN[/yellow]"

    results: list[tuple[str, str, str]] = []  # (check, status, note)

    # --- Tier 1 checks ---
    # Profile
    if PROFILE_PATH.exists():
        results.append(("profile.json", ok_mark, str(PROFILE_PATH)))
    else:
        results.append(("profile.json", fail_mark, "Run 'divapply init' to create"))

    # Resume
    if RESUME_PATH.exists():
        results.append(("resume.txt", ok_mark, str(RESUME_PATH)))
    elif RESUME_PDF_PATH.exists():
        results.append(("resume.txt", warn_mark, "Only PDF found â€” plain-text needed for AI stages"))
    else:
        results.append(("resume.txt", fail_mark, "Run 'divapply init' to add your resume"))

    # Search config
    if SEARCH_CONFIG_PATH.exists():
        results.append(("searches.yaml", ok_mark, str(SEARCH_CONFIG_PATH)))
    else:
        results.append(("searches.yaml", warn_mark, "Will use example config â€” run 'divapply init'"))

    # jobspy (discovery dep installed separately)
    try:
        import jobspy  # noqa: F401
        results.append(("python-jobspy", ok_mark, "Job board scraping available"))
    except ImportError:
        results.append(("python-jobspy", warn_mark,
                        "pip install --no-deps python-jobspy && pip install pydantic tls-client requests markdownify regex"))

    # --- Tier 2 checks ---
    import os
    has_gemini = bool(os.environ.get("GEMINI_API_KEY"))
    has_openai = bool(os.environ.get("OPENAI_API_KEY"))
    has_local = bool(os.environ.get("LLM_URL"))
    if has_gemini:
        model = os.environ.get("LLM_MODEL", "gemini-2.0-flash")
        results.append(("LLM API key", ok_mark, f"Gemini ({model})"))
    elif has_openai:
        model = os.environ.get("LLM_MODEL", "gpt-4o-mini")
        results.append(("LLM API key", ok_mark, f"OpenAI ({model})"))
    elif has_local:
        results.append(("LLM API key", ok_mark, f"Local: {os.environ.get('LLM_URL')}"))
    else:
        results.append(("LLM API key", fail_mark,
                        "Set GEMINI_API_KEY in ~/.divapply/.env (run 'divapply init')"))

    # --- Tier 3 checks ---
    from divapply.config import get_apply_backend, get_apply_backend_label, get_available_apply_backends
    detected_backends = get_available_apply_backends()
    selected_backend = get_apply_backend()
    if detected_backends:
        note = ", ".join(
            f"{get_apply_backend_label(name)}: {path}" for name, path in detected_backends.items()
        )
        results.append(("Apply agent CLI", ok_mark, note))
    else:
        results.append(("Apply agent CLI", fail_mark,
                        "Install Codex or Claude Code (needed for auto-apply)"))

    # Chrome
    try:
        chrome_path = get_chrome_path()
        results.append(("Chrome/Chromium", ok_mark, chrome_path))
    except FileNotFoundError:
        results.append(("Chrome/Chromium", fail_mark,
                        "Install Chrome or set CHROME_PATH env var (needed for auto-apply)"))

    # Node.js / npx (for Playwright MCP)
    npx_bin = shutil.which("npx")
    if npx_bin:
        results.append(("Node.js (npx)", ok_mark, npx_bin))
    else:
        results.append(("Node.js (npx)", fail_mark,
                        "Install Node.js 18+ from nodejs.org (needed for auto-apply)"))

    # CapSolver (optional)
    capsolver = os.environ.get("CAPSOLVER_API_KEY")
    if capsolver:
        results.append(("CapSolver API key", ok_mark, "CAPTCHA solving enabled"))
    else:
        results.append(("CapSolver API key", "[dim]optional[/dim]",
                        "Set CAPSOLVER_API_KEY in .env for CAPTCHA solving"))

    # --- Render results ---
    console.print()
    console.print("[bold]DivApply Doctor[/bold]\n")

    col_w = max(len(r[0]) for r in results) + 2
    for check, status, note in results:
        pad = " " * (col_w - len(check))
        console.print(f"  {check}{pad}{status}  [dim]{note}[/dim]")

    console.print()

    # Tier summary
    from divapply.config import get_tier, TIER_LABELS
    tier = get_tier()
    if selected_backend:
        console.print(f"[dim]  Auto-apply backend: {get_apply_backend_label(selected_backend)}[/dim]")
    console.print(f"[bold]Current tier: Tier {tier} â€” {TIER_LABELS[tier]}[/bold]")

    if tier == 1:
        console.print("[dim]  â†’ Tier 2 unlocks: scoring, tailoring, cover letters (needs LLM API key)[/dim]")
        console.print("[dim]  â†’ Tier 3 unlocks: auto-apply (needs Claude Code CLI + Chrome + Node.js)[/dim]")
    elif tier == 2:
        console.print("[dim]  â†’ Tier 3 unlocks: auto-apply (needs Claude Code CLI + Chrome + Node.js)[/dim]")

    console.print()


@app.command()
def prune(
    max_score: int = typer.Option(4, "--max-score", help="Delete scored jobs at or below this score (default: 4)."),
    dry_run: bool = typer.Option(False, "--dry-run", help="Preview without deleting."),
    yes: bool = typer.Option(False, "--yes", "-y", help="Skip confirmation prompt."),
) -> None:
    """Remove low-scoring jobs from the database to reduce clutter."""
    _bootstrap()

    from divapply.database import get_connection

    conn = get_connection()

    # Show breakdown by score before deleting
    rows = conn.execute(
        "SELECT fit_score, COUNT(*) FROM jobs "
        "WHERE fit_score IS NOT NULL AND fit_score <= ? "
        "GROUP BY fit_score ORDER BY fit_score",
        (max_score,),
    ).fetchall()

    if not rows:
        console.print(f"[green]No scored jobs with fit_score <= {max_score} found.[/green]")
        return

    total = sum(r[1] for r in rows)
    console.print(f"\n[yellow]Jobs to remove (fit_score <= {max_score}):[/yellow]")
    for score, count in rows:
        bar = "=" * min(count, 40)
        console.print(f"  Score {score}: {count:>4}  [{bar}]")
    console.print(f"  [bold]Total: {total}[/bold]\n")

    if dry_run:
        console.print("[dim]Dry run â€” no changes made.[/dim]")
        return

    if not yes:
        confirmed = typer.confirm(f"Delete {total} jobs permanently?")
        if not confirmed:
            console.print("[dim]Cancelled.[/dim]")
            return

    conn.execute(
        "DELETE FROM jobs WHERE fit_score IS NOT NULL AND fit_score <= ?",
        (max_score,),
    )
    conn.commit()
    console.print(f"[green]Deleted {total} low-scoring jobs (score <= {max_score}).[/green]")


@app.command()
def ultimate(
    top: int = typer.Option(10, "--top", "-n", help="Number of top-scoring jobs to draw from."),
    min_score: int = typer.Option(7, "--min-score", help="Minimum fit score to include."),
    out: Optional[str] = typer.Option(None, "--out", "-o", help="Output directory (default: ~/.divapply/)."),
) -> None:
    """Generate an ultimate general-purpose resume from your top-scoring jobs."""
    _bootstrap()

    from pathlib import Path
    from divapply.scoring.ultimate import generate_ultimate_resume

    output_dir = Path(out) if out else None

    try:
        result = generate_ultimate_resume(
            top_n=top,
            min_score=min_score,
            output_dir=output_dir,
        )
    except RuntimeError as e:
        console.print(f"[red]{e}[/red]")
        raise typer.Exit(code=1)

    console.print(f"\n[bold green]Ultimate resume generated![/bold green]")
    console.print(f"  Jobs used:  {result['jobs_used']}")
    console.print(f"  Text:       {result['text_path']}")
    if result.get("pdf_path"):
        console.print(f"  PDF:        {result['pdf_path']}")
    console.print(f"  Time:       {result['elapsed']:.1f}s")
    console.print()


@app.command()
def sync(
    platform: Optional[list[str]] = typer.Argument(
        None,
        help="Platforms to sync: github, linkedin, facebook. Defaults to all.",
    ),
    dry_run: bool = typer.Option(False, "--dry-run", help="Generate content without pushing or automating."),
    headless: bool = typer.Option(False, "--headless", help="Run browser automation in headless mode."),
) -> None:
    """Sync your profile across social platforms (GitHub, LinkedIn, Facebook).

    Uses your Firefox login cookies to automate profile updates.
    GitHub is updated via API (needs GITHUB_TOKEN in .env).
    LinkedIn and Facebook are updated via browser automation.
    """
    _bootstrap()

    from divapply.social import sync_profiles

    targets = platform if platform else None

    # Validate platform names
    valid = {"github", "linkedin", "facebook"}
    if targets:
        for t in targets:
            if t.lower() not in valid:
                console.print(f"[red]Unknown platform:[/red] '{t}'. Valid: {', '.join(sorted(valid))}")
                raise typer.Exit(code=1)

    console.print("\n[bold blue]Social Profile Sync[/bold blue]")
    if dry_run:
        console.print("[dim]Dry run â€” generating content only, no automation.[/dim]")
    else:
        console.print("[dim]Extracting Firefox cookies for login, launching browser...[/dim]")
    console.print()

    results = sync_profiles(platforms=targets, dry_run=dry_run, headless=headless)

    for r in results:
        header = f"[bold]{r.platform}[/bold]"
        if r.auto_updated:
            updated = ", ".join(r.sections_updated) if r.sections_updated else "all"
            console.print(f"  {header}  [green]UPDATED[/green] ({updated})")
        elif r.error:
            console.print(f"  {header}  [yellow]{r.error}[/yellow]")
        else:
            console.print(f"  {header}  [dim]done[/dim]")

        if r.sections_failed:
            console.print(f"    [red]failed:[/red] {', '.join(r.sections_failed)}")

        # Show generated content
        for key, val in r.content.items():
            display = val if len(val) <= 120 else val[:117] + "..."
            console.print(f"    {key}: {display}")
        console.print()

    # Mention the saved snapshot
    from divapply.config import APP_DIR as _app_dir
    console.print(f"[dim]Full content saved to {_app_dir / 'social_sync.json'}[/dim]")
    console.print(f"[dim]Debug screenshots in {_app_dir / 'social_screenshots/'}[/dim]\n")


if __name__ == "__main__":
    app()

