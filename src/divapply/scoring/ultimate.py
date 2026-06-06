"""Targeted resume generator for one saved job posting."""

from __future__ import annotations

import json
import logging
import re
import time
from datetime import datetime, timezone
from pathlib import Path

from divapply.config import RESUME_PATH, TAILORED_DIR, ensure_dirs, load_env, load_profile
from divapply.database import get_connection, init_db
from divapply.scoring.tailor import _format_job_trace, tailor_resume
from divapply.security import protect_file

log = logging.getLogger(__name__)


def _fetch_target_job(job_ref: str) -> dict | None:
    """Find one saved job by exact URL, application URL, URL fragment, or title."""
    needle = job_ref.strip()
    if not needle:
        return None

    like = f"%{needle.rstrip('/')}%"
    conn = get_connection()
    row = conn.execute(
        """
        SELECT *
        FROM jobs
        WHERE url = ?
           OR application_url = ?
           OR url LIKE ?
           OR application_url LIKE ?
           OR title LIKE ?
        ORDER BY COALESCE(fit_score, 0) DESC, discovered_at DESC
        LIMIT 1
        """,
        (needle, needle, like, like, like),
    ).fetchone()
    if not row:
        return None
    return dict(row)


def _safe_filename_piece(value: str, fallback: str) -> str:
    """Build a Windows-safe filename piece."""
    text = re.sub(r"[^\w\s-]", "", str(value or "")).strip().replace(" ", "_")
    text = re.sub(r"_+", "_", text)[:60].strip("_")
    if not text:
        text = fallback
    if text.upper() in {"CON", "PRN", "AUX", "NUL", "COM1", "COM2", "COM3", "COM4", "LPT1", "LPT2", "LPT3"}:
        text = f"_{text}"
    return text


def generate_targeted_resume(
    job_ref: str,
    output_dir: Path | None = None,
    validation_mode: str = "normal",
) -> dict:
    """Generate one tailored resume for one saved job posting.

    Args:
        job_ref: Exact URL, application URL, URL fragment, or title fragment.
        output_dir: Directory for generated files. Defaults to tailored_resumes.
        validation_mode: strict, normal, lenient, or none.

    Returns:
        Metadata for generated text, PDF, trace, and validation report files.
    """
    t0 = time.time()

    load_env()
    ensure_dirs()
    init_db()

    job = _fetch_target_job(job_ref)
    if not job:
        raise RuntimeError(f"No saved job matched '{job_ref}'. Run discovery/enrichment first.")
    if not job.get("full_description"):
        raise RuntimeError(f"Matched job has no full description yet: {job.get('title') or job.get('url')}")

    profile = load_profile()
    resume_text = RESUME_PATH.read_text(encoding="utf-8")

    out_dir = output_dir or TAILORED_DIR
    out_dir.mkdir(parents=True, exist_ok=True)

    tailored, report = tailor_resume(
        resume_text,
        job,
        profile,
        validation_mode=validation_mode,
    )

    safe_site = _safe_filename_piece(job.get("site") or job.get("company") or "job", "job")
    safe_title = _safe_filename_piece(job.get("title") or "targeted_resume", "targeted_resume")
    prefix = f"targeted_{safe_site}_{safe_title}"

    txt_path = out_dir / f"{prefix}.txt"
    job_path = out_dir / f"{prefix}_JOB.txt"
    report_path = out_dir / f"{prefix}_REPORT.json"

    txt_path.write_text(tailored, encoding="utf-8")
    job_path.write_text(_format_job_trace(job), encoding="utf-8")
    report_path.write_text(json.dumps(report, indent=2), encoding="utf-8")
    protect_file(txt_path)
    protect_file(job_path)
    protect_file(report_path)

    pdf_path = None
    if report.get("status") in {"approved", "approved_with_judge_warning"}:
        try:
            from divapply.scoring.pdf import convert_to_pdf

            pdf_path = str(convert_to_pdf(txt_path))
        except Exception as exc:
            log.warning("PDF generation failed for %s: %s", txt_path, exc)

    now = datetime.now(timezone.utc).isoformat()
    conn = get_connection()
    if report.get("status") in {"approved", "approved_with_judge_warning"}:
        conn.execute(
            """
            UPDATE jobs
            SET tailored_resume_path = ?,
                tailored_at = ?,
                tailor_attempts = COALESCE(tailor_attempts, 0) + 1
            WHERE url = ?
            """,
            (str(txt_path), now, job["url"]),
        )
    else:
        conn.execute(
            "UPDATE jobs SET tailor_attempts = COALESCE(tailor_attempts, 0) + 1 WHERE url = ?",
            (job["url"],),
        )
    conn.commit()

    elapsed = time.time() - t0
    log.info("Targeted resume generated in %.1fs: %s", elapsed, txt_path)

    return {
        "job": job,
        "text_path": str(txt_path),
        "pdf_path": pdf_path,
        "job_path": str(job_path),
        "report_path": str(report_path),
        "status": report.get("status", "unknown"),
        "attempts": report.get("attempts", 0),
        "elapsed": elapsed,
    }
