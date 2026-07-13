"""Local maintenance helpers for generated DivApply artifacts."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import stat
import time

from divapply import config
from divapply.security import _is_link_or_reparse


@dataclass(frozen=True)
class CleanupResult:
    """Result metadata for a cleanup preview or delete run."""

    candidates: tuple[Path, ...]
    deleted: tuple[Path, ...]
    skipped: tuple[Path, ...]
    dry_run: bool


def cleanup_expired_logs(
    *,
    retention_days: int | None = None,
    now: float | None = None,
) -> CleanupResult:
    """Delete regular log files older than the configured retention period."""
    days = config.get_log_retention_days() if retention_days is None else retention_days
    if not 0 <= days <= 3650:
        raise ValueError("log retention days must be from 0 to 3650")
    if days == 0:
        return CleanupResult(candidates=(), deleted=(), skipped=(), dry_run=False)

    log_dir = config.LOG_DIR.expanduser()
    if not log_dir.exists():
        return CleanupResult(candidates=(), deleted=(), skipped=(), dry_run=False)
    try:
        root = log_dir.resolve()
    except OSError:
        return CleanupResult(candidates=(), deleted=(), skipped=(log_dir,), dry_run=False)

    cutoff = (time.time() if now is None else now) - days * 86400
    candidates: list[Path] = []
    deleted: list[Path] = []
    skipped: list[Path] = []
    for candidate in sorted(log_dir.iterdir()):
        try:
            metadata = candidate.lstat()
        except OSError:
            skipped.append(candidate)
            continue
        if metadata.st_mtime >= cutoff:
            continue
        if _is_link_or_reparse(candidate):
            candidates.append(candidate)
            skipped.append(candidate)
            continue
        if not stat.S_ISREG(metadata.st_mode):
            continue
        candidates.append(candidate)
        try:
            candidate.resolve().relative_to(root)
            candidate.unlink()
            deleted.append(candidate)
        except (OSError, ValueError):
            skipped.append(candidate)

    return CleanupResult(
        candidates=tuple(candidates),
        deleted=tuple(deleted),
        skipped=tuple(skipped),
        dry_run=False,
    )


def cleanup_artifacts(
    *,
    dry_run: bool = True,
    include_backups: bool = False,
) -> CleanupResult:
    """Remove stale local benchmark, backup, and temporary configuration files."""
    app_dir = config.APP_DIR.expanduser().resolve()
    candidates = _cleanup_candidates(include_backups=include_backups)
    deleted: list[Path] = []
    skipped: list[Path] = []

    for candidate in candidates:
        try:
            resolved = candidate.expanduser().resolve()
            resolved.relative_to(app_dir)
        except (OSError, ValueError):
            skipped.append(candidate)
            continue
        if candidate.is_symlink():
            skipped.append(candidate)
            continue
        if dry_run:
            continue
        try:
            candidate.unlink()
            deleted.append(candidate)
        except OSError:
            skipped.append(candidate)

    if include_backups and not dry_run:
        backups_dir = config.APP_DIR / "backups"
        try:
            if backups_dir.exists() and not any(backups_dir.iterdir()):
                backups_dir.rmdir()
        except OSError:
            pass

    return CleanupResult(
        candidates=tuple(candidates),
        deleted=tuple(deleted),
        skipped=tuple(skipped),
        dry_run=dry_run,
    )


def _cleanup_candidates(*, include_backups: bool) -> list[Path]:
    patterns = (
        "dashboard.perf-*.html",
        "dashboard-bench-*.html",
        "*.bak",
        "*.bak-*",
        "*.backup",
        "*.backup-*",
    )
    roots = (config.APP_DIR, config.USER_CONFIG_DIR)
    candidates: set[Path] = set()
    for root in roots:
        if not root.exists():
            continue
        for pattern in patterns:
                candidates.update(path for path in root.glob(pattern) if path.is_file() or path.is_symlink())

    for output_dir in (config.TAILORED_DIR, config.COVER_LETTER_DIR):
        if not output_dir.exists():
            continue
        candidates.update(
            path
            for path in output_dir.iterdir()
            if path.is_file() and path.suffix.lower() in {".txt", ".json", ".html"}
        )

    if include_backups:
        backups_dir = config.APP_DIR / "backups"
        if backups_dir.exists():
            candidates.update(path for path in backups_dir.glob("divapply-backup-*.zip") if path.is_file())

    return sorted(candidates)
