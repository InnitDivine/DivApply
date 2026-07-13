"""DivApply CLI - the main entry point."""

from __future__ import annotations

import csv
import json
import logging
import os
from typing import Optional
from pathlib import Path

import typer
from rich.console import Console
from rich.table import Table

from divapply import __version__
from divapply.jobspy_runtime import JOBSPY_WHEEL_URL, validate_installed_jobspy
from divapply.manual_url import extract_manual_job_metadata
from divapply.privacy import redact_error_snippet

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s",
    datefmt="%H:%M:%S",
)

app = typer.Typer(
    name="divapply",
    help="DivApply, an AI-powered end-to-end job application pipeline.",
    no_args_is_help=True,
    context_settings={"help_option_names": ["--help", "-h"]},
)
export_app = typer.Typer(
    help="Export safe DivApply data.",
    context_settings={"help_option_names": ["--help", "-h"]},
)
answers_app = typer.Typer(
    help="Manage saved application question answers.",
    context_settings={"help_option_names": ["--help", "-h"]},
)
app.add_typer(export_app, name="export")
app.add_typer(answers_app, name="answers")
console = Console()
log = logging.getLogger(__name__)

# Valid pipeline stages (in execution order)
VALID_STAGES = ("discover", "enrich", "score", "tailor", "cover", "pdf")
SAFE_APPLY_WORKERS = 1
SAFE_APPLY_LIMIT = 5


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _apply_cost_guard_message(
    *,
    dry_run: bool,
    allow_expensive: bool,
    continuous: bool,
    workers: int,
    effective_limit: int,
) -> str | None:
    """Return a cost guard error message, or None when the run is allowed."""
    if workers < 1:
        return "--workers must be at least 1."
    if effective_limit < 0:
        return "--limit cannot be negative."
    if dry_run or allow_expensive:
        return None
    if continuous or workers > SAFE_APPLY_WORKERS or effective_limit == 0 or effective_limit > SAFE_APPLY_LIMIT:
        return (
            "Cost guard blocked this real auto-apply run.\n"
            f"Default cost-safe mode allows up to {SAFE_APPLY_LIMIT} queued application(s) "
            f"with {SAFE_APPLY_WORKERS} worker. Use --dry-run first, lower "
            "the limit/workers, or add --allow-expensive when you intentionally "
            "want a higher-cost run."
        )
    return None


def _resolve_apply_model(backend: str | None, model: str | None = None) -> str:
    """Resolve the browser-agent model without inheriting scorer/tailor LLM settings."""
    default_model = "sonnet" if backend == "claude" else "gpt-5.4-mini"
    return model or os.environ.get("LLM_MODEL_APPLY") or default_model


def _bootstrap() -> None:
    """Common setup: load env, create dirs, init DB."""
    from divapply.config import load_env, ensure_dirs
    from divapply.database import init_db
    from divapply.maintenance import cleanup_expired_logs

    load_env()
    ensure_dirs()
    cleanup_expired_logs()
    init_db()


def _version_callback(value: bool) -> None:
    if value:
        console.print(f"[bold]DivApply[/bold] {__version__}")
        raise typer.Exit()


def _safe_apply_error(value: str | None) -> str:
    """Backward-compatible wrapper for exported error redaction."""
    return redact_error_snippet(value)


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
    """DivApply - AI-powered end-to-end job application pipeline."""


@app.command()
def init() -> None:
    """Run the first-time setup wizard (profile, resume, search config)."""
    from divapply.wizard.init import run_wizard

    run_wizard()


@app.command()
def edit(
    port: int = typer.Option(8765, "--port", help="Preferred localhost port for the editor."),
    no_open: bool = typer.Option(False, "--no-open", help="Print the URL without opening a browser."),
) -> None:
    """Open the local browser editor for profile and search settings."""
    from divapply.editor import run_editor

    console.print("[bold]Starting DivApply editor[/bold]")
    console.print("Press Ctrl+C in this terminal when you are done.")
    try:
        run_editor(port=port, open_browser=not no_open)
    except KeyboardInterrupt:
        console.print("\n[green]Editor stopped.[/green]")


@app.command()
def migrate(
    overwrite: bool = typer.Option(False, "--overwrite", help="Replace current files with legacy copies when both exist."),
) -> None:
    """Copy legacy user files into the current DivApply layout."""
    from divapply.config import ensure_dirs, migrate_legacy_user_data

    ensure_dirs()
    results = migrate_legacy_user_data(overwrite=overwrite)

    console.print("\n[bold]Migration summary[/bold]")
    for key, status in results.items():
        label = {
            "profile": "profile.json",
            "searches": "searches.yaml",
            "env": ".env",
            "resume_txt": "resume.txt",
            "resume_pdf": "resume.pdf",
            "database": "divapply.db",
        }.get(key, key)
        color = "green" if status == "copied" else "yellow" if status == "skipped" else "dim"
        console.print(f"  [{color}]{label}[/{color}] {status}")

    copied = sum(1 for status in results.values() if status == "copied")
    skipped = sum(1 for status in results.values() if status == "skipped")
    if copied:
        console.print("[green]Legacy data copied into the DivApply layout.[/green]")
    if skipped:
        console.print("[yellow]Some current files already existed and were left in place.[/yellow]")
    if not copied and not skipped:
        console.print("[dim]No legacy files were found to migrate.[/dim]")


@app.command()
def backup(
    out: Optional[Path] = typer.Option(None, "--out", "-o", help="Backup zip path. Defaults to ~/.divapply/backups/."),
    include_secrets: bool = typer.Option(False, "--include-secrets", help="Include .env and credentials.yaml in the archive."),
    include_outputs: bool = typer.Option(True, "--include-outputs/--no-outputs", help="Include generated resumes and cover letters."),
    include_logs: bool = typer.Option(False, "--include-logs", help="Include redacted local logs; disabled by default."),
) -> None:
    """Create a local recovery backup of user data."""
    from divapply.backup import create_backup

    result = create_backup(
        out=out,
        include_secrets=include_secrets,
        include_outputs=include_outputs,
        include_logs=include_logs,
    )

    console.print(f"[green]Backup written:[/green] {result.path}")
    console.print(
        f"[dim]{result.file_count} file(s) included. "
        f"Secrets included: {'yes' if result.included_secrets else 'no'}.[/dim]"
    )


@app.command()
def cleanup(
    yes: bool = typer.Option(False, "--yes", "-y", help="Delete cleanup candidates instead of only previewing them."),
    include_backups: bool = typer.Option(
        False,
        "--include-backups",
        help="Also include old divapply-backup-*.zip archives under the backups folder.",
    ),
) -> None:
    """Preview or delete stale local dashboard benchmark and backup artifacts."""
    from divapply.maintenance import cleanup_artifacts

    result = cleanup_artifacts(dry_run=not yes, include_backups=include_backups)
    action = "Would remove" if result.dry_run else "Removed"

    if not result.candidates:
        console.print("[green]No cleanup candidates found.[/green]")
        return

    table = Table(title="DivApply cleanup")
    table.add_column("Action")
    table.add_column("Path")
    deleted = set(result.deleted)
    skipped = set(result.skipped)
    for path in result.candidates:
        if path in skipped:
            status = "Skipped"
        elif result.dry_run:
            status = "Would remove"
        elif path in deleted:
            status = "Removed"
        else:
            status = action
        table.add_row(status, str(path))
    console.print(table)

    if result.dry_run:
        console.print("[dim]Run `divapply cleanup --yes` to delete these files.[/dim]")
    elif result.skipped:
        console.print(f"[yellow]Skipped {len(result.skipped)} file(s) that could not be removed safely.[/yellow]")


@app.command("import-coursework")
def import_coursework(
    path: Path = typer.Argument(..., exists=True, readable=True, resolve_path=True, help="Transcript or coursework file to import."),
    replace: bool = typer.Option(
        False,
        "--replace",
        help="Wipe existing coursework before importing. Default appends new rows and skips exact duplicates so prior transcripts stay intact.",
    ),
) -> None:
    """Import coursework knowledge into the hidden SQLite coursework table.

    By default, new entries are appended and rows that already exist
    (matching school + course code + course title + term) are skipped.
    Pass --replace to wipe the existing coursework table first.
    """
    _bootstrap()

    from divapply.database import append_coursework, replace_coursework

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
                        "status": item.get("status") or item.get("course_status"),
                        "credits": item.get("credits") or item.get("units"),
                        "grade": item.get("grade"),
                        "source": item.get("source") or path.name,
                        "notes": item.get("notes"),
                        "raw_text": item.get("raw_text") or item.get("text") or json.dumps(item, ensure_ascii=True),
                    })
        else:
            entries.append({"source": path.name, "raw_text": text})
    elif suffix == ".csv":
        csv_reader = csv.DictReader(text.splitlines())
        for row in csv_reader:
            entries.append({
                "school": row.get("school") or row.get("institution"),
                "course_code": row.get("course_code") or row.get("code"),
                "course_title": row.get("course_title") or row.get("title") or row.get("name"),
                "subject_area": row.get("subject_area") or row.get("subject") or row.get("category"),
                "term": row.get("term") or row.get("semester") or row.get("session"),
                "status": row.get("status") or row.get("course_status"),
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

        pdf_reader = PdfReader(str(path))
        raw_text = "\n".join(page.extract_text() or "" for page in pdf_reader.pages).strip()
        entries.append({"source": path.name, "raw_text": raw_text, "notes": "Imported from PDF transcript"})
    else:
        text = path.read_text(encoding="utf-8", errors="ignore")
        entries.append({"source": path.name, "raw_text": text, "notes": "Imported plain text transcript"})

    if replace:
        inserted = replace_coursework(entries)
        console.print(
            f"[yellow]Replaced coursework table:[/yellow] {inserted} row(s) inserted "
            "(prior coursework wiped)."
        )
    else:
        result = append_coursework(entries)
        console.print(
            f"[green]Appended coursework:[/green] {result['inserted']} new, "
            f"{result['skipped']} duplicate(s) skipped."
        )


@app.command("coursework-summary")
def coursework_summary() -> None:
    """Show safe metadata about hidden coursework knowledge."""
    _bootstrap()

    from divapply.database import get_coursework_summary

    summary = get_coursework_summary()

    table = Table(title="Coursework Summary", show_header=True, header_style="bold cyan")
    table.add_column("Field", style="bold")
    table.add_column("Value")

    def _join(items: list[str]) -> str:
        return ", ".join(items) if items else "none"

    table.add_row("Rows", str(summary["row_count"]))
    table.add_row("Schools", _join(summary["schools"]))
    table.add_row("Subject areas", _join(summary["subject_areas"]))
    table.add_row("Inferred skills", _join(summary["inferred_skills"]))
    table.add_row("Import sources", _join(summary["import_sources"]))
    console.print()
    console.print(table)
    console.print("[dim]Coursework is hidden matching/tailoring knowledge. Transcript text is not shown or exported.[/dim]\n")


def _extract_manual_job_metadata(url: str) -> dict[str, str | bool]:
    """Backward-compatible wrapper for manual URL metadata extraction."""
    return extract_manual_job_metadata(url)


@app.command("add-url")
def add_url(
    job_url: str = typer.Argument(..., help="Job posting URL to add or update."),
    title: Optional[str] = typer.Option(None, "--title", help="Override the detected job title."),
    company: Optional[str] = typer.Option(None, "--company", help="Override the detected company."),
    location: Optional[str] = typer.Option(None, "--location", help="Job location, if known."),
    site: Optional[str] = typer.Option(None, "--site", help="Source/employer label, if known."),
    no_fetch: bool = typer.Option(False, "--no-fetch", help="Skip page fetch and use provided metadata only."),
    prepare: bool = typer.Option(
        False,
        "--prepare",
        help="Score this URL; documents require a later verified official-source refresh.",
    ),
    min_score: int = typer.Option(7, "--min-score", help="Minimum score required before tailoring/cover generation."),
    validation: str = typer.Option("normal", "--validation", help="Validation mode for generated documents."),
) -> None:
    """Add one pasted job URL, optionally preparing its application packet."""
    _bootstrap()

    from datetime import datetime, timezone

    from divapply.config import load_search_config
    from divapply.database import get_connection
    from divapply.search_policy import market_policy_for_job
    from divapply.security import validate_external_url

    valid_modes = ("strict", "normal", "lenient", "none")
    if validation not in valid_modes:
        console.print(f"[red]Invalid --validation value:[/red] {validation}")
        raise typer.Exit(code=1)

    safe_url = validate_external_url(job_url, field="job URL")
    metadata: dict[str, str | bool] = {
        "title": safe_url.rstrip("/").split("/")[-1].replace("-", " ").strip().title() or "Manual Job",
        "company": "Manual",
        "site": "Manual URL",
        "location": "",
        "description": f"Manual job URL: {safe_url}",
        "inactive": False,
    }
    if not no_fetch:
        try:
            metadata.update(_extract_manual_job_metadata(safe_url))
        except Exception as exc:
            console.print(f"[yellow]Could not fetch page metadata:[/yellow] {_safe_apply_error(str(exc))}")

    title_value = title or str(metadata["title"])
    company_value = company or str(metadata["company"])
    site_value = site or str(metadata["site"])
    location_value = location or str(metadata["location"])
    description_value = str(metadata["description"])
    inactive = bool(metadata["inactive"])
    now = datetime.now(timezone.utc).isoformat()

    apply_status = "failed" if inactive else None
    apply_error = "expired: posting appears inactive" if inactive else None
    apply_attempts = 99 if inactive else 0
    market_label, _ = market_policy_for_job(
        load_search_config(),
        {"company": company_value, "location": location_value},
    )

    conn = get_connection()
    conn.execute(
        """
        INSERT INTO jobs (
            url, canonical_key, title, company, salary, description,
            location, site, strategy, discovered_at, full_description,
            application_url, detail_scraped_at, detail_error,
            apply_status, apply_error, apply_attempts, verification_confidence,
            market_label, search_query, application_mode, employment_type,
            hours_per_week, source_verification, official_url_verified_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(url) DO UPDATE SET
            title=excluded.title,
            company=excluded.company,
            description=excluded.description,
            location=excluded.location,
            site=excluded.site,
            full_description=excluded.full_description,
            application_url=excluded.application_url,
            detail_scraped_at=excluded.detail_scraped_at,
            detail_error=excluded.detail_error,
            apply_status=excluded.apply_status,
            apply_error=excluded.apply_error,
            apply_attempts=excluded.apply_attempts,
            verification_confidence=excluded.verification_confidence,
            market_label=excluded.market_label,
            search_query=excluded.search_query,
            application_mode=excluded.application_mode,
            employment_type=excluded.employment_type,
            hours_per_week=excluded.hours_per_week,
            source_verification=excluded.source_verification,
            official_url_verified_at=excluded.official_url_verified_at,
            archived_at=NULL
        """,
        (
            safe_url,
            f"{title_value}|{company_value}|{location_value}".casefold(),
            title_value,
            company_value,
            "",
            description_value,
            location_value,
            site_value,
            "manual_url",
            now,
            description_value,
            safe_url,
            now,
            "Posting appears inactive." if inactive else None,
            apply_status,
            apply_error,
            apply_attempts,
            "manual_url_inactive" if inactive else "manual_url",
            market_label or None,
            "manual_url",
            "manual_review",
            None,
            None,
            "unknown",
            None,
        ),
    )
    conn.commit()

    console.print(f"[green]Added:[/green] {title_value} @ {company_value}")
    if inactive:
        console.print("[yellow]Posting appears inactive/expired, so it will not be queued for auto-apply.[/yellow]")

    if not prepare:
        console.print("[dim]Run again with --prepare to score this URL. Documents stay blocked until an official source verifies it.[/dim]")
        return

    from divapply.config import check_tier
    from divapply.scoring.cover_letter import run_cover_letters
    from divapply.scoring.scorer import run_scoring
    from divapply.scoring.tailor import run_tailoring

    check_tier(2, "AI scoring/tailoring")

    score_result = run_scoring(target_url=safe_url)
    if not score_result.get("scored"):
        console.print("[red]Could not score this URL. Check that the page has a readable job description.[/red]")
        raise typer.Exit(code=1)

    row = conn.execute(
        "SELECT fit_score, tailored_resume_path, cover_letter_path FROM jobs WHERE url = ?",
        (safe_url,),
    ).fetchone()
    score = int(row["fit_score"] or 0)
    console.print(f"[green]Score:[/green] {score}")
    if score < min_score:
        console.print(f"[yellow]Score is below --min-score {min_score}; not generating documents.[/yellow]")
        return

    provenance = conn.execute(
        "SELECT application_mode, source_verification FROM jobs WHERE url = ?",
        (safe_url,),
    ).fetchone()
    if provenance["application_mode"] != "active" or provenance["source_verification"] != "official":
        console.print(
            "[yellow]Score saved, but documents were withheld.[/yellow] "
            "Refresh this posting from a configured official employer source before tailoring or applying."
        )
        return

    tailor_result = run_tailoring(min_score=min_score, limit=1, validation_mode=validation, target_url=safe_url)
    cover_result = run_cover_letters(min_score=min_score, limit=1, validation_mode=validation, target_url=safe_url)
    row = conn.execute(
        "SELECT tailored_resume_path, cover_letter_path FROM jobs WHERE url = ?",
        (safe_url,),
    ).fetchone()
    console.print(
        f"[green]Prepared:[/green] resume={row['tailored_resume_path'] or 'not generated'}; "
        f"cover={row['cover_letter_path'] or 'not generated'}"
    )
    console.print(f"[dim]Tailor result: {tailor_result}; cover result: {cover_result}[/dim]")


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
    yes: bool = typer.Option(False, "--yes", "-y", help="Confirm destructive pruning when --prune-score is used."),
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

    if prune_score > 0 and not dry_run and not yes and ("all" in stage_list or "score" in stage_list):
        confirmed = typer.confirm(
            f"`run --prune-score {prune_score}` will delete jobs with fit_score <= {prune_score}. Continue?"
        )
        if not confirmed:
            console.print("[dim]Cancelled. Use --dry-run to preview or --yes to confirm pruning.[/dim]")
            return

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


@app.command("credentials")
def credentials_cmd(
    site: Optional[str] = typer.Option(
        None,
        "--site",
        "-s",
        help="Domain for a site-specific login, for example workdayjobs.com. Omit for the default login.",
    ),
    username: Optional[str] = typer.Option(None, "--username", "-u", help="Login username or email."),
    password: Optional[str] = typer.Option(
        None,
        "--password",
        help="Login password. Prefer omitting this so DivApply prompts without echoing it.",
    ),
    show: bool = typer.Option(False, "--show", help="Show saved usernames and domains, never passwords."),
) -> None:
    """Manage local-only job site login credentials."""
    _bootstrap()

    import getpass
    import yaml

    from divapply import config
    from divapply.security import protect_file

    path = config.CREDENTIALS_PATH
    data = config.load_credentials(path)
    data = data if isinstance(data, dict) else {}

    if show or (site is None and username is None and password is None):
        console.print(f"[bold]Credentials file:[/bold] {path}")
        default = data.get("default", {}) if isinstance(data.get("default"), dict) else {}
        if default:
            console.print(
                f"Default login: username={default.get('username', '') or '(missing)'} "
                f"password={'saved' if default.get('password') else 'missing'}"
            )
        sites = data.get("sites", {}) if isinstance(data.get("sites"), dict) else {}
        for domain, creds in sites.items():
            if isinstance(creds, dict):
                console.print(
                    f"{domain}: username={creds.get('username', '') or '(default)'} "
                    f"password={'saved' if creds.get('password') else 'missing'}"
                )
        if not data:
            console.print("No credentials saved yet.")
            console.print("Run: divapply credentials --username you@example.com")
        return

    if password is None:
        password = getpass.getpass("Job site password: ")
    if not password:
        console.print("[red]Password cannot be empty.[/red]")
        raise typer.Exit(code=1)

    if not username:
        try:
            profile = config.load_profile()
            username = profile.get("personal", {}).get("email", "")
        except Exception:
            username = ""
    if not username:
        console.print("[red]Username is required when profile email is unavailable.[/red]")
        raise typer.Exit(code=1)

    if site:
        sites = data.setdefault("sites", {})
        if not isinstance(sites, dict):
            sites = {}
            data["sites"] = sites
        sites[site.strip().lower()] = {"username": username, "password": password}
        label = site.strip().lower()
    else:
        data["default"] = {"username": username, "password": password}
        label = "default"

    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(yaml.safe_dump(data, sort_keys=False), encoding="utf-8")
    protect_file(path)
    console.print(f"[green]Saved {label} login to local credentials file.[/green]")
    console.print("[dim]Passwords are not stored in profile.json and are excluded from normal backups.[/dim]")


@app.command("browser-login")
def browser_login(
    url: str = typer.Option(
        "https://www.myworkday.com/",
        "--url",
        help="Login page to open in the persistent apply browser profile.",
    ),
    browser: Optional[str] = typer.Option(
        None,
        "--browser",
        help="Browser profile to prepare. Defaults to DIVAPPLY_BROWSER, or chromium.",
    ),
    worker: int = typer.Option(0, "--worker", "-w", help="Apply worker profile number to reuse."),
) -> None:
    """Open the persistent apply browser profile so logins/cookies can be saved."""
    _bootstrap()

    import subprocess
    import sys

    from divapply.config import get_apply_browser, get_chrome_path
    from divapply.apply.chrome import setup_worker_profile

    resolved_browser = get_apply_browser(browser)
    profile_dir = setup_worker_profile(worker, resolved_browser)
    profile_dir.mkdir(parents=True, exist_ok=True)

    if resolved_browser == "chrome":
        cmd = [
            get_chrome_path(),
            f"--user-data-dir={profile_dir}",
            "--profile-directory=Default",
            "--no-first-run",
            "--no-default-browser-check",
            url,
        ]
    else:
        cmd = [
            sys.executable,
            "-m",
            "playwright",
            "open",
            "--user-data-dir",
            str(profile_dir),
            "--viewport-size",
            "1280,900",
        ]
        if resolved_browser == "msedge":
            cmd.extend(["--browser", "chromium", "--channel", "msedge"])
        else:
            cmd.extend(["--browser", resolved_browser])
        cmd.append(url)

    console.print(f"[green]Opening persistent {resolved_browser} worker-{worker} profile.[/green]")
    console.print("[dim]Sign in, finish any 2FA, then close the browser window to save cookies.[/dim]")
    console.print(f"[dim]Profile: {profile_dir}[/dim]")
    result = subprocess.run(cmd)
    if result.returncode:
        raise typer.Exit(code=result.returncode)
    console.print("[green]Browser closed. Saved cookies will be reused by matching apply runs.[/green]")


@app.command()
def apply(
    limit: Optional[int] = typer.Option(None, "--limit", "-l", help="Max applications to submit."),
    workers: int = typer.Option(1, "--workers", "-w", help="Number of parallel browser workers."),
    min_score: int = typer.Option(7, "--min-score", help="Minimum fit score for job selection."),
    max_score: Optional[int] = typer.Option(None, "--max-score", help="Maximum fit score for job selection."),
    model: Optional[str] = typer.Option(None, "--model", "-m", help="Apply agent model name."),
    backend: Optional[str] = typer.Option(None, "--backend", "-b", help="Apply agent backend: codex or claude."),
    browser: Optional[str] = typer.Option(None, "--browser", help="Apply browser. Defaults to DIVAPPLY_BROWSER, or chromium."),
    continuous: bool = typer.Option(False, "--continuous", "-c", help="Run forever, polling for new jobs."),
    dry_run: bool = typer.Option(False, "--dry-run", help="Preview actions without submitting."),
    headless: bool = typer.Option(False, "--headless", help="Run browsers in headless mode."),
    url: Optional[str] = typer.Option(None, "--url", help="Apply to a specific job URL."),
    gen: bool = typer.Option(False, "--gen", help="Generate prompt file for manual debugging instead of running."),
    mark_applied: Optional[str] = typer.Option(None, "--mark-applied", help="Manually mark a job URL as applied."),
    mark_failed: Optional[str] = typer.Option(None, "--mark-failed", help="Manually mark a job URL as failed (provide URL)."),
    fail_reason: Optional[str] = typer.Option(None, "--fail-reason", help="Reason for --mark-failed."),
    reset_failed: bool = typer.Option(False, "--reset-failed", help="Reset all failed jobs for retry."),
    yes: bool = typer.Option(False, "--yes", "-y", help="Confirm real browser submission mode."),
    allow_expensive: bool = typer.Option(
        False,
        "--allow-expensive",
        help="Allow real auto-apply runs with multiple workers, high limits, or continuous polling.",
    ),
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
    from divapply.database import ACTIONABLE_JOB_SQL, get_connection

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

    # Check 1: Tier 3 required (apply agent CLI + browser runtime + Node.js)
    resolved_browser = get_apply_browser(browser)
    resolved_backend = get_apply_backend(backend)
    resolved_model = _resolve_apply_model(resolved_backend, model)
    check_tier(3, "auto-apply", preferred_backend=backend, preferred_browser=browser)
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
            "SELECT COUNT(*) FROM jobs WHERE tailored_resume_path IS NOT NULL "
            f"AND applied_at IS NULL AND archived_at IS NULL AND {ACTIONABLE_JOB_SQL}"
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
            max_score=max_score,
            model=resolved_model,
            backend=resolved_backend,
            browser=resolved_browser,
        )
        if not prompt_file:
            console.print("[red]No matching job found for that URL.[/red]")
            raise typer.Exit(code=1)
        mcp_path = _profile_path.parent / ".mcp-apply-0.json"
        console.print(f"[green]Wrote prompt to:[/green] {prompt_file}")
        console.print("\n[bold]Run manually:[/bold]")
        console.print(f"  {get_manual_command(resolved_backend, resolved_model, prompt_file, mcp_path)}")
        return

    from divapply.apply.launcher import main as apply_main

    effective_limit = limit if limit is not None else (0 if continuous else 1)
    cost_guard_message = _apply_cost_guard_message(
        dry_run=dry_run,
        allow_expensive=allow_expensive,
        continuous=continuous,
        workers=workers,
        effective_limit=effective_limit,
    )
    if cost_guard_message:
        console.print(f"[red]{cost_guard_message}[/red]")
        raise typer.Exit(code=1)

    console.print("\n[bold blue]Launching Auto-Apply[/bold blue]")
    console.print(f"  Limit:    {'unlimited' if continuous else effective_limit}")
    console.print(f"  Workers:  {workers}")
    console.print(f"  Backend:  {get_apply_backend_label(resolved_backend)}")
    console.print(f"  Browser:  {get_apply_browser_label(resolved_browser)}")
    console.print(f"  Model:    {resolved_model}")
    console.print(f"  Headless: {headless}")
    console.print(f"  Dry run:  {dry_run}")
    console.print(
        "  Cost:     "
        + (
            "unbounded (explicitly allowed)"
            if allow_expensive and not dry_run
            else f"guarded: <= {SAFE_APPLY_LIMIT} real queued application(s), {SAFE_APPLY_WORKERS} worker"
        )
    )
    if url:
        console.print(f"  Target:   {url}")
    console.print()

    if not dry_run and not yes:
        confirmed = typer.confirm(
            "Real auto-apply mode may click final Submit/Apply buttons. Continue?"
        )
        if not confirmed:
            console.print("[dim]Cancelled. Use --dry-run to test safely or --yes to confirm real submissions.[/dim]")
            return

    apply_main(
        limit=effective_limit,
        target_url=url,
        min_score=min_score,
        max_score=max_score,
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

    import sys
    from divapply.config import TAILORED_DIR, COVER_LETTER_DIR, PROFILE_PATH, RESUME_PATH, SEARCH_CONFIG_PATH
    from divapply.database import get_active_db_path, get_coursework_summary, get_stats

    stats = get_stats()
    coursework = get_coursework_summary()

    console.print("\n[bold]DivApply Pipeline Status[/bold]\n")

    # Summary table
    summary = Table(title="Pipeline Overview", show_header=True, header_style="bold cyan")
    summary.add_column("Metric", style="bold")
    summary.add_column("Count", justify="right")

    summary.add_row("Total jobs discovered", str(stats["total"]))
    summary.add_row("With full description", str(stats["with_description"]))
    summary.add_row("Pending enrichment", str(stats["pending_detail"]))
    summary.add_row("Enrichment errors", str(stats["detail_errors"]))
    summary.add_row("Scored", str(stats["scored"]))
    summary.add_row("Pending scoring", str(stats["unscored"]))
    summary.add_row("Tailored resumes", str(stats["tailored"]))
    summary.add_row("Pending tailoring (7+)", str(stats["untailored_eligible"]))
    summary.add_row("Cover letters", str(stats["with_cover_letter"]))
    summary.add_row("Ready to apply", str(stats["ready_to_apply"]))
    summary.add_row("Applied", str(stats["applied"]))
    summary.add_row("Apply in progress", str(stats.get("apply_in_progress", 0)))
    summary.add_row("Stale apply locks", str(stats.get("stale_apply_locks", 0)))
    summary.add_row("Due follow-ups", str(stats.get("due_followups", 0)))
    summary.add_row("Apply errors", str(stats["apply_errors"]))

    console.print(summary)

    runtime = Table(title="\nRuntime", show_header=True, header_style="bold blue")
    runtime.add_column("Check", style="bold")
    runtime.add_column("Value")
    runtime.add_row("Python", f"{sys.version.split()[0]} ({sys.executable})")
    runtime.add_row("DivApply", __version__)
    runtime.add_row("Database", str(get_active_db_path()))
    runtime.add_row("Coursework rows", str(coursework["row_count"]))
    runtime.add_row("profile.json", "present" if PROFILE_PATH.exists() else "missing")
    runtime.add_row("resume.txt", "present" if RESUME_PATH.exists() else "missing")
    runtime.add_row("searches.yaml", "present" if SEARCH_CONFIG_PATH.exists() else "missing")
    runtime.add_row("Tailored resume dir", "present" if TAILORED_DIR.exists() else "missing")
    runtime.add_row("Cover letter dir", "present" if COVER_LETTER_DIR.exists() else "missing")
    console.print(runtime)

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


@export_app.command("jobs")
def export_jobs(
    out: Path = typer.Option(Path("jobs.csv"), "--out", "-o", help="Output file path."),
    fmt: str = typer.Option("csv", "--format", help="Export format: csv or json."),
) -> None:
    """Export safe job tracking fields."""
    _bootstrap()

    from divapply.database import get_connection

    fmt = fmt.lower().strip()
    if fmt not in {"csv", "json"}:
        console.print("[red]--format must be csv or json[/red]")
        raise typer.Exit(code=1)

    safe_columns = [
        "title",
        "company",
        "site",
        "url",
        "application_url",
        "fit_score",
        "apply_status",
        "discovered_at",
        "scored_at",
        "tailored_at",
        "applied_at",
        "apply_error",
    ]

    conn = get_connection()
    rows = conn.execute(
        """
        SELECT title, company, site, url, application_url, fit_score, apply_status,
               discovered_at, scored_at, tailored_at, applied_at, apply_error
        FROM jobs
        ORDER BY CASE WHEN fit_score IS NULL THEN 1 ELSE 0 END, fit_score DESC, discovered_at DESC
        """
    ).fetchall()

    payload = []
    for row in rows:
        item = {key: row[key] for key in safe_columns}
        item["apply_error"] = _safe_apply_error(item.get("apply_error"))
        payload.append(item)

    out.parent.mkdir(parents=True, exist_ok=True)
    if fmt == "json":
        out.write_text(json.dumps(payload, indent=2, ensure_ascii=True), encoding="utf-8")
    else:
        with out.open("w", newline="", encoding="utf-8") as fh:
            writer = csv.DictWriter(fh, fieldnames=safe_columns)
            writer.writeheader()
            writer.writerows(payload)

    console.print(f"[green]Exported {len(payload)} job row(s):[/green] {out}")


@answers_app.command("add")
def answers_add(
    question: str = typer.Argument(..., help="Employer question text."),
    answer: str = typer.Argument(..., help="Factual answer to reuse."),
    tag: Optional[list[str]] = typer.Option(None, "--tag", help="Optional tag; repeatable."),
) -> None:
    """Add or replace a saved answer-bank entry."""
    _bootstrap()

    from divapply.apply.answers import add_answer
    result = add_answer(question, answer, tags=tag or [])
    verb = "Updated" if result["replaced"] else "Added"
    console.print(f"[green]{verb} answer:[/green] {question}")


@answers_app.command("list")
def answers_list() -> None:
    """List saved answer-bank questions without dumping secrets elsewhere."""
    _bootstrap()

    from divapply.apply.answers import load_answer_bank
    entries = load_answer_bank()
    table = Table(title="Answer Bank", show_header=True, header_style="bold cyan")
    table.add_column("#", justify="right")
    table.add_column("Question")
    table.add_column("Answer")
    for idx, entry in enumerate(entries, start=1):
        answer = entry["answer"]
        if len(answer) > 120:
            answer = answer[:117] + "..."
        table.add_row(str(idx), entry["question"], answer)
    console.print()
    console.print(table)
    console.print(f"[dim]{len(entries)} saved answer(s). Stored locally in ~/.divapply/answers.yaml.[/dim]\n")


@answers_app.command("match")
def answers_match(
    question: str = typer.Argument(..., help="Question text to fuzzy-match."),
    limit: int = typer.Option(3, "--limit", "-n", help="Number of matches."),
) -> None:
    """Fuzzy-match a form question against saved answers."""
    _bootstrap()

    from divapply.apply.answers import match_answers
    matches = match_answers(question, limit=limit)
    table = Table(title="Answer Matches", show_header=True, header_style="bold cyan")
    table.add_column("Score", justify="right")
    table.add_column("Question")
    table.add_column("Answer")
    for entry in matches:
        answer = entry["answer"]
        if len(answer) > 120:
            answer = answer[:117] + "..."
        table.add_row(f"{entry['score']:.2f}", entry["question"], answer)
    console.print()
    console.print(table)


@app.command()
def track(
    event: str = typer.Argument(..., help="Lifecycle event: applied, screening, interview, offer, rejection, withdrawn."),
    job_url: str = typer.Argument(..., help="Job URL to track."),
    follow_up: Optional[str] = typer.Option(None, "--follow-up", help="Follow-up date YYYY-MM-DD."),
    notes: Optional[str] = typer.Option(None, "--notes", "-n", help="Short private note."),
) -> None:
    """Append an application lifecycle event."""
    _bootstrap()

    from divapply.database import add_application_event, get_application_timeline

    valid = {"applied", "screening", "interview", "offer", "rejection", "rejected", "withdrawn", "failed"}
    normalized = event.strip().lower().replace("-", "_")
    if normalized not in valid:
        console.print(f"[red]Unknown event:[/red] {event}. Use: {', '.join(sorted(valid))}")
        raise typer.Exit(code=1)
    if follow_up:
        import re
        if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", follow_up):
            console.print("[red]--follow-up must be YYYY-MM-DD[/red]")
            raise typer.Exit(code=1)

    event_id = add_application_event(job_url, normalized, notes=notes, follow_up_at=follow_up)
    console.print(f"[green]Tracked {normalized} event #{event_id}[/green] for {job_url}")

    timeline = get_application_timeline(job_url)
    if timeline:
        table = Table(title="Timeline", show_header=True, header_style="bold cyan")
        table.add_column("When")
        table.add_column("Event")
        table.add_column("Follow-up")
        table.add_column("Notes")
        for row in timeline[-6:]:
            table.add_row(row["ts"], row["event_type"], row.get("follow_up_at") or "", row.get("notes") or "")
        console.print(table)


@app.command()
def followups() -> None:
    """Show application follow-ups due today or earlier."""
    _bootstrap()

    from divapply.database import get_due_followups
    rows = get_due_followups()
    table = Table(title="Due Follow-ups", show_header=True, header_style="bold cyan")
    table.add_column("Due")
    table.add_column("Event")
    table.add_column("Title")
    table.add_column("Company/Source")
    table.add_column("URL")
    for row in rows:
        table.add_row(
            row.get("follow_up_at") or "",
            row.get("event_type") or "",
            row.get("title") or "",
            row.get("company") or row.get("site") or "",
            row.get("job_url") or "",
        )
    console.print()
    console.print(table)
    console.print(f"[dim]{len(rows)} due follow-up(s).[/dim]\n")


@app.command()
def analytics() -> None:
    """Show application lifecycle analytics."""
    _bootstrap()

    from divapply.database import get_application_analytics
    data = get_application_analytics()

    states = Table(title="Application States", show_header=True, header_style="bold cyan")
    states.add_column("State")
    states.add_column("Count", justify="right")
    for state, count in data["states"]:
        states.add_row(state, str(count))

    events = Table(title="Lifecycle Events", show_header=True, header_style="bold magenta")
    events.add_column("Event")
    events.add_column("Count", justify="right")
    for event, count in data["events"]:
        events.add_row(event, str(count))

    console.print()
    console.print(states)
    console.print(events)
    console.print(f"[bold]Due follow-ups:[/bold] {data['due_followups']}\n")


@app.command()
def explain(
    job_url: str = typer.Argument(..., help="Job URL or URL fragment to explain."),
) -> None:
    """Explain one job's hybrid score without printing resume/profile text."""
    _bootstrap()

    from divapply.database import get_connection

    like = f"%{job_url.strip().rstrip('/')}%"
    conn = get_connection()
    row = conn.execute(
        """
        SELECT title, company, site, url, fit_score, llm_score, keyword_score,
               embedding_score, composite_score, score_breakdown, score_reasoning,
               matched_skills, missing_skills, keyword_hits, risk_flags,
               apply_or_skip_reason
        FROM jobs
        WHERE url = ? OR url LIKE ? OR application_url LIKE ?
        ORDER BY scored_at DESC
        LIMIT 1
        """,
        (job_url, like, like),
    ).fetchone()
    if not row:
        console.print("[red]No matching job found.[/red]")
        raise typer.Exit(code=1)

    table = Table(title="Score Explain", show_header=True, header_style="bold cyan")
    table.add_column("Field", style="bold")
    table.add_column("Value")
    for key in (
        "title", "company", "site", "fit_score", "llm_score",
        "keyword_score", "embedding_score", "composite_score",
        "matched_skills", "missing_skills", "keyword_hits",
        "risk_flags", "apply_or_skip_reason", "score_reasoning",
    ):
        table.add_row(key, str(row[key] if row[key] is not None else "legacy/missing"))
    console.print()
    console.print(table)

    if row["score_breakdown"]:
        try:
            data = json.loads(row["score_breakdown"])
            misses = data.get("keyword", {}).get("misses", [])[:12]
            if misses:
                console.print("[yellow]What to improve:[/yellow] " + ", ".join(misses))
        except json.JSONDecodeError:
            pass
    else:
        console.print("[dim]Legacy score: run `divapply rescore` for hybrid breakdown.[/dim]")


@app.command()
def rescore(
    limit: int = typer.Option(0, "--limit", "-l", help="Max rows to rescore; 0 = all."),
) -> None:
    """Recompute hybrid scores for existing enriched jobs."""
    _bootstrap()

    from divapply.scoring.scorer import run_scoring
    result = run_scoring(limit=limit, rescore=True)
    console.print(f"[green]Rescored {result['scored']} job(s).[/green] Errors: {result['errors']}")


@app.command()
def dashboard(
    static: bool = typer.Option(False, "--static", help="Write a static HTML file instead of starting the interactive dashboard."),
    port: int = typer.Option(8776, "--port", help="Preferred localhost port for the interactive dashboard."),
    no_open: bool = typer.Option(False, "--no-open", help="Print the URL/path without opening a browser."),
) -> None:
    """Open the dashboard. Interactive mode supports archiving applied jobs."""
    _bootstrap()

    from divapply.view import generate_dashboard, open_dashboard, serve_dashboard

    if static:
        if no_open:
            path = generate_dashboard()
            typer.echo(f"Dashboard written: {path}")
        else:
            open_dashboard()
        return

    console.print("[bold]Starting DivApply dashboard[/bold]")
    console.print("Press Ctrl+C in this terminal when you are done.")
    try:
        serve_dashboard(port=port, open_browser=not no_open)
    except KeyboardInterrupt:
        console.print("\n[green]Dashboard stopped.[/green]")


@app.command()
def selfcheck() -> None:
    """Run offline sanity checks without calling job boards, LLMs, browsers, or apply agents."""
    import sys

    from divapply.config import (
        APP_DIR,
        COVER_LETTER_DIR,
        PROFILE_PATH,
        RESUME_PATH,
        SEARCH_CONFIG_PATH,
        TAILORED_DIR,
        ensure_dirs,
        load_env,
        load_search_config,
        validate_search_config,
    )
    from divapply.database import get_active_db_path, get_coursework_summary, init_db

    load_env()
    ensure_dirs()

    checks: list[tuple[str, str, str]] = []

    def add(name: str, ok: bool, note: str = "", warn: bool = False) -> None:
        if ok:
            status = "[green]OK[/green]"
        elif warn:
            status = "[yellow]WARN[/yellow]"
        else:
            status = "[red]FAIL[/red]"
        checks.append((name, status, note))

    py = sys.version_info
    add("Python version", py >= (3, 11), f"{sys.version.split()[0]} ({sys.executable})")
    add(
        "JobSpy Python",
        py < (3, 13),
        "Python 3.12 recommended; Python 3.13/3.14 may fail with python-jobspy/numpy pins",
        warn=True,
    )

    for module in ("typer", "rich", "yaml", "playwright"):
        try:
            __import__(module)
            add(f"import {module}", True)
        except Exception as exc:
            add(f"import {module}", False, str(exc))

    try:
        __import__("jobspy")
        add("import jobspy", True)
    except Exception as exc:
        add("import jobspy", False, str(exc), warn=True)

    add("profile.json", PROFILE_PATH.exists(), str(PROFILE_PATH), warn=True)
    add("resume.txt", RESUME_PATH.exists(), str(RESUME_PATH), warn=True)
    add("searches.yaml", SEARCH_CONFIG_PATH.exists(), str(SEARCH_CONFIG_PATH), warn=True)

    try:
        conn = init_db()
        conn.execute("SELECT 1 FROM jobs LIMIT 1")
        add("DB init", True, str(get_active_db_path()))
    except Exception as exc:
        add("DB init", False, str(exc))

    try:
        summary = get_coursework_summary()
        add("coursework rows", True, str(summary["row_count"]))
    except Exception as exc:
        add("coursework rows", False, str(exc), warn=True)

    try:
        search_report = validate_search_config(load_search_config())
        note = "; ".join(search_report["errors"] + search_report["warnings"])
        add("search config", search_report["passed"], note or "valid", warn=not search_report["passed"])
    except Exception as exc:
        add("search config", False, str(exc), warn=True)

    for path in (APP_DIR, TAILORED_DIR, COVER_LETTER_DIR):
        add(f"dir {path.name}", path.exists(), str(path))

    table = Table(title="DivApply Offline Selfcheck", show_header=True, header_style="bold cyan")
    table.add_column("Check", style="bold")
    table.add_column("Status")
    table.add_column("Note")
    for row in checks:
        table.add_row(*row)
    console.print()
    console.print(table)
    console.print("[dim]Offline only: no job boards, LLMs, browsers, apply agents, or external sites called.[/dim]\n")

    failed = [name for name, status, _ in checks if "FAIL" in status]
    if failed:
        raise typer.Exit(code=1)


@app.command()
def doctor() -> None:
    """Check your setup and diagnose missing requirements."""
    import shutil
    import sys
    from divapply.config import (
        load_env, ensure_dirs, PROFILE_PATH, RESUME_PATH, RESUME_PDF_PATH,
        SEARCH_CONFIG_PATH, TAILORED_DIR, COVER_LETTER_DIR, get_chrome_path,
        get_apply_browser, get_apply_browser_label,
    )
    from divapply.database import get_active_db_path, get_coursework_summary, init_db

    load_env()
    ensure_dirs()
    init_db()

    ok_mark = "[green]OK[/green]"
    fail_mark = "[red]MISSING[/red]"
    warn_mark = "[yellow]WARN[/yellow]"

    results: list[tuple[str, str, str]] = []  # (check, status, note)

    results.append(("DivApply version", ok_mark, __version__))
    results.append(("Python executable", ok_mark, sys.executable))
    results.append(("Python version", ok_mark, sys.version.split()[0]))
    if sys.version_info >= (3, 13):
        results.append((
            "JobSpy Python",
            warn_mark,
            "Python 3.12 recommended; Python 3.13/3.14 may fail with python-jobspy/numpy pins",
        ))
    else:
        results.append(("JobSpy Python", ok_mark, "Python 3.12 recommended for full JobSpy support"))
    results.append(("database path", ok_mark, str(get_active_db_path())))
    try:
        coursework = get_coursework_summary()
        results.append(("coursework rows", ok_mark, str(coursework["row_count"])))
    except Exception as exc:
        results.append(("coursework rows", warn_mark, str(exc)))
    results.append(("generated resume dir", ok_mark if TAILORED_DIR.exists() else warn_mark, str(TAILORED_DIR)))
    results.append(("cover letter dir", ok_mark if COVER_LETTER_DIR.exists() else warn_mark, str(COVER_LETTER_DIR)))

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
        results.append(("resume.txt", warn_mark, "Only PDF found - plain-text needed for AI stages"))
    else:
        results.append(("resume.txt", fail_mark, "Run 'divapply init' to add your resume"))

    # Search config
    if SEARCH_CONFIG_PATH.exists():
        results.append(("searches.yaml", ok_mark, str(SEARCH_CONFIG_PATH)))
    else:
        results.append(("searches.yaml", warn_mark, "Will use example config - run 'divapply init'"))

    # jobspy (discovery dep installed separately)
    try:
        import jobspy  # noqa: F401
        jobspy_issues = validate_installed_jobspy()
        if jobspy_issues:
            results.append(("python-jobspy", fail_mark, "; ".join(jobspy_issues)))
        else:
            results.append(("python-jobspy", ok_mark, "Job board scraping available"))
    except ImportError:
        results.append(
            (
                "python-jobspy",
                warn_mark,
                f"pip install --upgrade 'divapply[full]' && pip install --no-deps '{JOBSPY_WHEEL_URL}'",
            )
        )

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

    # Browser runtime
    selected_browser = get_apply_browser()
    if selected_browser == "chrome":
        try:
            chrome_path = get_chrome_path()
            results.append(("Browser", ok_mark, chrome_path))
        except FileNotFoundError:
            results.append(("Browser", fail_mark,
                            "Install Chrome or set CHROME_PATH env var (needed for Chrome mode)"))
    else:
        results.append(("Browser", ok_mark,
                        f"Playwright channel: {get_apply_browser_label(selected_browser)}"))

    # Node.js + npm provision the integrity-locked MCP runtime.
    node_bin = shutil.which("node")
    npm_bin = shutil.which("npm")
    if node_bin and npm_bin:
        results.append(("Node.js / npm", ok_mark, f"{node_bin}; {npm_bin}"))
    else:
        results.append(("Node.js / npm", fail_mark,
                        "Install Node.js 18+ from nodejs.org (needed for locked auto-apply runtime)"))

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
    console.print(f"[bold]Current tier: Tier {tier} - {TIER_LABELS[tier]}[/bold]")

    if tier == 1:
        console.print("[dim]  -> Tier 2 unlocks: scoring, tailoring, cover letters (needs LLM API key)[/dim]")
        console.print("[dim]  -> Tier 3 unlocks: auto-apply (needs an apply backend CLI + Node.js + browser runtime)[/dim]")
    elif tier == 2:
        console.print("[dim]  -> Tier 3 unlocks: auto-apply (needs an apply backend CLI + Node.js + browser runtime)[/dim]")

    console.print()


@app.command()
def prune(
    max_score: int = typer.Option(
        4,
        "--max-score",
        "--maxscore",
        help="Delete scored jobs at or below this score (default: 4).",
    ),
    dry_run: bool = typer.Option(False, "--dry-run", help="Preview without deleting."),
    yes: bool = typer.Option(False, "--yes", "-y", help="Skip confirmation prompt."),
) -> None:
    """Remove low-scoring jobs from the database to reduce clutter."""
    _bootstrap()

    from divapply.database import delete_scored_jobs_at_or_below, get_connection

    conn = get_connection()

    # Show breakdown by score before deleting
    rows = conn.execute(
        "SELECT fit_score, COUNT(*) FROM jobs "
        "WHERE fit_score IS NOT NULL AND fit_score <= ? AND archived_at IS NULL "
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
        console.print("[dim]Dry run - no changes made.[/dim]")
        return

    if not yes:
        confirmed = typer.confirm(f"Delete {total} jobs permanently?")
        if not confirmed:
            console.print("[dim]Cancelled.[/dim]")
            return

    deleted = delete_scored_jobs_at_or_below(max_score, conn=conn)
    console.print(f"[green]Deleted {deleted} low-scoring jobs (score <= {max_score}).[/green]")


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
        console.print("[dim]Dry run - generating content only, no automation.[/dim]")
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
