from __future__ import annotations

from typer.testing import CliRunner

import divapply.config as config
import divapply.pipeline as pipeline
from divapply import cli
from divapply.cli import app


runner = CliRunner()


def test_short_help_flag_works_for_run_command() -> None:
    result = runner.invoke(app, ["run", "-h"])

    assert result.exit_code == 0
    assert "Run pipeline stages" in result.output


def test_run_prune_score_requires_confirmation(monkeypatch) -> None:
    called = False

    monkeypatch.setattr(cli, "_bootstrap", lambda: None)
    monkeypatch.setattr(config, "check_tier", lambda *args, **kwargs: None)

    def fake_run_pipeline(*args, **kwargs):
        nonlocal called
        called = True
        return {"errors": {}}

    monkeypatch.setattr(pipeline, "run_pipeline", fake_run_pipeline)

    result = runner.invoke(app, ["run", "score", "--prune-score", "3"], input="n\n")

    assert result.exit_code == 0
    assert "Cancelled" in result.output
    assert called is False


def test_run_prune_score_yes_executes(monkeypatch) -> None:
    received: dict = {}

    monkeypatch.setattr(cli, "_bootstrap", lambda: None)
    monkeypatch.setattr(config, "check_tier", lambda *args, **kwargs: None)

    def fake_run_pipeline(*args, **kwargs):
        received.update(kwargs)
        return {"errors": {}}

    monkeypatch.setattr(pipeline, "run_pipeline", fake_run_pipeline)

    result = runner.invoke(app, ["run", "score", "--prune-score", "3", "--yes"])

    assert result.exit_code == 0
    assert received["prune_below"] == 3


def test_apply_cost_guard_allows_default_real_single_job() -> None:
    assert cli._apply_cost_guard_message(
        dry_run=False,
        allow_expensive=False,
        continuous=False,
        workers=1,
        effective_limit=1,
    ) is None


def test_apply_cost_guard_blocks_accidental_expensive_real_runs() -> None:
    message = cli._apply_cost_guard_message(
        dry_run=False,
        allow_expensive=False,
        continuous=False,
        workers=2,
        effective_limit=10,
    )

    assert message is not None
    assert "Cost guard blocked" in message


def test_apply_cost_guard_allows_dry_run_and_explicit_override() -> None:
    assert cli._apply_cost_guard_message(
        dry_run=True,
        allow_expensive=False,
        continuous=True,
        workers=4,
        effective_limit=0,
    ) is None
    assert cli._apply_cost_guard_message(
        dry_run=False,
        allow_expensive=True,
        continuous=True,
        workers=4,
        effective_limit=0,
    ) is None


def test_credentials_command_writes_local_credentials(tmp_path, monkeypatch) -> None:
    credentials_path = tmp_path / "credentials.yaml"

    monkeypatch.setattr(cli, "_bootstrap", lambda: None)
    monkeypatch.setattr(config, "CREDENTIALS_PATH", credentials_path)
    monkeypatch.setattr(config, "load_credentials", lambda path=None: {})

    result = runner.invoke(
        app,
        [
            "credentials",
            "--site",
            "workdayjobs.com",
            "--username",
            "person@example.com",
            "--password",
            "site-password",
        ],
    )

    assert result.exit_code == 0
    assert "Saved workdayjobs.com login" in result.output
    assert "site-password" not in result.output
    saved = credentials_path.read_text(encoding="utf-8")
    assert "workdayjobs.com" in saved
    assert "person@example.com" in saved
    assert "site-password" in saved
