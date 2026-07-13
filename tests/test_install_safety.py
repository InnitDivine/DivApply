from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_recreate_installers_validate_delete_target_inside_repository() -> None:
    bash = (ROOT / "install.sh").read_text(encoding="utf-8")
    powershell = (ROOT / "tools" / "bootstrap.ps1").read_text(encoding="utf-8")

    message = "Refusing virtual environment outside repository"
    assert message in bash
    assert message in powershell
    assert 'rm -rf -- "$venv_path"' in bash
    assert "Assert-SafeVenvPath" in powershell
    assert "Remove-Item -Recurse -Force -LiteralPath $venvPath" in powershell
