from __future__ import annotations

import re
import subprocess
import tomllib
from pathlib import Path

import yaml


ROOT = Path(__file__).resolve().parents[1]
WORKFLOW_DIR = ROOT / ".github" / "workflows"


def test_private_applicant_artifacts_cannot_be_tracked() -> None:
    tracked = subprocess.check_output(["git", "ls-files"], cwd=ROOT, text=True, encoding="utf-8").splitlines()
    private_prefixes = (
        ".divapply/",
        ".applypilot/",
        "apply-workers/",
        "apply_logs/",
        "backups/",
        "chrome-workers/",
        "coursework/",
        "logs/",
        "qa-renders/",
        "screenshots/",
        "social_screenshots/",
        "tmp/",
        "tailored_resumes/",
        "cover_letters/",
        "transcripts/",
    )
    private_names = {
        ".env",
        "answers.yaml",
        "credentials.yaml",
        "divapply.db",
        "profile.json",
        "resume.pdf",
        "resume.txt",
        "searches.yaml",
    }

    leaked = [
        path
        for path in tracked
        if path.startswith(private_prefixes)
        or Path(path).name in private_names
        or Path(path).suffix.casefold() in {".db", ".sqlite", ".sqlite3", ".log"}
    ]

    assert leaked == [], f"Private applicant artifacts are tracked: {leaked}"


def test_v48_public_location_fixtures_use_only_fictional_sentinels() -> None:
    fixture_paths = (
        ROOT / "profile.example.json",
        ROOT / "tests" / "test_apply_prompt.py",
        ROOT / "tests" / "test_editor.py",
    )
    field_pattern = re.compile(
        r'["\'](?P<key>address|city|city_state|province_state|postal_code)["\']'
        r'\s*:\s*["\'](?P<value>[^"\']+)["\']'
    )
    seen: set[str] = set()

    for path in fixture_paths:
        for match in field_pattern.finditer(path.read_text(encoding="utf-8")):
            key = match.group("key")
            value = match.group("value")
            seen.add(key)
            if key == "postal_code":
                assert value == "00000", f"{path.name}: postal fixture must use 00000"
            elif key == "province_state":
                assert value in {"YY", "ZZ"}, f"{path.name}: state fixture must be fictional"
            else:
                assert re.search(r"example|sample", value, re.IGNORECASE), (
                    f"{path.name}: {key} fixture must be unmistakably fictional"
                )

    assert seen == {"address", "city", "city_state", "province_state", "postal_code"}


def test_v49_release_version_is_consistent_and_not_retired() -> None:
    project_version = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))["project"][
        "version"
    ]
    init_text = (ROOT / "src" / "divapply" / "__init__.py").read_text(encoding="utf-8")
    init_match = re.search(r'__version__\s*=\s*"([^"]+)"', init_text)
    lock = tomllib.loads((ROOT / "uv.lock").read_text(encoding="utf-8"))
    lock_version = next(package["version"] for package in lock["package"] if package["name"] == "divapply")

    assert init_match is not None
    assert project_version == init_match.group(1) == lock_version
    assert project_version not in {"0.4.2", "0.4.3", "0.4.4", "0.4.5", "0.4.6", "0.4.7", "0.4.8"}
    assert f"## {project_version}" in (ROOT / "CHANGELOG.md").read_text(encoding="utf-8")

    publish = _workflow_text("publish.yml")
    assert 'tag_version = "${{ github.ref_name }}".removeprefix("v")' in publish
    assert "tag_version != pyproject_version or tag_version != init_version" in publish


def _workflow_text(name: str) -> str:
    return (WORKFLOW_DIR / name).read_text(encoding="utf-8")


def _workflow_data(name: str) -> dict:
    return yaml.safe_load(_workflow_text(name))


def test_external_actions_are_immutable_and_version_documented() -> None:
    action_line = re.compile(
        r"^\s*uses:\s+(?P<action>[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+)@"
        r"(?P<ref>[^\s#]+)(?:\s+#\s+(?P<version>v?\d+\.\d+\.\d+))?\s*$"
    )
    references: list[tuple[Path, int, str, str | None]] = []

    for workflow in sorted(WORKFLOW_DIR.glob("*.yml")):
        for line_number, line in enumerate(workflow.read_text(encoding="utf-8").splitlines(), start=1):
            match = action_line.match(line)
            if match:
                references.append((workflow, line_number, match.group("ref"), match.group("version")))

    assert references, "No external GitHub Actions were discovered"
    for workflow, line_number, action_ref, version in references:
        location = f"{workflow.relative_to(ROOT)}:{line_number}"
        assert re.fullmatch(r"[0-9a-f]{40}", action_ref), f"{location} must pin a full commit SHA"
        assert version is not None, f"{location} must document the release tag behind the pinned SHA"


def test_ci_enforces_locked_dependencies_coverage_and_cross_platform_types() -> None:
    ci = _workflow_text("ci.yml")
    project = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))

    assert "uv sync --locked" in ci
    assert "uv lock --check" in ci
    assert "uv run coverage run -m pytest -q" in ci
    assert "uv run coverage report" in ci
    assert "uv run mypy --platform linux src/divapply" in ci
    assert "uv run mypy --platform win32 src/divapply" in ci
    assert 'node-version: "24.18.0"' in ci
    assert "npm ci --omit=dev --ignore-scripts --no-audit --no-fund" in ci
    assert "npm audit --omit=dev --audit-level=high" in ci
    assert "python -m build --no-isolation" in ci

    dev_requirements = project["project"]["optional-dependencies"]["dev"]
    dev_packages = {re.split(r"[<>=!~\[]", requirement, maxsplit=1)[0].lower() for requirement in dev_requirements}
    assert {"build", "coverage", "hatchling", "mypy", "pip-audit", "pytest", "ruff", "twine"} <= dev_packages
    assert project["build-system"]["requires"] == ["hatchling==1.31.0"]

    assert project["tool"]["coverage"]["run"]["branch"] is True
    assert project["tool"]["coverage"]["report"]["fail_under"] >= 50
    assert project["tool"]["mypy"]["python_version"] == "3.11"

    lock = tomllib.loads((ROOT / "uv.lock").read_text(encoding="utf-8"))
    assert lock["version"] >= 1

    dependabot = _workflow_text("../dependabot.yml")
    assert 'package-ecosystem: "npm"' in dependabot
    assert 'directory: "/src/divapply/mcp_runtime_assets"' in dependabot
    assert 'package-ecosystem: "docker"' in dependabot
    assert 'directory: "/"' in dependabot


def test_container_build_uses_immutable_locked_inputs() -> None:
    dockerfile = (ROOT / "Dockerfile").read_text(encoding="utf-8")

    assert re.search(r"^FROM python:3\.12-slim@sha256:[0-9a-f]{64}$", dockerfile, re.MULTILINE)
    assert re.search(
        r"^COPY --from=ghcr\.io/astral-sh/uv:0\.11\.28@sha256:[0-9a-f]{64} /uv /uvx /bin/$",
        dockerfile,
        re.MULTILINE,
    )
    assert "COPY pyproject.toml uv.lock README.md LICENSE ./" in dockerfile
    assert "uv sync --locked --no-dev --extra full --no-install-project" in dockerfile
    assert "uv sync --locked --no-dev --extra full --no-editable" in dockerfile
    assert "python_jobspy-1.1.82-py3-none-any.whl" in dockerfile
    assert "sha256=93d638b35ffd30a714253e065907f68c5bac624e3937a3ad2ba09f618a072ee9" in dockerfile
    assert "pip install --upgrade" not in dockerfile
    assert 'pip install ".[full]"' not in dockerfile


def test_release_verification_and_build_use_the_lockfile() -> None:
    release = _workflow_text("publish.yml")
    ci = _workflow_text("ci.yml")

    assert release.count("uv sync --locked") >= 2
    assert "uv lock --check" in release
    assert "uv run pip-audit" in release
    assert "pip install --upgrade pip build twine" not in release
    assert "python -m build --no-isolation" in release
    for workflow in (ci, release):
        assert "python_jobspy-1.1.82-py3-none-any.whl" in workflow
        assert "sha256=93d638b35ffd30a714253e065907f68c5bac624e3937a3ad2ba09f618a072ee9" in workflow
        assert "python -m pip install --no-deps python-jobspy\n" not in workflow


def test_ci_executes_native_windows_gate_and_cmd_smoke() -> None:
    workflow = _workflow_data("ci.yml")
    windows = workflow["jobs"]["windows"]
    steps = "\n".join(str(step.get("run", "")) for step in windows["steps"])

    assert windows["runs-on"] == "windows-latest"
    assert "uv sync --locked --extra dev --extra full" in steps
    assert "uv run pytest -q" in steps
    assert "uv run ruff check ." in steps
    assert "uv run mypy --platform win32 src/divapply" in steps
    assert ".\\scripts\\divapply.cmd --version" in steps
    assert "windows" in workflow["jobs"]["package"]["needs"]
    assert "windows" in workflow["jobs"]["container"]["needs"]


def test_release_builds_read_only_then_promotes_without_checkout() -> None:
    workflow = _workflow_data("publish.yml")
    jobs = workflow["jobs"]
    build = jobs["build"]
    pypi = jobs["publish-pypi"]
    github_release = jobs["publish-github"]
    attest = jobs["attest-release"]

    assert build["permissions"] == {"contents": "read"}
    assert build["needs"] == "verify"
    assert set(pypi["needs"]) == {"build", "attest-release"}
    assert pypi["permissions"] == {"contents": "read", "id-token": "write"}
    assert set(github_release["needs"]) == {"build", "attest-release", "publish-pypi"}
    assert github_release["permissions"] == {"contents": "write"}
    assert attest["needs"] == "build"
    assert attest["permissions"] == {
        "id-token": "write",
        "attestations": "write",
        "artifact-metadata": "write",
    }

    build_text = "\n".join(str(step) for step in build["steps"])
    pypi_text = "\n".join(str(step) for step in pypi["steps"])
    github_text = "\n".join(str(step) for step in github_release["steps"])
    attest_text = "\n".join(str(step) for step in attest["steps"])
    assert "python -m build --no-isolation" in build_text
    assert "actions/upload-artifact@" in build_text
    assert "actions/checkout@" not in pypi_text
    assert "actions/download-artifact@" in pypi_text
    assert "pypa/gh-action-pypi-publish@" in pypi_text
    assert "actions/checkout@" not in github_text
    assert "actions/download-artifact@" in github_text
    assert "softprops/action-gh-release@" in github_text
    assert "actions/checkout@" not in attest_text
    assert "actions/download-artifact@" in attest_text
    assert "actions/attest@" in attest_text
    assert "subject-checksums" in attest_text
    assert "release/SHA256SUMS" in attest_text
    assert pypi["steps"][-1]["with"]["packages-dir"] == "release/packages/"
    assert "tools/build_release_evidence.py" in build_text
    assert "release/*.cdx.json" in github_text
    assert "release/SHA256SUMS" in github_text

    for job in jobs.values():
        permissions = job.get("permissions", {})
        assert not (permissions.get("contents") == "write" and permissions.get("id-token") == "write")


def test_all_workflow_checkouts_disable_persisted_credentials() -> None:
    for workflow_name in ("ci.yml", "publish.yml"):
        jobs = _workflow_data(workflow_name)["jobs"]
        for job_name, job in jobs.items():
            for step in job.get("steps", []):
                if "actions/checkout@" not in str(step.get("uses", "")):
                    continue
                assert step.get("with", {}).get("persist-credentials") is False, (
                    f"{workflow_name}:{job_name} checkout must disable persisted credentials"
                )


def test_local_preflight_matches_ci_quality_and_supply_chain_gates() -> None:
    preflight = (ROOT / "tools" / "preflight.ps1").read_text(encoding="utf-8")

    assert "uv lock --check" in preflight
    assert "uv sync --locked --extra dev --extra full" in preflight
    assert "mypy --platform linux src/divapply" in preflight
    assert "mypy --platform win32 src/divapply" in preflight
    assert "coverage run -m pytest -q" in preflight
    assert "coverage report" in preflight
    assert "python -m build --no-isolation" in preflight
    assert "npm audit --omit=dev --audit-level=high" in preflight
    assert "pip install --upgrade build twine" not in preflight
    assert "tools/build_release_evidence.py" in preflight
    assert "tools/check_private_collisions.py" in preflight
    assert "--profile $privateProfile" in preflight
    assert "--dist-dir" in preflight


def test_local_quality_artifacts_are_ignored() -> None:
    ignored = (ROOT / ".gitignore").read_text(encoding="utf-8").splitlines()

    assert ".coverage" in ignored
    assert "coverage.xml" in ignored
    assert ".mypy_cache/" in ignored
