from __future__ import annotations

import re
import os
import subprocess
import sys
import tomllib
from pathlib import Path

import pytest
from typer.testing import CliRunner

import divapply.config as config
import divapply.database as database
import divapply.pipeline as pipeline
from divapply import cli
from divapply.cli import app


runner = CliRunner()
ROOT = Path(__file__).resolve().parents[1]


def test_console_script_and_module_entrypoint_report_same_version() -> None:
    scripts_dir = Path(sys.executable).resolve().parent
    launcher = scripts_dir / ("divapply.cmd" if os.name == "nt" else "divapply")
    if not launcher.exists():
        pytest.skip("DivApply script launcher is not installed for this interpreter")
    try:
        console_result = subprocess.run(
            [str(launcher), "--version"],
            check=True,
            capture_output=True,
            text=True,
        )
    except OSError as exc:
        if getattr(exc, "winerror", None) == 4551:
            pytest.skip("Windows Application Control blocked the console-script launcher")
        raise
    module_result = subprocess.run(
        [sys.executable, "-m", "divapply", "--version"],
        check=True,
        capture_output=True,
        text=True,
    )

    assert console_result.stdout == module_result.stdout


def test_pyproject_keeps_secure_jobspy_install_contract() -> None:
    pyproject = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    dependencies = pyproject["project"]["dependencies"]
    extras = pyproject["project"]["optional-dependencies"]
    jobspy_runtime = {
        "numpy==1.26.3; python_version < '3.13'",
        "pydantic>=2.3.0,<3.0.0",
        "requests>=2.31.0,<3.0.0",
        "tls-client>=1.0.1,<2.0.0",
        "regex>=2024.4.28,<2025.0.0",
        "markdownify>=0.14.1",
    }

    assert "soupsieve>=2.8.4" in dependencies
    assert "beautifulsoup4>=4.12.2,<5.0.0" in dependencies
    assert "pandas>=2.1.0,<3.0.0" in dependencies
    assert "jobspy-upstream" not in extras
    assert jobspy_runtime <= set(extras["jobspy-runtime"])
    assert jobspy_runtime <= set(extras["full"])
    assert "pypdf>=6.13.3" in extras["coursework"]
    assert "pypdf>=6.13.3" in extras["full"]
    assert all("python-jobspy" not in dep for dep in extras["full"])

    bootstrap = (ROOT / "tools" / "bootstrap.ps1").read_text(encoding="utf-8")
    installer = (ROOT / "install.sh").read_text(encoding="utf-8")
    cli_source = (ROOT / "src" / "divapply" / "cli.py").read_text(encoding="utf-8")
    runtime_source = (ROOT / "src" / "divapply" / "jobspy_runtime.py").read_text(encoding="utf-8")
    for install_surface in (bootstrap, installer, runtime_source):
        assert "python_jobspy-1.1.82-py3-none-any.whl" in install_surface
        assert "sha256=93d638b35ffd30a714253e065907f68c5bac624e3937a3ad2ba09f618a072ee9" in install_surface
    assert "JOBSPY_WHEEL_URL" in cli_source
    assert "divapply.jobspy_runtime" in bootstrap
    assert "divapply.jobspy_runtime" in installer
    assert '"--no-deps", "python-jobspy")' not in bootstrap
    assert "pip install --no-deps python-jobspy\n" not in installer

    lock_text = (ROOT / "uv.lock").read_text(encoding="utf-8")
    assert "jobspy-upstream" not in lock_text
    assert 'name = "python-jobspy"' not in lock_text
    lock = tomllib.loads(lock_text)
    markdownify_versions = {
        tuple(int(part) for part in package["version"].split("."))
        for package in lock["package"]
        if package["name"] == "markdownify"
    }
    assert markdownify_versions
    assert min(markdownify_versions) >= (0, 14, 1)


def test_pyproject_uses_plain_script_launchers_for_windows_device_guard() -> None:
    pyproject = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    wheel = pyproject["tool"]["hatch"]["build"]["targets"]["wheel"]

    assert "scripts" not in pyproject["project"]
    assert wheel["shared-scripts"]["scripts/divapply"] == "divapply"
    assert wheel["shared-scripts"]["scripts/divapply.cmd"] == "divapply.cmd"
    assert (ROOT / "scripts" / "divapply.cmd").read_text(encoding="utf-8").startswith("@echo off")


def test_runtime_does_not_advertise_retired_captcha_solver_secret() -> None:
    for relative in ("src/divapply/cli.py", "src/divapply/wizard/init.py", ".env.example"):
        text = (ROOT / relative).read_text(encoding="utf-8")
        assert "CAPSOLVER_API_KEY" not in text


def test_dockerfile_uses_module_entrypoint_not_script_launcher() -> None:
    dockerfile = (ROOT / "Dockerfile").read_text(encoding="utf-8")

    assert 'ENTRYPOINT ["python", "-m", "divapply"]' in dockerfile
    assert "CMD python -m divapply selfcheck" in dockerfile


def test_readme_common_commands_match_registered_cli_commands() -> None:
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    common_commands = re.search(r"## Common Commands\s+```powershell\n(?P<body>.*?)\n```", readme, re.S)

    assert common_commands is not None
    documented = {
        line.split()[1]
        for line in common_commands.group("body").splitlines()
        if line.startswith("divapply ") and len(line.split()) > 1
    }
    registered = {
        command.name or command.callback.__name__.replace("_", "-")
        for command in cli.app.registered_commands
    }
    registered.update(group.name for group in cli.app.registered_groups)

    assert documented <= registered
    assert {
        "add-url",
        "credentials",
        "browser-login",
        "track",
        "followups",
        "analytics",
        "rescore",
        "answers",
        "prune",
        "sync",
    } <= documented


def test_install_docs_use_full_editable_and_entrypoint_parity_checks() -> None:
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    publishing = (ROOT / "PUBLISHING.md").read_text(encoding="utf-8")
    contributing = (ROOT / "CONTRIBUTING.md").read_text(encoding="utf-8")
    operations = (ROOT / "docs" / "OPERATIONS.md").read_text(encoding="utf-8")
    migration = (ROOT / "docs" / "MIGRATION.md").read_text(encoding="utf-8")
    cli_source = (ROOT / "src" / "divapply" / "cli.py").read_text(encoding="utf-8")

    assert 'python -m pip install -e ".[dev,full]"' in contributing
    assert "python -m divapply --version" in contributing
    assert "ruff check ." in contributing

    assert 'python -m pip install --upgrade "divapply[full]"' in operations
    assert "python -m divapply --version" in operations

    assert 'python -m pip install --upgrade "divapply[full]"' in readme
    assert 'pip install --upgrade "divapply[full]"' in publishing
    assert 'pip install --upgrade "divapply[full] @ git+https://github.com/InnitDivine/DivApply.git"' in publishing
    assert "pip install --upgrade 'divapply[full]'" in cli_source

    assert 'pip install ".[full]"' in migration
    assert 'pip install -e ".[dev,full]"' in migration
    for document in (readme, publishing, contributing, operations, migration):
        assert "python_jobspy-1.1.82-py3-none-any.whl" in document
        assert "sha256=93d638b35ffd30a714253e065907f68c5bac624e3937a3ad2ba09f618a072ee9" in document
        assert "pip install --no-deps python-jobspy==1.1.82" not in document


def test_import_coursework_preserves_json_status(tmp_path, monkeypatch) -> None:
    source = tmp_path / "coursework.json"
    source.write_text(
        '[{"school":"Example University","course_title":"Networking",'
        '"status":"Completed","credits":3}]',
        encoding="utf-8",
    )
    captured: list[dict] = []

    monkeypatch.setattr(cli, "_bootstrap", lambda: None)
    monkeypatch.setattr(
        database,
        "append_coursework",
        lambda entries: captured.extend(entries) or {"inserted": len(entries), "skipped": 0},
    )

    result = runner.invoke(app, ["import-coursework", str(source)])

    assert result.exit_code == 0
    assert captured[0]["status"] == "Completed"


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


def test_prune_accepts_maxscore_alias_in_dry_run(tmp_path, monkeypatch) -> None:
    db_path = tmp_path / "divapply.db"
    conn = database.init_db(db_path)
    conn.execute(
        "INSERT INTO jobs (url, title, fit_score, discovered_at) VALUES (?, ?, ?, ?)",
        ("https://example.com/low", "Low Fit", 4, "2026-01-01"),
    )
    conn.commit()
    database.close_connection(db_path)

    monkeypatch.setattr(cli, "_bootstrap", lambda: None)
    monkeypatch.setattr(database, "DB_PATH", db_path)
    monkeypatch.setattr(database, "LEGACY_DB_PATH", tmp_path / "missing.db")

    result = runner.invoke(app, ["prune", "--maxscore", "4", "--dry-run"])

    assert result.exit_code == 0
    assert "Dry run - no changes made." in result.output
    database.close_connection(db_path)


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


def test_apply_model_does_not_inherit_general_llm_model(monkeypatch) -> None:
    monkeypatch.setenv("LLM_MODEL", "gpt-5.4-nano")
    monkeypatch.delenv("LLM_MODEL_APPLY", raising=False)

    assert cli._resolve_apply_model("codex") == "gpt-5.4-mini"


def test_apply_model_prefers_apply_specific_env(monkeypatch) -> None:
    monkeypatch.setenv("LLM_MODEL", "gpt-5.4-nano")
    monkeypatch.setenv("LLM_MODEL_APPLY", "gpt-5.4-mini")

    assert cli._resolve_apply_model("codex") == "gpt-5.4-mini"
    assert cli._resolve_apply_model("codex", "custom-model") == "custom-model"


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


def test_browser_login_uses_persistent_worker_profile(tmp_path, monkeypatch) -> None:
    import subprocess

    from divapply.apply import chrome

    calls: list[list[str]] = []

    monkeypatch.setattr(cli, "_bootstrap", lambda: None)
    monkeypatch.setattr(config, "get_apply_browser", lambda browser=None: browser or "chromium")
    monkeypatch.setattr(chrome, "setup_worker_profile", lambda worker, browser: tmp_path / f"{browser}-{worker}")

    class Result:
        returncode = 0

    def fake_run(cmd):
        calls.append(cmd)
        return Result()

    monkeypatch.setattr(subprocess, "run", fake_run)

    result = runner.invoke(app, ["browser-login", "--url", "https://example.com/login", "--worker", "2"])

    assert result.exit_code == 0
    cmd = calls[0]
    assert "playwright" in cmd
    assert "--user-data-dir" in cmd
    assert str(tmp_path / "chromium-2") in cmd
    assert "https://example.com/login" in cmd


def test_browser_login_with_chrome_uses_direct_chrome_not_playwright(tmp_path, monkeypatch) -> None:
    import subprocess

    from divapply.apply import chrome

    calls: list[list[str]] = []

    monkeypatch.setattr(cli, "_bootstrap", lambda: None)
    monkeypatch.setattr(config, "get_apply_browser", lambda browser=None: browser or "chromium")
    monkeypatch.setattr(config, "get_chrome_path", lambda: "C:/Program Files/Google/Chrome/Application/chrome.exe")
    monkeypatch.setattr(chrome, "setup_worker_profile", lambda worker, browser: tmp_path / f"{browser}-{worker}")

    class Result:
        returncode = 0

    def fake_run(cmd):
        calls.append(cmd)
        return Result()

    monkeypatch.setattr(subprocess, "run", fake_run)

    result = runner.invoke(
        app,
        ["browser-login", "--browser", "chrome", "--url", "https://accounts.google.com/", "--worker", "0"],
    )

    assert result.exit_code == 0
    cmd = calls[0]
    assert cmd[0].endswith("chrome.exe")
    assert "playwright" not in cmd
    assert f"--user-data-dir={tmp_path / 'chrome-0'}" in cmd
    assert "https://accounts.google.com/" in cmd


def test_apply_uses_configured_browser_when_option_omitted(tmp_path, monkeypatch) -> None:
    from divapply.apply import launcher

    captured: dict[str, str | None] = {}
    profile_path = tmp_path / "profile.json"
    profile_path.write_text("{}", encoding="utf-8")
    prompt_path = tmp_path / "prompt.txt"
    prompt_path.write_text("prompt", encoding="utf-8")

    monkeypatch.setattr(cli, "_bootstrap", lambda: None)
    monkeypatch.setattr(config, "PROFILE_PATH", profile_path)
    monkeypatch.setenv("DIVAPPLY_BROWSER", "chrome")
    monkeypatch.setattr(config, "get_apply_backend", lambda backend=None: "codex")
    monkeypatch.setattr(config, "get_apply_backend_label", lambda backend: "Codex CLI")
    monkeypatch.setattr(config, "get_chrome_path", lambda: "C:/Program Files/Google/Chrome/Application/chrome.exe")
    monkeypatch.setattr(config, "check_tier", lambda *args, **kwargs: None)

    def fake_gen_prompt(*args, **kwargs):
        captured["browser"] = kwargs["browser"]
        return prompt_path

    monkeypatch.setattr(launcher, "gen_prompt", fake_gen_prompt)
    monkeypatch.setattr(launcher, "get_manual_command", lambda *args, **kwargs: "codex exec")

    result = runner.invoke(app, ["apply", "--gen", "--url", "https://example.com/job"])

    assert result.exit_code == 0
    assert captured["browser"] == "chrome"


def test_add_url_is_manual_review_until_official_source_refresh(tmp_path, monkeypatch) -> None:
    db_path = tmp_path / "divapply.db"
    conn = database.init_db(db_path)
    monkeypatch.setattr(cli, "_bootstrap", lambda: None)
    monkeypatch.setattr(database, "get_connection", lambda: conn)
    monkeypatch.setattr(
        config,
        "load_search_config",
        lambda: {
            "default_market_label": "Current market",
            "locations": [{"label": "Current market", "location": "Exampletown, YY"}],
            "market_policies": {"Current market": {"application_mode": "active"}},
        },
    )

    result = runner.invoke(
        app,
        [
            "add-url",
            "https://example.com/jobs/it-assistant",
            "--no-fetch",
            "--title",
            "IT Assistant",
            "--company",
            "Example Employer",
            "--location",
            "Exampletown, YY",
        ],
    )

    assert result.exit_code == 0
    row = conn.execute(
        "SELECT market_label, search_query, application_mode, source_verification, "
        "official_url_verified_at FROM jobs"
    ).fetchone()
    assert dict(row) == {
        "market_label": "Current market",
        "search_query": "manual_url",
        "application_mode": "manual_review",
        "source_verification": "unknown",
        "official_url_verified_at": None,
    }
    assert "official source verifies it" in result.output
    database.close_connection(db_path)


def test_add_url_metadata_prefers_jobposting_schema_over_hidden_inactive(monkeypatch) -> None:
    html = """
    <html>
      <head>
        <script type="application/ld+json">
        {
          "@context": "https://schema.org",
          "@type": "JobPosting",
          "title": "Device Support Technician I",
          "datePosted": "2026-06-21",
          "employmentType": "FULL_TIME",
          "description": "<p>Position Overview</p><p>Assists with ticket resolution, configurations, testing, installation, LANs, mobile devices, Windows, Apple OS/iOS, Active Directory, and network troubleshooting.</p><p>Pay Range is $25.89 to $37.55 / hour</p>",
          "hiringOrganization": {"@type": "Organization", "name": "Sutter Health"},
          "jobLocation": {
            "@type": "Place",
            "address": {
              "@type": "PostalAddress",
              "addressLocality": "West Valley",
              "addressRegion": "UT",
              "addressCountry": "USA"
            }
          }
        }
        </script>
      </head>
      <body>
        <section class="phw-d-none">
          <h2>We're Sorry, This Job Is Inactive</h2>
          <p>This opportunity has passed.</p>
        </section>
      </body>
    </html>
    """

    class Response:
        text = html

        def raise_for_status(self) -> None:
            return None

    class Client:
        def __init__(self, *args, **kwargs) -> None:
            pass

        def __enter__(self):
            return self

        def __exit__(self, *args) -> None:
            return None

        def get(self, *args, **kwargs):
            return Response()

    monkeypatch.setattr("httpx.Client", Client)

    metadata = cli._extract_manual_job_metadata(
        "https://jobs.sutterhealth.org/us/en/job/R-133284/Device-Support-Technician-I"
    )

    assert metadata["inactive"] is False
    assert metadata["title"] == "Device Support Technician I"
    assert metadata["company"] == "Sutter Health"
    assert metadata["location"] == "West Valley, UT, USA"
    assert "Active Directory" in str(metadata["description"])
    assert "This opportunity has passed" not in str(metadata["description"])


def test_add_url_metadata_prefers_full_body_over_meta_summary(monkeypatch) -> None:
    html = """
    <html>
      <head>
        <title>IT Support Technician</title>
        <meta name="description" content="Short summary for sharing.">
      </head>
      <body>
        <main>
          <h1>IT Support Technician</h1>
          <section class="job-description">
            <h2>Responsibilities</h2>
            <p>Troubleshoot laptops, user accounts, printers, phones, and network access.</p>
            <h2>Requirements</h2>
            <p>Experience with Windows, Active Directory, ticket documentation, and customer support.</p>
          </section>
        </main>
      </body>
    </html>
    """

    class Response:
        text = html

        def raise_for_status(self) -> None:
            return None

    class Client:
        def __init__(self, *args, **kwargs) -> None:
            pass

        def __enter__(self):
            return self

        def __exit__(self, *args) -> None:
            return None

        def get(self, *args, **kwargs):
            return Response()

    monkeypatch.setattr("httpx.Client", Client)

    metadata = cli._extract_manual_job_metadata("https://careers.example.com/jobs/it-support-technician")

    assert metadata["inactive"] is False
    assert "Troubleshoot laptops" in str(metadata["description"])
    assert "Active Directory" in str(metadata["description"])
    assert metadata["description"] != "Short summary for sharing."
