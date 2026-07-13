"""Backup service for DivApply user data."""

from __future__ import annotations

from contextlib import closing
from dataclasses import dataclass
from datetime import datetime, timezone
import fnmatch
import os
from pathlib import Path
import sqlite3
import tempfile
import zipfile

from divapply import config
from divapply.database import get_active_db_path
from divapply.security import protect_file


@dataclass(frozen=True)
class BackupResult:
    """Result metadata for a completed backup."""

    path: Path
    file_count: int
    included_secrets: bool


def _is_link_or_reparse(path: Path) -> bool:
    if path.is_symlink():
        return True
    try:
        return bool(getattr(path.lstat(), "st_file_attributes", 0) & 0x400)
    except OSError:
        return False


def _canonical_output_path(path: Path) -> Path:
    if not path.name or path == path.parent:
        raise ValueError("backup output must be a non-root file path")
    if _is_link_or_reparse(path):
        raise ValueError("backup output must not be a link or reparse point")
    parent = path.parent.expanduser().resolve()
    parent.mkdir(parents=True, exist_ok=True)
    target = parent / path.name
    if target.exists() and not target.is_file():
        raise ValueError("backup output must be a regular file path")
    return target


def _validate_backup_target(
    target: Path,
    *,
    active_db: Path,
    include_outputs: bool,
    include_logs: bool,
) -> None:
    source_files = {
        active_db,
        config.PROFILE_PATH,
        config.RESUME_PATH,
        config.RESUME_PDF_PATH,
        config.SEARCH_CONFIG_PATH,
        config.ANSWERS_PATH,
        config.ENV_PATH,
        config.CREDENTIALS_PATH,
    }
    target_key = os.path.normcase(str(target))
    for source in source_files:
        source_path = source.expanduser().resolve()
        if target_key == os.path.normcase(str(source_path)):
            raise ValueError("backup output must not replace a source file")

    source_dirs = [config.USER_CONFIG_DIR]
    if include_outputs:
        source_dirs.extend([config.TAILORED_DIR, config.COVER_LETTER_DIR])
    if include_logs:
        source_dirs.append(config.LOG_DIR)
    for source_dir in source_dirs:
        try:
            target.relative_to(source_dir.expanduser().resolve())
        except ValueError:
            continue
        raise ValueError("backup output must not be inside an archived source directory")


def _snapshot_database(source: Path, destination: Path) -> None:
    """Create and verify a consistent SQLite snapshot, including committed WAL state."""
    source_uri = f"{source.expanduser().resolve().as_uri()}?mode=ro"
    with closing(sqlite3.connect(source_uri, uri=True, timeout=30)) as source_conn:
        with closing(sqlite3.connect(destination)) as destination_conn:
            source_conn.backup(destination_conn)
            result = destination_conn.execute("PRAGMA integrity_check").fetchone()
            if result is None or str(result[0]).casefold() != "ok":
                raise sqlite3.DatabaseError("backup database failed integrity_check")
            destination_conn.commit()
    protect_file(destination)


def _verify_backup_archive(path: Path, *, expect_database: bool) -> None:
    with zipfile.ZipFile(path, "r") as archive:
        bad_member = archive.testzip()
        if bad_member is not None:
            raise zipfile.BadZipFile(f"backup archive member failed CRC: {bad_member}")
        if expect_database and config.DB_PATH.name not in archive.namelist():
            raise zipfile.BadZipFile("backup archive is missing the active database snapshot")


def create_backup(
    *,
    out: Path | None = None,
    include_secrets: bool = False,
    include_outputs: bool = True,
    include_logs: bool = False,
) -> BackupResult:
    """Create a local recovery backup of configured DivApply user files."""
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    requested_path = out or config.APP_DIR / "backups" / f"divapply-backup-{timestamp}.zip"
    backup_path = _canonical_output_path(Path(requested_path).expanduser())
    active_db = get_active_db_path().expanduser()
    _validate_backup_target(
        backup_path,
        active_db=active_db,
        include_outputs=include_outputs,
        include_logs=include_logs,
    )

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
        config.USER_CONFIG_DIR,
    ]
    if include_outputs:
        paths.extend([config.TAILORED_DIR, config.COVER_LETTER_DIR])
    if include_logs:
        paths.append(config.LOG_DIR)
    if include_secrets:
        paths.extend([config.ENV_PATH, config.CREDENTIALS_PATH])

    count = 0
    database_exists = active_db.is_file()
    with tempfile.TemporaryDirectory(prefix=f".{backup_path.name}.", dir=backup_path.parent) as temp_dir:
        stage_dir = Path(temp_dir)
        stage_archive = stage_dir / backup_path.name
        snapshot_path = stage_dir / config.DB_PATH.name
        if database_exists:
            _snapshot_database(active_db, snapshot_path)

        with zipfile.ZipFile(stage_archive, "w", compression=zipfile.ZIP_DEFLATED) as archive:
            if database_exists:
                archive.write(snapshot_path, config.DB_PATH.name)
                count += 1
            for path in paths:
                count += _add_backup_path(
                    archive,
                    path,
                    config.APP_DIR,
                    excluded_names=excluded_names,
                    excluded_patterns=excluded_patterns,
                    archive_path=backup_path,
                )

        _verify_backup_archive(stage_archive, expect_database=database_exists)
        protect_file(stage_archive)
        os.replace(stage_archive, backup_path)
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
