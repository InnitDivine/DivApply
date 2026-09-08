from __future__ import annotations

import os
import subprocess
from contextlib import ExitStack
from unittest.mock import patch

from divapply import runtime


def _stacked_tier_test(
    *,
    backend_value,
    browser_value,
    node_value="C:/node/node.exe",
    npm_value="C:/node/npm.cmd",
    node_version="v20.19.4",
    chrome_ok: bool = True,
):
    stack = ExitStack()
    stack.enter_context(patch("divapply.config.load_env", return_value=None))
    stack.enter_context(patch.dict(os.environ, {"GEMINI_API_KEY": "x"}, clear=True))
    stack.enter_context(
        patch.object(runtime, "get_apply_backend", side_effect=lambda preferred=None: backend_value(preferred))
    )
    stack.enter_context(
        patch.object(runtime, "get_apply_browser", side_effect=lambda preferred=None: browser_value(preferred))
    )
    stack.enter_context(
        patch.object(
            runtime.shutil,
            "which",
            side_effect=lambda name: {"node": node_value, "npm": npm_value}.get(name),
        )
    )
    stack.enter_context(
        patch(
            "divapply.mcp_runtime.subprocess.run",
            return_value=subprocess.CompletedProcess([str(node_value), "--version"], 0, stdout=node_version),
        )
    )
    if chrome_ok:
        stack.enter_context(patch.object(runtime, "get_chrome_path", return_value="C:/Chrome/chrome.exe"))
    else:
        stack.enter_context(patch.object(runtime, "get_chrome_path", side_effect=FileNotFoundError()))
    return stack


def test_get_tier_needs_compatible_node_for_tier_three() -> None:
    with _stacked_tier_test(
        backend_value=lambda preferred=None: "codex",
        browser_value=lambda preferred=None: "firefox",
        node_value=None,
    ):
        assert runtime.get_tier() == 2


def test_get_tier_rejects_node_18_for_tier_three() -> None:
    with _stacked_tier_test(
        backend_value=lambda preferred=None: "codex",
        browser_value=lambda preferred=None: "firefox",
        node_version="v18.20.8",
    ):
        assert runtime.get_tier() == 2


def test_get_tier_is_three_when_backend_browser_node_and_npm_are_compatible() -> None:
    with _stacked_tier_test(
        backend_value=lambda preferred=None: "codex",
        browser_value=lambda preferred=None: "firefox",
    ):
        assert runtime.get_tier() == 3


def test_check_tier_honors_selected_backend_and_browser() -> None:
    with _stacked_tier_test(
        backend_value=lambda preferred=None: preferred if preferred == "claude" else "codex",
        browser_value=lambda preferred=None: preferred or "firefox",
    ):
        runtime.check_tier(3, "auto-apply", preferred_backend="claude", preferred_browser="firefox")


def test_check_tier_rejects_missing_selected_backend_even_if_env_has_another() -> None:
    with _stacked_tier_test(
        backend_value=lambda preferred=None: "codex" if preferred is None else None,
        browser_value=lambda preferred=None: "firefox",
    ):
        try:
            runtime.check_tier(3, "auto-apply", preferred_backend="claude", preferred_browser="firefox")
        except SystemExit:
            return
        raise AssertionError("expected SystemExit for an unavailable selected backend")
