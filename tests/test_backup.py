from __future__ import annotations

import sqlite3
import zipfile
from pathlib import Path

import pytest

from divapply import backup as backup_mod
from divapply.backup import create_backup
from divapply import cli


def _patch_backup_paths(monkeypatch, tmp_path: Path) -> dict[str, Path]:
    import divapply.config as config
    import divapply.database as database

    app_dir = tmp_path / "app"
    paths = {
        "APP_DIR": app_dir,
        "DB_PATH": app_dir / "divapply.db",
        "LEGACY_DB_PATH": tmp_path / "legacy" / "applypilot.db",
        "PROFILE_PATH": app_dir / "profile.json",
        "RESUME_PATH": app_dir / "resume.txt",
        "RESUME_PDF_PATH": app_dir / "resume.pdf",
        "SEARCH_CONFIG_PATH": app_dir / "searches.yaml",
        "ANSWERS_PATH": app_dir / "answers.yaml",
        "CREDENTIALS_PATH": app_dir / "credentials.yaml",
        "ENV_PATH": app_dir / ".env",
        "USER_CONFIG_DIR": app_dir / "config",
        "TAILORED_DIR": app_dir / "tailored_resumes",
        "COVER_LETTER_DIR": app_dir / "cover_letters",
        "LOG_DIR": app_dir / "logs",
    }
    for name, value in paths.items():
        monkeypatch.setattr(config, name, value)
    monkeypatch.setattr(database, "DB_PATH", paths["DB_PATH"])
    monkeypatch.setattr(database, "LEGACY_DB_PATH", paths["LEGACY_DB_PATH"])

    def ensure_dirs() -> None:
        for value in (
            paths["APP_DIR"],
            paths["USER_CONFIG_DIR"],
            paths["TAILORED_DIR"],
            paths["COVER_LETTER_DIR"],
            paths["LOG_DIR"],
        ):
            value.mkdir(parents=True, exist_ok=True)

    monkeypatch.setattr(config, "ensure_dirs", ensure_dirs)
    return paths


def test_backup_excludes_secrets_by_default(tmp_path, monkeypatch) -> None:
    _patch_backup_paths(monkeypatch, tmp_path)

    app_dir = tmp_path / "app"
    (app_dir / "config").mkdir(parents=True)
    (app_dir / "profile.json").write_text("{}", encoding="utf-8")
    (app_dir / "resume.txt").write_text("resume", encoding="utf-8")
    (app_dir / "searches.yaml").write_text("queries: []", encoding="utf-8")
    (app_dir / ".env").write_text("OPENAI_API_KEY=secret", encoding="utf-8")
    (app_dir / "credentials.yaml").write_text("site: secret", encoding="utf-8")
    (app_dir / "config" / "sites.yaml").write_text("sites: []", encoding="utf-8")

    out = tmp_path / "backup.zip"
    cli.backup(out=out, include_secrets=False, include_outputs=False, include_logs=False)

    with zipfile.ZipFile(out) as archive:
        names = set(archive.namelist())

    assert "profile.json" in names
    assert "resume.txt" in names
    assert "searches.yaml" in names
    assert "config/sites.yaml" in names
    assert ".env" not in names
    assert "credentials.yaml" not in names


def test_backup_excludes_secret_bearing_prompt_outputs_by_default(tmp_path, monkeypatch) -> None:
    _patch_backup_paths(monkeypatch, tmp_path)

    app_dir = tmp_path / "app"
    logs_dir = app_dir / "logs"
    logs_dir.mkdir(parents=True)
    (app_dir / "profile.json").write_text("{}", encoding="utf-8")
    (logs_dir / "prompt_example.txt").write_text("password=prompt-secret", encoding="utf-8")
    (logs_dir / "worker-0.log").write_text("redacted worker log", encoding="utf-8")

    out = tmp_path / "backup.zip"
    cli.backup(out=out, include_secrets=False, include_outputs=True, include_logs=False)

    with zipfile.ZipFile(out) as archive:
        names = set(archive.namelist())

    assert "logs/worker-0.log" not in names
    assert "logs/prompt_example.txt" not in names

    explicit_out = tmp_path / "backup-with-logs.zip"
    cli.backup(
        out=explicit_out,
        include_secrets=False,
        include_outputs=True,
        include_logs=True,
    )

    with zipfile.ZipFile(explicit_out) as archive:
        explicit_names = set(archive.namelist())

    assert "logs/worker-0.log" in explicit_names
    assert "logs/prompt_example.txt" not in explicit_names


def test_backup_does_not_follow_symlinks_outside_app_dir(tmp_path, monkeypatch) -> None:
    _patch_backup_paths(monkeypatch, tmp_path)

    app_dir = tmp_path / "app"
    logs_dir = app_dir / "logs"
    logs_dir.mkdir(parents=True)
    outside = tmp_path / "outside-secret.txt"
    outside.write_text("do not archive", encoding="utf-8")
    (logs_dir / "worker-0.log").write_text("regular log", encoding="utf-8")
    symlink_path = logs_dir / "linked-secret.txt"
    try:
        symlink_path.symlink_to(outside)
    except OSError:
        return

    out = tmp_path / "backup.zip"
    cli.backup(out=out, include_secrets=False, include_outputs=True, include_logs=True)

    with zipfile.ZipFile(out) as archive:
        names = set(archive.namelist())
        contents = {name: archive.read(name).decode("utf-8") for name in names}

    assert "logs/worker-0.log" in names
    assert "logs/linked-secret.txt" not in names
    assert "do not archive" not in "\n".join(contents.values())


def test_backup_can_include_secrets_explicitly(tmp_path, monkeypatch) -> None:
    _patch_backup_paths(monkeypatch, tmp_path)

    app_dir = tmp_path / "app"
    logs_dir = app_dir / "logs"
    logs_dir.mkdir(parents=True)
    (app_dir / ".env").write_text("OPENAI_API_KEY=secret", encoding="utf-8")
    (app_dir / "credentials.yaml").write_text("site: secret", encoding="utf-8")
    (logs_dir / "prompt_example.txt").write_text("password=prompt-secret", encoding="utf-8")

    out = tmp_path / "backup.zip"
    cli.backup(out=out, include_secrets=True, include_outputs=True, include_logs=True)

    with zipfile.ZipFile(out) as archive:
        names = set(archive.namelist())

    assert ".env" in names
    assert "credentials.yaml" in names
    assert "logs/prompt_example.txt" in names


def test_create_backup_returns_reusable_result_metadata(tmp_path, monkeypatch) -> None:
    _patch_backup_paths(monkeypatch, tmp_path)

    app_dir = tmp_path / "app"
    app_dir.mkdir(parents=True)
    (app_dir / "profile.json").write_text("{}", encoding="utf-8")

    out = tmp_path / "backup.zip"
    result = create_backup(out=out, include_secrets=False, include_outputs=False)

    assert result.path == out.resolve()
    assert result.file_count == 1
    assert result.included_secrets is False


def test_create_backup_skips_missing_configured_paths(tmp_path, monkeypatch) -> None:
    _patch_backup_paths(monkeypatch, tmp_path)

    app_dir = tmp_path / "app"
    app_dir.mkdir(parents=True)

    out = tmp_path / "empty.zip"
    result = create_backup(out=out, include_secrets=False, include_outputs=False)

    assert result.file_count == 0
    with zipfile.ZipFile(out) as archive:
        assert archive.namelist() == []


def test_create_backup_excludes_output_directories_when_disabled(tmp_path, monkeypatch) -> None:
    _patch_backup_paths(monkeypatch, tmp_path)

    app_dir = tmp_path / "app"
    tailored_dir = app_dir / "tailored_resumes"
    cover_dir = app_dir / "cover_letters"
    logs_dir = app_dir / "logs"
    tailored_dir.mkdir(parents=True)
    cover_dir.mkdir()
    logs_dir.mkdir()
    (app_dir / "profile.json").write_text("{}", encoding="utf-8")
    (tailored_dir / "resume.pdf").write_text("resume", encoding="utf-8")
    (cover_dir / "cover.pdf").write_text("cover", encoding="utf-8")
    (logs_dir / "worker.log").write_text("log", encoding="utf-8")

    out = tmp_path / "backup.zip"
    result = create_backup(out=out, include_secrets=False, include_outputs=False)

    with zipfile.ZipFile(out) as archive:
        names = set(archive.namelist())

    assert result.file_count == 1
    assert names == {"profile.json"}


def test_create_backup_excludes_archive_itself_and_backup_folder_contents(tmp_path, monkeypatch) -> None:
    _patch_backup_paths(monkeypatch, tmp_path)

    app_dir = tmp_path / "app"
    backups_dir = app_dir / "backups"
    backups_dir.mkdir(parents=True)
    (app_dir / "profile.json").write_text("{}", encoding="utf-8")
    (backups_dir / "old-backup.zip").write_text("old backup", encoding="utf-8")

    out = backups_dir / "new-backup.zip"
    result = create_backup(out=out, include_secrets=True, include_outputs=True)

    with zipfile.ZipFile(out) as archive:
        names = set(archive.namelist())

    assert result.file_count == 1
    assert names == {"profile.json"}
    assert "backups/old-backup.zip" not in names
    assert "backups/new-backup.zip" not in names


def test_create_backup_excludes_mcp_and_apply_prompt_files_without_secrets(tmp_path, monkeypatch) -> None:
    _patch_backup_paths(monkeypatch, tmp_path)

    app_dir = tmp_path / "app"
    logs_dir = app_dir / "logs"
    logs_dir.mkdir(parents=True)
    (logs_dir / ".mcp-apply-job.json").write_text("token=secret", encoding="utf-8")
    (logs_dir / "apply_prompt.txt").write_text("password=secret", encoding="utf-8")
    (logs_dir / "regular.log").write_text("safe", encoding="utf-8")

    out = tmp_path / "backup.zip"
    result = create_backup(
        out=out,
        include_secrets=False,
        include_outputs=True,
        include_logs=True,
    )

    with zipfile.ZipFile(out) as archive:
        names = set(archive.namelist())

    assert result.file_count == 1
    assert names == {"logs/regular.log"}


def _restore_database(archive_path: Path, destination: Path) -> sqlite3.Connection:
    with zipfile.ZipFile(archive_path) as archive:
        destination.write_bytes(archive.read("divapply.db"))
    connection = sqlite3.connect(destination)
    connection.row_factory = sqlite3.Row
    return connection


def test_backup_restores_committed_rows_from_live_wal_database(tmp_path, monkeypatch) -> None:
    paths = _patch_backup_paths(monkeypatch, tmp_path)
    paths["APP_DIR"].mkdir(parents=True)
    live = sqlite3.connect(paths["DB_PATH"])
    live.execute("PRAGMA journal_mode=WAL")
    live.execute("PRAGMA wal_autocheckpoint=0")
    live.execute("CREATE TABLE durable (value TEXT)")
    live.commit()
    live.execute("INSERT INTO durable VALUES ('committed-in-wal')")
    live.commit()
    assert paths["DB_PATH"].with_name("divapply.db-wal").exists()

    out = tmp_path / "wal-backup.zip"
    result = create_backup(out=out, include_outputs=False)
    restored = _restore_database(result.path, tmp_path / "restored-wal.db")

    assert restored.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
    assert restored.execute("SELECT value FROM durable").fetchone()[0] == "committed-in-wal"
    restored.close()
    live.close()


def test_backup_uses_legacy_database_when_it_is_the_active_path(tmp_path, monkeypatch) -> None:
    paths = _patch_backup_paths(monkeypatch, tmp_path)
    paths["APP_DIR"].mkdir(parents=True)
    paths["LEGACY_DB_PATH"].parent.mkdir(parents=True)
    legacy = sqlite3.connect(paths["LEGACY_DB_PATH"])
    legacy.execute("CREATE TABLE legacy_jobs (url TEXT)")
    legacy.execute("INSERT INTO legacy_jobs VALUES ('https://legacy.example/job')")
    legacy.commit()
    legacy.close()

    result = create_backup(out=tmp_path / "legacy-backup.zip", include_outputs=False)
    restored = _restore_database(result.path, tmp_path / "restored-legacy.db")

    assert restored.execute("SELECT url FROM legacy_jobs").fetchone()[0] == "https://legacy.example/job"
    restored.close()


def test_backup_rejects_source_and_link_targets_before_write(tmp_path, monkeypatch) -> None:
    paths = _patch_backup_paths(monkeypatch, tmp_path)
    paths["APP_DIR"].mkdir(parents=True)
    source = sqlite3.connect(paths["DB_PATH"])
    source.execute("CREATE TABLE keep (value TEXT)")
    source.execute("INSERT INTO keep VALUES ('database remains intact')")
    source.commit()
    source.close()
    original = paths["DB_PATH"].read_bytes()

    with pytest.raises(ValueError, match="backup output"):
        create_backup(out=paths["DB_PATH"], include_outputs=False)
    assert paths["DB_PATH"].read_bytes() == original

    linked = tmp_path / "linked-backup.zip"
    linked.write_text("existing", encoding="utf-8")
    monkeypatch.setattr(backup_mod, "_is_link_or_reparse", lambda path: path == linked)
    with pytest.raises(ValueError, match="link or reparse"):
        create_backup(out=linked, include_outputs=False)
    assert linked.read_text(encoding="utf-8") == "existing"


def test_backup_failure_preserves_existing_target(tmp_path, monkeypatch) -> None:
    paths = _patch_backup_paths(monkeypatch, tmp_path)
    paths["APP_DIR"].mkdir(parents=True)
    source = sqlite3.connect(paths["DB_PATH"])
    source.execute("CREATE TABLE value (id INTEGER)")
    source.commit()
    source.close()
    out = tmp_path / "existing-backup.zip"
    out.write_bytes(b"prior-valid-backup")

    def fail_snapshot(_source: Path, _destination: Path) -> None:
        raise sqlite3.DatabaseError("snapshot failed")

    monkeypatch.setattr(backup_mod, "_snapshot_database", fail_snapshot)

    with pytest.raises(sqlite3.DatabaseError, match="snapshot failed"):
        create_backup(out=out, include_outputs=False)
    assert out.read_bytes() == b"prior-valid-backup"
