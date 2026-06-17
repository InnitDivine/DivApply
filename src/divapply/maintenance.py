"""Local maintenance helpers for generated DivApply artifacts."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from divapply import config


@dataclass(frozen=True)
class CleanupResult:
    """Result metadata for a cleanup preview or delete run."""

    candidates: tuple[Path, ...]
    deleted: tuple[Path, ...]
    skipped: tuple[Path, ...]
    dry_run: bool


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

    if include_backups:
        backups_dir = config.APP_DIR / "backups"
        if backups_dir.exists():
            candidates.update(path for path in backups_dir.glob("divapply-backup-*.zip") if path.is_file())

    return sorted(candidates)
