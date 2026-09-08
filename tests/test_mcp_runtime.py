from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest

from divapply import mcp_runtime


def test_bundled_mcp_dependencies_are_exact_and_integrity_locked() -> None:
    manifest = json.loads(mcp_runtime.read_bundled_asset("package.json"))
    lock = json.loads(mcp_runtime.read_bundled_asset("package-lock.json"))

    expected = {"@playwright/mcp": "0.0.80"}
    assert manifest["dependencies"] == expected
    assert lock["packages"][""]["dependencies"] == expected

    registry_entries = [
        entry
        for entry in lock["packages"].values()
        if str(entry.get("resolved", "")).startswith("https://registry.npmjs.org/")
    ]
    assert registry_entries
    assert all(str(entry.get("integrity", "")).startswith("sha512-") for entry in registry_entries)


def test_compatible_node_executable_accepts_node_20(tmp_path, monkeypatch) -> None:
    node = tmp_path / "node.exe"
    node.touch()
    monkeypatch.setattr(mcp_runtime.shutil, "which", lambda name: str(node) if name == "node" else None)
    monkeypatch.setattr(
        mcp_runtime.subprocess,
        "run",
        lambda command, **kwargs: subprocess.CompletedProcess(command, 0, stdout="v20.19.4\n"),
    )

    assert mcp_runtime.compatible_node_executable() == node.resolve()


def test_compatible_npm_executable_prefers_windows_command_wrapper(tmp_path, monkeypatch) -> None:
    extensionless = tmp_path / "npm"
    command_wrapper = tmp_path / "npm.cmd"
    extensionless.touch()
    command_wrapper.touch()
    candidates = {"npm": str(extensionless), "npm.cmd": str(command_wrapper)}
    monkeypatch.setattr(mcp_runtime.shutil, "which", candidates.get)

    assert mcp_runtime.compatible_npm_executable(windows=True) == command_wrapper.resolve()


def test_compatible_npm_executable_rejects_extensionless_windows_shim(tmp_path, monkeypatch) -> None:
    extensionless = tmp_path / "npm"
    extensionless.touch()
    monkeypatch.setattr(
        mcp_runtime.shutil,
        "which",
        lambda name: str(extensionless) if name == "npm" else None,
    )

    assert mcp_runtime.compatible_npm_executable(windows=True) is None


@pytest.mark.parametrize("version", [None, "v18.20.8", "not-a-node-version"])
def test_expected_mcp_runtime_rejects_missing_old_or_unparseable_node(tmp_path, monkeypatch, version) -> None:
    node = tmp_path / "node.exe"
    node.touch()
    monkeypatch.setattr(
        mcp_runtime.shutil,
        "which",
        lambda name: str(node) if name == "node" and version is not None else None,
    )
    monkeypatch.setattr(
        mcp_runtime.subprocess,
        "run",
        lambda command, **kwargs: subprocess.CompletedProcess(command, 0, stdout=version or ""),
    )

    with pytest.raises(RuntimeError, match=r"Node\.js 20\+"):
        mcp_runtime.expected_mcp_runtime(app_dir=tmp_path / "app")


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
        if command == [str(node), "--version"]:
            return subprocess.CompletedProcess(command, 0, stdout="v20.19.4")
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
        if command == [str(node), "--version"]:
            return subprocess.CompletedProcess(command, 0, stdout="v20.19.4")
        raise subprocess.CalledProcessError(1, command, output="registry failure")

    monkeypatch.setattr(mcp_runtime.subprocess, "run", fail_install)

    expected = mcp_runtime.expected_mcp_runtime(app_dir=tmp_path / "app")
    with pytest.raises(RuntimeError, match="locked MCP runtime"):
        mcp_runtime.ensure_mcp_runtime(app_dir=tmp_path / "app")

    assert not expected.root.exists()


def _fake_locked_runtime(tmp_path: Path) -> mcp_runtime.McpRuntime:
    node = tmp_path / "node.exe"
    root = tmp_path / "mcp-runtime"
    playwright_script = root / "node_modules" / "@playwright" / "mcp" / "cli.js"
    playwright_core = root / "node_modules" / "playwright-core"
    playwright_script.parent.mkdir(parents=True)
    playwright_core.mkdir(parents=True)
    node.touch()
    playwright_script.touch()
    (playwright_core / "package.json").write_text("{}", encoding="utf-8")
    return mcp_runtime.McpRuntime(
        node=node,
        root=root,
        playwright_script=playwright_script,
        lock_digest="test-digest",
    )


@pytest.mark.parametrize("browser", ["chrome", "msedge"])
def test_ensure_mcp_browser_keeps_system_browser_channels_unmanaged(tmp_path, monkeypatch, browser) -> None:
    monkeypatch.setattr(
        mcp_runtime.subprocess,
        "run",
        lambda *_args, **_kwargs: pytest.fail("system browser channels must not run Playwright installers"),
    )

    assert mcp_runtime.ensure_mcp_browser(browser) is None


@pytest.mark.parametrize("browser", ["chromium", "firefox", "webkit"])
def test_ensure_mcp_browser_uses_locked_cli_and_verifies_executable(
    tmp_path,
    monkeypatch,
    browser,
) -> None:
    runtime = _fake_locked_runtime(tmp_path)
    executable = (tmp_path / "browsers" / browser / f"{browser}.exe").resolve()
    install_calls: list[list[str]] = []

    def fake_run(command: list[str], **kwargs) -> subprocess.CompletedProcess[str]:
        assert kwargs["cwd"] == runtime.root
        assert "NODE_OPTIONS" not in kwargs["env"]
        assert command[0] == str(runtime.node)
        if command[1] == "-e":
            assert command[-2:] == [str(runtime.root / "node_modules" / "playwright-core"), browser]
            return subprocess.CompletedProcess(command, 0, stdout=str(executable))
        install_calls.append(command)
        executable.parent.mkdir(parents=True)
        executable.touch()
        return subprocess.CompletedProcess(command, 0, stdout="installed")

    monkeypatch.setattr(mcp_runtime.subprocess, "run", fake_run)
    monkeypatch.setenv("NODE_OPTIONS", "--require=attacker.js")

    assert mcp_runtime.ensure_mcp_browser(browser, runtime=runtime) == executable
    assert install_calls == [
        [str(runtime.node), str(runtime.playwright_script), "install-browser", browser]
    ]

    assert mcp_runtime.ensure_mcp_browser(browser, runtime=runtime) == executable
    assert len(install_calls) == 1


def test_ensure_mcp_browser_rejects_install_without_executable(tmp_path, monkeypatch) -> None:
    runtime = _fake_locked_runtime(tmp_path)
    missing_executable = (tmp_path / "browsers" / "chromium" / "chrome.exe").resolve()

    def fake_run(command: list[str], **kwargs) -> subprocess.CompletedProcess[str]:
        output = str(missing_executable) if command[1] == "-e" else "installed"
        return subprocess.CompletedProcess(command, 0, stdout=output)

    monkeypatch.setattr(mcp_runtime.subprocess, "run", fake_run)

    with pytest.raises(RuntimeError, match="without its executable"):
        mcp_runtime.ensure_mcp_browser("chromium", runtime=runtime)


def test_apply_runtime_sources_do_not_use_npx() -> None:
    root = Path(__file__).resolve().parents[1]
    for relative in (
        "src/divapply/apply/launcher.py",
        "src/divapply/cli.py",
        "src/divapply/runtime.py",
    ):
        assert "npx" not in (root / relative).read_text(encoding="utf-8").lower()
