from __future__ import annotations

from divapply import runtime


def test_get_apply_browser_defaults_invalid_values_to_chromium(monkeypatch) -> None:
    monkeypatch.setenv("DIVAPPLY_BROWSER", "not-a-browser")

    assert runtime.get_apply_browser() == "chromium"


def test_get_apply_backend_rejects_unavailable_requested_backend(monkeypatch) -> None:
    monkeypatch.setattr(runtime, "get_available_apply_backends", lambda: {"codex": "C:/bin/codex.exe"})

    assert runtime.get_apply_backend("claude") is None


def test_get_apply_backend_executable_prefers_codex_env_path(tmp_path, monkeypatch) -> None:
    codex = tmp_path / "codex.exe"
    codex.write_text("", encoding="utf-8")
    monkeypatch.setenv("DIVAPPLY_CODEX_PATH", str(codex))
    monkeypatch.setenv("CODEX_CLI_PATH", str(tmp_path / "other-codex.exe"))
    monkeypatch.setattr(runtime.shutil, "which", lambda name: None)

    assert runtime.get_apply_backend_executable("codex") == str(codex)


def test_get_chrome_path_prefers_existing_env_path(tmp_path, monkeypatch) -> None:
    chrome = tmp_path / "chrome.exe"
    chrome.write_text("", encoding="utf-8")
    monkeypatch.setenv("CHROME_PATH", str(chrome))

    assert runtime.get_chrome_path() == str(chrome)
