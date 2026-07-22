"""Chrome lifecycle management for apply workers.

Handles launching an isolated Chrome instance with remote debugging,
worker profile setup/cloning, and cross-platform process cleanup.
"""

import json
import logging
import platform
import socket
import shutil
import subprocess
import threading
import time
import urllib.request
import urllib.error
from pathlib import Path

from divapply import config

logger = logging.getLogger(__name__)

# CDP port base â€” each worker uses BASE_CDP_PORT + worker_id
BASE_CDP_PORT = 9222

# Track Chrome processes per worker for cleanup
_chrome_procs: dict[int, subprocess.Popen] = {}
_chrome_lock = threading.Lock()


def get_worker_browser_profile_dir(worker_id: int, browser: str = "chrome") -> Path:
    """Return the persistent browser profile directory for a worker."""
    safe_browser = browser.lower()
    if safe_browser == "chrome":
        return config.CHROME_WORKER_DIR / f"worker-{worker_id}"
    return config.APPLY_WORKER_DIR / f"{safe_browser}-profile-{worker_id}"


# ---------------------------------------------------------------------------
# Cross-platform process helpers
# ---------------------------------------------------------------------------

def _kill_process_tree(pid: int) -> None:
    """Kill a process and all its children.

    On Windows, Chrome spawns 10+ child processes (GPU, renderer, etc.),
    so taskkill /T is needed to kill the entire tree. On Unix, os.killpg
    handles the process group.
    """
    import signal as _signal

    try:
        if platform.system() == "Windows":
            subprocess.run(
                ["taskkill", "/F", "/T", "/PID", str(pid)],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                timeout=10,
            )
        else:
            # Unix: kill entire process group
            import os
            get_process_group = getattr(os, "getpgid", None)
            kill_process_group = getattr(os, "killpg", None)
            kill_signal = getattr(_signal, "SIGKILL", _signal.SIGTERM)

            def _kill_single_process() -> None:
                try:
                    os.kill(pid, kill_signal)
                except (ProcessLookupError, PermissionError):
                    pass

            if callable(get_process_group) and callable(kill_process_group):
                try:
                    kill_process_group(get_process_group(pid), kill_signal)
                except (ProcessLookupError, PermissionError):
                    # Process already gone or group access denied; try tracked PID only.
                    _kill_single_process()
            else:
                _kill_single_process()
    except Exception:
        logger.debug("Failed to kill process tree for PID %d", pid, exc_info=True)


def _port_is_available(port: int) -> bool:
    """Return whether the loopback CDP port can be bound without killing its owner."""
    if not 1 <= port <= 65535:
        return False
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        try:
            sock.bind(("127.0.0.1", port))
        except OSError:
            return False
    return True

# ---------------------------------------------------------------------------
# Worker profile management
# ---------------------------------------------------------------------------

PROFILE_MARKER_NAME = ".divapply-profile-v2"


def _write_profile_marker(profile_dir: Path) -> None:
    marker = profile_dir / PROFILE_MARKER_NAME
    marker.write_text("2\n", encoding="utf-8")


def setup_worker_profile(worker_id: int, browser: str = "chrome") -> Path:
    """Create or reuse only a dedicated DivApply browser profile.

    Chrome profiles created by older releases are unmarked because they may
    contain a copy of the user's personal Chrome data. They are preserved but
    refused until the user moves or deletes them and signs in intentionally via
    divapply browser-login.
    """
    if worker_id < 0:
        raise ValueError("worker_id must be non-negative")

    profile_dir = get_worker_browser_profile_dir(worker_id, browser)
    marker = profile_dir / PROFILE_MARKER_NAME
    browser_name = browser.lower()

    if browser_name != "chrome":
        profile_dir.mkdir(parents=True, exist_ok=True)
        if not marker.exists():
            _write_profile_marker(profile_dir)
        return profile_dir

    if marker.exists():
        return profile_dir

    if profile_dir.exists() and any(profile_dir.iterdir()):
        raise RuntimeError(
            f"Legacy unmarked Chrome worker profile at {profile_dir} may contain copied "
            "personal browser credentials. Move or delete that directory manually, then "
            f"run 'divapply browser-login --browser chrome --worker {worker_id}' to create "
            "a dedicated profile."
        )

    profile_dir.mkdir(parents=True, exist_ok=True)
    _write_profile_marker(profile_dir)
    logger.info("[worker-%d] Created blank dedicated Chrome profile at %s", worker_id, profile_dir)
    return profile_dir
def _suppress_restore_nag(profile_dir: Path) -> None:
    """Clear Chrome's 'restore pages' nag by fixing Preferences.

    Chrome writes exit_type=Crashed when killed, which triggers a
    'Restore pages?' prompt on next launch. This patches it out.
    """
    prefs_file = profile_dir / "Default" / "Preferences"
    if not prefs_file.exists():
        return

    try:
        prefs = json.loads(prefs_file.read_text(encoding="utf-8"))
        prefs.setdefault("profile", {})["exit_type"] = "Normal"
        prefs.setdefault("session", {})["restore_on_startup"] = 4  # 4 = open blank
        prefs.setdefault("session", {}).pop("startup_urls", None)
        prefs["credentials_enable_service"] = False
        prefs.setdefault("password_manager", {})["saving_enabled"] = False
        prefs.setdefault("autofill", {})["profile_enabled"] = False
        prefs_file.write_text(json.dumps(prefs), encoding="utf-8")
    except Exception:
        logger.debug("Could not patch Chrome preferences", exc_info=True)


# ---------------------------------------------------------------------------
# Chrome launch / kill
# ---------------------------------------------------------------------------

def launch_chrome(worker_id: int, port: int | None = None,
                  headless: bool = False) -> subprocess.Popen:
    """Launch a Chrome instance with remote debugging for a worker.

    Args:
        worker_id: Numeric worker identifier.
        port: CDP port. Defaults to BASE_CDP_PORT + worker_id.
        headless: Run Chrome in headless mode (no visible window).

    Returns:
        subprocess.Popen handle for the Chrome process.
    """
    if port is None:
        port = BASE_CDP_PORT + worker_id

    if not _port_is_available(port):
        raise RuntimeError(
            f"CDP port {port} is already in use; refusing to terminate an unowned process"
        )
    profile_dir = setup_worker_profile(worker_id)

    # Patch preferences to suppress restore nag
    _suppress_restore_nag(profile_dir)

    chrome_exe = config.get_chrome_path()

    cmd = [
        chrome_exe,
        f"--remote-debugging-port={port}",
        f"--user-data-dir={profile_dir}",
        "--profile-directory=Default",
        "--no-first-run",
        "--no-default-browser-check",
        "--window-size=1024,768",
        "--disable-session-crashed-bubble",
        "--disable-features=InfiniteSessionRestore,PasswordManagerOnboarding",
        "--hide-crash-restore-bubble",
        "--noerrdialogs",
        "--password-store=basic",
        "--disable-save-password-bubble",
        "--disable-popup-blocking",
        # Block dangerous permissions at browser level without Chrome's
        # unsupported fake-media flags or their warning banner.
        "--deny-permission-prompts",
        "--disable-notifications",
    ]
    if headless:
        cmd.append("--headless=new")

    # On Unix, start in a new process group so we can kill the whole tree
    kwargs: dict = dict(stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    if platform.system() != "Windows":
        import os
        start_process_group = getattr(os, "setsid", None)
        if callable(start_process_group):
            kwargs["preexec_fn"] = start_process_group

    proc = subprocess.Popen(cmd, **kwargs)
    with _chrome_lock:
        _chrome_procs[worker_id] = proc

    # Wait for Chrome to open the CDP debug port (up to 15s)
    _wait_for_cdp(port, timeout=15, worker_id=worker_id)
    logger.info("[worker-%d] Chrome started on port %d (pid %d)",
                worker_id, port, proc.pid)
    return proc


def _wait_for_cdp(port: int, timeout: int = 15, worker_id: int = 0) -> None:
    """Poll http://localhost:{port}/json/version until Chrome is ready.

    Raises RuntimeError if Chrome doesn't respond within timeout seconds.
    This prevents @playwright/mcp from falling back to headless Chromium
    (which has no cookies) when Chrome is slow to start.
    """
    url = f"http://localhost:{port}/json/version"
    deadline = time.time() + timeout
    last_err = None
    while time.time() < deadline:
        try:
            with urllib.request.urlopen(url, timeout=2) as resp:
                if resp.status == 200:
                    logger.info("[worker-%d] CDP ready on port %d", worker_id, port)
                    return
        except Exception as e:
            last_err = e
        time.sleep(0.5)
    raise RuntimeError(
        f"[worker-{worker_id}] Chrome CDP port {port} not ready after {timeout}s: {last_err}"
    )


def cleanup_worker(worker_id: int, process: subprocess.Popen | None) -> None:
    """Kill a worker's Chrome instance and remove it from tracking.

    Args:
        worker_id: Numeric worker identifier.
        process: The Popen handle returned by launch_chrome.
    """
    if process and process.poll() is None:
        _kill_process_tree(process.pid)
    with _chrome_lock:
        _chrome_procs.pop(worker_id, None)
    logger.info("[worker-%d] Chrome cleaned up", worker_id)


def kill_all_chrome() -> None:
    """Kill only Chrome instances launched and tracked by this process."""
    with _chrome_lock:
        procs = dict(_chrome_procs)
        _chrome_procs.clear()

    for proc in procs.values():
        if proc.poll() is None:
            _kill_process_tree(proc.pid)


def reset_worker_dir(worker_id: int) -> Path:
    """Wipe and recreate a worker's isolated working directory.

    Each job gets a fresh working directory so that file conflicts
    (resume PDFs, MCP configs) don't bleed between jobs.

    Args:
        worker_id: Numeric worker identifier.

    Returns:
        Path to the clean worker directory.
    """
    worker_dir = config.APPLY_WORKER_DIR / f"worker-{worker_id}"
    if worker_dir.exists():
        shutil.rmtree(str(worker_dir), ignore_errors=True)
    worker_dir.mkdir(parents=True, exist_ok=True)
    return worker_dir


def cleanup_on_exit() -> None:
    """Atexit handler that terminates only processes launched by DivApply."""
    kill_all_chrome()

