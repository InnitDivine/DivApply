from __future__ import annotations

import os
from pathlib import Path
import time

import pytest
from typer.testing import CliRunner

from divapply import config
from divapply import cli
from divapply import database
from divapply import maintenance
from divapply.cli import app
from divapply.maintenance import cleanup_artifacts, cleanup_expired_logs


runner = CliRunner()


def _patch_cleanup_paths(monkeypatch, tmp_path: Path) -> Path:
    app_dir = tmp_path / "app"
    monkeypatch.setattr(config, "APP_DIR", app_dir)
    monkeypatch.setattr(config, "USER_CONFIG_DIR", app_dir / "config")
    app_dir.mkdir(parents=True)
    (app_dir / "config").mkdir()
    return app_dir


def test_cleanup_artifacts_previews_generated_dashboard_and_backup_files(tmp_path, monkeypatch) -> None:
    app_dir = _patch_cleanup_paths(monkeypatch, tmp_path)
    tailored_dir = app_dir / "tailored_resumes"
    cover_dir = app_dir / "cover_letters"
    tailored_dir.mkdir()
    cover_dir.mkdir()
    monkeypatch.setattr(config, "TAILORED_DIR", tailored_dir)
    monkeypatch.setattr(config, "COVER_LETTER_DIR", cover_dir)
    stale_files = {
        app_dir / "dashboard.perf-before.html",
        app_dir / "dashboard-bench-repeat.html",
        app_dir / "profile.json.bak-simplify-20260610T233316",
        app_dir / "config" / "sites.yaml.bak-20260608T220818",
        tailored_dir / "Indeed_Support.txt",
        tailored_dir / "Indeed_Support_JOB.txt",
        tailored_dir / "Indeed_Support_REPORT.json",
        cover_dir / "Indeed_Support_CL.txt",
    }
    for path in stale_files:
        path.write_text("stale", encoding="utf-8")
    keep_pdf = tailored_dir / "Indeed_Support.pdf"
    keep_pdf.write_text("pdf", encoding="utf-8")
    (app_dir / "dashboard.html").write_text("current", encoding="utf-8")
    backup = app_dir / "backups" / "divapply-backup-20260606T073702Z.zip"
    backup.parent.mkdir()
    backup.write_text("backup", encoding="utf-8")

    result = cleanup_artifacts(dry_run=True, include_backups=True)

    assert set(result.candidates) == stale_files | {backup}
    assert result.deleted == ()
    assert all(path.exists() for path in result.candidates)
    assert (app_dir / "dashboard.html").exists()
    assert keep_pdf.exists()


def test_cleanup_artifacts_deletes_only_selected_files_and_requires_backup_flag(tmp_path, monkeypatch) -> None:
    app_dir = _patch_cleanup_paths(monkeypatch, tmp_path)
    stale_dashboard = app_dir / "dashboard-bench-final.html"
    stale_dashboard.write_text("stale", encoding="utf-8")
    backup = app_dir / "backups" / "divapply-backup-20260606T073702Z.zip"
    backup.parent.mkdir()
    backup.write_text("backup", encoding="utf-8")

    result = cleanup_artifacts(dry_run=False, include_backups=False)

    assert result.deleted == (stale_dashboard,)
    assert not stale_dashboard.exists()
    assert backup.exists()

    result = cleanup_artifacts(dry_run=False, include_backups=True)

    assert result.deleted == (backup,)
    assert not backup.exists()
    assert not backup.parent.exists()


def test_cleanup_artifacts_skips_symlink_candidates(tmp_path, monkeypatch) -> None:
    app_dir = _patch_cleanup_paths(monkeypatch, tmp_path)
    target = app_dir / "real-dashboard.html"
    target.write_text("keep", encoding="utf-8")
    symlink = app_dir / "dashboard-bench-link.html"
    try:
        symlink.symlink_to(target)
    except OSError as exc:
        pytest.skip(f"symlinks unavailable in this environment: {exc}")

    result = cleanup_artifacts(dry_run=False)

    assert symlink in result.candidates
    assert result.deleted == ()
    assert result.skipped == (symlink,)
    assert symlink.exists()
    assert target.exists()


def test_cleanup_command_is_preview_by_default(tmp_path, monkeypatch) -> None:
    app_dir = _patch_cleanup_paths(monkeypatch, tmp_path)
    stale_file = app_dir / "dashboard.perf-after.html"
    stale_file.write_text("stale", encoding="utf-8")

    result = runner.invoke(app, ["cleanup"])

    assert result.exit_code == 0
    assert "Would remove" in result.output
    assert "cleanup --yes" in result.output
    assert stale_file.exists()


def test_cleanup_command_deletes_with_yes(tmp_path, monkeypatch) -> None:
    app_dir = _patch_cleanup_paths(monkeypatch, tmp_path)
    stale_file = app_dir / "dashboard-bench-after.html"
    stale_file.write_text("stale", encoding="utf-8")

    result = runner.invoke(app, ["cleanup", "--yes"])

    assert result.exit_code == 0
    assert "Removed" in result.output
    assert not stale_file.exists()


def test_cleanup_expired_logs_removes_only_old_regular_files(tmp_path, monkeypatch) -> None:
    app_dir = _patch_cleanup_paths(monkeypatch, tmp_path)
    logs = app_dir / "logs"
    logs.mkdir()
    monkeypatch.setattr(config, "LOG_DIR", logs)
    old = logs / "worker-0.log"
    fresh = logs / "worker-1.log"
    outside = tmp_path / "outside.log"
    old.write_text("old", encoding="utf-8")
    fresh.write_text("fresh", encoding="utf-8")
    outside.write_text("keep", encoding="utf-8")
    now = time.time()
    os.utime(old, (now - 31 * 86400, now - 31 * 86400))
    linked = logs / "linked.log"
    try:
        linked.symlink_to(outside)
        os.utime(linked, (now - 31 * 86400, now - 31 * 86400), follow_symlinks=False)
    except OSError:
        linked = None

    result = cleanup_expired_logs(retention_days=30, now=now)

    assert result.deleted == (old,)
    assert not old.exists()
    assert fresh.exists()
    assert outside.exists()
    if linked is not None:
        assert linked in result.skipped
        assert linked.exists()


def test_bootstrap_enforces_log_retention_after_directories_exist(monkeypatch) -> None:
    calls: list[str] = []
    monkeypatch.setattr(config, "load_env", lambda: calls.append("env"))
    monkeypatch.setattr(config, "ensure_dirs", lambda: calls.append("dirs"))
    monkeypatch.setattr(maintenance, "cleanup_expired_logs", lambda: calls.append("logs"))
    monkeypatch.setattr(database, "init_db", lambda: calls.append("db"))

    cli._bootstrap()

    assert calls == ["env", "dirs", "logs", "db"]
