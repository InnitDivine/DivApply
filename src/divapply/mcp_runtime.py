"""Install and locate DivApply's integrity-locked Node.js MCP runtime."""

from __future__ import annotations

import hashlib
import importlib.resources
import os
import shutil
import stat
import subprocess
import tempfile
import threading
from dataclasses import dataclass
from pathlib import Path

from divapply import config


PLAYWRIGHT_MCP_PACKAGE = "@playwright/mcp@0.0.78"
_ASSET_PACKAGE = "divapply.mcp_runtime_assets"
_ASSET_NAMES = ("package.json", "package-lock.json")
_INSTALL_LOCK = threading.Lock()
_NPM_ENV_ALLOWLIST = (
    "APPDATA",
    "COMSPEC",
    "HOME",
    "HTTP_PROXY",
    "HTTPS_PROXY",
    "LOCALAPPDATA",
    "NO_PROXY",
    "PATH",
    "PATHEXT",
    "SYSTEMROOT",
    "TEMP",
    "TMP",
    "TMPDIR",
    "USERPROFILE",
    "WINDIR",
    "http_proxy",
    "https_proxy",
    "no_proxy",
    "NODE_EXTRA_CA_CERTS",
    "SSL_CERT_DIR",
    "SSL_CERT_FILE",
)


@dataclass(frozen=True)
class McpRuntime:
    """Absolute paths for one immutable MCP dependency tree."""

    node: Path
    root: Path
    playwright_script: Path
    lock_digest: str


def read_bundled_asset(name: str) -> str:
    """Read one known MCP manifest bundled in the Python package."""
    if name not in _ASSET_NAMES:
        raise ValueError(f"Unsupported MCP runtime asset: {name}")
    return importlib.resources.files(_ASSET_PACKAGE).joinpath(name).read_text(encoding="utf-8")


def _lock_digest() -> str:
    digest = hashlib.sha256()
    for name in _ASSET_NAMES:
        digest.update(name.encode("ascii"))
        digest.update(b"\0")
        digest.update(read_bundled_asset(name).encode("utf-8"))
        digest.update(b"\0")
    return digest.hexdigest()


def expected_mcp_runtime(*, app_dir: Path | None = None) -> McpRuntime:
    """Return expected paths without installing or executing package code."""
    node_executable = shutil.which("node")
    if node_executable is None:
        raise RuntimeError("Node.js 18+ is required for the locked MCP runtime")

    digest = _lock_digest()
    runtime_root = (Path(app_dir or config.APP_DIR).expanduser().resolve() / "mcp-runtime" / digest).resolve()
    modules = runtime_root / "node_modules"
    return McpRuntime(
        node=Path(node_executable).expanduser().resolve(),
        root=runtime_root,
        playwright_script=modules / "@playwright" / "mcp" / "cli.js",
        lock_digest=digest,
    )


def _is_link_or_reparse(path: Path) -> bool:
    if path.is_symlink():
        return True
    try:
        attributes = getattr(path.lstat(), "st_file_attributes", 0)
    except OSError:
        return False
    return bool(attributes & getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0))


def _runtime_ready(runtime: McpRuntime) -> bool:
    if not runtime.root.is_dir() or _is_link_or_reparse(runtime.root):
        return False
    try:
        root = runtime.root.resolve(strict=True)
        for script in (runtime.playwright_script,):
            resolved = script.resolve(strict=True)
            if not resolved.is_file() or not resolved.is_relative_to(root):
                return False
    except OSError:
        return False
    return True


def _npm_environment(stage: Path) -> dict[str, str]:
    """Return minimum environment for public-registry, scriptless npm install."""
    user_config = stage / ".npmrc"
    global_config = stage / ".npmrc-global"
    config_text = "registry=https://registry.npmjs.org/\nignore-scripts=true\naudit=false\nfund=false\n"
    user_config.write_text(config_text, encoding="utf-8")
    global_config.write_text(config_text, encoding="utf-8")

    environment = {name: os.environ[name] for name in _NPM_ENV_ALLOWLIST if os.environ.get(name)}
    environment.update({
        "CI": "true",
        "NPM_CONFIG_AUDIT": "false",
        "NPM_CONFIG_FUND": "false",
        "NPM_CONFIG_GLOBALCONFIG": str(global_config),
        "NPM_CONFIG_IGNORE_SCRIPTS": "true",
        "NPM_CONFIG_PROGRESS": "false",
        "NPM_CONFIG_REGISTRY": "https://registry.npmjs.org/",
        "NPM_CONFIG_UPDATE_NOTIFIER": "false",
        "NPM_CONFIG_USERCONFIG": str(user_config),
    })
    return environment


def ensure_mcp_runtime(*, app_dir: Path | None = None) -> McpRuntime:
    """Install exact lockfile contents once, without running lifecycle scripts."""
    runtime = expected_mcp_runtime(app_dir=app_dir)
    if runtime.root.exists() and _is_link_or_reparse(runtime.root):
        raise RuntimeError(f"Refusing linked MCP runtime cache: {runtime.root}")
    if _runtime_ready(runtime):
        return runtime

    npm_executable = shutil.which("npm")
    if npm_executable is None:
        raise RuntimeError("npm is required to install the locked MCP runtime")

    runtime_parent = runtime.root.parent
    runtime_parent.mkdir(parents=True, exist_ok=True)
    with _INSTALL_LOCK:
        if _runtime_ready(runtime):
            return runtime
        if runtime.root.exists():
            raise RuntimeError(f"Locked MCP runtime cache is incomplete: {runtime.root}")

        stage = Path(tempfile.mkdtemp(prefix=f".{runtime.lock_digest[:12]}-", dir=runtime_parent))
        try:
            for name in _ASSET_NAMES:
                (stage / name).write_text(read_bundled_asset(name), encoding="utf-8")

            command = [
                str(Path(npm_executable).expanduser().resolve()),
                "ci",
                "--omit=dev",
                "--ignore-scripts",
                "--no-audit",
                "--no-fund",
            ]
            try:
                subprocess.run(
                    command,
                    cwd=stage,
                    env=_npm_environment(stage),
                    check=True,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.STDOUT,
                    text=True,
                    encoding="utf-8",
                    errors="replace",
                    timeout=300,
                )
            except (OSError, subprocess.SubprocessError) as exc:
                raise RuntimeError("Could not install the locked MCP runtime") from exc

            staged_scripts = (stage / runtime.playwright_script.relative_to(runtime.root),)
            if not all(script.is_file() for script in staged_scripts):
                raise RuntimeError("Locked MCP runtime install did not contain expected server entry points")

            try:
                stage.rename(runtime.root)
            except OSError:
                if not _runtime_ready(runtime):
                    raise
        finally:
            if stage.exists():
                shutil.rmtree(stage, ignore_errors=True)

    if not _runtime_ready(runtime):
        raise RuntimeError("Locked MCP runtime install failed validation")
    return runtime
