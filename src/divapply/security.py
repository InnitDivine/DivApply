"""Security helpers for untrusted URLs, secrets, and local artifacts."""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
import csv
from functools import lru_cache
import ipaddress
import os
import re
import secrets
import shutil
import socket
import subprocess
import sys
from pathlib import Path
from typing import TextIO, cast
from urllib.parse import urljoin, urlparse, urlsplit, urlunsplit


class UnsafeUrlError(ValueError):
    """Raised when a URL is not safe for outbound scraping/navigation."""


class PrivateFileError(PermissionError):
    """Raised when a sensitive file cannot be created with private access."""


_PRIVATE_HOST_SUFFIXES = (".local", ".localhost", ".internal")
_SECRET_TOKEN_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9._~+/=-]{7,}")
_HTTP_URL_RE = re.compile(r"https?://[^\s<>\"']+", re.IGNORECASE)
MAX_LOCAL_FORM_BYTES = 64 * 1024


def _private_networks_allowed() -> bool:
    return os.environ.get("DIVAPPLY_ALLOW_PRIVATE_URLS", "").strip().lower() in {"1", "true", "yes", "on"}


def _host_is_private(host: str) -> bool:
    normalized = host.strip("[]").casefold()
    if normalized in {"localhost", "localhost.localdomain"} or normalized.endswith(_PRIVATE_HOST_SUFFIXES):
        return True
    try:
        ip = ipaddress.ip_address(normalized)
        return (
            ip.is_private
            or ip.is_loopback
            or ip.is_link_local
            or ip.is_multicast
            or ip.is_reserved
            or ip.is_unspecified
        )
    except ValueError:
        pass

    try:
        infos = socket.getaddrinfo(normalized, None, type=socket.SOCK_STREAM)
    except socket.gaierror:
        return False

    for info in infos:
        try:
            ip = ipaddress.ip_address(info[4][0])
        except ValueError:
            continue
        if (
            ip.is_private
            or ip.is_loopback
            or ip.is_link_local
            or ip.is_multicast
            or ip.is_reserved
            or ip.is_unspecified
        ):
            return True
    return False


def validate_external_url(url: str | None, *, field: str = "url") -> str:
    """Return a normalized HTTP(S) URL safe for scraper/browser navigation."""
    value = str(url or "").strip()
    if not value:
        raise UnsafeUrlError(f"{field} is empty")
    parsed = urlparse(value)
    if parsed.scheme.casefold() not in {"http", "https"}:
        raise UnsafeUrlError(f"{field} must use http or https")
    if not parsed.hostname:
        raise UnsafeUrlError(f"{field} needs a hostname")
    if not _private_networks_allowed() and _host_is_private(parsed.hostname):
        raise UnsafeUrlError(f"{field} points to a private or local address")
    if parsed.username or parsed.password:
        raise UnsafeUrlError(f"{field} must not embed credentials")
    return value


def safe_join_external_url(base_url: str, path: str, *, field: str = "url") -> str:
    """Join a relative path to a validated external base URL without changing hosts."""
    base = validate_external_url(base_url, field=f"{field}.base_url")
    base_host = urlparse(base).hostname
    relative_path = str(path or "").strip()
    parsed_path = urlparse(relative_path)
    if parsed_path.scheme or parsed_path.netloc:
        raise UnsafeUrlError(f"{field} path must be relative")
    joined = urljoin(base.rstrip("/") + "/", relative_path.lstrip("/"))
    safe = validate_external_url(joined, field=field)
    if urlparse(safe).hostname != base_host:
        raise UnsafeUrlError(f"{field} must stay on the base host")
    return safe


def sanitize_external_url(url: str | None, *, field: str = "url") -> str | None:
    """Return a safe URL or None for optional scraped links."""
    if not url:
        return None
    try:
        return validate_external_url(url, field=field)
    except UnsafeUrlError:
        return None


def validate_navigation_url(url: str | None, *, field: str = "url") -> str:
    """Validate the final browser navigation URL after redirects."""
    return validate_external_url(url, field=f"{field} final URL")


def _is_link_or_reparse(path: Path | str) -> bool:
    """Return True for symlinks and Windows reparse points without following them."""
    candidate = Path(path)
    if candidate.is_symlink():
        return True
    try:
        return bool(getattr(candidate.lstat(), "st_file_attributes", 0) & 0x400)
    except OSError:
        return False


@lru_cache(maxsize=1)
def _windows_current_sid() -> str:
    """Return the current Windows account SID without relying on localized names."""
    flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    completed = subprocess.run(
        ["whoami", "/user", "/fo", "csv", "/nh"],
        check=True,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        creationflags=flags,
    )
    for row in csv.reader(completed.stdout.splitlines()):
        if len(row) >= 2 and row[1].strip().upper().startswith("S-"):
            return row[1].strip()
    raise OSError("could not determine current Windows user SID")


def _set_windows_user_only_dacl(path: Path, sid: str) -> None:
    """Replace a file DACL with one protected full-control ACE for the current SID."""
    import ctypes
    from ctypes import wintypes

    win_dll = getattr(ctypes, "WinDLL")
    win_error = getattr(ctypes, "WinError")
    get_last_error = getattr(ctypes, "get_last_error")
    advapi32 = win_dll("advapi32", use_last_error=True)
    kernel32 = win_dll("kernel32", use_last_error=True)
    security_descriptor = ctypes.c_void_p()
    dacl = ctypes.c_void_p()
    dacl_present = wintypes.BOOL()
    dacl_defaulted = wintypes.BOOL()

    convert = advapi32.ConvertStringSecurityDescriptorToSecurityDescriptorW
    convert.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, ctypes.POINTER(ctypes.c_void_p), ctypes.c_void_p]
    convert.restype = wintypes.BOOL
    get_dacl = advapi32.GetSecurityDescriptorDacl
    get_dacl.argtypes = [
        ctypes.c_void_p,
        ctypes.POINTER(wintypes.BOOL),
        ctypes.POINTER(ctypes.c_void_p),
        ctypes.POINTER(wintypes.BOOL),
    ]
    get_dacl.restype = wintypes.BOOL
    set_security = advapi32.SetNamedSecurityInfoW
    set_security.argtypes = [
        wintypes.LPWSTR,
        wintypes.DWORD,
        wintypes.DWORD,
        ctypes.c_void_p,
        ctypes.c_void_p,
        ctypes.c_void_p,
        ctypes.c_void_p,
    ]
    set_security.restype = wintypes.DWORD
    kernel32.LocalFree.argtypes = [ctypes.c_void_p]
    kernel32.LocalFree.restype = ctypes.c_void_p

    descriptor = f"D:P(A;;FA;;;{sid})"
    if not convert(descriptor, 1, ctypes.byref(security_descriptor), None):
        raise win_error(get_last_error())
    try:
        if not get_dacl(
            security_descriptor,
            ctypes.byref(dacl_present),
            ctypes.byref(dacl),
            ctypes.byref(dacl_defaulted),
        ):
            raise win_error(get_last_error())
        if not dacl_present.value or not dacl.value:
            raise OSError("private DACL was not created")
        error = set_security(
            str(path),
            1,  # SE_FILE_OBJECT
            0x80000004,  # PROTECTED_DACL_SECURITY_INFORMATION | DACL_SECURITY_INFORMATION
            None,
            None,
            dacl,
            None,
        )
        if error:
            raise win_error(error)
    finally:
        kernel32.LocalFree(security_descriptor)


def protect_file(path: Path | str, *, strict: bool = True) -> None:
    """Apply user-only permissions; raise on failure when strict is requested."""
    target = Path(path)
    try:
        if _is_link_or_reparse(target):
            raise OSError("target is a link or reparse point")
        if sys.platform == "win32":
            sid = _windows_current_sid()
            flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
            subprocess.run(
                [
                    "icacls",
                    str(target),
                    "/inheritancelevel:r",
                    "/grant:r",
                    f"*{sid}:F",
                    "/Q",
                ],
                check=True,
                capture_output=True,
                text=True,
                creationflags=flags,
            )
            _set_windows_user_only_dacl(target, sid)
        else:
            target.chmod(0o600)
    except (OSError, subprocess.SubprocessError) as exc:
        if strict:
            raise PrivateFileError(f"could not enforce private permissions for {target}") from exc


def protect_directory(path: Path | str, *, strict: bool = False) -> None:
    """Apply user-only directory permissions, preserving owner traversal."""
    target = Path(path)
    try:
        if _is_link_or_reparse(target):
            raise OSError("target is a link or reparse point")
        if sys.platform == "win32":
            sid = _windows_current_sid()
            flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
            subprocess.run(
                [
                    "icacls",
                    str(target),
                    "/inheritancelevel:r",
                    "/grant:r",
                    f"*{sid}:F",
                    "/Q",
                ],
                check=True,
                capture_output=True,
                text=True,
                creationflags=flags,
            )
            _set_windows_user_only_dacl(target, sid)
        else:
            target.chmod(0o700)
    except (OSError, subprocess.SubprocessError) as exc:
        if strict:
            raise PrivateFileError(f"could not enforce private permissions for directory {target}") from exc


@contextmanager
def open_private_text(
    path: Path | str,
    mode: str = "w",
    *,
    encoding: str = "utf-8",
    strict: bool = True,
) -> Iterator[TextIO]:
    """Open a no-follow text file and protect it before truncating or appending."""
    if mode not in {"w", "a"}:
        raise ValueError("private text mode must be 'w' or 'a'")
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    existed = target.exists()
    if _is_link_or_reparse(target):
        raise PrivateFileError(f"refusing private file link or reparse point: {target}")

    flags = os.O_WRONLY | os.O_CREAT
    if mode == "a":
        flags |= os.O_APPEND
    flags |= getattr(os, "O_NOFOLLOW", 0)
    fd: int | None = None
    protected = False
    try:
        fd = os.open(str(target), flags, 0o600)
        opened = os.fstat(fd)
        current = target.lstat()
        if _is_link_or_reparse(target) or (opened.st_dev, opened.st_ino) != (current.st_dev, current.st_ino):
            raise PrivateFileError(f"private file target changed or became a link or reparse point: {target}")
        if sys.platform != "win32":
            os.fchmod(fd, 0o600)
        protect_file(target, strict=strict)
        protected = True
        if mode == "w":
            os.ftruncate(fd, 0)
            os.lseek(fd, 0, os.SEEK_SET)
        handle = cast(TextIO, os.fdopen(fd, mode, encoding=encoding))
        fd = None
        try:
            yield handle
        finally:
            handle.close()
    except PrivateFileError:
        raise
    except OSError as exc:
        raise PrivateFileError(f"could not safely open private file {target}") from exc
    finally:
        if fd is not None:
            os.close(fd)
        if strict and not protected and not existed and target.exists():
            # A failed strict create must not leave a broadly readable artifact.
            try:
                target.unlink()
            except OSError:
                pass


def write_private_text(
    path: Path | str,
    text: str,
    *,
    encoding: str = "utf-8",
    strict: bool = True,
) -> None:
    """Write sensitive text with user-only permissions from file creation."""
    with open_private_text(path, mode="w", encoding=encoding, strict=strict) as handle:
        handle.write(text)


def copy_private_file(source: Path | str, target: Path | str) -> None:
    """Copy a sensitive file through a protected sibling before promotion."""
    src = Path(source)
    dst = Path(target)
    if _is_link_or_reparse(src):
        raise PrivateFileError(f"refusing private source link or reparse point: {src}")
    if dst.exists() and _is_link_or_reparse(dst):
        raise PrivateFileError(f"refusing private target link or reparse point: {dst}")
    dst.parent.mkdir(parents=True, exist_ok=True)
    temporary = dst.with_name(f".{dst.name}.{secrets.token_hex(8)}.tmp")
    try:
        shutil.copyfile(src, temporary)
        protect_file(temporary, strict=True)
        os.replace(temporary, dst)
        protect_file(dst, strict=True)
    except PrivateFileError:
        raise
    except OSError as exc:
        raise PrivateFileError(f"could not safely copy private file to {dst}") from exc
    finally:
        if temporary.exists():
            try:
                temporary.unlink()
            except OSError:
                pass


def redact_url_for_log(url: str | None) -> str:
    """Drop URL credentials, query, and fragment before display or persistence."""
    value = str(url or "").strip()
    try:
        parsed = urlsplit(value)
        host = parsed.hostname or ""
        if ":" in host and not host.startswith("["):
            host = f"[{host}]"
        try:
            port = parsed.port
        except ValueError:
            port = None
        netloc = f"{host}:{port}" if host and port is not None else host
        return urlunsplit((parsed.scheme, netloc, parsed.path, "", ""))
    except ValueError:
        return value.split("?", 1)[0].split("#", 1)[0]


def parse_local_form_length(raw_length: str | None, *, max_bytes: int = MAX_LOCAL_FORM_BYTES) -> int:
    """Validate a local form Content-Length before reading the request body."""
    try:
        length = int(raw_length or "0")
    except ValueError as exc:
        raise ValueError("invalid content length") from exc
    if length < 0:
        raise ValueError("invalid content length")
    if length > max_bytes:
        raise ValueError("request body too large")
    return length


def local_request_is_same_origin(headers: object, host: str, port: int) -> bool:
    """Return False for browser cross-origin writes to local-only HTTP tools."""
    allowed_hosts = {host}
    if host in {"127.0.0.1", "::1"}:
        allowed_hosts.add("localhost")

    allowed = {
        f"http://{host}:{port}",
        f"http://localhost:{port}" if host in {"127.0.0.1", "::1"} else f"http://{host}:{port}",
    }

    def _get(name: str) -> str:
        getter = getattr(headers, "get", None)
        if getter is None:
            return ""
        return str(getter(name, "") or "").strip()

    host_header = _get("Host")
    if host_header:
        parsed_host = urlparse(f"//{host_header}")
        request_host = (parsed_host.hostname or "").strip("[]").casefold()
        try:
            request_port = parsed_host.port or 80
        except ValueError:
            return False
        if request_host not in {item.strip("[]").casefold() for item in allowed_hosts} or request_port != port:
            return False

    origin = _get("Origin")
    if origin and origin.rstrip("/") not in allowed:
        return False

    referer = _get("Referer")
    if referer:
        parsed = urlparse(referer)
        referer_origin = f"{parsed.scheme}://{parsed.netloc}"
        if referer_origin not in allowed:
            return False

    return True


def collect_known_secret_values(*sources: object) -> set[str]:
    """Collect redaction candidates from nested dict/list structures and env."""
    values: set[str] = set()

    def walk(obj: object, key_hint: str = "") -> None:
        if isinstance(obj, dict):
            for key, value in obj.items():
                walk(value, str(key).casefold())
        elif isinstance(obj, (list, tuple, set)):
            for value in obj:
                walk(value, key_hint)
        elif isinstance(obj, str):
            text = obj.strip()
            if len(text) >= 8 and (
                any(token in key_hint for token in ("password", "token", "secret", "key"))
                or _SECRET_TOKEN_RE.fullmatch(text)
            ):
                values.add(text)

    for source in sources:
        walk(source)

    for key, value in os.environ.items():
        if (
            value
            and len(value) >= 8
            and any(token in key.casefold() for token in ("password", "token", "secret", "key"))
        ):
            values.add(value)

    return values


def redact_known_secrets(text: str, secrets: set[str]) -> str:
    """Replace known secret values and common credential patterns in logs."""
    redacted = text
    for secret in sorted(secrets, key=len, reverse=True):
        if secret:
            redacted = redacted.replace(secret, "[redacted]")
    redacted = re.sub(
        r"(?i)\b(password|passwd|api[_-]?key|token|secret)\s*[:=]\s*([^\s,;]+)",
        lambda m: f"{m.group(1)}=[redacted]",
        redacted,
    )
    redacted = re.sub(r"(?i)\bBearer\s+[A-Za-z0-9._~+/=-]+", "Bearer [redacted]", redacted)
    redacted = _HTTP_URL_RE.sub(lambda match: redact_url_for_log(match.group(0)), redacted)
    return redacted
