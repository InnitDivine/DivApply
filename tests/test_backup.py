from __future__ import annotations

import zipfile
from pathlib import Path

from divapply.backup import create_backup
from divapply import cli


def _patch_backup_paths(monkeypatch, tmp_path: Path) -> None:
    import divapply.config as config

    app_dir = tmp_path / "app"
    paths = {
        "APP_DIR": app_dir,
        "DB_PATH": app_dir / "divapply.db",
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
    cli.backup(out=out, include_secrets=False, include_outputs=False)

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
    cli.backup(out=out, include_secrets=False, include_outputs=True)

    with zipfile.ZipFile(out) as archive:
        names = set(archive.namelist())

    assert "logs/worker-0.log" in names
    assert "logs/prompt_example.txt" not in names


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
    cli.backup(out=out, include_secrets=False, include_outputs=True)

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
    cli.backup(out=out, include_secrets=True, include_outputs=True)

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
    result = create_backup(out=out, include_secrets=False, include_outputs=True)

    with zipfile.ZipFile(out) as archive:
        names = set(archive.namelist())

    assert result.file_count == 1
    assert names == {"logs/regular.log"}
