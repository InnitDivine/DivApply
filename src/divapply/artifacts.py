"""Stable ownership helpers for generated per-job artifacts."""

from __future__ import annotations

from collections.abc import Mapping
import hashlib
import os
from pathlib import Path
import re
import sqlite3


class ArtifactCollisionError(RuntimeError):
    """Raised when an active job shares generated artifacts with another job."""


def _safe_component(value: object, *, limit: int, fallback: str) -> str:
    text = re.sub(r"[^\w\s-]", "", str(value or ""))[:limit].strip().replace(" ", "_")
    return text.strip("._-") or fallback


def job_artifact_stem(job: Mapping[str, object]) -> str:
    """Return a readable filename stem bound to the job URL identity."""
    url = str(job.get("url") or "").strip()
    if not url:
        raise ValueError("Generated job artifacts require a non-empty job URL")
    site = _safe_component(job.get("site"), limit=20, fallback="Unknown")
    title = _safe_component(job.get("title"), limit=50, fallback="Job")
    identity = hashlib.sha256(url.encode("utf-8")).hexdigest()
    return f"{site}_{title}--{identity}"


def tailored_artifact_paths(root: Path, job: Mapping[str, object]) -> tuple[Path, Path, Path]:
    """Return text, job-trace, and validation-report paths for one job."""
    stem = job_artifact_stem(job)
    return (
        root / f"{stem}.txt",
        root / f"{stem}_JOB.txt",
        root / f"{stem}_REPORT.json",
    )


def cover_letter_artifact_path(root: Path, job: Mapping[str, object]) -> Path:
    """Return the text cover-letter path for one job."""
    return root / f"{job_artifact_stem(job)}_CL.txt"


def artifact_family_key(path: Path | str) -> str:
    """Normalize text/PDF/HTML siblings into one comparison key."""
    expanded = Path(path).expanduser().with_suffix("")
    return os.path.normcase(os.path.abspath(os.path.normpath(str(expanded))))


def _job_paths(job: Mapping[str, object]) -> dict[str, str]:
    return {
        key: str(value)
        for key in ("tailored_resume_path", "cover_letter_path")
        if (value := job.get(key))
    }


def shared_job_artifact_paths(
    job: Mapping[str, object],
    *,
    conn: sqlite3.Connection,
) -> set[str]:
    """Return this job's artifact paths referenced by another active job."""
    url = str(job.get("url") or "").strip()
    current = _job_paths(job)
    if not url or not current:
        return set()
    current_families = {key: artifact_family_key(path) for key, path in current.items()}
    columns = {row[1] for row in conn.execute("PRAGMA table_info(jobs)").fetchall()}
    active_clause = "AND archived_at IS NULL" if "archived_at" in columns else ""
    other_rows = conn.execute(
        f"""
        SELECT tailored_resume_path, cover_letter_path
        FROM jobs
        WHERE url != ? {active_clause}
          AND (tailored_resume_path IS NOT NULL OR cover_letter_path IS NOT NULL)
        """,
        (url,),
    ).fetchall()
    other_families = {
        artifact_family_key(raw)
        for row in other_rows
        for raw in (row[0], row[1])
        if raw
    }
    return {
        current[key]
        for key, family in current_families.items()
        if family in other_families
    }


def ensure_job_artifacts_unshared(
    job: Mapping[str, object],
    *,
    conn: sqlite3.Connection,
) -> None:
    """Fail closed when an active job shares a generated artifact family."""
    shared = shared_job_artifact_paths(job, conn=conn)
    if shared:
        raise ArtifactCollisionError(
            "Generated application artifact is shared by another active job; "
            "regenerate job documents before applying"
        )
