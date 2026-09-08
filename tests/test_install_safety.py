from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]


def _run_bootstrap_function_harness(tmp_path: Path, body: str) -> subprocess.CompletedProcess[str]:
    pwsh = shutil.which("pwsh")
    if pwsh is None:
        pytest.skip("PowerShell is unavailable")

    source = (ROOT / "tools" / "bootstrap.ps1").read_text(encoding="utf-8")
    functions_only = source.split("$repoRoot =", 1)[0]
    harness = tmp_path / "bootstrap-functions.ps1"
    harness.write_text(functions_only + "\n" + body, encoding="utf-8")
    return subprocess.run(
        [pwsh, "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", str(harness)],
        check=True,
        capture_output=True,
        text=True,
    )


def test_recreate_installers_validate_delete_target_inside_repository() -> None:
    bash = (ROOT / "install.sh").read_text(encoding="utf-8")
    powershell = (ROOT / "tools" / "bootstrap.ps1").read_text(encoding="utf-8")

    message = "Refusing virtual environment outside repository"
    assert message in bash
    assert message in powershell
    assert 'rm -rf -- "$venv_path"' in bash
    assert "Assert-SafeVenvPath" in powershell
    assert "Remove-Item -Recurse -Force -LiteralPath $venvPath" in powershell


def test_windows_installer_prefers_python_312_and_installs_persistent_launcher() -> None:
    powershell = (ROOT / "tools" / "bootstrap.ps1").read_text(encoding="utf-8")

    assert "Programs\\Python\\Python312\\python.exe" in powershell
    assert 'Args    = @("-3.12")' in powershell
    assert "Install-UserLauncher" in powershell
    assert 'Microsoft\\WindowsApps' in powershell
    assert '"$VenvPython" -m divapply %*' in powershell
    assert '$HOME' not in powershell


def test_windows_installer_probes_py_312_before_selecting_it() -> None:
    powershell = (ROOT / "tools" / "bootstrap.ps1").read_text(encoding="utf-8")

    assert "Command = $py.Source" in powershell
    assert 'Args    = @("-3.12")' in powershell
    assert "foreach ($candidate in $candidates)" in powershell
    assert "Test-PythonCommand -Spec $candidate" in powershell


def test_windows_installer_rebuilds_an_unusable_existing_venv() -> None:
    powershell = (ROOT / "tools" / "bootstrap.ps1").read_text(encoding="utf-8")

    assert "Test-PythonCommand -Spec $venvSpec" in powershell
    assert "Rebuilding unusable virtual environment" in powershell
    assert powershell.count("Remove-Item -Recurse -Force -LiteralPath $venvPath") == 2


def test_python_probe_rejects_a_command_that_exists_but_cannot_run_requested_interpreter(tmp_path) -> None:
    python_executable = str(Path(sys.executable).resolve()).replace("'", "''")
    completed = _run_bootstrap_function_harness(
        tmp_path,
        f"$bad = [pscustomobject]@{{ Command = '{python_executable}'; Args = @('-c', 'raise SystemExit(1)') }}\n"
        + f"$good = [pscustomobject]@{{ Command = '{python_executable}'; Args = @() }}\n"
        + 'Write-Output "bad=$(Test-PythonCommand -Spec $bad -RequireJobSpyCompatible)"\n'
        + 'Write-Output "good=$(Test-PythonCommand -Spec $good -RequireJobSpyCompatible)"\n',
    )

    assert "bad=False" in completed.stdout
    assert "good=True" in completed.stdout


def test_resolver_skips_broken_py_312_and_uses_working_python(tmp_path) -> None:
    python_executable = str(Path(sys.executable).resolve()).replace("'", "''")
    completed = _run_bootstrap_function_harness(
        tmp_path,
        "function Test-Path { param($LiteralPath, $PathType); return $false }\n"
        + "function Get-Command {\n"
        + "  param([string]$Name, $ErrorAction)\n"
        + f"  if ($Name -in @('py', 'python')) {{ return [pscustomobject]@{{ Source = '{python_executable}' }} }}\n"
        + "  return $null\n"
        + "}\n"
        + "$resolved = Resolve-PythonCommand -RequireJobSpyCompatible\n"
        + 'Write-Output "command=$($resolved.Command)"\n'
        + 'Write-Output "args=$($resolved.Args -join ",")"\n',
    )

    assert f"command={Path(sys.executable).resolve()}" in completed.stdout
    assert "args=-3.12" not in completed.stdout
