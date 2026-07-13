from __future__ import annotations

import argparse
from collections.abc import Iterator
from contextlib import contextmanager
import importlib.util
import os
from pathlib import Path
import re
import stat
import tarfile
import tomllib
from typing import BinaryIO
import zipfile


Issue = tuple[str, str]

MAX_OUTER_ARCHIVE_BYTES = 256 * 1024 * 1024
MAX_ARCHIVE_MEMBERS = 10_000
MAX_MEMBER_BYTES = 32 * 1024 * 1024
MAX_TOTAL_EXPANDED_BYTES = 128 * 1024 * 1024
MAX_ARCHIVE_METADATA_BYTES = 16 * 1024 * 1024
_MAGIC_PREFIX_BYTES = 560
_REPARSE_POINT = getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400)


def _load_archive_preflight():
    module_path = Path(__file__).with_name("archive_preflight.py")
    spec = importlib.util.spec_from_file_location("divapply_archive_preflight", module_path)
    if spec is None or spec.loader is None:
        raise RuntimeError("archive metadata preflight is unavailable")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


_ARCHIVE_PREFLIGHT = _load_archive_preflight()

_RELEASE_COMPONENTS = {"build", "dist", "release"}
_RUNTIME_COMPONENTS = {
    ".mypy_cache",
    ".pytest_cache",
    ".ruff_cache",
    ".venv",
    "__pycache__",
    "apply-workers",
    "apply_logs",
    "backups",
    "chrome-workers",
    "cover_letters",
    "logs",
    "node_modules",
    "qa-renders",
    "screenshots",
    "social_screenshots",
    "tailored_resumes",
    "tmp",
}
_RUNTIME_NAMES = {".coverage", "coverage.xml"}
_PRIVATE_NAMES = {
    "answers.yaml",
    "credentials.yaml",
    "profile.json",
    "resume.pdf",
    "resume.txt",
    "searches.local.yaml",
    "searches.yaml",
}
_DATABASE_SUFFIXES = (".db", ".db-shm", ".db-wal", ".sqlite", ".sqlite3")
_NESTED_ARCHIVE_SUFFIXES = (
    ".7z",
    ".bz2",
    ".egg",
    ".gz",
    ".jar",
    ".nupkg",
    ".rar",
    ".tar",
    ".tar.bz2",
    ".tar.gz",
    ".tar.xz",
    ".tbz2",
    ".tgz",
    ".txz",
    ".whl",
    ".xz",
    ".zip",
)
_ROOT_METADATA_FILES = {".gitignore", "LICENSE", "PKG-INFO", "README.md", "pyproject.toml"}
_PACKAGE_ASSETS = {
    "src/divapply/config/employers.yaml",
    "src/divapply/config/searches.example.yaml",
    "src/divapply/config/sites.yaml",
    "src/divapply/mcp_runtime_assets/package-lock.json",
    "src/divapply/mcp_runtime_assets/package.json",
}
_WHEEL_PACKAGE_ASSETS = {item.removeprefix("src/") for item in _PACKAGE_ASSETS}
_WHEEL_RE = re.compile(
    r"^divapply-(?P<version>[A-Za-z0-9][A-Za-z0-9_.!+]*)-py3-none-any\.whl$",
    re.IGNORECASE,
)
_SDIST_RE = re.compile(
    r"^divapply-(?P<version>[A-Za-z0-9][A-Za-z0-9_.!+]*)\.tar\.gz$",
    re.IGNORECASE,
)


def _issue(code: str, archive: Path, index: int) -> Issue:
    return code, f"{archive.name}:member#{index}"


def _entry_issue(code: str, dist_dir: Path, index: int) -> Issue:
    return code, f"{dist_dir.name or 'dist'}:entry#{index}"


def _canonical_member_path(archive: Path, name: str, index: int) -> tuple[str | None, list[Issue]]:
    issues: list[Issue] = []
    if not name or "\\" in name or any(ord(char) < 32 or 127 <= ord(char) <= 159 for char in name):
        issues.append(_issue("unsafe_member_path", archive, index))
        return None, issues

    is_directory_spelling = name.endswith("/")
    core = name[:-1] if is_directory_spelling else name
    parts = core.split("/")
    unsafe = (
        not core
        or name.startswith("/")
        or any(part in {"", ".", ".."} for part in parts)
        or any(re.match(r"^[A-Za-z]:", part) is not None for part in parts)
    )
    canonical = "/".join(parts)
    if unsafe or canonical != core:
        issues.append(_issue("unsafe_member_path", archive, index))
        return None, issues
    return canonical, issues


def _member_issues(archive: Path, canonical: str, index: int) -> list[Issue]:
    lowered_parts = tuple(part.casefold() for part in canonical.split("/"))
    basename = lowered_parts[-1]
    issues: list[Issue] = []

    if any(part in _RELEASE_COMPONENTS for part in lowered_parts):
        issues.append(_issue("release_output", archive, index))
    if any(part in _RUNTIME_COMPONENTS for part in lowered_parts) or basename in _RUNTIME_NAMES:
        issues.append(_issue("runtime_artifact", archive, index))
    if basename in _PRIVATE_NAMES:
        issues.append(_issue("private_artifact", archive, index))
    if basename.startswith(".env") and basename != ".env.example":
        issues.append(_issue("private_artifact", archive, index))
    if basename.startswith(".mcp") or basename.endswith(_DATABASE_SUFFIXES):
        issues.append(_issue("private_artifact", archive, index))
    if basename.endswith(_NESTED_ARCHIVE_SUFFIXES):
        issues.append(_issue("nested_archive", archive, index))
    return issues


def _sdist_member_allowed(relative: str, *, is_dir: bool) -> bool:
    if not relative:
        return True
    if is_dir:
        return relative in {"scripts", "src", "src/divapply"} or relative.startswith("src/divapply/")
    return (
        relative in _ROOT_METADATA_FILES
        or relative in {"scripts/divapply", "scripts/divapply.cmd"}
        or relative in _PACKAGE_ASSETS
        or (relative.startswith("src/divapply/") and relative.endswith(".py"))
    )


def _wheel_member_allowed(canonical: str, version: str, *, is_dir: bool) -> bool:
    normalized_version = version.replace("-", "_")
    dist_info = f"divapply-{normalized_version}.dist-info"
    data_root = f"divapply-{normalized_version}.data"
    if is_dir:
        return (
            canonical == "divapply"
            or canonical.startswith("divapply/")
            or canonical == dist_info
            or canonical.startswith(f"{dist_info}/")
            or canonical in {data_root, f"{data_root}/scripts"}
        )
    return (
        (canonical.startswith("divapply/") and canonical.endswith(".py"))
        or canonical in _WHEEL_PACKAGE_ASSETS
        or canonical.startswith(f"{dist_info}/")
        or canonical in {f"{data_root}/scripts/divapply", f"{data_root}/scripts/divapply.cmd"}
    )


def _strict_manifest_issues(
    archive: Path,
    canonical: str,
    index: int,
    *,
    is_dir: bool,
    kind: str | None,
    version: str | None,
) -> list[Issue]:
    if kind == "sdist" and version:
        root = f"divapply-{version}"
        parts = canonical.split("/")
        if not parts or parts[0].casefold() != root.casefold():
            return [_issue("unexpected_member", archive, index)]
        relative = "/".join(parts[1:])
        return [] if _sdist_member_allowed(relative, is_dir=is_dir) else [_issue("unexpected_member", archive, index)]
    if kind == "wheel" and version:
        return (
            []
            if _wheel_member_allowed(canonical, version, is_dir=is_dir)
            else [_issue("unexpected_member", archive, index)]
        )
    return []


def _archive_identity(path: Path) -> tuple[str | None, str | None]:
    wheel_match = _WHEEL_RE.fullmatch(path.name)
    if wheel_match:
        return "wheel", wheel_match.group("version")
    sdist_match = _SDIST_RE.fullmatch(path.name)
    if sdist_match:
        return "sdist", sdist_match.group("version")
    lowered = path.name.casefold()
    if lowered.endswith(".whl"):
        return "wheel", None
    if lowered.endswith((".tar.gz", ".tgz")):
        return "sdist", None
    return None, None


def _looks_like_archive(prefix: bytes) -> bool:
    return (
        prefix.startswith((b"PK\x03\x04", b"PK\x05\x06", b"PK\x07\x08"))
        or prefix.startswith(b"\x1f\x8b")
        or prefix.startswith(b"BZh")
        or prefix.startswith(b"\xfd7zXZ\x00")
        or prefix.startswith(b"7z\xbc\xaf'\x1c")
        or prefix.startswith((b"Rar!\x1a\x07\x00", b"Rar!\x1a\x07\x01\x00"))
        or (len(prefix) >= 262 and prefix[257:262] == b"ustar")
    )


def _size_issues(archive: Path, index: int, size: int, expanded_total: int) -> list[Issue]:
    issues: list[Issue] = []
    if size < 0 or size > MAX_MEMBER_BYTES:
        issues.append(_issue("member_size_limit", archive, index))
    if expanded_total > MAX_TOTAL_EXPANDED_BYTES:
        issues.append(_issue("expanded_size_limit", archive, index))
    return issues


def _track_member_name(
    archive: Path,
    index: int,
    canonical: str,
    *,
    is_dir: bool,
    seen: set[str],
    seen_casefold: set[str],
    path_types: dict[str, str],
) -> list[Issue]:
    issues: list[Issue] = []
    folded = canonical.casefold()
    if canonical in seen:
        issues.append(_issue("duplicate_member", archive, index))
    elif folded in seen_casefold:
        issues.append(_issue("case_collision", archive, index))

    parts = folded.split("/")
    for end in range(1, len(parts)):
        ancestor = "/".join(parts[:end])
        if path_types.get(ancestor) == "file":
            issues.append(_issue("path_type_conflict", archive, index))
        path_types.setdefault(ancestor, "dir")
    entry_type = "dir" if is_dir else "file"
    prior_type = path_types.get(folded)
    if prior_type is not None and prior_type != entry_type:
        issues.append(_issue("path_type_conflict", archive, index))
    path_types.setdefault(folded, entry_type)

    seen.add(canonical)
    seen_casefold.add(folded)
    return issues


def _live_archive_issues(path: Path, stream: BinaryIO) -> list[Issue]:
    opened_before = os.fstat(stream.fileno())
    rebound = path.lstat()
    opened_after = os.fstat(stream.fileno())
    metadata = (opened_before, rebound, opened_after)
    if any(
        stat.S_ISLNK(item.st_mode)
        or getattr(item, "st_file_attributes", 0) & _REPARSE_POINT
        or not stat.S_ISREG(item.st_mode)
        for item in metadata
    ):
        return [("unsafe_archive", path.name)]
    identities = {(item.st_dev, item.st_ino) for item in metadata}
    if len(identities) != 1 or opened_before.st_size != opened_after.st_size:
        return [("unsafe_archive", path.name)]
    if max(item.st_size for item in metadata) > MAX_OUTER_ARCHIVE_BYTES:
        return [("outer_size_limit", path.name)]
    return []


@contextmanager
def _preflighted_zip(path: Path) -> Iterator[tuple[list[Issue], zipfile.ZipFile | None]]:
    with path.open("rb") as stream:
        issues = _live_archive_issues(path, stream)
        if issues:
            yield issues, None
            return
        raw_issues = _ARCHIVE_PREFLIGHT.preflight_zip(
            stream,
            max_members=MAX_ARCHIVE_MEMBERS,
            max_member_bytes=MAX_MEMBER_BYTES,
            max_total_bytes=MAX_TOTAL_EXPANDED_BYTES,
            max_metadata_bytes=MAX_ARCHIVE_METADATA_BYTES,
        )
        if raw_issues:
            yield [_issue(code, path, index) for code, index in raw_issues], None
            return
        stream.seek(0)
        with zipfile.ZipFile(stream) as archive:
            yield [], archive


@contextmanager
def _preflighted_tar(path: Path) -> Iterator[tuple[list[Issue], tarfile.TarFile | None]]:
    with path.open("rb") as stream:
        issues = _live_archive_issues(path, stream)
        if issues:
            yield issues, None
            return
        raw_issues = _ARCHIVE_PREFLIGHT.preflight_tar_gzip(
            stream,
            max_members=MAX_ARCHIVE_MEMBERS,
            max_member_bytes=MAX_MEMBER_BYTES,
            max_total_bytes=MAX_TOTAL_EXPANDED_BYTES,
            max_metadata_bytes=MAX_ARCHIVE_METADATA_BYTES,
        )
        if raw_issues:
            yield [_issue(code, path, index) for code, index in raw_issues], None
            return
        stream.seek(0)
        with tarfile.open(fileobj=stream, mode="r:gz") as archive:
            yield [], archive


def _validate_zip(path: Path, *, kind: str | None, version: str | None) -> list[Issue]:
    with _preflighted_zip(path) as (preflight_issues, archive):
        if preflight_issues:
            return preflight_issues
        assert archive is not None

        issues: list[Issue] = []
        seen: set[str] = set()
        seen_casefold: set[str] = set()
        path_types: dict[str, str] = {}
        expanded_total = 0
        members = archive.infolist()
        if len(members) > MAX_ARCHIVE_MEMBERS:
            issues.append(_issue("member_count_limit", path, MAX_ARCHIVE_MEMBERS + 1))
        bounded_members = members[:MAX_ARCHIVE_MEMBERS]
        resource_issues: list[Issue] = []
        for index, member in enumerate(bounded_members, 1):
            is_dir = member.is_dir()
            size = int(member.file_size)
            expanded_total += size if not is_dir else 0
            resource_issues.extend(_size_issues(path, index, size, expanded_total))

        issues.extend(resource_issues)
        for index, member in enumerate(bounded_members, 1):
            is_dir = member.is_dir()
            size = int(member.file_size)

            canonical, path_issues = _canonical_member_path(path, member.filename, index)
            issues.extend(path_issues)
            if canonical is not None:
                issues.extend(
                    _track_member_name(
                        path,
                        index,
                        canonical,
                        is_dir=is_dir,
                        seen=seen,
                        seen_casefold=seen_casefold,
                        path_types=path_types,
                    )
                )
                issues.extend(_member_issues(path, canonical, index))
                issues.extend(
                    _strict_manifest_issues(
                        path,
                        canonical,
                        index,
                        is_dir=is_dir,
                        kind=kind,
                        version=version,
                    )
                )

            mode = (member.external_attr >> 16) & 0xFFFF
            file_type = stat.S_IFMT(mode)
            allowed_types = {0, stat.S_IFDIR} if is_dir else {0, stat.S_IFREG}
            if file_type not in allowed_types:
                issues.append(_issue("non_regular_member", path, index))
            if not resource_issues and len(members) <= MAX_ARCHIVE_MEMBERS and not is_dir and size > 0:
                prefix = archive.open(member).read(_MAGIC_PREFIX_BYTES)
                if _looks_like_archive(prefix):
                    issues.append(_issue("nested_archive_magic", path, index))
        return issues


def _validate_tar(path: Path, *, kind: str | None, version: str | None) -> list[Issue]:
    with _preflighted_tar(path) as (preflight_issues, archive):
        if preflight_issues:
            return preflight_issues
        assert archive is not None

        issues: list[Issue] = []
        seen: set[str] = set()
        seen_casefold: set[str] = set()
        path_types: dict[str, str] = {}
        expanded_total = 0
        members: list[tarfile.TarInfo] = []
        for index, member in enumerate(archive, 1):
            if index > MAX_ARCHIVE_MEMBERS:
                issues.append(_issue("member_count_limit", path, index))
                break
            members.append(member)
            size = int(member.size)
            expanded_total += size if member.isfile() else 0
            issues.extend(_size_issues(path, index, size, expanded_total))

        has_resource_issue = any(
            code in {"member_count_limit", "member_size_limit", "expanded_size_limit"}
            for code, _location in issues
        )
        for index, member in enumerate(members, 1):
            is_dir = member.isdir()
            size = int(member.size)

            canonical, path_issues = _canonical_member_path(path, member.name, index)
            issues.extend(path_issues)
            if canonical is not None:
                issues.extend(
                    _track_member_name(
                        path,
                        index,
                        canonical,
                        is_dir=is_dir,
                        seen=seen,
                        seen_casefold=seen_casefold,
                        path_types=path_types,
                    )
                )
                issues.extend(_member_issues(path, canonical, index))
                issues.extend(
                    _strict_manifest_issues(
                        path,
                        canonical,
                        index,
                        is_dir=is_dir,
                        kind=kind,
                        version=version,
                    )
                )

            if not (member.isfile() or member.isdir()):
                issues.append(_issue("non_regular_member", path, index))
            if not has_resource_issue and member.isfile() and size > 0:
                extracted = archive.extractfile(member)
                prefix = extracted.read(_MAGIC_PREFIX_BYTES) if extracted is not None else b""
                if _looks_like_archive(prefix):
                    issues.append(_issue("nested_archive_magic", path, index))
        return issues


def validate_archive(path: Path) -> list[Issue]:
    """Reject release members that can carry local state or unsafe archives."""
    path = Path(path)
    issues: list[Issue] = []
    kind, version = _archive_identity(path)

    try:
        metadata = path.lstat()
        if (
            stat.S_ISLNK(metadata.st_mode)
            or getattr(metadata, "st_file_attributes", 0) & _REPARSE_POINT
            or not stat.S_ISREG(metadata.st_mode)
        ):
            return [("unsafe_archive", path.name)]
        if metadata.st_size > MAX_OUTER_ARCHIVE_BYTES:
            issues.append(("outer_size_limit", path.name))
            return issues
        if kind == "wheel":
            issues.extend(_validate_zip(path, kind=kind if version else None, version=version))
        elif kind == "sdist":
            issues.extend(_validate_tar(path, kind=kind if version else None, version=version))
        else:
            issues.append(("unsupported_archive", path.name))
    except (OSError, EOFError, RuntimeError, ValueError, tarfile.TarError, zipfile.BadZipFile):
        issues.append(("invalid_archive", path.name))

    return sorted(set(issues))


def _load_project_version(dist_dir: Path) -> tuple[str | None, list[Issue]]:
    pyproject = dist_dir.parent / "pyproject.toml"
    try:
        metadata = pyproject.lstat()
        if (
            stat.S_ISLNK(metadata.st_mode)
            or getattr(metadata, "st_file_attributes", 0) & _REPARSE_POINT
            or not stat.S_ISREG(metadata.st_mode)
        ):
            raise ValueError("project metadata is not a regular file")
        with pyproject.open("rb") as handle:
            raw_version = tomllib.load(handle)["project"]["version"]
        if not isinstance(raw_version, str):
            raise TypeError("project version must be a string")
        version = raw_version.strip()
        if not version:
            raise ValueError("empty version")
        return version, []
    except (KeyError, OSError, TypeError, ValueError, tomllib.TOMLDecodeError):
        return None, [("project_version_unavailable", "pyproject.toml")]


def _classify_distribution_entries(
    dist_dir: Path,
) -> tuple[list[tuple[Path, str]], list[tuple[Path, str]], list[Issue]]:
    entries = sorted(dist_dir.iterdir(), key=lambda item: item.name.casefold()) if dist_dir.is_dir() else []
    wheels: list[tuple[Path, str]] = []
    sdists: list[tuple[Path, str]] = []
    issues: list[Issue] = []
    for index, path in enumerate(entries, 1):
        try:
            metadata = path.lstat()
        except OSError:
            issues.append(_entry_issue("unsafe_distribution_entry", dist_dir, index))
            continue
        if (
            stat.S_ISLNK(metadata.st_mode)
            or getattr(metadata, "st_file_attributes", 0) & _REPARSE_POINT
            or not stat.S_ISREG(metadata.st_mode)
        ):
            issues.append(_entry_issue("unsafe_distribution_entry", dist_dir, index))
            continue
        wheel_match = _WHEEL_RE.fullmatch(path.name)
        sdist_match = _SDIST_RE.fullmatch(path.name)
        if wheel_match:
            wheels.append((path, wheel_match.group("version")))
        elif sdist_match:
            sdists.append((path, sdist_match.group("version")))
        else:
            issues.append(_entry_issue("unexpected_distribution_entry", dist_dir, index))
    return wheels, sdists, issues


def scan_dist(dist_dir: Path) -> list[Issue]:
    dist_dir = Path(dist_dir)
    issues: list[Issue] = []
    project_version, project_issues = _load_project_version(dist_dir)
    issues.extend(project_issues)

    wheels, sdists, entry_issues = _classify_distribution_entries(dist_dir)
    issues.extend(entry_issues)
    if entry_issues:
        issues.append(("unexpected_archive", "distribution-set"))

    if not wheels:
        issues.append(("missing_distribution", "wheel"))
    elif len(wheels) > 1:
        issues.append(("unexpected_archive", "wheel-set"))
    if not sdists:
        issues.append(("missing_distribution", "sdist"))
    elif len(sdists) > 1:
        issues.append(("unexpected_archive", "sdist-set"))

    for path, _version in (*wheels, *sdists):
        issues.extend(validate_archive(path))

    if len(wheels) == 1 and len(sdists) == 1:
        wheel_version = wheels[0][1]
        sdist_version = sdists[0][1]
        if wheel_version != sdist_version:
            issues.append(("version_mismatch", "distribution-set"))
        if project_version and (wheel_version != project_version or sdist_version != project_version):
            issues.append(("version_mismatch", "project-distribution"))

    return sorted(set(issues))


def main() -> int:
    parser = argparse.ArgumentParser(description="Reject unsafe files inside Python release archives.")
    parser.add_argument("--dist-dir", type=Path, default=Path("dist"))
    args = parser.parse_args()

    issues = scan_dist(args.dist_dir)
    if issues:
        print(f"DISTRIBUTION_CONTENT_ISSUES count={len(issues)}")
        for code, location in issues:
            print(f"{code}\t{location}")
        return 1
    print("Distribution content check passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
