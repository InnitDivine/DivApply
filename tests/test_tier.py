from __future__ import annotations

import os
from contextlib import ExitStack
from unittest.mock import patch

from divapply import config


def _stacked_tier_test(
    *,
    backend_value,
    browser_value,
    npx_value,
    chrome_ok: bool = True,
):
    stack = ExitStack()
    stack.enter_context(patch.object(config, "load_env", return_value=None))
    stack.enter_context(patch.dict(os.environ, {"GEMINI_API_KEY": "x"}, clear=True))
    stack.enter_context(patch.object(config, "get_apply_backend", side_effect=lambda preferred=None: backend_value(preferred)))
    stack.enter_context(patch.object(config, "get_apply_browser", side_effect=lambda preferred=None: browser_value(preferred)))
    stack.enter_context(patch.object(config.shutil, "which", return_value=npx_value))
    if chrome_ok:
        stack.enter_context(patch.object(config, "get_chrome_path", return_value="C:/Chrome/chrome.exe"))
    else:
        stack.enter_context(patch.object(config, "get_chrome_path", side_effect=FileNotFoundError()))
    return stack


def test_get_tier_needs_npx_for_tier_three() -> None:
    with _stacked_tier_test(
        backend_value=lambda preferred=None: "codex",
        browser_value=lambda preferred=None: "firefox",
        npx_value=None,
    ):
        assert config.get_tier() == 2


def test_get_tier_is_three_when_backend_browser_and_npx_exist() -> None:
    with _stacked_tier_test(
        backend_value=lambda preferred=None: "codex",
        browser_value=lambda preferred=None: "firefox",
        npx_value="C:/node/npx.exe",
    ):
        assert config.get_tier() == 3


def test_check_tier_honors_selected_backend_and_browser() -> None:
    with _stacked_tier_test(
        backend_value=lambda preferred=None: preferred if preferred == "claude" else "codex",
        browser_value=lambda preferred=None: preferred or "firefox",
        npx_value="C:/node/npx.exe",
    ):
        config.check_tier(3, "auto-apply", preferred_backend="claude", preferred_browser="firefox")


def test_check_tier_rejects_missing_selected_backend_even_if_env_has_another() -> None:
    with _stacked_tier_test(
        backend_value=lambda preferred=None: "codex" if preferred is None else None,
        browser_value=lambda preferred=None: "firefox",
        npx_value="C:/node/npx.exe",
    ):
        try:
            config.check_tier(3, "auto-apply", preferred_backend="claude", preferred_browser="firefox")
        except SystemExit:
            return
        raise AssertionError("expected SystemExit for an unavailable selected backend")
