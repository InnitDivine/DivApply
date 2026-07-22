"""Apply orchestration: acquire jobs, run apply agents, track results.

This is the main entry point for the apply pipeline. It claims jobs from
SQLite, prepares isolated browser/MCP state, launches Codex or Claude,
parses the agent result contract, and records lifecycle events.
"""

import atexit
import json
import logging
import os
import platform
import queue
import re
import shlex
import shutil
import signal
import sqlite3
import subprocess
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import urlsplit

from rich.console import Console
from rich.live import Live

from divapply import config
from divapply.artifacts import ArtifactCollisionError, ensure_job_artifacts_unshared, job_artifact_stem
from divapply.database import (
    ACTIONABLE_JOB_SQL,
    add_application_event,
    get_connection,
    record_reliability_event,
)
from divapply.apply import prompt as prompt_mod
from divapply.apply.chrome import (
    launch_chrome, cleanup_worker, kill_all_chrome,
    reset_worker_dir, cleanup_on_exit, _kill_process_tree,
    setup_worker_profile,
    BASE_CDP_PORT,
)
from divapply.mcp_runtime import (
    McpRuntime,
    ensure_mcp_runtime,
    expected_mcp_runtime,
)
from divapply.apply.dashboard import (
    init_worker, update_state, add_event, get_state,
    render_full, get_totals,
)
from divapply.security import (
    UnsafeUrlError,
    collect_known_secret_values,
    open_private_text,
    redact_known_secrets,
    redact_url_for_log,
    validate_external_url,
    write_private_text,
)
from divapply.privacy import redact_error_snippet

logger = logging.getLogger(__name__)


def _load_blocked():
    """Load skip rules lazily so config file reads stay outside DB locks."""
    from divapply.config import load_blocked_sites
    return load_blocked_sites()


def inspect_apply_queue(
    conn: sqlite3.Connection,
    *,
    min_score: int,
    max_score: int | None,
) -> tuple[int, int | None]:
    """Read the queue through the same non-mutating gates used by acquisition."""
    blocked_sites, blocked_patterns = _load_blocked()
    params: list[object] = [config.DEFAULTS["max_apply_attempts"]]
    site_clause = ""
    if blocked_sites:
        placeholders = ",".join("?" for _ in blocked_sites)
        site_clause = f"AND (site IS NULL OR site NOT IN ({placeholders}))"
        params.extend(sorted(blocked_sites))
    url_clause = ""
    if blocked_patterns:
        url_clause = " ".join("AND url NOT LIKE ?" for _ in blocked_patterns)
        params.extend(blocked_patterns)

    rows = conn.execute(
        f"""
        SELECT url, title, company, site, application_url,
               tailored_resume_path, cover_letter_path, fit_score
        FROM jobs
        WHERE tailored_resume_path IS NOT NULL
          AND {ACTIONABLE_JOB_SQL}
          AND archived_at IS NULL
          AND (apply_status IS NULL OR apply_status = 'failed')
          AND (apply_attempts IS NULL OR apply_attempts < ?)
          AND fit_score IS NOT NULL
          {site_clause}
          {url_clause}
        """,
        params,
    ).fetchall()

    scores: list[int] = []
    for raw_row in rows:
        job = dict(raw_row)
        apply_url = job.get("application_url") or job["url"]
        try:
            validate_external_url(apply_url, field="apply url")
            ensure_job_artifacts_unshared(job, conn=conn)
        except (UnsafeUrlError, ArtifactCollisionError):
            continue
        if config.is_manual_ats(apply_url):
            continue
        scores.append(int(job["fit_score"]))

    eligible = sum(
        score >= min_score and (max_score is None or score <= max_score)
        for score in scores
    )
    return eligible, max(scores) if scores else None


def _display_company(job: dict) -> str:
    """Return employer name for user-facing logs, falling back to source."""
    return job.get("company") or job.get("site") or ""


def _job_log_stem(job: dict) -> str:
    """Return a compact safe filename stem bound to one job URL."""
    readable, identity = job_artifact_stem(job).rsplit("--", 1)
    return f"{readable[:48]}--{identity[:16]}"


def _safe_agent_error(
    value: object,
    *,
    known_secrets: set[str] | None = None,
    max_length: int = 240,
) -> str:
    """Redact an agent-facing error before UI, logs, or database persistence."""
    secrets = known_secrets if known_secrets is not None else collect_known_secret_values()
    redacted = redact_known_secrets(str(value), secrets)
    return redact_error_snippet(redacted, max_length=max_length)

# Runtime coordination shared by worker threads and Ctrl+C handling.
POLL_INTERVAL = int(config.DEFAULTS["poll_interval"])
MAX_RUNTIME_WORKERS = 4
DEFAULT_APPLY_IDLE_TIMEOUT = 300
_stop_event = threading.Event()
_claude_procs: dict[int, subprocess.Popen] = {}
_claude_lock = threading.Lock()

# Worker browsers must be cleaned up even when the CLI exits mid-apply.
atexit.register(cleanup_on_exit)
if platform.system() != "Windows":
    signal.signal(signal.SIGTERM, lambda *_: sys.exit(0))


# ---------------------------------------------------------------------------
# MCP config
# ---------------------------------------------------------------------------

UNSAFE_PLAYWRIGHT_TOOLS = ("browser_run_code", "browser_run_code_unsafe", "browser_evaluate")
PLAYWRIGHT_AGENT_TOOLS = (
    "browser_click",
    "browser_close",
    "browser_console_messages",
    "browser_drag",
    "browser_file_upload",
    "browser_fill_form",
    "browser_handle_dialog",
    "browser_hover",
    "browser_navigate",
    "browser_navigate_back",
    "browser_network_requests",
    "browser_press_key",
    "browser_resize",
    "browser_select_option",
    "browser_snapshot",
    "browser_tabs",
    "browser_take_screenshot",
    "browser_type",
    "browser_wait_for",
)
def _make_mcp_config(
    cdp_port: int,
    browser: str = "chromium",
    worker_profile_dir: Path | None = None,
    headless: bool = False,
    enable_gmail: bool = False,
    mcp_runtime: McpRuntime | None = None,
    navigation_guard_path: Path | None = None,
) -> dict:
    """Build MCP config dict for a specific browser configuration."""
    if enable_gmail:
        raise ValueError("Gmail MCP is unavailable until an audited maintained replacement exists")
    runtime = mcp_runtime or expected_mcp_runtime()
    playwright_args = [
        str(runtime.playwright_script),
        "--sandbox",
        "--block-service-workers",
    ]
    if navigation_guard_path is not None:
        playwright_args.append(f"--init-page={navigation_guard_path}")
    if browser == "chrome":
        playwright_args.extend([
            f"--cdp-endpoint=http://localhost:{cdp_port}",
            f"--viewport-size={config.DEFAULTS['viewport']}",
        ])
    else:
        playwright_args.extend([
            f"--browser={browser}",
            f"--viewport-size={config.DEFAULTS['viewport']}",
        ])
        if worker_profile_dir is not None:
            playwright_args.append(f"--user-data-dir={worker_profile_dir}")
        if headless:
            playwright_args.append("--headless")

    servers = {
        "playwright": {
            "command": str(runtime.node),
            "args": playwright_args,
        },
    }
    return {"mcpServers": servers}


def _trusted_job_origins(job: dict) -> list[str]:
    """Return validated job/application origins for one isolated browser run."""
    origins: set[str] = set()
    for key in ("url", "application_url"):
        raw_url = job.get(key)
        if not raw_url:
            continue
        try:
            safe_url = validate_external_url(str(raw_url), field=key)
        except UnsafeUrlError:
            continue
        parsed = urlsplit(safe_url)
        origins.add(f"{parsed.scheme.casefold()}://{parsed.netloc.casefold()}")
    if not origins:
        raise UnsafeUrlError("job has no validated browser origin")
    return sorted(origins)


def _write_navigation_guard(path: Path, job: dict) -> Path:
    """Write an owned Playwright route that blocks active cross-origin requests."""
    origins = _trusted_job_origins(job)
    source = f"""// DivApply owned navigation guard. Generated per job; do not edit.
const allowedOrigins = new Set({json.dumps(origins)});
const protectedTypes = new Set(['document', 'xhr', 'fetch', 'websocket', 'eventsource']);

export default async ({{ page }}) => {{
  await page.context().route('**/*', async route => {{
    const request = route.request();
    let parsed;
    try {{ parsed = new URL(request.url()); }} catch {{ await route.abort('blockedbyclient'); return; }}
    if (['data:', 'blob:', 'about:'].includes(parsed.protocol)) {{ await route.continue(); return; }}
    if (protectedTypes.has(request.resourceType()) && !allowedOrigins.has(parsed.origin.toLowerCase())) {{
      await route.abort('blockedbyclient');
      return;
    }}
    if (parsed.protocol !== 'https:' && !allowedOrigins.has(parsed.origin.toLowerCase())) {{
      await route.abort('blockedbyclient');
      return;
    }}
    await route.continue();
  }});
}};
"""
    write_private_text(path, source, strict=True)
    return path


# ---------------------------------------------------------------------------
# Database operations
# ---------------------------------------------------------------------------

def acquire_job(target_url: str | None = None, min_score: int = 7,
                max_score: int | None = None,
                worker_id: int = 0) -> dict | None:
    """Atomically acquire the next job to apply to.

    Args:
        target_url: Apply to a specific URL instead of picking from queue.
        min_score: Minimum fit_score threshold.
        max_score: Optional maximum fit_score threshold.
        worker_id: Worker claiming this job (for tracking).

    Returns:
        Job dict or None if the queue is empty.
    """
    conn = get_connection()
    recover_stale_apply_locks(conn=conn)
    # Load blocked sites BEFORE acquiring the DB lock to avoid file I/O inside transaction
    blocked_sites, blocked_patterns = _load_blocked()
    while True:
        try:
            conn.execute("BEGIN IMMEDIATE")

            if target_url:
                like = f"%{target_url.split('?')[0].rstrip('/')}%"
                row = conn.execute(f"""
                    SELECT url, title, company, site, application_url, tailored_resume_path,
                           fit_score, location, full_description, cover_letter_path,
                           application_mode, source_verification
                    FROM jobs
                    WHERE (url = ? OR application_url = ? OR application_url LIKE ? OR url LIKE ?)
                      AND {ACTIONABLE_JOB_SQL}
                      AND archived_at IS NULL
                      AND tailored_resume_path IS NOT NULL
                      AND (apply_status IS NULL OR apply_status IN ('failed', 'manual'))
                    LIMIT 1
                """, (target_url, target_url, like, like)).fetchone()
            else:
                # Build parameterized filters to avoid SQL injection
                params: list = [min_score]
                max_score_clause = ""
                if max_score is not None:
                    max_score_clause = "AND fit_score <= ?"
                    params.append(max_score)
                site_clause = ""
                if blocked_sites:
                    placeholders = ",".join("?" * len(blocked_sites))
                    site_clause = f"AND (site IS NULL OR site NOT IN ({placeholders}))"
                    params.extend(sorted(blocked_sites))
                url_clauses = ""
                if blocked_patterns:
                    url_clauses = " ".join("AND url NOT LIKE ?" for _ in blocked_patterns)
                    params.extend(blocked_patterns)
                row = conn.execute(f"""
                    SELECT url, title, company, site, application_url, tailored_resume_path,
                           fit_score, location, full_description, cover_letter_path,
                           application_mode, source_verification
                    FROM jobs
                    WHERE tailored_resume_path IS NOT NULL
                      AND {ACTIONABLE_JOB_SQL}
                      AND archived_at IS NULL
                      AND (apply_status IS NULL OR apply_status = 'failed')
                      AND (apply_attempts IS NULL OR apply_attempts < ?)
                      AND fit_score >= ?
                      {max_score_clause}
                      {site_clause}
                      {url_clauses}
                    ORDER BY fit_score DESC, url
                    LIMIT 1
                """, [config.DEFAULTS["max_apply_attempts"]] + params).fetchone()

            if not row:
                conn.rollback()
                return None

            from divapply.config import is_manual_ats
            apply_url = row["application_url"] or row["url"]
            try:
                validate_external_url(apply_url, field="apply url")
            except UnsafeUrlError as exc:
                conn.execute(
                    "UPDATE jobs SET apply_status = 'failed', apply_error = ?, apply_attempts = 99 WHERE url = ?",
                    (_safe_agent_error(f"unsafe apply URL: {exc}"), row["url"]),
                )
                conn.commit()
                logger.warning(
                    "Skipping unsafe apply URL for %s: %s",
                    redact_url_for_log(row["url"])[:80],
                    _safe_agent_error(exc),
                )
                if target_url:
                    return None
                continue
            if is_manual_ats(apply_url):
                conn.execute(
                    "UPDATE jobs SET apply_status = 'manual', apply_error = 'manual ATS' WHERE url = ?",
                    (row["url"],),
                )
                conn.commit()
                logger.info("Skipping manual ATS: %s", row["url"][:80])
                if target_url:
                    return None
                continue

            try:
                ensure_job_artifacts_unshared(dict(row), conn=conn)
            except ArtifactCollisionError as exc:
                conn.execute(
                    "UPDATE jobs SET apply_status = 'failed', apply_error = ?, apply_attempts = 99 WHERE url = ?",
                    (_safe_agent_error(exc), row["url"]),
                )
                conn.commit()
                logger.error("Refusing shared application artifacts for %s", row["url"][:80])
                if target_url:
                    return None
                continue

            now = datetime.now(timezone.utc).isoformat()
            conn.execute("""
                UPDATE jobs SET apply_status = 'in_progress',
                               agent_id = ?,
                               last_attempted_at = ?
                WHERE url = ?
            """, (f"worker-{worker_id}", now, row["url"]))
            conn.commit()

            return dict(row)
        except Exception:
            conn.rollback()
            raise


def recover_stale_apply_locks(
    *,
    conn=None,
    timeout_seconds: int | None = None,
) -> int:
    """Recover jobs abandoned in in_progress after worker/process crashes."""
    if conn is None:
        conn = get_connection()
    timeout = timeout_seconds or int(config.DEFAULTS.get("apply_lock_timeout", 3600))
    cutoff = (datetime.now(timezone.utc) - timedelta(seconds=timeout)).isoformat()
    cursor = conn.execute(
        """
        UPDATE jobs
        SET apply_status = 'failed',
            apply_error = 'stale in_progress lock recovered',
            apply_attempts = COALESCE(apply_attempts, 0) + 1,
            agent_id = NULL
        WHERE apply_status = 'in_progress'
          AND (last_attempted_at IS NULL OR last_attempted_at < ?)
        """,
        (cutoff,),
    )
    conn.commit()
    recovered = cursor.rowcount
    if recovered:
        logger.warning("Recovered %d stale apply lock(s)", recovered)
    return recovered


def mark_result(url: str, status: str, error: str | None = None,
                permanent: bool = False, duration_ms: int | None = None,
                task_id: str | None = None) -> None:
    """Update a job's apply status in the database."""
    conn = get_connection()
    now = datetime.now(timezone.utc).isoformat()
    safe_error = _safe_agent_error(error or "unknown")
    try:
        conn.execute("BEGIN IMMEDIATE")
        if status == "applied":
            conn.execute("""
                UPDATE jobs SET apply_status = 'applied', applied_at = ?,
                               apply_error = NULL, agent_id = NULL,
                               apply_duration_ms = ?, apply_task_id = ?
                WHERE url = ?
            """, (now, duration_ms, task_id, url))
            add_application_event(url, "applied", notes="Auto-apply submitted", ts=now, conn=conn)
        else:
            if permanent:
                conn.execute("""
                    UPDATE jobs SET apply_status = ?, apply_error = ?,
                                   applied_at = NULL,
                                   apply_attempts = 99, agent_id = NULL,
                                   apply_duration_ms = ?, apply_task_id = ?
                    WHERE url = ?
                """, (status, safe_error, duration_ms, task_id, url))
            else:
                conn.execute("""
                    UPDATE jobs SET apply_status = ?, apply_error = ?,
                                   apply_attempts = COALESCE(apply_attempts, 0) + 1,
                                   applied_at = NULL, agent_id = NULL,
                                   apply_duration_ms = ?, apply_task_id = ?
                    WHERE url = ?
                """, (status, safe_error, duration_ms, task_id, url))
            add_application_event(url, status, notes=safe_error, ts=now, conn=conn)
        conn.commit()
    except Exception:
        logger.error("Failed to atomically record apply result for %s", redact_url_for_log(url)[:80])
        conn.rollback()
        raise


def mark_dry_run(
    url: str,
    duration_ms: int | None = None,
    task_id: str | None = None,
    result: str | None = None,
) -> None:
    """Record a completed dry run without marking the application submitted."""
    conn = get_connection()
    now = datetime.now(timezone.utc).isoformat()
    result_note = (
        f"Dry run result: {_safe_agent_error(result)}"
        if result
        else "Dry run completed; no application submitted"
    )
    try:
        conn.execute("BEGIN IMMEDIATE")
        conn.execute(
            """
            UPDATE jobs SET apply_status = NULL,
                           apply_error = ?,
                           agent_id = NULL,
                           apply_duration_ms = ?,
                           apply_task_id = ?
            WHERE url = ?
            """,
            (result_note, duration_ms, task_id, url),
        )
        add_application_event(url, "dry_run", notes=result_note, ts=now, conn=conn)
        conn.commit()
    except Exception:
        conn.rollback()
        raise


def release_lock(url: str) -> None:
    """Release the in_progress lock without changing status."""
    conn = get_connection()
    conn.execute(
        "UPDATE jobs SET apply_status = NULL, agent_id = NULL WHERE url = ? AND apply_status = 'in_progress'",
        (url,),
    )
    conn.commit()


# ---------------------------------------------------------------------------
# Utility modes (--gen, --mark-applied, --mark-failed, --reset-failed)
# ---------------------------------------------------------------------------

def mark_job(url: str, status: str, reason: str | None = None) -> None:
    """Manually mark a job's apply status in the database.

    Args:
        url: Job URL to mark.
        status: Either 'applied' or 'failed'.
        reason: Failure reason (only for status='failed').
    """
    conn = get_connection()
    now = datetime.now(timezone.utc).isoformat()
    safe_reason = _safe_agent_error(reason or "manual")
    try:
        conn.execute("BEGIN IMMEDIATE")
        if status == "applied":
            conn.execute("""
                UPDATE jobs SET apply_status = 'applied', applied_at = ?,
                               apply_error = NULL, agent_id = NULL
                WHERE url = ?
            """, (now, url))
            add_application_event(url, "applied", notes="Manually marked applied", ts=now, conn=conn)
        else:
            conn.execute("""
                UPDATE jobs SET apply_status = 'failed', apply_error = ?,
                               apply_attempts = 99, agent_id = NULL
                WHERE url = ?
            """, (safe_reason, url))
            add_application_event(url, "failed", notes=safe_reason, ts=now, conn=conn)
        conn.commit()
    except Exception:
        logger.error("Failed to atomically mark job %s as %s", redact_url_for_log(url)[:80], status)
        conn.rollback()
        raise


def reset_failed() -> int:
    """Reset all failed jobs so they can be retried.

    Returns:
        Number of jobs reset.
    """
    conn = get_connection()
    cursor = conn.execute("""
        UPDATE jobs SET apply_status = NULL, apply_error = NULL,
                       apply_attempts = 0, agent_id = NULL
        WHERE apply_status = 'failed'
    """)
    conn.commit()
    return cursor.rowcount


# ---------------------------------------------------------------------------
# Permanent failure classification
# ---------------------------------------------------------------------------

PERMANENT_FAILURES: set[str] = {
    "expired", "captcha", "login_issue",
    "not_eligible_location", "not_eligible_salary",
    "not_eligible_work_auth",
    "already_applied", "account_required",
    "not_a_job_application", "unsafe_permissions",
    "unsafe_verification", "sso_required",
    "site_blocked", "cloudflare_blocked", "blocked_by_cloudflare",
    "scam", "bank_details", "payment_required", "biometric_verification",
    "email_required",
}

PERMANENT_PREFIXES: tuple[str, ...] = (
    "site_blocked", "cloudflare", "blocked_by", "captcha", "expired", "login_issue",
)


def _normalize_result_reason(text: str) -> str:
    """Normalize compact RESULT reasons for retry/permanent decisions."""
    reason = _clean_result_reason(text)
    reason = re.sub(r"^[\s:.-]+|[\s:.,;!-]+$", "", reason)
    return reason.strip().lower().replace(" ", "_")


def _is_permanent_failure(result: str) -> bool:
    """Determine if a failure should never be retried."""
    reason = _normalize_result_reason(result.split(":", 1)[-1] if ":" in result else result)
    result_lower = result.lower()
    return (
        result_lower in PERMANENT_FAILURES
        or reason in PERMANENT_FAILURES
        or any(reason.startswith(p) for p in PERMANENT_PREFIXES)
        or "ssn" in reason
        or "social_security" in reason
        or re.search(r"\bsin\b", result_lower) is not None
        or "bank_account" in reason
        or "routing_number" in reason
        or "payment" in reason
        or "biometric" in reason
        or "unsafe_verification" in reason
    )


def _clean_result_reason(text: str, known_secrets: set[str] | None = None) -> str:
    cleaned = re.sub(r'[*`"]+$', "", text).strip()
    return _safe_agent_error(cleaned, known_secrets=known_secrets)


def _promoted_failure_status(reason: str) -> str | None:
    normalized = _normalize_result_reason(reason)
    for status in ("captcha", "expired", "login_issue"):
        if normalized == status or normalized.startswith(f"{status}_"):
            return status
    return None


APPLIED_CONFIRMATION_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(r"\bthank you\b", re.IGNORECASE),
    re.compile(r"\bapplication (?:has been )?(?:submitted|received|sent)\b", re.IGNORECASE),
    re.compile(r"\bsubmitted successfully\b", re.IGNORECASE),
    re.compile(r"\bconfirmation (?:number|email|message|page)\b", re.IGNORECASE),
    re.compile(r"\breference (?:number|id)\b", re.IGNORECASE),
    re.compile(r"\bemail (?:application|resume) sent\b", re.IGNORECASE),
    re.compile(r"\bconfirmation:\s*\S+", re.IGNORECASE),
)

NEGATED_CONFIRMATION_RE = re.compile(
    r"\b(?:no|not|without|missing|could not|cannot|can't|unable to)\s+"
    r"(?:\w+\s+){0,3}(?:confirm|confirmation|submitted|submission|received)\b",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class SubmissionProof:
    """Origin-bound evidence asserted by the browser agent after submission."""

    origin: str
    evidence: str


class SubmissionProofError(ValueError):
    """Raised when an APPLIED result lacks the exact origin-bound proof block."""

    def __init__(self, reason: str) -> None:
        self.reason = reason
        super().__init__(reason)


def _normalized_http_origin(value: object) -> str | None:
    try:
        parsed = urlsplit(str(value or "").strip())
        if parsed.scheme not in {"http", "https"} or not parsed.hostname:
            return None
        if parsed.username is not None or parsed.password is not None:
            return None
        host = parsed.hostname.rstrip(".").casefold().encode("idna").decode("ascii")
        port = parsed.port
    except (UnicodeError, ValueError):
        return None
    if ":" in host:
        host = f"[{host}]"
    if port is None or (parsed.scheme == "http" and port == 80) or (parsed.scheme == "https" and port == 443):
        return f"{parsed.scheme}://{host}"
    return f"{parsed.scheme}://{host}:{port}"


def parse_submission_proof(output: str, job: dict) -> SubmissionProof:
    """Parse an exact final proof block and bind its origin to the supplied job."""
    lines = [line.strip() for line in _agent_output_region(output).splitlines() if line.strip()]
    if len(lines) < 3 or lines[-1] != "RESULT:APPLIED":
        raise SubmissionProofError("missing_submission_proof")
    origin_match = re.fullmatch(r"SUBMISSION_ORIGIN:(https?://\S+)", lines[-3])
    confirmation_match = re.fullmatch(r"CONFIRMATION:(.+)", lines[-2])
    if origin_match is None or confirmation_match is None:
        raise SubmissionProofError("missing_submission_proof")

    evidence = confirmation_match.group(1).strip()
    if (
        not evidence
        or NEGATED_CONFIRMATION_RE.search(evidence)
        or not any(pattern.search(evidence) for pattern in APPLIED_CONFIRMATION_PATTERNS)
    ):
        raise SubmissionProofError("missing_submission_proof")

    claimed_url = urlsplit(origin_match.group(1))
    if claimed_url.path not in {"", "/"} or claimed_url.query or claimed_url.fragment:
        raise SubmissionProofError("submission_origin_mismatch")
    claimed_origin = _normalized_http_origin(origin_match.group(1))
    allowed_origins = {
        origin
        for key in ("url", "application_url")
        if (origin := _normalized_http_origin(job.get(key))) is not None
    }
    if claimed_origin is None or claimed_origin not in allowed_origins:
        raise SubmissionProofError("submission_origin_mismatch")
    return SubmissionProof(origin=claimed_origin, evidence=evidence)


RESULT_LINE_RE = re.compile(
    r"^\s*RESULT:\s*(APPLIED|EXPIRED|CAPTCHA|LOGIN_ISSUE|FAILED(?:\s*:\s*[^\r\n]+)?)\s*$",
    re.IGNORECASE,
)


def _agent_output_region(output: str) -> str:
    """Drop echoed prompt/config text before parsing the final agent result."""
    lines = output.splitlines()
    marker_idx = -1
    for idx, line in enumerate(lines):
        if line.strip().lower() in {"codex", "claude"}:
            marker_idx = idx
    if marker_idx >= 0:
        return "\n".join(lines[marker_idx + 1:])
    return output


def _last_explicit_result(output: str) -> str | None:
    """Return the last standalone RESULT line from agent output."""
    region = _agent_output_region(output)
    result: str | None = None
    for line in region.splitlines():
        match = RESULT_LINE_RE.match(line)
        if match:
            result = re.sub(r"\s*:\s*", ":", match.group(1).strip())
    return result


def _agent_setup_failure(output: str) -> str | None:
    """Return a normalized setup failure when the backend exits before acting."""
    output_lower = output.lower()
    if "out of credits" in output_lower or "add credits to continue" in output_lower:
        return "agent_out_of_credits"
    if "invalid_request_error" in output_lower and "model" in output_lower and "not supported" in output_lower:
        return "agent_model_unsupported"
    return None


def _is_agent_infrastructure_failure(result: str) -> bool:
    return result in {
        "failed:agent_exit_error",
        "failed:agent_startup_error",
        "failed:agent_model_unsupported",
        "failed:agent_out_of_credits",
        "failed:browser_navigation_blocked",
    }


# ---------------------------------------------------------------------------
# Agent result parsing
# ---------------------------------------------------------------------------

def _extract_result(
    output: str,
    worker_id: int,
    job: dict,
    duration_ms: int,
    known_secrets: set[str] | None = None,
) -> tuple[str, int]:
    """Translate backend output into one normalized application status."""
    elapsed = max(1, duration_ms // 1000)

    setup_failure = _agent_setup_failure(output)
    if setup_failure:
        add_event(f"[W{worker_id}] FAILED ({elapsed}s): {setup_failure}")
        update_state(worker_id, status="failed", last_action=f"FAILED: {setup_failure}")
        return f"failed:{setup_failure}", duration_ms

    # Preferred path: the agent follows the prompt contract and emits RESULT:*.
    explicit_result = _last_explicit_result(output)
    if explicit_result:
        if explicit_result.upper().startswith("FAILED"):
            parts = explicit_result.split(":", 1)
            raw_reason = parts[1].strip() if len(parts) > 1 and parts[1].strip() else "unknown"
            reason = _clean_result_reason(raw_reason, known_secrets)
            promoted = _promoted_failure_status(reason)
            if promoted:
                add_event(f"[W{worker_id}] {promoted.upper()} ({elapsed}s): {job['title'][:30]}")
                update_state(worker_id, status=promoted, last_action=f"{promoted.upper()} ({elapsed}s)")
                return promoted, duration_ms
            add_event(f"[W{worker_id}] FAILED ({elapsed}s): {reason[:30]}")
            update_state(worker_id, status="failed", last_action=f"FAILED: {reason[:25]}")
            return f"failed:{reason}", duration_ms

        result_status = explicit_result.upper()
        if result_status == "APPLIED":
            try:
                parse_submission_proof(output, job)
            except SubmissionProofError as exc:
                reason = exc.reason
                add_event(f"[W{worker_id}] FAILED ({elapsed}s): {reason}")
                update_state(worker_id, status="failed", last_action=f"FAILED: {reason}")
                return f"failed:{reason}", duration_ms
        if result_status in {"APPLIED", "EXPIRED", "CAPTCHA", "LOGIN_ISSUE"}:
            add_event(f"[W{worker_id}] {result_status} ({elapsed}s): {job['title'][:30]}")
            update_state(worker_id, status=result_status.lower(),
                         last_action=f"{result_status} ({elapsed}s)")
            return result_status.lower(), duration_ms

    agent_region = _agent_output_region(output)
    if "result:failed" in agent_region.lower():
        # Preserve structured failure reasons so retry logic can distinguish
        # transient failures from permanent blocks such as CAPTCHA or login.
        for out_line in agent_region.splitlines():
            if "result:failed" not in out_line.lower():
                continue
            parts = re.split(r"RESULT:FAILED:", out_line, maxsplit=1, flags=re.IGNORECASE)
            raw_reason = parts[1].strip() if len(parts) > 1 and parts[1].strip() else "unknown"
            reason = _clean_result_reason(raw_reason, known_secrets)
            promoted = _promoted_failure_status(reason)
            if promoted:
                add_event(f"[W{worker_id}] {promoted.upper()} ({elapsed}s): {job['title'][:30]}")
                update_state(worker_id, status=promoted, last_action=f"{promoted.upper()} ({elapsed}s)")
                return promoted, duration_ms
            add_event(f"[W{worker_id}] FAILED ({elapsed}s): {reason[:30]}")
            update_state(worker_id, status="failed", last_action=f"FAILED: {reason[:25]}")
            return f"failed:{reason}", duration_ms
        return "failed:unknown", duration_ms

    add_event(f"[W{worker_id}] NO RESULT ({elapsed}s)")
    update_state(worker_id, status="failed", last_action=f"no result ({elapsed}s)")
    return "failed:no_result_line", duration_ms


# ---------------------------------------------------------------------------
# Backend command construction
# ---------------------------------------------------------------------------

_COMMON_AGENT_ENV = (
    "PATH",
    "PATHEXT",
    "SYSTEMROOT",
    "WINDIR",
    "COMSPEC",
    "TEMP",
    "TMP",
    "TMPDIR",
    "HOME",
    "USERPROFILE",
    "APPDATA",
    "LOCALAPPDATA",
    "PROGRAMDATA",
    "PROGRAMFILES",
    "PROGRAMFILES(X86)",
    "LANG",
    "LC_ALL",
    "LC_CTYPE",
    "TERM",
    "NO_COLOR",
    "SSL_CERT_FILE",
    "SSL_CERT_DIR",
    "REQUESTS_CA_BUNDLE",
    "CURL_CA_BUNDLE",
    "NODE_EXTRA_CA_CERTS",
)
_BACKEND_AGENT_ENV = {
    "codex": (
        "OPENAI_API_KEY",
        "OPENAI_BASE_URL",
        "OPENAI_ORGANIZATION",
        "OPENAI_PROJECT",
        "CODEX_API_KEY",
        "CODEX_HOME",
    ),
    "claude": (
        "ANTHROPIC_API_KEY",
        "ANTHROPIC_AUTH_TOKEN",
        "ANTHROPIC_BASE_URL",
        "CLAUDE_CODE_OAUTH_TOKEN",
        "CLAUDE_CONFIG_DIR",
    ),
}


def _agent_environment(backend: str) -> dict[str, str]:
    """Return the minimum environment needed by the selected agent runtime."""
    normalized = backend.strip().lower()
    if normalized not in _BACKEND_AGENT_ENV:
        raise ValueError(f"Unsupported apply backend: {backend}")
    names = (*_COMMON_AGENT_ENV, *_BACKEND_AGENT_ENV[normalized])
    return {name: os.environ[name] for name in names if os.environ.get(name)}


def _validated_mcp_servers(mcp_config_path: Path) -> dict[str, dict]:
    """Load only the exact MCP server commands DivApply owns and audits."""
    expected_runtime = expected_mcp_runtime()
    try:
        raw_config = json.loads(mcp_config_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(f"Invalid MCP config: {mcp_config_path}") from exc

    if not isinstance(raw_config, dict) or set(raw_config) != {"mcpServers"}:
        raise ValueError("MCP config must contain only mcpServers")
    servers = raw_config["mcpServers"]
    if not isinstance(servers, dict):
        raise ValueError("MCP config requires an mcpServers object")

    unsupported = set(servers) - {"playwright"}
    if unsupported:
        raise ValueError(f"Unsupported MCP server: {sorted(unsupported)[0]}")
    if "playwright" not in servers:
        raise ValueError("MCP config requires the Playwright server")

    for name, server in servers.items():
        if not isinstance(server, dict) or set(server) != {"command", "args"}:
            raise ValueError(f"Invalid MCP server config: {name}")
        if server["command"] != str(expected_runtime.node) or not isinstance(server["args"], list):
            raise ValueError(f"Invalid MCP server command: {name}")
        args = server["args"]
        if not all(isinstance(arg, str) for arg in args):
            raise ValueError(f"Invalid MCP server arguments: {name}")

        if not args or args[0] != str(expected_runtime.playwright_script):
            raise ValueError("Playwright MCP must use the audited locked runtime entry point")
        if "--sandbox" not in args or "--block-service-workers" not in args:
            raise ValueError("Playwright MCP sandbox controls are required")
        forbidden_flags = (
            "--allow-unrestricted-file-access",
            "--no-sandbox",
            "--init-script",
            "--secrets",
            "--extension",
            "--caps",
        )
        if any(arg == flag or arg.startswith(f"{flag}=") for flag in forbidden_flags for arg in args):
            raise ValueError("Playwright MCP config contains a forbidden capability")
        init_page_args = [arg for arg in args if arg.startswith("--init-page=")]
        if init_page_args:
            if len(init_page_args) != 1:
                raise ValueError("Playwright MCP requires exactly one navigation guard")
            guard_path = Path(init_page_args[0].split("=", 1)[1]).resolve()
            config_parent = mcp_config_path.resolve().parent
            if guard_path.parent != config_parent or guard_path.name != "navigation_guard.ts":
                raise ValueError("Playwright navigation guard must be owned by the worker")
            if not guard_path.is_file():
                raise ValueError("Playwright navigation guard is missing")

    return servers


def _compact_json(value: object) -> str:
    return json.dumps(value, separators=(",", ":"))

def _build_agent_command(
    backend: str,
    model: str,
    mcp_config_path: Path,
    prompt_file: Path,
) -> list[str]:
    """Build the selected CLI command without invoking a shell."""
    backend = backend.strip().lower()
    servers = _validated_mcp_servers(mcp_config_path)
    allowed_tools = [f"mcp__playwright__{name}" for name in PLAYWRIGHT_AGENT_TOOLS]

    if backend == "claude":
        claude_executable = config.get_apply_backend_executable("claude") or "claude"
        return [
            claude_executable,
            "--model", model,
            "-p",
            "--max-turns", "150",
            "--mcp-config", str(mcp_config_path),
            "--strict-mcp-config",
            "--permission-mode", "dontAsk",
            "--tools", "",
            "--allowedTools", ",".join(allowed_tools),
            "--no-session-persistence",
            "--disallowedTools", ",".join(
                f"mcp__playwright__{tool}" for tool in UNSAFE_PLAYWRIGHT_TOOLS
            ),
            "--output-format", "stream-json",
            "--verbose", "-",
        ]

    if backend != "codex":
        raise ValueError(f"Unsupported apply backend: {backend}")

    # Codex receives MCP server settings through config overrides. Playwright
    # navigation and form actions advertise side effects, so a non-interactive
    # `never` policy rejects them without a reviewer. Keep the agent read-only
    # and route only approval-required calls through Codex auto-review.
    codex_executable = config.get_apply_backend_executable("codex") or "codex"
    codex_args = [
        codex_executable,
        "exec",
        "--model",
        model,
        "--sandbox",
        "read-only",
        "-c",
        'approval_policy="on-request"',
        "-c",
        'approvals_reviewer="auto_review"',
        "--disable",
        "shell_tool",
        "--disable",
        "unified_exec",
        "--disable",
        "remote_plugin",
        "--disable",
        "skill_mcp_dependency_install",
        "--skip-git-repo-check",
        "--ignore-user-config",
        "--ignore-rules",
        "--ephemeral",
        "--color",
        "never",
        "-c",
        'web_search="disabled"',
        "-c",
        'shell_environment_policy.inherit="none"',
        "-c",
        'history.persistence="none"',
        "-c",
        "tools.view_image=false",
    ]

    if (
        os.environ.get("DIVAPPLY_CODEX_OSS", "").strip().lower() in {"1", "true", "yes", "on"}
        or ":" in model
    ):
        codex_args.append("--oss")

    for server_name, server_cfg in servers.items():
        prefix = f"mcp_servers.{server_name}"
        codex_args.extend(["-c", f'{prefix}.command={json.dumps(server_cfg["command"])}'])
        codex_args.extend(["-c", f"{prefix}.args={_compact_json(server_cfg['args'])}"])
        codex_args.extend(["-c", f"{prefix}.enabled=true"])
        codex_args.extend(["-c", f"{prefix}.required=true"])
        codex_args.extend([
            "-c",
            f"{prefix}.enabled_tools={_compact_json(list(PLAYWRIGHT_AGENT_TOOLS))}",
            "-c",
            f"{prefix}.disabled_tools={_compact_json(list(UNSAFE_PLAYWRIGHT_TOOLS))}",
        ])

    return codex_args


def _get_apply_idle_timeout(total_timeout: int | None) -> int | None:
    """Return max seconds without agent output before killing the job."""
    raw = os.environ.get("DIVAPPLY_APPLY_IDLE_TIMEOUT") or os.environ.get("APPLYPILOT_APPLY_IDLE_TIMEOUT")
    if raw:
        if raw.strip().lower() in {"0", "none", "off", "false", "no"}:
            return None
        try:
            return max(30, int(raw))
        except ValueError:
            return DEFAULT_APPLY_IDLE_TIMEOUT
    if total_timeout is None:
        return DEFAULT_APPLY_IDLE_TIMEOUT
    return min(DEFAULT_APPLY_IDLE_TIMEOUT, max(30, total_timeout // 3))


def _write_agent_prompt(proc: subprocess.Popen[str], agent_prompt: str) -> str | None:
    """Write prompt; return startup output when child closes stdin early."""
    if proc.stdin is None:
        return "agent stdin unavailable"
    try:
        proc.stdin.write(agent_prompt)
        proc.stdin.close()
        return None
    except (BrokenPipeError, OSError) as exc:
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            return f"agent closed stdin before prompt: {type(exc).__name__}"
        output = proc.stdout.read() if proc.stdout is not None else ""
        return output.strip() or f"agent closed stdin before prompt: {type(exc).__name__}"


# ---------------------------------------------------------------------------
# Manual prompt generation
# ---------------------------------------------------------------------------

def _read_tailored_resume_text(job: dict) -> str:
    """Read the tailored resume text for a claimed job, if present."""
    resume_path = job.get("tailored_resume_path")
    if not resume_path:
        return ""
    path = Path(resume_path)
    txt_path = path.with_suffix(".txt")
    if txt_path.exists():
        return txt_path.read_text(encoding="utf-8")
    if path.suffix.lower() == ".txt" and path.exists():
        return path.read_text(encoding="utf-8")
    pdf_path = path if path.suffix.lower() == ".pdf" else path.with_suffix(".pdf")
    if pdf_path.exists():
        try:
            from pypdf import PdfReader

            reader = PdfReader(str(pdf_path))
            return "\n".join(page.extract_text() or "" for page in reader.pages).strip()
        except Exception:
            logger.debug("Could not extract tailored resume text from %s", pdf_path, exc_info=True)
    return ""


def get_manual_command(backend: str, model: str, prompt_file: Path, mcp_path: Path) -> str:
    """Return a copy-pasteable manual debug command."""
    cmd = _build_agent_command(backend, model, mcp_path, prompt_file)
    return " ".join(shlex.quote(part) for part in cmd) + f" < {shlex.quote(str(prompt_file))}"


def gen_prompt(target_url: str, min_score: int = 7, max_score: int | None = None,
               model: str = "gpt-5.4-mini", worker_id: int = 0,
               backend: str | None = None, browser: str = "chromium",
               headless: bool = False) -> Path | None:
    """Generate prompt and MCP files without running the apply agent."""
    job = acquire_job(
        target_url=target_url,
        min_score=min_score,
        max_score=max_score,
        worker_id=worker_id,
    )
    if not job:
        return None

    config.load_env()
    gmail_enabled = config.gmail_mcp_enabled()
    resume_text = _read_tailored_resume_text(job)
    prompt = prompt_mod.build_prompt(
        job=job,
        tailored_resume=resume_text,
        gmail_enabled=gmail_enabled,
    )
    # Prompt generation is read-only from the user's point of view; release the
    # DB claim so the same job can be applied later.
    release_lock(job["url"])

    config.ensure_dirs()
    prompt_file = config.LOG_DIR / f"prompt_{_job_log_stem(job)}.txt"
    write_private_text(prompt_file, prompt, strict=True)

    port = BASE_CDP_PORT + worker_id
    worker_profile_dir = setup_worker_profile(worker_id, browser)
    mcp_runtime = ensure_mcp_runtime()
    mcp_path = config.APP_DIR / f".mcp-apply-{worker_id}.json"
    navigation_guard_path = _write_navigation_guard(
        mcp_path.with_name("navigation_guard.ts"), job
    )
    write_private_text(
        mcp_path,
        json.dumps(
            _make_mcp_config(
                port,
                browser=browser,
                worker_profile_dir=worker_profile_dir,
                headless=headless,
                enable_gmail=gmail_enabled,
                mcp_runtime=mcp_runtime,
                navigation_guard_path=navigation_guard_path,
            )
        ),
        strict=True,
    )
    return prompt_file


# ---------------------------------------------------------------------------
# Per-job backend execution
# ---------------------------------------------------------------------------

def _remove_worker_run_dir(worker_dir: Path) -> None:
    """Remove one numeric worker directory without following it outside the root."""
    root = config.APPLY_WORKER_DIR.expanduser().resolve()
    candidate = worker_dir.expanduser().resolve()
    if candidate.parent != root or re.fullmatch(r"worker-\d+", candidate.name) is None:
        logger.error("Refusing to remove unsafe worker directory: %s", worker_dir)
        return
    try:
        if candidate.exists():
            shutil.rmtree(candidate)
    except OSError:
        logger.warning("Could not remove transient worker directory %s", candidate, exc_info=True)


def _prepare_worker_run(
    job: dict,
    port: int,
    worker_id: int,
    model: str,
    backend: str,
    browser: str,
    dry_run: bool,
    headless: bool,
) -> tuple[Path, str, Path, list[str], dict[str, str]]:
    """Stage one agent run entirely below its fresh worker directory."""
    worker_dir = reset_worker_dir(worker_id)
    try:
        config.load_env()
        gmail_enabled = config.gmail_mcp_enabled()
        resume_text = _read_tailored_resume_text(job)
        agent_prompt = prompt_mod.build_prompt(
            job=job,
            tailored_resume=resume_text,
            dry_run=dry_run,
            gmail_enabled=gmail_enabled,
            upload_dir=worker_dir,
        )

        worker_profile_dir = setup_worker_profile(worker_id, browser)
        mcp_runtime = ensure_mcp_runtime()
        mcp_config_path = worker_dir / "mcp.json"
        navigation_guard_path = _write_navigation_guard(
            worker_dir / "navigation_guard.ts", job
        )
        write_private_text(
            mcp_config_path,
            json.dumps(
                _make_mcp_config(
                    port,
                    browser=browser,
                    worker_profile_dir=worker_profile_dir,
                    headless=headless,
                    enable_gmail=gmail_enabled,
                    mcp_runtime=mcp_runtime,
                    navigation_guard_path=navigation_guard_path,
                )
            ),
            strict=True,
        )

        prompt_file = worker_dir / "apply_prompt.txt"
        write_private_text(prompt_file, agent_prompt, strict=True)
        cmd = _build_agent_command(backend, model, mcp_config_path, prompt_file)
        return worker_dir, agent_prompt, prompt_file, cmd, _agent_environment(backend)
    except Exception:
        _remove_worker_run_dir(worker_dir)
        raise

def run_job(job: dict, port: int, worker_id: int = 0,
            model: str = "gpt-5.4-mini", backend: str = "codex",
            browser: str = "chromium", dry_run: bool = False,
            headless: bool = False) -> tuple[str, int]:
    """Run one auto-apply job through the selected backend."""
    start = time.time()
    company = _display_company(job)
    source = job.get("site") or ""
    try:
        known_secrets = collect_known_secret_values(config.load_credentials())
    except Exception:
        known_secrets = collect_known_secret_values()
    safe_title = redact_known_secrets(str(job["title"]), known_secrets)
    safe_company = redact_known_secrets(str(company), known_secrets)
    safe_source = redact_known_secrets(str(source), known_secrets)
    source_suffix = f" (source: {safe_source})" if safe_source and safe_source != safe_company else ""

    worker_dir: Path | None = None
    try:
        ensure_job_artifacts_unshared(job, conn=get_connection())
        worker_dir, agent_prompt, prompt_file, cmd, env = _prepare_worker_run(
            job,
            port,
            worker_id,
            model,
            backend,
            browser,
            dry_run,
            headless,
        )
    except Exception as exc:
        duration_ms = int((time.time() - start) * 1000)
        safe_error = _safe_agent_error(exc, known_secrets=known_secrets, max_length=100)
        logger.error("Worker %d agent preparation failed: %s", worker_id, safe_error)
        add_event(f"[W{worker_id}] Agent preparation failed; queue stopped")
        update_state(worker_id, status="failed", last_action="agent preparation failed")
        return "failed:agent_startup_error", duration_ms

    update_state(worker_id, status="applying", job_title=safe_title,
                 company=safe_company, score=job.get("fit_score", 0),
                 start_time=time.time(), actions=0, last_action=f"{backend} starting")
    add_event(
        f"[W{worker_id}] Starting via {backend}/{browser}: {safe_title[:40]} @ {safe_company}{source_suffix}"
    )

    worker_log = config.LOG_DIR / f"worker-{worker_id}.log"
    ts_header = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    log_header = (
        f"\n{'=' * 60}\n"
        f"[{ts_header}] {safe_title} @ {safe_company}\n"
        f"Source: {safe_source or 'N/A'}\n"
        f"Backend: {backend}\n"
        f"Browser: {browser}\n"
        f"URL: {redact_url_for_log(job.get('application_url') or job['url'])}\n"
        f"Score: {job.get('fit_score', 'N/A')}/10\n"
        f"{'=' * 60}\n"
    )
    log_header = redact_known_secrets(log_header, known_secrets)

    proc = None
    text_parts: list[str] = []
    stats: dict = {}
    try:
        # Use argv list + stdin, never shell=True; job data can contain user or
        # employer-provided text.
        proc = subprocess.Popen(
            cmd,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            encoding="utf-8",
            errors="replace",
            env=env,
            cwd=str(worker_dir),
        )
        with _claude_lock:
            _claude_procs[worker_id] = proc

        startup_output = _write_agent_prompt(proc, agent_prompt)
        if startup_output is not None:
            duration_ms = int((time.time() - start) * 1000)
            safe_output = redact_known_secrets(startup_output, known_secrets)
            with open_private_text(worker_log, mode="a", strict=True) as lf:
                lf.write(log_header)
                lf.write(safe_output + "\n")
            reason = _agent_setup_failure(startup_output) or "agent_startup_error"
            add_event(f"[W{worker_id}] Agent startup failed; queue stopped")
            update_state(worker_id, status="failed", last_action="agent startup failed")
            return f"failed:{reason}", duration_ms

        output_queue: queue.Queue[str | None] = queue.Queue()
        process_stdout = proc.stdout

        def _read_stdout() -> None:
            try:
                for raw in process_stdout or ():
                    output_queue.put(raw)
            finally:
                output_queue.put(None)

        reader = threading.Thread(target=_read_stdout, daemon=True)
        reader.start()
        timeout_seconds = config.get_apply_timeout()
        deadline = start + timeout_seconds if timeout_seconds is not None else None
        idle_timeout_seconds = _get_apply_idle_timeout(timeout_seconds)
        idle_deadline = (
            time.time() + idle_timeout_seconds
            if idle_timeout_seconds is not None
            else None
        )

        with open_private_text(worker_log, mode="a", strict=True) as lf:
            lf.write(log_header)
            while True:
                remaining = None if deadline is None else deadline - time.time()
                if remaining is not None and remaining <= 0:
                    assert timeout_seconds is not None
                    raise subprocess.TimeoutExpired(cmd, timeout_seconds)
                idle_remaining = None if idle_deadline is None else idle_deadline - time.time()
                if idle_remaining is not None and idle_remaining <= 0:
                    assert idle_timeout_seconds is not None
                    raise subprocess.TimeoutExpired(cmd, idle_timeout_seconds)
                wait_for = 0.5
                if remaining is not None:
                    wait_for = min(wait_for, remaining)
                if idle_remaining is not None:
                    wait_for = min(wait_for, idle_remaining)
                try:
                    raw_line = output_queue.get(timeout=wait_for)
                except queue.Empty:
                    continue
                if raw_line is None:
                    break
                if idle_timeout_seconds is not None:
                    idle_deadline = time.time() + idle_timeout_seconds
                line = raw_line.strip()
                if not line:
                    continue
                if backend == "claude":
                    # Claude stream-json has typed assistant/result messages;
                    # Codex currently falls through as plain text.
                    try:
                        msg = json.loads(line)
                    except json.JSONDecodeError:
                        msg = None
                    if msg:
                        msg_type = msg.get("type")
                        if msg_type == "assistant":
                            for block in msg.get("message", {}).get("content", []):
                                if block.get("type") == "text":
                                    text = block["text"]
                                    text_parts.append(text)
                                    lf.write(redact_known_secrets(text, known_secrets) + "\n")
                                elif block.get("type") == "tool_use":
                                    name = (
                                        block.get("name", "")
                                        .replace("mcp__playwright__", "")
                                    )
                                    lf.write(f"  >> {name}\n")
                                    ws = get_state(worker_id)
                                    cur_actions = ws.actions if ws else 0
                                    update_state(worker_id, actions=cur_actions + 1, last_action=name[:35])
                            continue
                        if msg_type == "result":
                            stats = {
                                "cost_usd": msg.get("total_cost_usd", 0),
                                "turns": msg.get("num_turns", 0),
                            }
                            result_text = msg.get("result", "")
                            text_parts.append(result_text)
                            lf.write(redact_known_secrets(result_text, known_secrets) + "\n")
                            continue
                text_parts.append(line)
                redacted_line = redact_known_secrets(line, known_secrets)
                lf.write(redacted_line + "\n")
                update_state(worker_id, last_action=redacted_line[:35])
        proc.wait(timeout=1)
        returncode = proc.returncode
        proc = None

        duration_ms = int((time.time() - start) * 1000)
        output = "\n".join(text_parts)
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        safe_backend = re.sub(r"[^A-Za-z0-9_-]", "_", backend)[:20] or "agent"
        job_log = config.LOG_DIR / f"apply_agent_{safe_backend}_{ts}_w{worker_id}_{_job_log_stem(job)}.txt"
        write_private_text(
            job_log,
            redact_known_secrets(output, known_secrets),
            strict=True,
        )

        if returncode and returncode < 0:
            return "skipped", duration_ms
        if returncode and _last_explicit_result(output) is None:
            reason = _agent_setup_failure(output) or "agent_exit_error"
            add_event(f"[W{worker_id}] Agent exited {returncode}; queue stopped")
            update_state(worker_id, status="failed", last_action="agent process failed")
            return f"failed:{reason}", duration_ms

        if stats:
            cost = stats.get("cost_usd", 0)
            ws = get_state(worker_id)
            prev_cost = ws.total_cost if ws else 0.0
            update_state(worker_id, total_cost=prev_cost + cost)

        return _extract_result(output, worker_id, job, duration_ms, known_secrets)

    except subprocess.TimeoutExpired:
        duration_ms = int((time.time() - start) * 1000)
        elapsed = max(1, duration_ms // 1000)
        add_event(f"[W{worker_id}] TIMEOUT ({elapsed}s)")
        update_state(worker_id, status="failed", last_action=f"TIMEOUT ({elapsed}s)")
        return "failed:timeout", duration_ms
    except OSError as e:
        duration_ms = int((time.time() - start) * 1000)
        safe_error = _safe_agent_error(e, known_secrets=known_secrets, max_length=100)
        add_event(f"[W{worker_id}] Agent startup error: {safe_error[:30]}")
        update_state(worker_id, status="failed", last_action="agent startup failed")
        return "failed:agent_startup_error", duration_ms
    except Exception as e:
        duration_ms = int((time.time() - start) * 1000)
        safe_error = _safe_agent_error(e, known_secrets=known_secrets, max_length=100)
        add_event(f"[W{worker_id}] ERROR: {safe_error[:40]}")
        update_state(worker_id, status="failed", last_action=f"ERROR: {safe_error[:25]}")
        return f"failed:{safe_error}", duration_ms
    finally:
        with _claude_lock:
            _claude_procs.pop(worker_id, None)
        if proc is not None and proc.poll() is None:
            _kill_process_tree(proc.pid)
        if worker_dir is not None:
            _remove_worker_run_dir(worker_dir)


# ---------------------------------------------------------------------------
# Worker queue loop
# ---------------------------------------------------------------------------

def worker_loop(worker_id: int = 0, limit: int = 1,
                target_url: str | None = None,
                min_score: int = 7, max_score: int | None = None,
                headless: bool = False,
                model: str = "gpt-5.4-mini", backend: str = "codex",
                browser: str = "chromium",
                dry_run: bool = False,
                continuous: bool = False) -> tuple[int, int]:
    """Run jobs sequentially until limit is reached or queue is empty."""
    applied = 0
    failed = 0
    jobs_done = 0
    empty_polls = 0
    port = BASE_CDP_PORT + worker_id

    while not _stop_event.is_set():
        if not continuous and jobs_done >= limit:
            break

        update_state(worker_id, status="idle", job_title="", company="",
                     last_action="waiting for job", actions=0)

        job = acquire_job(
            target_url=target_url,
            min_score=min_score,
            max_score=max_score,
            worker_id=worker_id,
        )
        if not job:
            if not continuous:
                add_event(f"[W{worker_id}] Queue empty")
                update_state(worker_id, status="done", last_action="queue empty")
                break
            empty_polls += 1
            update_state(worker_id, status="idle", last_action=f"polling ({empty_polls})")
            if empty_polls == 1:
                add_event(f"[W{worker_id}] Queue empty, polling every {POLL_INTERVAL}s...")
            if _stop_event.wait(timeout=POLL_INTERVAL):
                break
            continue

        empty_polls = 0
        jobs_done += 1
        chrome_proc = None
        try:
            if browser == "chrome":
                add_event(f"[W{worker_id}] Launching Chrome...")
                chrome_proc = launch_chrome(worker_id, port=port, headless=headless)
            else:
                add_event(f"[W{worker_id}] Preparing {browser} profile...")
            result, duration_ms = run_job(
                job,
                port=port,
                worker_id=worker_id,
                model=model,
                backend=backend,
                browser=browser,
                dry_run=dry_run,
                headless=headless,
            )

            # Convert process output into normalized state and durable status.
            if result == "skipped":
                release_lock(job["url"])
                add_event(f"[W{worker_id}] Skipped: {job['title'][:30]}")
                if target_url:
                    break
                continue
            if _is_agent_infrastructure_failure(result):
                release_lock(job["url"])
                _stop_event.set()
                add_event(f"[W{worker_id}] Stopping queue: {result.split(':', 1)[1]}")
                break
            if dry_run:
                mark_dry_run(job["url"], duration_ms=duration_ms, result=result)
                add_event(f"[W{worker_id}] Dry run result: {result} - {job['title'][:30]}")
            if result == "applied":
                if not dry_run:
                    mark_result(job["url"], "applied", duration_ms=duration_ms)
                    applied += 1
                    update_state(worker_id, jobs_applied=applied, jobs_done=applied + failed)
            elif not dry_run:
                reason = result.split(":", 1)[-1] if ":" in result else result
                mark_result(job["url"], "failed", reason,
                            permanent=_is_permanent_failure(result),
                            duration_ms=duration_ms)
                failed += 1
                update_state(worker_id, jobs_failed=failed, jobs_done=applied + failed)
        except KeyboardInterrupt:
            release_lock(job["url"])
            if _stop_event.is_set():
                break
            add_event(f"[W{worker_id}] Job skipped (Ctrl+C)")
            if target_url:
                break
            continue
        except Exception as e:
            safe_error = _safe_agent_error(e, max_length=100)
            logger.error("Worker %d launcher error: %s", worker_id, safe_error)
            add_event(f"[W{worker_id}] Launcher error: {safe_error[:40]}")
            release_lock(job["url"])
            failed += 1
            update_state(worker_id, jobs_failed=failed)
        finally:
            if chrome_proc:
                cleanup_worker(worker_id, chrome_proc)

        if target_url:
            break

    update_state(worker_id, status="done", last_action="finished")
    return applied, failed


# ---------------------------------------------------------------------------
# Apply command entry point
# ---------------------------------------------------------------------------

def main(limit: int = 1, target_url: str | None = None,
         min_score: int = 7, max_score: int | None = None,
         headless: bool = False,
         model: str = "gpt-5.4-mini", backend: str = "codex",
         browser: str = "chromium",
         dry_run: bool = False, continuous: bool = False,
         poll_interval: int = 60, workers: int = 1) -> None:
    """Launch the apply pipeline."""
    global POLL_INTERVAL
    if workers < 1:
        raise ValueError("workers must be at least 1")
    if workers > MAX_RUNTIME_WORKERS:
        raise ValueError(f"workers cannot exceed {MAX_RUNTIME_WORKERS}")
    if limit < 0:
        raise ValueError("limit cannot be negative")
    if max_score is not None and max_score < min_score:
        raise ValueError("max_score cannot be less than min_score")
    if poll_interval < 1:
        raise ValueError("poll_interval must be at least 1")
    POLL_INTERVAL = poll_interval
    _stop_event.clear()

    config.ensure_dirs()
    console = Console()
    recovered = recover_stale_apply_locks()
    if recovered:
        add_event(f"Recovered {recovered} stale in-progress job(s)")

    effective_limit = 0 if continuous else limit
    mode_label = "continuous" if continuous else f"{limit} jobs"

    for i in range(workers):
        init_worker(i)

    worker_label = f"{workers} worker{'s' if workers > 1 else ''}"
    console.print(
        f"Launching apply pipeline ({mode_label}, {worker_label}, "
        f"backend={backend}, browser={browser}, poll every {POLL_INTERVAL}s)..."
    )
    console.print("[dim]Ctrl+C = skip current job(s) | Ctrl+C x2 = stop[/dim]")

    ctrl_c_count = 0

    def _sigint_handler(sig, frame):
        nonlocal ctrl_c_count
        ctrl_c_count += 1
        if ctrl_c_count == 1:
            console.print("\n[yellow]Skipping current job(s)... (Ctrl+C again to STOP)[/yellow]")
            with _claude_lock:
                for cproc in list(_claude_procs.values()):
                    if cproc.poll() is None:
                        _kill_process_tree(cproc.pid)
        else:
            console.print("\n[red bold]STOPPING[/red bold]")
            _stop_event.set()
            with _claude_lock:
                for cproc in list(_claude_procs.values()):
                    if cproc.poll() is None:
                        _kill_process_tree(cproc.pid)
            kill_all_chrome()
            raise KeyboardInterrupt

    signal.signal(signal.SIGINT, _sigint_handler)

    try:
        with Live(render_full(), console=console, refresh_per_second=2) as live:
            dashboard_stop = threading.Event()

            def _refresh():
                try:
                    while not dashboard_stop.is_set():
                        live.update(render_full())
                        time.sleep(0.5)
                except Exception as exc:
                    safe_error = _safe_agent_error(exc)
                    logger.error("Apply dashboard refresh thread crashed: %s", safe_error)
                    record_reliability_event(
                        "apply_dashboard_refresh_crashed",
                        "Apply dashboard refresh thread crashed",
                        severity="error",
                        context={"error": safe_error},
                    )
                    dashboard_stop.set()

            refresh_thread = threading.Thread(target=_refresh, daemon=True)
            refresh_thread.start()

            try:
                if workers == 1:
                    total_applied, total_failed = worker_loop(
                        worker_id=0,
                        limit=effective_limit,
                        target_url=target_url,
                        min_score=min_score,
                        max_score=max_score,
                        headless=headless,
                        model=model,
                        backend=backend,
                        browser=browser,
                        dry_run=dry_run,
                        continuous=continuous,
                    )
                else:
                    if effective_limit:
                        base = effective_limit // workers
                        extra = effective_limit % workers
                        limits = [base + (1 if i < extra else 0) for i in range(workers)]
                    else:
                        limits = [0] * workers

                    with ThreadPoolExecutor(max_workers=workers, thread_name_prefix="apply-worker") as executor:
                        futures = {
                            executor.submit(
                                worker_loop,
                                worker_id=i,
                                limit=limits[i],
                                target_url=target_url,
                                min_score=min_score,
                                max_score=max_score,
                                headless=headless,
                                model=model,
                                backend=backend,
                                browser=browser,
                                dry_run=dry_run,
                                continuous=continuous,
                            ): i
                            for i in range(workers)
                        }

                        results: list[tuple[int, int]] = []
                        for future in as_completed(futures):
                            wid = futures[future]
                            try:
                                results.append(future.result())
                            except Exception as exc:
                                safe_error = _safe_agent_error(exc)
                                logger.error("Worker %d crashed: %s", wid, safe_error)
                                record_reliability_event(
                                    "apply_worker_crashed",
                                    "Apply worker crashed",
                                    severity="error",
                                    context={"worker_id": wid, "error": safe_error},
                                )
                                results.append((0, 0))

                    total_applied = sum(r[0] for r in results)
                    total_failed = sum(r[1] for r in results)
            finally:
                dashboard_stop.set()
                refresh_thread.join(timeout=2)
            live.update(render_full())

        totals = get_totals()
        console.print(
            f"\n[bold]Done: {total_applied} applied, {total_failed} failed "
            f"(${totals['cost']:.3f})[/bold]"
        )
        console.print(f"Logs: {config.LOG_DIR}")

    except KeyboardInterrupt:
        pass
    finally:
        _stop_event.set()
        kill_all_chrome()
