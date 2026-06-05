from __future__ import annotations

from typer.testing import CliRunner

from divapply.cli import app


runner = CliRunner()


def test_short_help_flag_works_for_run_command() -> None:
    result = runner.invoke(app, ["run", "-h"])

    assert result.exit_code == 0
    assert "Run pipeline stages" in result.output


def test_ultimate_help_describes_targeted_resume_not_general_resume() -> None:
    result = runner.invoke(app, ["ultimate", "-h"])

    assert result.exit_code == 0
    assert "Generate one targeted resume" in result.output
    assert "general-purpose" not in result.output
