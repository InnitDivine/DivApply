from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest

from divapply import mcp_runtime


def test_bundled_mcp_dependencies_are_exact_and_integrity_locked() -> None:
    manifest = json.loads(mcp_runtime.read_bundled_asset("package.json"))
    lock = json.loads(mcp_runtime.read_bundled_asset("package-lock.json"))

    expected = {"@playwright/mcp": "0.0.78"}
    assert manifest["dependencies"] == expected
    assert lock["packages"][""]["dependencies"] == expected

    registry_entries = [
        entry
        for entry in lock["packages"].values()
        if str(entry.get("resolved", "")).startswith("https://registry.npmjs.org/")
    ]
    assert registry_entries
    assert all(str(entry.get("integrity", "")).startswith("sha512-") for entry in registry_entries)


def test_ensure_mcp_runtime_uses_frozen_scriptless_install_and_cache(tmp_path, monkeypatch) -> None:
    node = tmp_path / "bin" / "node.exe"
    npm = tmp_path / "bin" / "npm.cmd"
    node.parent.mkdir()
    node.touch()
    npm.touch()
    calls: list[tuple[list[str], Path, dict[str, str]]] = []

    def fake_which(name: str) -> str | None:
        return {"node": str(node), "npm": str(npm)}.get(name)

    def fake_run(command: list[str], **kwargs) -> subprocess.CompletedProcess[str]:
        stage = Path(kwargs["cwd"])
        calls.append((command, stage, kwargs["env"]))
        (stage / "node_modules" / "@playwright" / "mcp").mkdir(parents=True)
        (stage / "node_modules" / "@playwright" / "mcp" / "cli.js").touch()
        return subprocess.CompletedProcess(command, 0, stdout="installed")

    monkeypatch.setattr(mcp_runtime.shutil, "which", fake_which)
    monkeypatch.setattr(mcp_runtime.subprocess, "run", fake_run)
    monkeypatch.setenv("CAPSOLVER_API_KEY", "captcha-secret")
    monkeypatch.setenv("GITHUB_TOKEN", "github-secret")
    monkeypatch.setenv("NODE_OPTIONS", "--require=attacker.js")
    monkeypatch.setenv("NPM_TOKEN", "registry-secret")

    installed = mcp_runtime.ensure_mcp_runtime(app_dir=tmp_path / "app")

    assert calls[0][0] == [
        str(npm),
        "ci",
        "--omit=dev",
        "--ignore-scripts",
        "--no-audit",
        "--no-fund",
    ]
    install_env = calls[0][2]
    assert install_env["NPM_CONFIG_REGISTRY"] == "https://registry.npmjs.org/"
    assert Path(install_env["NPM_CONFIG_USERCONFIG"]).parent == calls[0][1]
    for secret_name in ("CAPSOLVER_API_KEY", "GITHUB_TOKEN", "NODE_OPTIONS", "NPM_TOKEN"):
        assert secret_name not in install_env
    assert installed.node == node.resolve()
    assert installed.playwright_script.is_file()
    assert installed.root.parent == (tmp_path / "app" / "mcp-runtime").resolve()

    assert mcp_runtime.ensure_mcp_runtime(app_dir=tmp_path / "app") == installed
    assert len(calls) == 1


def test_failed_mcp_install_is_not_promoted(tmp_path, monkeypatch) -> None:
    node = tmp_path / "node"
    npm = tmp_path / "npm"
    node.touch()
    npm.touch()
    monkeypatch.setattr(
        mcp_runtime.shutil,
        "which",
        lambda name: str(node if name == "node" else npm) if name in {"node", "npm"} else None,
    )

    def fail_install(command: list[str], **kwargs) -> subprocess.CompletedProcess[str]:
        raise subprocess.CalledProcessError(1, command, output="registry failure")

    monkeypatch.setattr(mcp_runtime.subprocess, "run", fail_install)

    expected = mcp_runtime.expected_mcp_runtime(app_dir=tmp_path / "app")
    with pytest.raises(RuntimeError, match="locked MCP runtime"):
        mcp_runtime.ensure_mcp_runtime(app_dir=tmp_path / "app")

    assert not expected.root.exists()


def test_apply_runtime_sources_do_not_use_npx() -> None:
    root = Path(__file__).resolve().parents[1]
    for relative in (
        "src/divapply/apply/launcher.py",
        "src/divapply/cli.py",
        "src/divapply/runtime.py",
    ):
        assert "npx" not in (root / relative).read_text(encoding="utf-8").lower()
