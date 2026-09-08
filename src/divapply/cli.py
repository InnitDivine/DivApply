"""DivApply CLI - the main entry point."""

from __future__ import annotations

import csv
import json
import logging
import os
import sqlite3
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
    help="Local job application assistant. Use divapply run to find jobs and prepare resume/cover-letter PDFs.",
    no_args_is_help=False,
    invoke_without_command=True,
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
settings_app = typer.Typer(help="Edit your profile, searches, coursework, and application logins.", no_args_is_help=True)
jobs_app = typer.Typer(help="Inspect, repair, export, and track saved jobs.", no_args_is_help=True)
system_app = typer.Typer(help="Check setup, back up data, and preview safe cleanup.", no_args_is_help=True)
coursework_app = typer.Typer(help="Import and inspect your private coursework knowledge.", no_args_is_help=True)
app.add_typer(settings_app, name="settings")
app.add_typer(jobs_app, name="jobs")
app.add_typer(system_app, name="system")
settings_app.add_typer(coursework_app, name="coursework")
settings_app.add_typer(answers_app, name="answers")
# Existing scripts keep working, but the main help advertises one path per task.
app.add_typer(export_app, name="export", hidden=True)
app.add_typer(answers_app, name="answers", hidden=True)
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


def _apply_queue_window(
    conn: sqlite3.Connection,
    *,
    min_score: int,
    max_score: int | None,
) -> tuple[int, int | None]:
    """Return eligible count and highest prepared score for a bounded apply run."""
    from divapply.apply.launcher import inspect_apply_queue

    return inspect_apply_queue(
        conn,
        min_score=min_score,
        max_score=max_score,
    )


def _run_assisted_cli(
    target_url: str,
    *,
    min_score: int,
    max_score: int | None,
    model: str,
    backend: str,
) -> str:
    """Run one visible no-submit autofill session and wait for the user's decision."""
    from divapply.apply.launcher import (
        abort_assisted_apply,
        finish_assisted_apply,
        resume_assisted_apply,
        start_assisted_apply,
    )
    from divapply.apply.prompt import ApplicationAuthorization

    authorization = ApplicationAuthorization(
        profile_fields=True,
        final_submit=False,
        source="assisted_review",
    )
    try:
        session = start_assisted_apply(
            target_url,
            min_score=min_score,
            max_score=max_score,
            model=model,
            backend=backend,
            authorization=authorization,
        )
    except (KeyboardInterrupt, EOFError):
        console.print("\n[yellow]Assisted startup was interrupted; the job claim and Chrome were cleaned up.[/yellow]")
        return "interrupted"
    except Exception as exc:
        safe_error = redact_error_snippet(str(exc), max_length=180)
        console.print(f"[red]Could not start assisted apply:[/red] {safe_error}")
        return "failed"
    if session is None:
        console.print(
            "[red]This link is not ready for assisted apply.[/red] "
            "Prepare it first or confirm the exact direct URL in the link workflow."
        )
        return "not_ready"

    def finish_or_report(decision: str, action: str, *, reason: str | None = None) -> str | None:
        """Finish the handoff, leaving Chrome open when persistence fails."""
        try:
            return finish_assisted_apply(session, decision, reason=reason)
        except Exception as exc:
            console.print(
                f"[red]Could not {action}; Chrome remains open.[/red] "
                f"{redact_error_snippet(str(exc), max_length=160)}"
            )
            return None

    console.print(f"\n[bold cyan]Chrome is ready for your review.[/bold cyan] Agent result: {session.result}")
    console.print(
        "[dim]The DivApply Chrome window will stay open. Fix or answer anything uncertain there, "
        "then return to this terminal.[/dim]"
    )
    try:
        while True:
            choice = typer.prompt(
                "Choose: R retry autofill, A I submitted it, L save for later, F failed, Q skip",
                default="L",
            ).strip().casefold()
            if choice in {"r", "retry"}:
                console.print("[cyan]Resuming the agent in the same Chrome window...[/cyan]")
                try:
                    result = resume_assisted_apply(session)
                except (KeyboardInterrupt, EOFError):
                    raise
                except Exception as exc:
                    safe_error = redact_error_snippet(str(exc), max_length=180)
                    console.print(
                        f"[yellow]Could not resume autofill:[/yellow] {safe_error}\n"
                        "The handoff is still open. Choose L to save it for later or retry after fixing Chrome."
                    )
                    continue
                console.print(f"[cyan]Agent result:[/cyan] {result}")
                continue
            if choice in {"a", "applied", "submitted"}:
                outcome = finish_or_report("submitted", "record the submission")
                if outcome is None:
                    continue
                console.print("[green]Recorded as submitted by you.[/green]")
                return outcome
            if choice in {"l", "later", "save"}:
                outcome = finish_or_report("later", "save the handoff")
                if outcome is None:
                    continue
                console.print("[yellow]Saved for later; no application was marked submitted.[/yellow]")
                return outcome
            if choice in {"f", "failed"}:
                reason = typer.prompt("Short failure reason", default="Could not complete assisted application")
                outcome = finish_or_report("failed", "record the failure", reason=reason)
                if outcome is None:
                    continue
                console.print("[yellow]Recorded as failed.[/yellow]")
                return outcome
            if choice in {"q", "quit", "skip"}:
                outcome = finish_or_report("skip", "release the handoff")
                if outcome is None:
                    continue
                console.print("[dim]Skipped without marking it submitted.[/dim]")
                return outcome
            console.print("[yellow]Enter R, A, L, F, or Q.[/yellow]")
    except (KeyboardInterrupt, EOFError):
        saved = False
        cleaned = session.closed
        if not session.closed:
            try:
                finish_assisted_apply(session, "later", reason="Assisted session interrupted; review later")
                saved = True
                cleaned = True
            except Exception:
                try:
                    abort_assisted_apply(session)
                    cleaned = True
                except Exception:
                    log.exception("Could not fully clean up an interrupted assisted session")
        if saved:
            console.print("\n[yellow]Saved for later and closed DivApply's Chrome window.[/yellow]")
            return "saved_for_later"
        if cleaned:
            console.print("\n[yellow]Interrupted; released the handoff and closed DivApply's Chrome window.[/yellow]")
            return "aborted"
        console.print(
            "\n[red]Interrupted, but DivApply could not confirm cleanup.[/red] "
            "Close any DivApply Chrome window and do not retry this link until a later run reports the stale claim recovered."
        )
        return "cleanup_failed"


def _resolve_apply_model(backend: str | None, model: str | None = None) -> str:
    """Resolve the browser-agent model without inheriting scorer/tailor LLM settings."""
    default_model = "sonnet" if backend == "claude" else "gpt-5.6-luna"
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


def _invoke_root_command(ctx: typer.Context, name: str, **values) -> None:
    """Invoke the registered Click command so Typer option defaults are resolved."""
    from typer.core import TyperGroup

    root = ctx.find_root()
    if not isinstance(root.command, TyperGroup):
        raise RuntimeError("DivApply command group is unavailable")
    command = root.command.get_command(root, name)
    if command is None:
        raise RuntimeError(f"DivApply command is unavailable: {name}")
    # Typer's bundled Context.invoke accepts callbacks, not command objects.
    # Parse defaults in a child context, then supply the already-validated values.
    with command.make_context(name, [], parent=root, resilient_parsing=True) as child:
        child.params.update(values)
        command.invoke(child)


# ---------------------------------------------------------------------------
# Commands
# ---------------------------------------------------------------------------


@app.callback()
def main(
    ctx: typer.Context,
    version: bool = typer.Option(
        False,
        "--version",
        "-V",
        help="Show version and exit.",
        callback=_version_callback,
        is_eager=True,
    ),
) -> None:
    """Show the command menu unless an explicit command was selected."""
    if ctx.invoked_subcommand is None:
        typer.echo(ctx.get_help())


@settings_app.command("init")
def init() -> None:
    """Run the first-time setup wizard (profile, resume, search config)."""
    from divapply.wizard.init import run_wizard

    run_wizard()


@settings_app.command("edit")
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


@system_app.command("migrate")
def migrate(
    overwrite: bool = typer.Option(
        False, "--overwrite", help="Replace current files with legacy copies when both exist."
    ),
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


@system_app.command("backup")
def backup(
    out: Optional[Path] = typer.Option(None, "--out", "-o", help="Backup zip path. Defaults to ~/.divapply/backups/."),
    include_secrets: bool = typer.Option(
        False, "--include-secrets", help="Include .env and credentials.yaml in the archive."
    ),
    include_outputs: bool = typer.Option(
        True, "--include-outputs/--no-outputs", help="Include generated resumes and cover letters."
    ),
    include_logs: bool = typer.Option(
        False, "--include-logs", help="Include redacted local logs; disabled by default."
    ),
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


@app.command("audit", hidden=True)
def audit_command(
    min_score: int = typer.Option(7, "--min-score", min=1, max=10),
    details: bool = typer.Option(False, "--details", help="Show the reason and saved error for every active job."),
) -> None:
    """Explain missing documents, stale grades, and blocked jobs without AI calls."""
    _bootstrap()
    from divapply.job_health import audit_jobs
    report = audit_jobs(min_score=min_score)
    table = Table(title=f"DivApply job health: {report['active']} active jobs")
    table.add_column("Status")
    table.add_column("Jobs", justify="right")
    for reason, count in report["counts"].items():
        table.add_row(reason, str(count))
    console.print(table)
    if details:
        jobs = Table(title="Job details")
        jobs.add_column("Job")
        jobs.add_column("Score")
        jobs.add_column("Status")
        jobs.add_column("Error")
        for job in report["jobs"]:
            jobs.add_row(job["title"], str(job["score"] if job["score"] is not None else "Not graded"),
                         job["documents"], redact_error_snippet(job["error"], max_length=180))
        console.print(jobs)
    console.print("Use `divapply run --saved --limit 3` to complete a small batch, or add --refresh to regrade.")


@jobs_app.command("repair")
def repair_command(
    limit: int = typer.Option(3, "--limit", "-l", min=0, help="Maximum jobs; 0 processes all saved jobs."),
    min_score: int = typer.Option(7, "--min-score", min=1, max=10),
    urls: Optional[list[str]] = typer.Option(None, "--url", help="Repair this saved URL; repeat to select more."),
    refresh: bool = typer.Option(True, "--refresh/--no-refresh", help="Read the live posting and linked qualifications."),
    rescore_jobs: bool = typer.Option(True, "--rescore/--no-rescore", help="Regrade with the configured AI provider."),
    prepare: bool = typer.Option(True, "--prepare/--no-prepare", help="Generate missing resumes and cover letters."),
    retry_failed: bool = typer.Option(False, "--retry-failed", help="Reset exhausted document attempts for selected jobs."),
    dry_run: bool = typer.Option(False, "--dry-run", help="Show selected jobs without changing them."),
) -> None:
    """Refresh, audit qualifications, and complete packets for a bounded job batch."""
    _bootstrap()
    from divapply.job_health import repair_jobs
    if not dry_run and (rescore_jobs or prepare):
        from divapply.config import check_tier
        check_tier(2, "AI qualification audit and application documents")
    report = repair_jobs(
        limit=limit, min_score=min_score, urls=urls, refresh=refresh,
        rescore=rescore_jobs, prepare=prepare, retry_failed=retry_failed, dry_run=dry_run,
    )
    table = Table(title="DivApply repair preview" if dry_run else "DivApply repair results")
    table.add_column("Job")
    table.add_column("Score")
    table.add_column("Result")
    for item in report["jobs"]:
        table.add_row(item["title"], str(item.get("score", "")), item.get("error") or item.get("after") or item["before"])
    console.print(table)
    if report["errors"]:
        raise typer.Exit(code=1)


@system_app.command("cleanup")
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


@coursework_app.command("import")
def import_coursework(
    path: Path = typer.Argument(
        ..., exists=True, readable=True, resolve_path=True, help="Transcript or coursework file to import."
    ),
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
                    entries.append(
                        {
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
                        }
                    )
        else:
            entries.append({"source": path.name, "raw_text": text})
    elif suffix == ".csv":
        csv_reader = csv.DictReader(text.splitlines())
        for row in csv_reader:
            entries.append(
                {
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
                }
            )
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
            f"[yellow]Replaced coursework table:[/yellow] {inserted} row(s) inserted (prior coursework wiped)."
        )
    else:
        result = append_coursework(entries)
        console.print(
            f"[green]Appended coursework:[/green] {result['inserted']} new, {result['skipped']} duplicate(s) skipped."
        )


@coursework_app.command("summary")
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
    console.print(
        "[dim]Coursework is hidden matching/tailoring knowledge. Transcript text is not shown or exported.[/dim]\n"
    )


def _extract_manual_job_metadata(url: str) -> dict[str, str | bool]:
    """Backward-compatible wrapper for manual URL metadata extraction."""
    return extract_manual_job_metadata(url)


def _persist_manual_url(
    conn: sqlite3.Connection,
    *,
    safe_url: str,
    metadata: dict[str, str | bool],
    title_value: str,
    company_value: str,
    site_value: str,
    location_value: str,
    description_value: str,
    inactive: bool,
    now: str,
    market_label: str,
    market_policy: dict,
    search_config: dict,
    official_source: str | None,
    closed_official_source: str | None,
    user_confirmed: bool = False,
) -> bool:
    """Persist one fetched manual URL without mixing storage into the CLI flow."""
    application_url_value = str(metadata.get("application_url") or metadata.get("final_url") or safe_url)
    if official_source:
        from divapply.discovery.smartextract import _store_jobs_filtered

        new, existing = _store_jobs_filtered(
            conn,
            [
                {
                    "url": safe_url,
                    "application_url": application_url_value,
                    "title": title_value,
                    "company": company_value,
                    "location": location_value,
                    "description": description_value,
                    "full_description": description_value,
                    "employment_type": str(metadata.get("employment_type") or ""),
                    "availability_state": "open",
                }
            ],
            site=official_source,
            strategy="manual_url_official",
            accept_locs=[location_value] if location_value else [],
            reject_locs=[],
            title_excludes=[],
            filter_rules={"allow_unknown_location": True},
            market_label=market_label,
            search_query="manual_url",
            application_mode=str(market_policy.get("application_mode") or "manual_review"),
            source_verification="official",
            # A pasted URL is an explicit user selection, not a discovery
            # candidate. Preserve the market policy resolved above without
            # reapplying broad title, keyword, company, or remote filters.
            search_config=None,
        )
        if new or existing:
            _persist_requirement_metadata(conn, safe_url, metadata)
        return bool(new or existing)

    # Metadata refreshes must never reset an application lifecycle.  In
    # particular, leave apply_status/error/attempts and the other apply-owned
    # columns (applied_at, agent_id, timestamps, duration, and task id) out of
    # the conflict update so applied, in-progress, and terminal rows retain
    # their exact state.
    conn.execute(
        """
        INSERT INTO jobs (
            url, canonical_key, title, company, salary, description,
            location, site, strategy, discovered_at, full_description,
            application_url, detail_scraped_at, detail_error,
            apply_status, apply_error, apply_attempts, verification_confidence,
            market_label, search_query, application_mode, employment_type,
            hours_per_week, source_verification, official_url_verified_at,
            availability_state, availability_checked_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
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
            verification_confidence=excluded.verification_confidence,
            market_label=excluded.market_label,
            search_query=excluded.search_query,
            application_mode=excluded.application_mode,
            employment_type=excluded.employment_type,
            hours_per_week=excluded.hours_per_week,
            source_verification=excluded.source_verification,
            official_url_verified_at=excluded.official_url_verified_at,
            availability_state=excluded.availability_state,
            availability_checked_at=excluded.availability_checked_at
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
            application_url_value,
            now,
            "Posting appears inactive." if inactive else None,
            "failed" if inactive else None,
            "expired: posting appears inactive" if inactive else None,
            99 if inactive else 0,
            "manual_url_inactive" if inactive else (
                "user_confirmed_direct" if user_confirmed else "manual_url"
            ),
            market_label or None,
            "manual_url",
            "manual_review",
            str(metadata.get("employment_type") or "") or None,
            None,
            "official" if closed_official_source else (
                "user_confirmed_direct" if user_confirmed else "unknown"
            ),
            now if closed_official_source else None,
            "closed" if inactive else "unknown",
            now if inactive else None,
        ),
    )
    conn.commit()
    _persist_requirement_metadata(conn, safe_url, metadata)
    if inactive:
        from divapply.database import archive_job

        archive_job(safe_url, conn=conn, reason="source_closed")
    return True


def _persist_requirement_metadata(conn: sqlite3.Connection, url: str, metadata: dict) -> None:
    fields = ("requirements_description", "requirements_sources", "requirements_error", "requirements_checked_at")
    if any(field in metadata for field in fields):
        conn.execute(
            "UPDATE jobs SET " + ", ".join(field + "=?" for field in fields) + " WHERE url=?",
            (*(metadata.get(field) for field in fields), url),
        )
        conn.commit()


def _resolve_owned_resume_artifact(path: Path, root: Path, suffix: str) -> Path | None:
    """Resolve one regular generated artifact without following it outside its owned root."""
    from divapply.security import _is_link_or_reparse

    if path.suffix.casefold() != suffix or not path.is_file() or _is_link_or_reparse(path):
        return None
    try:
        resolved = path.resolve(strict=True)
    except OSError:
        return None
    return resolved if resolved.is_relative_to(root) else None


def _manual_resume_pdf_is_usable(pdf_path: Path, source_path: Path | None) -> bool:
    """Validate a recovered PDF against its text source, or at least its text layer."""
    try:
        if source_path is not None:
            from divapply.scoring.pdf import parse_resume, validate_ats_pdf

            source_text = source_path.read_text(encoding="utf-8")
            required_sections = list(parse_resume(source_text)["sections"])
            validate_ats_pdf(
                source_text,
                pdf_path,
                required_sections=required_sections,
            )
            return True

        from pypdf import PdfReader

        reader = PdfReader(str(pdf_path))
        if reader.is_encrypted or not reader.pages:
            return False
        return bool("\n".join((page.extract_text() or "") for page in reader.pages).strip())
    except Exception as exc:
        log.warning(
            "Existing resume PDF is unreadable for %s: %s",
            pdf_path.name,
            redact_error_snippet(str(exc)),
        )
        return False


def _ensure_manual_resume_pdf(
    conn: sqlite3.Connection,
    *,
    safe_url: str,
    resume_path: str | None,
) -> str | None:
    """Promote a retained text fallback to the PDF promised by link preparation."""
    from divapply.config import TAILORED_DIR
    from divapply.security import _is_link_or_reparse

    if not resume_path:
        return None

    try:
        if _is_link_or_reparse(TAILORED_DIR):
            raise OSError("tailored-resume directory is a link or reparse point")
        tailored_root = TAILORED_DIR.resolve(strict=True)
    except OSError:
        console.print("[red]DivApply's tailored-resume directory could not be resolved safely.[/red]")
        return None

    original_pointer = str(resume_path)
    artifact_path = Path(original_pointer)
    source_path: Path | None = None
    existing_pdf: Path | None = None

    if artifact_path.suffix.casefold() == ".pdf":
        existing_pdf = _resolve_owned_resume_artifact(artifact_path, tailored_root, ".pdf")
        source_path = _resolve_owned_resume_artifact(
            artifact_path.with_suffix(".txt"),
            tailored_root,
            ".txt",
        )
        if existing_pdf and _manual_resume_pdf_is_usable(existing_pdf, source_path):
            current = conn.execute(
                "SELECT 1 FROM jobs WHERE url = ? AND tailored_resume_path = ? AND archived_at IS NULL",
                (safe_url, original_pointer),
            ).fetchone()
            return str(existing_pdf) if current else None
        if source_path is None:
            console.print("[red]The saved resume PDF is unreadable and no text source is available to repair it.[/red]")
            return None
    elif artifact_path.suffix.casefold() == ".txt":
        source_path = _resolve_owned_resume_artifact(artifact_path, tailored_root, ".txt")
    else:
        console.print(f"[red]Resume source has an unsupported type:[/red] {artifact_path}")
        return None

    if source_path is None:
        console.print("[red]Refusing to convert a resume outside DivApply's owned tailored-resume directory.[/red]")
        return None

    final_pdf_path = source_path.with_suffix(".pdf")
    resolved_existing = _resolve_owned_resume_artifact(final_pdf_path, tailored_root, ".pdf")
    if resolved_existing and _manual_resume_pdf_is_usable(resolved_existing, source_path):
        generated_pdf = resolved_existing
        temporary_pdf: Path | None = None
    else:
        if final_pdf_path.exists() and resolved_existing is None:
            console.print("[red]Refusing to replace an unsafe resume PDF path.[/red]")
            return None

        import tempfile

        from divapply.scoring.pdf import convert_to_pdf

        with tempfile.NamedTemporaryFile(
            prefix=f".{source_path.stem}.manual-",
            suffix=".pdf",
            dir=tailored_root,
            delete=False,
        ) as temporary:
            temporary_pdf = Path(temporary.name)
        try:
            generated_pdf = Path(convert_to_pdf(source_path, output_path=temporary_pdf))
        except Exception as exc:
            temporary_pdf.unlink(missing_ok=True)
            detail = redact_error_snippet(str(exc))
            log.warning("Resume PDF finalization failed for %s: %s", source_path.name, detail)
            console.print(f"[red]Resume PDF generation failed:[/red] {detail}")
            return None

        resolved_generated = _resolve_owned_resume_artifact(generated_pdf, tailored_root, ".pdf")
        if resolved_generated is None or resolved_generated != temporary_pdf.resolve():
            temporary_pdf.unlink(missing_ok=True)
            console.print("[red]Resume PDF generation returned an unsafe output path.[/red]")
            return None
        generated_pdf = resolved_generated

    try:
        conn.execute("BEGIN IMMEDIATE")
        current = conn.execute(
            "SELECT tailored_resume_path FROM jobs WHERE url = ? AND archived_at IS NULL",
            (safe_url,),
        ).fetchone()
        if current is None or current["tailored_resume_path"] != original_pointer:
            conn.rollback()
            if temporary_pdf is not None:
                temporary_pdf.unlink(missing_ok=True)
            console.print("[yellow]Resume changed during PDF generation; the stale result was discarded.[/yellow]")
            return None

        if temporary_pdf is not None:
            if final_pdf_path.exists() and _is_link_or_reparse(final_pdf_path):
                raise OSError("resume PDF destination became a link or reparse point")
            temporary_pdf.replace(final_pdf_path)
            generated_pdf = final_pdf_path.resolve(strict=True)

        cursor = conn.execute(
            """
            UPDATE jobs SET tailored_resume_path = ?
            WHERE url = ? AND tailored_resume_path = ? AND archived_at IS NULL
            """,
            (str(generated_pdf), safe_url, original_pointer),
        )
        if cursor.rowcount != 1:
            raise sqlite3.OperationalError("active resume pointer changed before promotion")
        conn.commit()
    except (OSError, sqlite3.Error) as exc:
        conn.rollback()
        if temporary_pdf is not None:
            temporary_pdf.unlink(missing_ok=True)
        detail = redact_error_snippet(str(exc))
        log.warning("Could not promote resume PDF for %s: %s", source_path.name, detail)
        console.print(f"[red]Resume PDF could not be saved safely:[/red] {detail}")
        return None

    return str(generated_pdf)


def _prepare_manual_url(
    conn: sqlite3.Connection,
    *,
    safe_url: str,
    min_score: int,
    validation: str,
    allow_user_confirmed: bool = False,
    raise_on_score_error: bool = True,
) -> dict[str, object]:
    """Score and prepare one verified manual URL after provenance gates pass."""
    from divapply.config import check_tier
    from divapply.scoring.cover_letter import run_cover_letters
    from divapply.scoring.scorer import run_scoring
    from divapply.scoring.tailor import run_tailoring

    check_tier(2, "AI scoring/tailoring")
    score_result = run_scoring(target_url=safe_url)
    if not score_result.get("scored"):
        console.print("[red]Could not score this URL. Check that the page has a readable job description.[/red]")
        if raise_on_score_error:
            raise typer.Exit(code=1)
        return {"status": "score_failed", "score": None}

    row = conn.execute(
        "SELECT fit_score, tailored_resume_path, cover_letter_path FROM jobs WHERE url = ?",
        (safe_url,),
    ).fetchone()
    score = int(row["fit_score"] or 0)
    console.print(f"[green]Score:[/green] {score}")
    if score < min_score:
        console.print(f"[yellow]Score is below --min-score {min_score}; not generating documents.[/yellow]")
        return {"status": "below_threshold", "score": score}

    provenance = conn.execute(
        "SELECT application_mode, source_verification FROM jobs WHERE url = ?",
        (safe_url,),
    ).fetchone()
    verified_for_documents = (
        provenance["application_mode"] == "active" and provenance["source_verification"] == "official"
    )
    assisted_for_documents = allow_user_confirmed and (
        provenance["application_mode"] in {"active", "manual_review"}
        and provenance["source_verification"] in {"official", "user_confirmed_direct"}
    )
    if not (verified_for_documents or assisted_for_documents):
        console.print(
            "[yellow]Score saved, but documents were withheld.[/yellow] "
            "Refresh this posting from a configured official employer source before tailoring or applying."
        )
        return {"status": "unverified_source", "score": score}

    tailor_result = run_tailoring(
        min_score=min_score,
        limit=1,
        validation_mode=validation,
        target_url=safe_url,
        allow_user_confirmed=allow_user_confirmed,
    )
    cover_result = run_cover_letters(
        min_score=min_score,
        limit=1,
        validation_mode=validation,
        target_url=safe_url,
        allow_user_confirmed=allow_user_confirmed,
    )
    row = conn.execute(
        "SELECT tailored_resume_path, cover_letter_path FROM jobs WHERE url = ?",
        (safe_url,),
    ).fetchone()
    resume_pdf_path = _ensure_manual_resume_pdf(
        conn,
        safe_url=safe_url,
        resume_path=row["tailored_resume_path"],
    )
    cover_path = row["cover_letter_path"]
    if cover_path and Path(cover_path).suffix.casefold() == ".txt":
        from divapply.scoring.pdf import batch_convert
        try:
            batch_convert(limit=2, target_url=safe_url)
            cover_path = conn.execute("SELECT cover_letter_path FROM jobs WHERE url=?", (safe_url,)).fetchone()[0]
        except Exception as exc:
            console.print(f"[red]Cover PDF conversion failed:[/red] {redact_error_snippet(str(exc))}")
    packet_ready = bool(resume_pdf_path and cover_path and Path(cover_path).suffix.casefold() == ".pdf" and Path(cover_path).is_file())
    preparation_label = "[green]Prepared:[/green]" if packet_ready else "[red]Preparation incomplete:[/red]"
    console.print(
        f"{preparation_label} resume={resume_pdf_path or 'PDF not generated'}; "
        f"cover={cover_path or 'PDF not generated'}"
    )
    console.print(f"[dim]Tailor result: {tailor_result}; cover result: {cover_result}[/dim]")
    return {
        "status": "prepared" if packet_ready else "document_generation_failed",
        "score": score,
        "tailored_resume_path": resume_pdf_path,
        "cover_letter_path": cover_path,
    }


def _ingest_manual_url(
    job_url: str,
    *,
    title: str | None = None,
    company: str | None = None,
    location: str | None = None,
    site: str | None = None,
    no_fetch: bool = False,
    user_confirmed: bool = False,
    emit: bool = True,
) -> dict[str, object]:
    """Fetch and persist one pasted URL, returning its resolved identity and provenance."""
    from datetime import datetime, timezone

    from divapply.config import configured_official_source_name, load_search_config
    from divapply.database import get_connection
    from divapply.search_policy import market_policy_for_job
    from divapply.security import validate_external_url

    safe_url = validate_external_url(job_url, field="job URL")
    metadata: dict[str, str | bool] = {
        "title": safe_url.rstrip("/").split("/")[-1].replace("-", " ").strip().title() or "Manual Job",
        "company": "Manual",
        "site": "Manual URL",
        "location": "",
        "description": f"Manual job URL: {safe_url}",
        "employment_type": "",
        "job_posting_schema": False,
        "inactive": False,
        "final_url": safe_url,
        "application_url": safe_url,
    }
    fetch_error: str | None = None
    if not no_fetch:
        try:
            metadata.update(_extract_manual_job_metadata(safe_url))
        except Exception as exc:
            fetch_error = _safe_apply_error(str(exc))
            if emit:
                console.print(f"[yellow]Could not fetch page metadata:[/yellow] {fetch_error}")

    title_value = title or str(metadata["title"])
    company_value = company or str(metadata["company"])
    location_value = location or str(metadata["location"])
    description_value = str(metadata["description"])
    inactive = bool(metadata["inactive"])
    search_config = load_search_config()
    market_label, market_policy = market_policy_for_job(
        search_config,
        {"company": company_value, "location": location_value},
    )
    final_url = str(metadata.get("final_url") or safe_url)
    application_url = str(metadata.get("application_url") or final_url)
    configured_source = None
    if not no_fetch:
        configured_source = configured_official_source_name(final_url) or configured_official_source_name(safe_url)
    official_source = (
        configured_source if bool(metadata.get("job_posting_schema")) and not inactive and not no_fetch else None
    )
    closed_official_source = configured_source if inactive and not no_fetch else None
    if closed_official_source and company is None:
        company_value = closed_official_source
    site_value = site or closed_official_source or str(metadata["site"])

    conn = get_connection()
    persisted = _persist_manual_url(
        conn,
        safe_url=safe_url,
        metadata=metadata,
        title_value=title_value,
        company_value=company_value,
        site_value=site_value,
        location_value=location_value,
        description_value=description_value,
        inactive=inactive,
        now=datetime.now(timezone.utc).isoformat(),
        market_label=market_label,
        market_policy=market_policy,
        search_config=search_config,
        official_source=official_source,
        closed_official_source=closed_official_source,
        user_confirmed=user_confirmed and official_source is None,
    )
    if not persisted:
        raise RuntimeError("Validated manual job URL was not saved.")
    verification = "official" if (official_source or closed_official_source) else (
        "user_confirmed_direct" if user_confirmed else "unknown"
    )
    result: dict[str, object] = {
        "url": safe_url,
        "application_url": application_url,
        "title": title_value,
        "company": company_value,
        "location": location_value,
        "site": site_value,
        "inactive": inactive,
        "verification": verification,
        "official_source": official_source or closed_official_source,
        "fetch_error": fetch_error,
    }
    if emit:
        console.print(f"[green]Added:[/green] {title_value} @ {company_value}")
        if official_source:
            console.print(f"[green]Verified from configured official source:[/green] {official_source}")
        elif closed_official_source:
            console.print(f"[yellow]Verified closed from configured official source:[/yellow] {closed_official_source}")
        elif user_confirmed:
            console.print("[cyan]Accepted for this assisted, no-submit workflow by your confirmation.[/cyan]")
    return result


def _confirm_manual_url_for_assist(conn: sqlite3.Connection, url: str) -> bool:
    """Mark one exact, open pasted URL as user-confirmed for no-submit assistance."""
    cursor = conn.execute(
        """
        UPDATE jobs
        SET source_verification = 'user_confirmed_direct',
            verification_confidence = 'user_confirmed_direct',
            application_mode = 'manual_review'
        WHERE url = ?
          AND source_verification != 'official'
          AND COALESCE(availability_state, 'unknown') != 'closed'
          AND archived_at IS NULL
        """,
        (url,),
    )
    conn.commit()
    return cursor.rowcount == 1


@app.command("add-url", hidden=True)
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
        help="Score this URL; documents require configured official-source verification.",
    ),
    min_score: int = typer.Option(7, "--min-score", help="Minimum score required before tailoring/cover generation."),
    validation: str = typer.Option("normal", "--validation", help="Validation mode for generated documents."),
    confirm_source: bool = typer.Option(
        False,
        "--confirm-source",
        help="Confirm this direct job URL for assisted preparation only; unattended auto-submit remains blocked.",
    ),
) -> None:
    """Add one pasted job URL, optionally preparing its application packet."""
    _bootstrap()

    from divapply.database import get_connection

    valid_modes = ("strict", "normal", "lenient", "none")
    if validation not in valid_modes:
        console.print(f"[red]Invalid --validation value:[/red] {validation}")
        raise typer.Exit(code=1)

    ingest = _ingest_manual_url(
        job_url,
        title=title,
        company=company,
        location=location,
        site=site,
        no_fetch=no_fetch,
        user_confirmed=confirm_source,
    )
    safe_url = str(ingest["url"])
    if bool(ingest["inactive"]):
        console.print("[yellow]Posting appears inactive/expired, so it will not be queued for auto-apply.[/yellow]")
        return

    if not prepare:
        if ingest["verification"] == "official":
            console.print(
                "[dim]Run again with --prepare to score this verified URL and create eligible documents.[/dim]"
            )
        elif confirm_source:
            console.print("[dim]Run again with --prepare to create an assisted-review packet.[/dim]")
        else:
            console.print(
                "[dim]Run again with --prepare to score this URL. "
                "Documents stay blocked until an official source verifies it.[/dim]"
            )
        return

    result = _prepare_manual_url(
        get_connection(),
        safe_url=safe_url,
        min_score=min_score,
        validation=validation,
        allow_user_confirmed=confirm_source,
    )
    if result["status"] in {"score_failed", "document_generation_failed"}:
        raise typer.Exit(code=1)


@app.command("apply-links", hidden=True)
def apply_links(
    links_file: Path = typer.Argument(
        ...,
        exists=True,
        file_okay=True,
        dir_okay=False,
        readable=True,
        resolve_path=True,
        help="UTF-8 text file containing one direct job URL per line.",
    ),
    min_score: int = typer.Option(5, "--min-score", help="Minimum score required before preparing a packet."),
    validation: str = typer.Option("normal", "--validation", help="Document validation mode."),
    prepare_only: bool = typer.Option(
        False,
        "--prepare-only",
        help="Ingest, score, and create documents without opening application forms.",
    ),
    model: Optional[str] = typer.Option(None, "--model", "-m", help="Apply agent model name."),
    backend: Optional[str] = typer.Option(None, "--backend", "-b", help="Apply agent backend: codex or claude."),
    yes: bool = typer.Option(
        False,
        "--yes",
        "-y",
        help="Confirm processing and assisted use of every valid direct URL in this file.",
    ),
) -> None:
    """Prepare pasted links and hand each application to you in visible Chrome."""
    _bootstrap()

    from datetime import datetime, timezone

    from divapply import config as app_config
    from divapply.database import get_connection
    from divapply.link_batch import parse_link_batch_file
    from divapply.security import write_private_text

    if validation not in {"strict", "normal", "lenient", "none"}:
        console.print(f"[red]Invalid --validation value:[/red] {validation}")
        raise typer.Exit(code=1)
    if not 0 <= min_score <= 10:
        console.print("[red]--min-score must be between 0 and 10.[/red]")
        raise typer.Exit(code=1)

    parsed = parse_link_batch_file(links_file)
    if parsed.invalid:
        for record in parsed.invalid:
            console.print(f"[yellow]Line {record.line_number} ignored:[/yellow] {record.error}")
    if parsed.duplicates:
        for record in parsed.duplicates:
            console.print(
                f"[dim]Line {record.line_number} duplicates line {record.duplicate_of_line}; ignored.[/dim]"
            )
    if not parsed.entries:
        console.print("[red]No valid job URLs were found in the file.[/red]")
        raise typer.Exit(code=1)

    action = "prepare" if prepare_only else "prepare and open for assisted review"
    if not yes and not typer.confirm(f"{action.title()} {len(parsed.entries)} valid job link(s)?"):
        console.print("[dim]Cancelled; no links were processed.[/dim]")
        return

    resolved_backend: str | None = None
    resolved_model = ""
    if not prepare_only:
        from divapply.config import check_tier, get_apply_backend, get_chrome_path

        resolved_backend = get_apply_backend(backend)
        if resolved_backend is None:
            console.print("[red]No supported browser-agent backend is installed.[/red]")
            raise typer.Exit(code=1)
        check_tier(3, "assisted apply", preferred_backend=backend, preferred_browser="chrome")
        try:
            get_chrome_path()
        except FileNotFoundError:
            console.print("[red]Google Chrome was not found. Install Chrome or set CHROME_PATH.[/red]")
            raise typer.Exit(code=1)
        if not app_config.PROFILE_PATH.exists():
            console.print("[red]Profile not found. Run divapply init first.[/red]")
            raise typer.Exit(code=1)
        resolved_model = _resolve_apply_model(resolved_backend, model)

    conn = get_connection()
    reports: list[dict[str, object]] = []
    for record in parsed.entries:
        assert record.url is not None
        item: dict[str, object] = {
            "line": record.line_number,
            "input_url": record.url,
            "status": "started",
        }
        console.print(f"\n[bold]Line {record.line_number}[/bold] {record.url}")
        try:
            ingest = _ingest_manual_url(record.url, emit=False)
            item.update(ingest)
            console.print(f"  Job:      {ingest['title']} @ {ingest['company']}")
            console.print(f"  Location: {ingest['location'] or 'not detected'}")
            console.print(f"  Opens:    {ingest['application_url']}")
            console.print(f"  Source:   {ingest['verification']}")

            if bool(ingest["inactive"]):
                item["status"] = "closed"
                console.print("[yellow]Posting is closed; skipped.[/yellow]")
                reports.append(item)
                continue

            if ingest["verification"] != "official":
                confirmed = yes or typer.confirm(
                    "Use this exact link for assisted, no-submit form filling?",
                    default=False,
                )
                if not confirmed:
                    item["status"] = "source_not_confirmed"
                    reports.append(item)
                    continue
                if not _confirm_manual_url_for_assist(conn, str(ingest["url"])):
                    item["status"] = "source_confirmation_failed"
                    reports.append(item)
                    continue
                item["verification"] = "user_confirmed_direct"

            prepared = _prepare_manual_url(
                conn,
                safe_url=str(ingest["url"]),
                min_score=min_score,
                validation=validation,
                allow_user_confirmed=True,
                raise_on_score_error=False,
            )
            item.update(prepared)
            if prepared["status"] != "prepared":
                reports.append(item)
                continue
            if prepare_only:
                item["status"] = "prepared"
                reports.append(item)
                continue

            assert resolved_backend is not None
            item["status"] = _run_assisted_cli(
                str(ingest["url"]),
                min_score=min_score,
                max_score=None,
                model=resolved_model,
                backend=resolved_backend,
            )
        except Exception as exc:
            item["status"] = "failed"
            item["error"] = _safe_apply_error(str(exc))
            console.print(f"[red]Could not process this link:[/red] {item['error']}")
        reports.append(item)

    for record in parsed.invalid:
        reports.append(
            {
                "line": record.line_number,
                "input_url": record.input_value,
                "status": "invalid_url",
                "error": record.error,
            }
        )
    for record in parsed.duplicates:
        reports.append(
            {
                "line": record.line_number,
                "input_url": record.input_value,
                "status": "duplicate_input",
                "duplicate_of_line": record.duplicate_of_line,
            }
        )

    report_path = app_config.LOG_DIR / (
        f"apply_links_{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')}.json"
    )
    write_private_text(
        report_path,
        json.dumps(
            {
                "source_file": str(links_file),
                "created_at": datetime.now(timezone.utc).isoformat(),
                "prepare_only": prepare_only,
                "min_score": min_score,
                "results": sorted(reports, key=lambda item: int(str(item["line"]))),
            },
            indent=2,
        ),
        strict=True,
    )

    table = Table(title="Link Batch Results", show_header=True, header_style="bold cyan")
    table.add_column("Line", justify="right")
    table.add_column("Job")
    table.add_column("Score", justify="right")
    table.add_column("Result")
    for item in sorted(reports, key=lambda value: int(str(value["line"]))):
        job_label = str(item.get("title") or item.get("input_url") or "")
        if item.get("company"):
            job_label = f"{job_label} @ {item['company']}"
        table.add_row(
            str(item["line"]),
            job_label[:70],
            "" if item.get("score") is None else str(item["score"]),
            str(item["status"]),
        )
    console.print()
    console.print(table)
    console.print(f"[dim]Private report: {report_path}[/dim]")
    if any(item.get("status") in {"failed", "score_failed", "document_generation_failed", "source_confirmation_failed"} for item in reports):
        raise typer.Exit(code=1)


@app.command("add")
def add(
    ctx: typer.Context,
    url: Optional[str] = typer.Argument(None, help="One direct job posting URL."),
    file: Optional[Path] = typer.Option(None, "--file", exists=True, dir_okay=False, readable=True, help="Text file with one job URL per line."),
    min_score: int = typer.Option(7, "--min-score", min=1, max=10, help="Minimum qualification score for documents."),
    save_only: bool = typer.Option(False, "--save-only", help="Save one URL without AI scoring or documents."),
    confirm_source: bool = typer.Option(False, "--confirm-source", help="Confirm these exact direct links for preparation, never unattended submission."),
) -> None:
    """Add a URL (or --file of URLs) and prepare both PDFs."""
    if bool(url) == bool(file):
        raise typer.BadParameter("Provide one URL or --file, not both.")
    if file:
        if save_only:
            raise typer.BadParameter("--save-only accepts one URL; omit it to prepare a file of links.")
        _invoke_root_command(ctx, "apply-links", links_file=file, min_score=min_score, prepare_only=True, yes=confirm_source)
    else:
        _invoke_root_command(ctx, "add-url", job_url=url, prepare=not save_only, min_score=min_score, confirm_source=confirm_source)


@app.command()
def run(
    stages: Optional[list[str]] = typer.Argument(
        None,
        hidden=True,
        help=(f"Advanced: run specific stages ({', '.join(VALID_STAGES)})."),
    ),
    min_score: int = typer.Option(7, "--min-score", min=1, max=10, help="Minimum qualification score for documents."),
    saved: bool = typer.Option(False, "--saved", help="Finish saved jobs without searching for new ones."),
    limit: int = typer.Option(0, "--limit", "-l", min=0, help="Maximum job packets to process; 0 finishes all pending jobs."),
    refresh: bool = typer.Option(False, "--refresh", help="Reread and regrade saved jobs, preserving existing documents."),
    prune_score: int = typer.Option(
        0, "--prune-score", min=0, max=10, hidden=True, help="Legacy stage mode: delete low scores (0 = off)."
    ),
    workers: int = typer.Option(1, "--workers", "-w", min=1, max=16, help="Search workers. Job packets are saved one at a time."),
    stream: bool = typer.Option(False, "--stream", hidden=True, help="Advanced stage mode: run stages concurrently."),
    dry_run: bool = typer.Option(False, "--dry-run", help="Preview stages without executing."),
    yes: bool = typer.Option(False, "--yes", "-y", hidden=True, help="Confirm destructive pruning when --prune-score is used."),
    validation: str = typer.Option(
        "normal",
        "--validation",
        hidden=True,
        help=(
            "Validation strictness for tailor/cover stages. "
            "strict: banned words = errors, judge must pass. "
            "normal: banned words = warnings only (default). "
            "lenient: banned words ignored, LLM judge skipped. "
            "none: skip all validation entirely, accept whatever the LLM returns."
        ),
    ),
) -> None:
    """Find jobs, check qualifications, and finish resume/cover-letter PDFs. Never submit."""
    _bootstrap()

    from divapply.pipeline import run_pipeline, run_preparation

    stage_list = stages if stages else ["all"]

    # Validate stage names
    for s in stage_list:
        if s != "all" and s not in VALID_STAGES:
            console.print(f"[red]Unknown stage:[/red] '{s}'. Valid stages: {', '.join(VALID_STAGES)}, all")
            raise typer.Exit(code=1)

    # Gate AI stages behind Tier 2
    llm_stages = {"score", "tailor", "cover"}
    if not dry_run and (any(s in stage_list for s in llm_stages) or "all" in stage_list):
        from divapply.config import check_tier

        check_tier(2, "AI scoring/tailoring")

    # Validate the --validation flag value
    valid_modes = ("strict", "normal", "lenient", "none")
    if validation not in valid_modes:
        console.print(f"[red]Invalid --validation value:[/red] '{validation}'. Choose from: {', '.join(valid_modes)}")
        raise typer.Exit(code=1)

    advanced = bool(stages and stage_list != ["all"]) or stream or prune_score > 0
    if advanced and (saved or limit or refresh):
        raise typer.BadParameter("Use --saved/--limit/--refresh with the normal run, not individual stages, --stream, or --prune-score.")
    if not advanced:
        result = run_preparation(
            saved=saved, limit=limit, min_score=min_score, refresh=refresh,
            workers=workers, validation_mode=validation, dry_run=dry_run,
        )
        if result.get("errors"):
            raise typer.Exit(code=1)
        return

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


@settings_app.command("credentials")
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


@settings_app.command("browser-login")
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
    browser: Optional[str] = typer.Option(
        None, "--browser", help="Apply browser. Defaults to DIVAPPLY_BROWSER, or chromium."
    ),
    continuous: bool = typer.Option(False, "--continuous", "-c", help="Run forever, polling for new jobs."),
    dry_run: bool = typer.Option(False, "--dry-run", help="Preview actions without submitting."),
    assist: bool = typer.Option(
        False,
        "--assist",
        help="Fill one explicit job in visible Chrome, then wait for you to review and submit it.",
    ),
    headless: bool = typer.Option(False, "--headless", help="Run browsers in headless mode."),
    url: Optional[str] = typer.Option(None, "--url", help="Apply to a specific job URL."),
    gen: bool = typer.Option(False, "--gen", help="Generate prompt file for manual debugging instead of running."),
    mark_applied: Optional[str] = typer.Option(None, "--mark-applied", help="Manually mark a job URL as applied."),
    mark_failed: Optional[str] = typer.Option(
        None, "--mark-failed", help="Manually mark a job URL as failed (provide URL)."
    ),
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
    if assist:
        if not url:
            console.print("[red]--assist requires --url with one exact job link.[/red]")
            raise typer.Exit(code=1)
        if dry_run or headless or continuous or workers != 1:
            console.print("[red]--assist cannot be combined with --dry-run, --headless, --continuous, or multiple workers.[/red]")
            raise typer.Exit(code=1)
        if browser is not None and get_apply_browser(browser) != "chrome":
            console.print("[red]--assist uses visible Google Chrome so the browser can remain open for you.[/red]")
            raise typer.Exit(code=1)
        browser = "chrome"

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
        console.print("[red]Profile not found.[/red]\nRun [bold]divapply init[/bold] to create your profile first.")
        raise typer.Exit(code=1)

    # Check 3: Tailored resumes exist (skip for --gen with --url)
    if not (gen and url) and not assist:
        conn = get_connection()
        ready = int(
            conn.execute(
                "SELECT COUNT(*) FROM jobs WHERE tailored_resume_path IS NOT NULL "
                f"AND applied_at IS NULL AND archived_at IS NULL AND {ACTIONABLE_JOB_SQL}"
            ).fetchone()[0]
            or 0
        )
        if ready == 0 and not continuous:
            console.print(
                "[red]No tailored resumes ready.[/red]\n"
                "Run [bold]divapply run score tailor[/bold] first to prepare applications."
            )
            raise typer.Exit(code=1)
        if not url and not continuous:
            eligible, highest = _apply_queue_window(
                conn,
                min_score=min_score,
                max_score=max_score,
            )
            if eligible == 0:
                window = f"--min-score {min_score}"
                if max_score is not None:
                    window += f" --max-score {max_score}"
                console.print(f"[red]No queued jobs match {window}.[/red]")
                if highest is not None:
                    console.print(f"Highest prepared score: {highest}.")
                    console.print(
                        "Choose a reviewed threshold explicitly, for example: "
                        f"[bold]divapply apply --min-score {highest}[/bold]"
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

    if assist:
        assert url is not None
        console.print("\n[bold blue]Launching Assisted Apply[/bold blue]")
        console.print("  Browser:  Google Chrome (visible, isolated DivApply profile)")
        console.print("  Submit:   You review and click the final button")
        console.print(f"  Target:   {url}")
        _run_assisted_cli(
            url,
            min_score=min_score,
            max_score=max_score,
            model=resolved_model,
            backend=resolved_backend,
        )
        return

    from divapply.apply.launcher import main as apply_main
    from divapply.apply.prompt import ApplicationAuthorization, AuthorizationSource

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
    score_window = f">= {min_score}" if max_score is None else f"{min_score} to {max_score}"
    console.print(f"  Score:    {score_window}")
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

    authorization_source: AuthorizationSource = "dry_run_request" if dry_run else "cli_yes"
    if not dry_run and not yes:
        confirmed = typer.confirm("Real auto-apply mode may click final Submit/Apply buttons. Continue?")
        if not confirmed:
            console.print("[dim]Cancelled. Use --dry-run to test safely or --yes to confirm real submissions.[/dim]")
            return
        authorization_source = "interactive_confirmation"

    authorization = ApplicationAuthorization(
        profile_fields=True,
        final_submit=not dry_run,
        source=authorization_source,
    )

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
        authorization=authorization,
    )


@app.command()
def status(
    details: bool = typer.Option(False, "--details", help="Show the document status and saved error for every job."),
    min_score: int = typer.Option(7, "--min-score", min=1, max=10, help="Document qualification threshold."),
) -> None:
    """Show actual packet readiness and explain missing documents (no AI calls)."""
    audit_command(min_score=min_score, details=details)


@jobs_app.command("stats")
def statistics() -> None:
    """Show detailed database, search, and application counts."""
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


@jobs_app.command("export")
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


@jobs_app.command("track")
def track(
    event: str = typer.Argument(
        ..., help="Lifecycle event: applied, screening, interview, offer, rejection, withdrawn."
    ),
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


@jobs_app.command("followups")
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


@jobs_app.command("analytics")
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


@jobs_app.command("explain")
def explain(
    job_url: str = typer.Argument(..., help="Job URL or URL fragment to explain."),
) -> None:
    """Explain qualification scoring and diagnostics without printing resume/profile text."""
    _bootstrap()

    from divapply.database import get_connection

    like = f"%{job_url.strip().rstrip('/')}%"
    conn = get_connection()
    row = conn.execute(
        """
        SELECT title, company, site, url, fit_score, llm_score, keyword_score,
               embedding_score, composite_score, score_breakdown, score_reasoning,
               matched_skills, missing_skills, keyword_hits, risk_flags,
               apply_or_skip_reason, eligibility_status, scoring_version, requirements_error,
               scoring_source_url, detail_source_url, detail_scraped_at, requirements_sources,
               requirements_assessment, detail_error
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

    from divapply.scoring.requirements import SCORING_VERSION
    if row["fit_score"] is None or row["scoring_version"] != SCORING_VERSION:
        console.print("[yellow]No current qualification audit. Prior diagnostics are not an eligibility recommendation.[/yellow]")
    table = Table(title="Score Explain", show_header=True, header_style="bold cyan")
    table.add_column("Field", style="bold")
    table.add_column("Value")
    for key in (
        "title",
        "company",
        "site",
        "fit_score",
        "eligibility_status",
        "scoring_source_url",
        "detail_source_url",
        "detail_scraped_at",
        "detail_error",
        "requirements_error",
        "llm_score",
        "keyword_score",
        "embedding_score",
        "composite_score",
        "matched_skills",
        "missing_skills",
        "keyword_hits",
        "risk_flags",
        "apply_or_skip_reason",
        "score_reasoning",
    ):
        table.add_row(key, str(row[key] if row[key] is not None else "legacy/missing"))
    console.print()
    console.print(table)
    for source in json.loads(row["requirements_sources"] or "[]"):
        console.print(f"Linked document ({source['status']}): {source['url']}", markup=False)
    if row["requirements_assessment"] and row["scoring_version"] == SCORING_VERSION:
        audit = Table(title="Requirement evidence", show_lines=True)
        for column in ("Kind / result", "Requirement", "Posting evidence", "Comparison"):
            audit.add_column(column)
        for item in json.loads(row["requirements_assessment"]):
            audit.add_row(f"{item['kind']} / {item['status']}", item['requirement'], item['quote'], item['reason'])
        console.print(audit)

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


@app.command(hidden=True)
def rescore(
    limit: int = typer.Option(0, "--limit", "-l", min=0, help="Max rows to rescore; 0 = all."),
) -> None:
    """Re-read employer pages and linked requirements, then reaudit saved jobs."""
    _bootstrap()

    from divapply.scoring.scorer import run_scoring
    from divapply.config import check_tier

    check_tier(2, "AI qualification scoring")
    result = run_scoring(limit=limit, rescore=True)
    console.print(f"[green]Rescored {result['scored']} job(s).[/green] Errors: {result['errors']}")
    if result["errors"]:
        raise typer.Exit(code=1)


@app.command()
def dashboard(
    static: bool = typer.Option(
        False, "--static", help="Write a static HTML file instead of starting the interactive dashboard."
    ),
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


@system_app.command("check")
def doctor() -> None:
    """Check setup, database integrity, and search config offline (no AI or browser calls)."""
    import sys
    from divapply.config import (
        load_env,
        ensure_dirs,
        PROFILE_PATH,
        RESUME_PATH,
        RESUME_PDF_PATH,
        SEARCH_CONFIG_PATH,
        TAILORED_DIR,
        COVER_LETTER_DIR,
        get_chrome_path,
        get_apply_browser,
        get_apply_browser_label,
        load_search_config,
        validate_search_config,
    )
    from divapply.database import get_active_db_path, get_coursework_summary, init_db

    load_env()
    ensure_dirs()
    conn = init_db()

    ok_mark = "[green]OK[/green]"
    fail_mark = "[red]MISSING[/red]"
    warn_mark = "[yellow]WARN[/yellow]"

    results: list[tuple[str, str, str]] = []  # (check, status, note)
    failures: list[str] = []
    for module in ("typer", "rich", "yaml", "playwright"):
        try:
            __import__(module)
        except Exception as exc:
            failures.append(f"import {module}")
            results.append((f"import {module}", fail_mark, redact_error_snippet(str(exc))))
    if conn is not None:
        integrity = conn.execute("PRAGMA quick_check").fetchone()[0]
        foreign_keys = conn.execute("PRAGMA foreign_key_check").fetchall()
        healthy = integrity == "ok" and not foreign_keys
        results.append(("database integrity", ok_mark if healthy else fail_mark, "ok" if healthy else "Integrity check failed"))
        if not healthy:
            failures.append("database integrity")
    try:
        search_report = validate_search_config(load_search_config())
        results.append(("search config", ok_mark if search_report["passed"] else fail_mark,
                        "; ".join(search_report["errors"] + search_report["warnings"]) or "valid"))
        if not search_report["passed"]:
            failures.append("search config")
    except Exception as exc:
        failures.append("search config")
        results.append(("search config", fail_mark, redact_error_snippet(str(exc))))

    results.append(("DivApply version", ok_mark, __version__))
    results.append(("Python executable", ok_mark, sys.executable))
    results.append(("Python version", ok_mark, sys.version.split()[0]))
    if sys.version_info >= (3, 13):
        results.append(
            (
                "JobSpy Python",
                warn_mark,
                "Python 3.12 recommended; Python 3.13/3.14 may fail with python-jobspy/numpy pins",
            )
        )
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
        model = os.environ.get("LLM_MODEL", "gpt-5.6-luna")
        results.append(("LLM API key", ok_mark, f"OpenAI ({model})"))
    elif has_local:
        results.append(("LLM API key", ok_mark, f"Local: {os.environ.get('LLM_URL')}"))
    else:
        results.append(("LLM API key", fail_mark, "Set GEMINI_API_KEY in ~/.divapply/.env (run 'divapply init')"))

    # --- Tier 3 checks ---
    from divapply.config import get_apply_backend, get_apply_backend_label, get_available_apply_backends

    detected_backends = get_available_apply_backends()
    selected_backend = get_apply_backend()
    if detected_backends:
        note = ", ".join(f"{get_apply_backend_label(name)}: {path}" for name, path in detected_backends.items())
        results.append(("Apply agent CLI", ok_mark, note))
    else:
        results.append(("Apply agent CLI", fail_mark, "Install Codex or Claude Code (needed for auto-apply)"))

    # Browser runtime
    selected_browser = get_apply_browser()
    if selected_browser == "chrome":
        try:
            chrome_path = get_chrome_path()
            results.append(("Browser", ok_mark, chrome_path))
        except FileNotFoundError:
            results.append(("Browser", fail_mark, "Install Chrome or set CHROME_PATH env var (needed for Chrome mode)"))
    else:
        results.append(("Browser", ok_mark, f"Playwright channel: {get_apply_browser_label(selected_browser)}"))

    # Node.js + npm provision the integrity-locked MCP runtime.
    from divapply.mcp_runtime import compatible_node_executable, compatible_npm_executable

    node_bin = compatible_node_executable()
    npm_bin = compatible_npm_executable()
    if node_bin and npm_bin:
        results.append(("Node.js / npm", ok_mark, f"{node_bin}; {npm_bin}"))
    else:
        results.append(
            ("Node.js / npm", fail_mark, "Install Node.js 20+ from nodejs.org (needed for locked auto-apply runtime)")
        )

    # --- Render results ---
    console.print()
    console.print("[bold]DivApply System Check[/bold]\n")

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
        console.print(
            "[dim]  -> Tier 3 unlocks: auto-apply (needs an apply backend CLI + Node.js + browser runtime)[/dim]"
        )
    elif tier == 2:
        console.print(
            "[dim]  -> Tier 3 unlocks: auto-apply (needs an apply backend CLI + Node.js + browser runtime)[/dim]"
        )

    console.print("[dim]Offline only: no job boards, LLMs, browsers, or apply agents called.[/dim]")
    if failures:
        raise typer.Exit(code=1)


@jobs_app.command("prune")
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


@app.command(hidden=True)
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


# Legacy spellings reuse the implementations above without duplicating workflows.
for _alias, _command in {
    "init": init, "edit": edit, "migrate": migrate, "backup": backup,
    "cleanup": cleanup, "import-coursework": import_coursework,
    "coursework-summary": coursework_summary, "credentials": credentials_cmd,
    "browser-login": browser_login, "track": track, "followups": followups,
    "analytics": analytics, "explain": explain, "repair": repair_command,
    "doctor": doctor, "selfcheck": doctor, "prune": prune,
}.items():
    app.command(_alias, hidden=True)(_command)


if __name__ == "__main__":
    app()
