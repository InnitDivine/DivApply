"""Backup service for DivApply user data."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import fnmatch
from pathlib import Path
import zipfile

from divapply import config
from divapply.security import protect_file


@dataclass(frozen=True)
class BackupResult:
    """Result metadata for a completed backup."""

    path: Path
    file_count: int
    included_secrets: bool


def create_backup(
    *,
    out: Path | None = None,
    include_secrets: bool = False,
    include_outputs: bool = True,
) -> BackupResult:
    """Create a local recovery backup of configured DivApply user files."""
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    backup_path = out or config.APP_DIR / "backups" / f"divapply-backup-{timestamp}.zip"
    backup_path = backup_path.expanduser().resolve()
    backup_path.parent.mkdir(parents=True, exist_ok=True)

    excluded_names = set()
    excluded_patterns: set[str] = set()
    if not include_secrets:
        excluded_names.update({config.ENV_PATH.name, config.CREDENTIALS_PATH.name})
        excluded_patterns.update({
            ".mcp-apply-*.json",
            "apply_prompt.txt",
            "prompt_*.txt",
        })

    paths = [
        config.PROFILE_PATH,
        config.RESUME_PATH,
        config.RESUME_PDF_PATH,
        config.SEARCH_CONFIG_PATH,
        config.ANSWERS_PATH,
        config.DB_PATH,
        config.USER_CONFIG_DIR,
    ]
    if include_outputs:
        paths.extend([config.TAILORED_DIR, config.COVER_LETTER_DIR, config.LOG_DIR])
    if include_secrets:
        paths.extend([config.ENV_PATH, config.CREDENTIALS_PATH])

    count = 0
    with zipfile.ZipFile(backup_path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for path in paths:
            count += _add_backup_path(
                archive,
                path,
                config.APP_DIR,
                excluded_names=excluded_names,
                excluded_patterns=excluded_patterns,
                archive_path=backup_path,
            )
    protect_file(backup_path)
    return BackupResult(path=backup_path, file_count=count, included_secrets=include_secrets)


def _add_backup_path(
    archive: zipfile.ZipFile,
    path: Path,
    base_dir: Path,
    *,
    excluded_names: set[str],
    excluded_patterns: set[str] | None = None,
    archive_path: Path,
) -> int:
    """Add one file or directory tree to a backup archive."""
    if not path.exists():
        return 0

    archive_resolved = archive_path.resolve()
    base_resolved = base_dir.resolve()
    added = 0

    def should_skip(candidate: Path) -> bool:
        if candidate.is_symlink():
            return True
        if candidate.name in excluded_names:
            return True
        if excluded_patterns and any(fnmatch.fnmatch(candidate.name, pattern) for pattern in excluded_patterns):
            return True
        try:
            candidate_resolved = candidate.resolve()
            if candidate_resolved == archive_resolved:
                return True
            candidate_resolved.relative_to(base_resolved)
        except OSError:
            return True
        except ValueError:
            return True
        return any(parent.name == "backups" for parent in candidate.parents)

    if path.is_file():
        if should_skip(path):
            return 0
        archive.write(path, path.relative_to(base_dir).as_posix())
        return 1

    for item in sorted(path.rglob("*")):
        if not item.is_file() or should_skip(item):
            continue
        archive.write(item, item.relative_to(base_dir).as_posix())
        added += 1
    return added
